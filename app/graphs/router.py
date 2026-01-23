"""
Router graph that picks which agent to run based on chat intent.

Heuristics:
- If the chat is about registering an API (e.g., "register this API", metadata.intent == "register"),
  route to RegisterAgent.
- Otherwise, attempt to satisfy the user's ask by searching the catalog and then triggering an API:
  build a catalog query from the chat text, call ApiCatalogService, pick the first matching api id,
  and invoke ApiTriggerAgent (defaulting to useExampleDefaults when no runtime payload is provided).
"""
from __future__ import annotations

import json
from typing import Any, Dict, List

from langgraph.graph import END, StateGraph

from langchain_openai import ChatOpenAI

from app.agents.api_catalog_service import ApiCatalogService
from app.agents.api_trigger_agent import ApiTriggerAgent
from app.agents.register_agent import RegisterAgent
from app.agents.trigger_summary_agent import TriggerSummaryAgent
from app.shared.state import GovApiState, GovApiListItem


class RouterGraphFactory:
    def __init__(
        self,
        *,
        register_agent: RegisterAgent | None = None,
        catalog_service: ApiCatalogService | None = None,
        trigger_agent: ApiTriggerAgent | None = None,
        trigger_summary_agent: TriggerSummaryAgent | None = None,
        llm: ChatOpenAI | None = None,
    ):
        self.register_agent = register_agent or RegisterAgent()
        self.catalog_service = catalog_service or ApiCatalogService()
        self.trigger_agent = trigger_agent or ApiTriggerAgent()
        self.trigger_summary_agent = trigger_summary_agent or TriggerSummaryAgent()
        self.llm = llm or ChatOpenAI(model="gpt-4o-mini", temperature=0)

    def compile(self):
        graph = StateGraph(GovApiState)

        graph.add_node("route", lambda state: state)
        graph.add_node("prepare_catalog_query", self._prepare_catalog_query)
        graph.add_node("prepare_trigger_input", self._prepare_trigger_input)
        graph.add_node("register_agent", self.register_agent.run)
        graph.add_node("api_catalog_service", self.catalog_service.run)
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
        graph.add_edge("prepare_catalog_query", "api_catalog_service")
        graph.add_edge("api_catalog_service", "prepare_trigger_input")
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
        selected_candidate: GovApiListItem | None = None

        if not trigger.get("api_id") and not trigger.get("apiId"):
            catalog_response = state.get("catalog_response") or {}
            candidates: List[GovApiListItem] = self._extract_candidates(catalog_response)
            best = self._select_best_candidate(candidates, state.get("source_text") or "")
            if best:
                trigger["api_id"] = best["id"]
                selected_candidate = best
        else:
            # If the caller supplied an api_id, still try to fetch its catalog shape for payload drafting.
            catalog_response = state.get("catalog_response") or {}
            candidates: List[GovApiListItem] = self._extract_candidates(catalog_response)
            api_id = trigger.get("api_id") or trigger.get("apiId")
            if api_id:
                selected_candidate = next((c for c in candidates if c.get("id") == str(api_id)), None)

        # If no payload provided, default to useExampleDefaults=True to minimize runtime inputs.
        has_explicit_payload = trigger.get("request") or any(
            key in trigger for key in ("query", "body", "headerOverrides", "useExampleDefaults")
        )
        if not has_explicit_payload:
            drafted = self._draft_trigger_payload(selected_candidate, state.get("source_text") or "")
            if drafted:
                # Ensure we still allow defaults when LLM leaves gaps.
                drafted.setdefault("useExampleDefaults", True)
                trigger["request"] = drafted
            else:
                trigger["request"] = {"useExampleDefaults": True}

        metadata["trigger"] = trigger
        return {"metadata": metadata}

    @staticmethod
    def _extract_candidates(catalog_response: Dict[str, Any]) -> List[GovApiListItem]:
        """Flatten possible catalog response shapes into a list of candidates with id/name/description."""
        candidates: List[GovApiListItem] = []

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
                    "headers": item.get("headers") or [],
                    "queryParams": item.get("queryParams") or [],
                    "bodyParams": item.get("bodyParams") or [],
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

    def _select_best_candidate(self, candidates: List[GovApiListItem], user_text: str) -> GovApiListItem | None:
        """Use LLM similarity to pick the best candidate; fallback to first candidate."""
        if not candidates:
            return None
        if not user_text:
            return candidates[0]

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
                    return candidates[idx]
            # Otherwise, try to match id substring
            for c in candidates:
                if c["id"] in content:
                    return c
            # Fallback to first on unexpected output
            return candidates[0]
        except Exception:
            return candidates[0]

    def _draft_trigger_payload(self, candidate: GovApiListItem | None, user_text: str) -> Dict[str, Any] | None:
        """
        Use the catalog prototype + user ask to draft trigger payload fields.
        """

        if not candidate or not user_text:
            return None

        # Keep only fields that describe how to call the API.
        api_shape = {
            "id": candidate.get("id"),
            "name": candidate.get("name"),
            "description": candidate.get("description"),
            "method": candidate.get("method"),
            "baseUrl": candidate.get("baseUrl"),
            "headers": candidate.get("headers") or [],
            "queryParams": candidate.get("queryParams") or [],
            "bodyParams": candidate.get("bodyParams") or [],
        }

        prompt = (
            "You are preparing a trigger payload for a registered government API.\n"
            "Use ONLY the provided contract fields. Fill values from the user request when possible, "
            "otherwise leave the field out and rely on example defaults.\n"
            "Top-level keys allowed: query (object), body (object), headerOverrides (object), useExampleDefaults (boolean).\n"
            "Respect types and nesting: if a param has children, represent it as an object with those child keys.\n"
            "Do not invent API IDs or paths. Keep responses compact JSON only.\n\n"
            f"User request:\n{user_text}\n\n"
            f"API contract:\n{json.dumps(api_shape, indent=2)}\n\n"
            "Return the payload JSON (no prose):"
        )

        try:
            completion = self.llm.invoke(prompt)
            payload = self._parse_payload_json(str(completion.content).strip())
            if isinstance(payload, dict):
                allowed_keys = {"query", "body", "headerOverrides", "useExampleDefaults"}
                return {k: v for k, v in payload.items() if k in allowed_keys}
        except Exception:
            return None
        return None

    @staticmethod
    def _parse_payload_json(text: str) -> Dict[str, Any] | None:
        """Best-effort JSON extraction from model output."""

        if not text:
            return None

        candidates: List[str] = [text]
        if "```" in text:
            for part in text.split("```"):
                stripped = part.strip()
                if not stripped:
                    continue
                if stripped.startswith("json"):
                    stripped = stripped[4:].strip()
                candidates.append(stripped)

        for candidate in candidates:
            snippet = candidate
            if "{" in candidate and "}" in candidate:
                start = candidate.find("{")
                end = candidate.rfind("}")
                if end > start:
                    snippet = candidate[start : end + 1]
            try:
                parsed = json.loads(snippet)
                if isinstance(parsed, dict):
                    return parsed
            except Exception:
                continue
        return None


def create_router_graph():
    return RouterGraphFactory().compile()
