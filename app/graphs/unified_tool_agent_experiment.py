"""
Experimental LangChain agent that uses three tools:
- register a new API from pasted docs
- list/catalog existing APIs
- trigger a registered API

No existing graphs are modified; delete this file if the idea isn’t useful.
Usage:

```
from app.graphs.unified_tool_agent_experiment import UnifiedToolAgent

agent = UnifiedToolAgent()
result = agent.run("Trigger the latest schools API for California", max_iterations=4)
print(result["output"])
```
"""
from __future__ import annotations

import json
import os
from typing import Any, Dict, Optional, Annotated

from langchain.agents import create_agent
from langchain.agents.middleware.types import AgentState as BaseAgentState
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langchain_core.tools import tool
from langgraph.graph.message import add_messages
from langchain_openai import ChatOpenAI

from app.agents.api_trigger_agent import ApiTriggerAgent
from app.agents.register_agent import RegisterAgent
from app.shared.catalog import GovApiCatalogQuery
from app.shared.clients import GovApiRegistryClient
from app.shared.responses import GovApiListItemResponse, GovApiListResponse


class UnifiedAgentState(BaseAgentState):
    messages: Annotated[list[Any], add_messages]
    catalog_candidates: Optional[list[Dict[str, Any]]]


# Instantiate agents/clients once so tools stay lightweight.
_register_agent = RegisterAgent()
_trigger_agent = ApiTriggerAgent()
_registry_client = GovApiRegistryClient(
    base_url=os.getenv("GOV_API_BASE_URL", "http://localhost:8080/api/v1/gov/apis")
)
_selector_llm = ChatOpenAI(model="gpt-4o-mini", temperature=0)


def _fetch_catalog_items(
    *,
    page: int = 0,
    size: int = 20,
    sort: Optional[str] = None,
    id: Optional[str] = None,
) -> list[GovApiListItemResponse]:
    """Plain helper so other tools can reuse catalog calls without invoking the tool wrapper."""
    try:
        query_model = GovApiCatalogQuery(
            id=id,
            page=page,
            size=size,
            sort=sort,
        )
    except Exception:
        return []

    try:
        response = _registry_client.list_apis(query=query_model)
    except Exception:
        return []

    if isinstance(response, GovApiListResponse):
        return response.items

    if isinstance(response, dict):
        items = response.get("items") or []
        if isinstance(items, list):
            return [GovApiListItemResponse.model_validate(item) for item in items]

    return []


@tool
def register_tool(source_text: str, auto_register: bool = False, dry_run: bool = True) -> Dict[str, Any]:
    """Turn pasted API docs into a validated contract and optionally submit it (set auto_register=True to submit)."""
    state = {"source_text": source_text, "auto_register": auto_register}
    result = _register_agent.run(state, {"dry_run": dry_run})
    return result


@tool
def catalog_all_tool(
    page: int = 0,
    size: int = 20,
    sort: Optional[str] = None,
    id: Optional[str] = None,
) -> Dict[str, Any]:
    """List/search registered government APIs; omit description to retrieve all."""
    items = _fetch_catalog_items(page=page, size=size, sort=sort, id=id)
    candidates = [item.model_dump() for item in items]
    return {"catalog_candidates": candidates}


@tool
def find_best_catalog_match_tool(
    description: str,
    candidates: Optional[list[Dict[str, Any]]] = None,
    catalog_candidates: Optional[list[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """
    Choose the best-matching API by description using an LLM ranker.
    Expects the caller to supply `candidates` (e.g., from catalog_all_tool); it does not fetch catalog data itself.
    """
    desc = (description or "").strip()
    if len(desc) < 3:
        return {"error": "VALIDATION_ERROR", "message": "description must be at least 3 characters"}

    if not candidates:
        candidates = catalog_candidates
    if not candidates:
        return {
            "error": "NO_CANDIDATES",
            "message": "Provide catalog candidates from catalog_all_tool.",
            "candidates": [],
        }

    normalized_candidates: list[Dict[str, Any]] = []
    for item in candidates:
        item_dict = dict(item)
        normalized_candidates.append(
            {
                "id": item_dict.get("id"),
                "name": item_dict.get("name"),
                "description": item_dict.get("description"),
                "baseUrl": item_dict.get("baseUrl"),
                "httpMethod": item_dict.get("httpMethod"),
            }
        )

    # Keep prompt compact
    limited_candidates = normalized_candidates[: min(len(normalized_candidates), 30)]
    prompt = [
        SystemMessage(content="You rank registered APIs by semantic similarity to a request description."),
        HumanMessage(
            content=(
                "Pick the single best-matching API.\n"
                f"User description: {desc}\n\n"
                f"Candidates: {json.dumps(limited_candidates, ensure_ascii=False)}\n\n"
                "Return JSON with fields: id, name, reason."
            )
        ),
    ]

    try:
        ai_msg = _selector_llm.invoke(prompt)
        raw_content = (ai_msg.content or "").strip()
        # Handle fenced JSON or extra text by extracting the first JSON object.
        try:
            parsed = json.loads(raw_content)
        except json.JSONDecodeError:
            start = raw_content.find("{")
            end = raw_content.rfind("}")
            if start == -1 or end == -1 or end <= start:
                raise
            parsed = json.loads(raw_content[start : end + 1])
        best_id = parsed.get("id")
        best = next((c for c in normalized_candidates if c.get("id") == best_id), normalized_candidates[0])
        return {"best": best, "reason": parsed.get("reason"), "candidates_considered": limited_candidates}
    except Exception:
        # Fallback to first candidate if LLM parsing fails
        return {
            "best": normalized_candidates[0],
            "reason": "Fallback to first candidate",
            "candidates_considered": limited_candidates,
        }


@tool
def trigger_tool(
    api_id: str,
    query: Optional[Dict[str, Any]] = None,
    body: Optional[Dict[str, Any]] = None,
    headerOverrides: Optional[Dict[str, str]] = None,
    useExampleDefaults: bool = True,
    dry_run: bool = True,
) -> Dict[str, Any]:
    """Trigger a registered API by id. Provide query/body/headerOverrides to override defaults."""
    trigger_payload: Dict[str, Any] = {
        "api_id": api_id,
        "request": {
            "query": query,
            "body": body,
            "headerOverrides": headerOverrides,
            "useExampleDefaults": useExampleDefaults,
        },
    }
    state: Dict[str, Any] = {"metadata": {"trigger": trigger_payload}}
    result = _trigger_agent.run(state, {"dry_run": dry_run})
    return result


class UnifiedToolAgent:
    """
    A single LLM-driven agent that picks between register/catalog/trigger tools via LangChain.
    """

    def __init__(self, *, llm: ChatOpenAI | None = None):
        self.llm = llm or ChatOpenAI(
            model="gpt-5",
            temperature=0.1,
            max_tokens=1000,
            timeout=30,
        )
        self.tools = [register_tool, catalog_all_tool, find_best_catalog_match_tool, trigger_tool]
        self.system_prompt = (
            "You are a single operator with three tools: "
            "register_tool (make new API contracts), "
            "catalog_all_tool (list/search existing APIs), "
            "find_best_catalog_match_tool (pick the best existing API for a description), "
            "trigger_tool (invoke a registered API). "
            "Decide what the user wants and call tools as needed. "
            "When the user wants data or to 'run' an API: "
            "first call catalog_all_tool to get candidates, then call find_best_catalog_match_tool "
            "to select one (it will read catalog_candidates from state), then call trigger_tool with that id. "
            "When the user supplies API docs or asks to register/onboard, call register_tool. "
            "Keep replies concise."
        )


    def run(self, user_input: str, *, max_iterations: int = 4) -> Dict[str, Any]:
        # LangGraph's recursion_limit counts node executions (model, tools, etc.),
        # not just model/tool turns. Scale up to avoid premature GraphRecursionError.
        recursion_limit = max_iterations * 6
        agent = create_agent(
            model=self.llm,
            tools=self.tools,
            system_prompt=self.system_prompt,
            state_schema=UnifiedAgentState,
        )

        state = agent.invoke(
            {"messages": [HumanMessage(content=user_input)]},
            config={"recursion_limit": recursion_limit},
        )
        # Surface a simple output alongside the full LangGraph state for debugging.
        output_text = next((m.content for m in reversed(state["messages"]) if isinstance(m, AIMessage)), None)
        return {"output": output_text, **state}
