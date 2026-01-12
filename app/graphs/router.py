"""
Router graph that picks which agent to run based on chat intent.

Heuristics:
- If the chat is about registering an API (e.g., "register this API", metadata.intent == "register"),
  route to RegisterAgent.
- Otherwise, attempt to satisfy the user's ask by searching the catalog and then triggering an API:
  build a catalog query from the chat text, call ApiCatalogAgent, pick the first matching api id,
  and invoke ApiTriggerAgent (defaulting to useExampleDefaults when no runtime payload is provided).
"""
from __future__ import annotations

from typing import Any, Dict, List

from langgraph.graph import END, StateGraph

from langchain_openai import ChatOpenAI

from app.agents.api_catalog_agent import ApiCatalogAgent
from app.agents.api_trigger_agent import ApiTriggerAgent
from app.agents.register_agent import RegisterAgent
from app.agents.trigger_summary_agent import TriggerSummaryAgent
from app.shared.state import GovApiState


class RouterGraphFactory:
    def __init__(
        self,
        *,
        register_agent: RegisterAgent | None = None,
        catalog_agent: ApiCatalogAgent | None = None,
        trigger_agent: ApiTriggerAgent | None = None,
        trigger_summary_agent: TriggerSummaryAgent | None = None,
        llm: ChatOpenAI | None = None,
    ):
        self.register_agent = register_agent or RegisterAgent()
        self.catalog_agent = catalog_agent or ApiCatalogAgent()
        self.trigger_agent = trigger_agent or ApiTriggerAgent()
        self.trigger_summary_agent = trigger_summary_agent or TriggerSummaryAgent()
        self.llm = llm or ChatOpenAI(model="gpt-4o-mini", temperature=0)

    def compile(self):
        graph = StateGraph(GovApiState)

        graph.add_node("route", lambda state: state)
        graph.add_node("prepare_catalog_query", self._prepare_catalog_query)
        graph.add_node("prepare_trigger_input", self._prepare_trigger_input)
        graph.add_node("register_agent", self.register_agent.run)
        graph.add_node("api_catalog_agent", self.catalog_agent.run)
        graph.add_node("api_trigger_agent", self.trigger_agent.run)
        graph.add_node("trigger_summary_agent", self.trigger_summary_agent.run)

        graph.set_entry_point("route")

        graph.add_conditional_edges(
            "route",
            self._choose_path,
            {
                "register": "register_agent",
                "invoke": "prepare_catalog_query",
            },
        )
        graph.add_edge("prepare_catalog_query", "api_catalog_agent")
        graph.add_edge("api_catalog_agent", "prepare_trigger_input")
        graph.add_edge("prepare_trigger_input", "api_trigger_agent")
        graph.add_edge("api_trigger_agent", "trigger_summary_agent")
        graph.add_edge("register_agent", END)
        graph.add_edge("trigger_summary_agent", END)
        return graph.compile()

    def _choose_path(self, state: GovApiState) -> str:
        """
        Decide register vs invoke using an LLM (or existing metadata intent). Defaults to invoke.
        """

        metadata: Dict[str, Any] = dict(state.get("metadata") or {})
        intent = str(metadata.get("intent") or "").lower()

        user_text = (state.get("source_text") or "").strip()
        system = (
            "Classify the user's request for routing.\n"
            "Return exactly one of: REGISTER or INVOKE.\n"
            "REGISTER means the user wants to add/register a new API.\n"
            "INVOKE means the user wants to call/trigger an existing API to fetch data.\n"
            "Respond with only the label, nothing else."
        )
        try:
            completion = self.llm.invoke([("system", system), ("user", user_text)])
            label = str(completion.content).strip().lower()
            if "register" in label:
                intent = "register"
            elif "invoke" in label:
                intent = "invoke"
            else:
                intent = "invoke"
        except Exception:
            intent = "invoke"

        metadata["intent"] = intent
        state["metadata"] = metadata
        
        return intent

    def _prepare_catalog_query(self, state: GovApiState) -> GovApiState:
        """
        Build a broad catalog_query when none is provided so we can LLM-rank candidates.
        """

        metadata: Dict[str, Any] = dict(state.get("metadata") or {})
        catalog_query: Dict[str, Any] = dict(metadata.get("catalog_query") or {})
        if not catalog_query:
            catalog_query = {"page": 0, "size": 100}
        metadata["catalog_query"] = catalog_query
        return {"metadata": metadata}

    def _prepare_trigger_input(self, state: GovApiState) -> GovApiState:
        """
        Choose an api_id from the catalog response when one is not provided,
        and ensure the trigger payload has a minimal request shape.
        """

        metadata: Dict[str, Any] = dict(state.get("metadata") or {})
        trigger: Dict[str, Any] = dict(metadata.get("trigger") or {})

        if not trigger.get("api_id") and not trigger.get("apiId"):
            catalog_response = state.get("catalog_response") or {}
            candidates = self._extract_candidates(catalog_response)
            best = self._select_best_candidate(candidates, state.get("source_text") or "")
            if best:
                trigger["api_id"] = best

        # If no payload provided, default to useExampleDefaults=True to minimize runtime inputs.
        has_explicit_payload = trigger.get("request") or any(
            key in trigger for key in ("query", "body", "headerOverrides", "useExampleDefaults")
        )
        if not has_explicit_payload:
            trigger["request"] = {"useExampleDefaults": True}

        metadata["trigger"] = trigger
        return {"metadata": metadata}

    @staticmethod
    def _extract_candidates(catalog_response: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Flatten possible catalog response shapes into a list of candidates with id/name/description."""
        candidates: List[Dict[str, Any]] = []

        def add_item(item: Dict[str, Any]):
            api_id = item.get("id") or item.get("apiId")
            if not api_id:
                return
            candidates.append(
                {
                    "id": str(api_id),
                    "name": item.get("name") or item.get("title") or "",
                    "description": item.get("description") or item.get("summary") or "",
                    "method": item.get("httpMethod") or item.get("method") or "",
                    "baseUrl": item.get("baseUrl") or "",
                }
            )

        if isinstance(catalog_response, dict):
            for key in ("content", "items", "results", "data", "apis"):
                items = catalog_response.get(key)
                if isinstance(items, list):
                    for item in items:
                        if isinstance(item, dict):
                            add_item(item)
            # Handle singleton shape
            add_item(catalog_response)
        return candidates

    def _select_best_candidate(self, candidates: List[Dict[str, Any]], user_text: str) -> str | None:
        """Use LLM similarity to pick the best api_id; fallback to first candidate."""
        if not candidates:
            return None
        if not user_text:
            return candidates[0]["id"]

        lines = [f"User request: {user_text}", "Candidates:"]
        for idx, c in enumerate(candidates, start=1):
            lines.append(
                f"{idx}. id={c['id']} name={c['name']} method={c['method']} url={c['baseUrl']} desc={c['description']}"
            )
        lines.append(
            "Pick the best matching candidate for the user request. "
            "Respond with the candidate id only (do not include any other text)."
        )
        prompt = "\n".join(lines)

        try:
            completion = self.llm.invoke(prompt)
            content = str(completion.content).strip()
            # If model returned an index instead of id, map it.
            if content.isdigit():
                idx = int(content) - 1
                if 0 <= idx < len(candidates):
                    return candidates[idx]["id"]
            # Otherwise, try to match id substring
            for c in candidates:
                if c["id"] in content:
                    return c["id"]
            # Fallback to first on unexpected output
            return candidates[0]["id"]
        except Exception:
            return candidates[0]["id"]


def create_router_graph():
    return RouterGraphFactory().compile()
