import json
import logging
from typing import Optional

from langchain_core.messages import HumanMessage, SystemMessage, ToolMessage
from langchain_openai import ChatOpenAI

from app.services.geocoding import geocode_place
from app.domains.taxi.tools import (
    count_taxis_in_zone,
    count_taxis_nearby,
    count_taxis_near_road,
    find_nearest_taxis,
    get_recent_taxi_activity,
    get_taxi_history,
    resolve_zone,
)

logger = logging.getLogger(__name__)
trace = logging.getLogger("trace")

_RESULT_PREVIEW_LEN = 200


def _preview(s: str) -> str:
    s = s.replace("\n", " ")
    return s[:_RESULT_PREVIEW_LEN] + "…" if len(s) > _RESULT_PREVIEW_LEN else s

_TOOLS = [
    resolve_zone,
    count_taxis_in_zone,
    count_taxis_nearby,
    count_taxis_near_road,
    find_nearest_taxis,
    get_taxi_history,
    get_recent_taxi_activity,
    geocode_place,
]

_TOOL_MAP = {t.name: t for t in _TOOLS}

_SYSTEM = """\
You are a taxi availability assistant for Singapore.
Always call a tool to get real data — never invent taxi counts.

Tool selection guide:
- Named zone/district (Punggol, CBD, Changi, Tampines…) → count_taxis_in_zone
- Place name needing coordinates → geocode_place first, then count_taxis_nearby
- Road or expressway (PIE, CTE, AYE, Orchard Road…) → count_taxis_near_road
- Nearest taxi to a location → geocode_place first, then find_nearest_taxis
- Historical or trend question → get_taxi_history or get_recent_taxi_activity
- Unsure about a zone name → resolve_zone first\
"""


async def run_taxi_agent(message: str) -> tuple[str, Optional[dict]]:
    """Run the tools-based taxi agent. Returns (answer, raw_data)."""
    trace.info("[taxi] Sub-question: %s", message)
    trace.info("[taxi] Available tools: %s", [t.name for t in _TOOLS])

    llm = ChatOpenAI(model="gpt-4o-mini", temperature=0)
    llm_with_tools = llm.bind_tools(_TOOLS)

    messages = [
        SystemMessage(content=_SYSTEM),
        HumanMessage(content=message),
    ]

    last_tool_result: Optional[dict] = None
    max_iters = 5

    for iteration in range(1, max_iters + 1):
        trace.info("[taxi] ── Iteration %d/%d: calling LLM...", iteration, max_iters)
        response = await llm_with_tools.ainvoke(messages)
        messages.append(response)

        if not response.tool_calls:
            trace.info("[taxi] ── LLM decision: no tool calls → generating final answer")
            trace.info("[taxi] ── Answer: %s", _preview(response.content))
            return response.content, last_tool_result

        trace.info(
            "[taxi] ── LLM decision: call %d tool(s): %s",
            len(response.tool_calls),
            [tc["name"] for tc in response.tool_calls],
        )

        for tc in response.tool_calls:
            tool_fn = _TOOL_MAP.get(tc["name"])
            args_str = json.dumps(tc["args"], ensure_ascii=False)
            trace.info("[taxi]    ▶ %s(%s)", tc["name"], args_str)

            if tool_fn is None:
                result_str = f"Unknown tool: {tc['name']}"
                trace.info("[taxi]    ✗ Unknown tool")
            else:
                try:
                    result_str = await tool_fn.ainvoke(tc["args"])
                    trace.info("[taxi]    ← %s", _preview(result_str))
                    try:
                        last_tool_result = json.loads(result_str)
                    except (json.JSONDecodeError, ValueError):
                        pass
                except Exception as exc:
                    result_str = f"Tool error: {exc}"
                    logger.warning("Tool %s failed: %s", tc["name"], exc)
                    trace.info("[taxi]    ✗ Tool error: %s", exc)

            messages.append(ToolMessage(content=result_str, tool_call_id=tc["id"]))

    trace.info("[taxi] ── Reached max iterations (%d), returning last message", max_iters)
    return messages[-1].content if hasattr(messages[-1], "content") else "", last_tool_result
