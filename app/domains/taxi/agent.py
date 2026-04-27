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
    llm = ChatOpenAI(model="gpt-4o-mini", temperature=0)
    llm_with_tools = llm.bind_tools(_TOOLS)

    messages = [
        SystemMessage(content=_SYSTEM),
        HumanMessage(content=message),
    ]

    last_tool_result: Optional[dict] = None

    for _ in range(5):
        response = await llm_with_tools.ainvoke(messages)
        messages.append(response)

        if not response.tool_calls:
            return response.content, last_tool_result

        for tc in response.tool_calls:
            tool_fn = _TOOL_MAP.get(tc["name"])
            if tool_fn is None:
                result_str = f"Unknown tool: {tc['name']}"
            else:
                try:
                    result_str = await tool_fn.ainvoke(tc["args"])
                    try:
                        last_tool_result = json.loads(result_str)
                    except (json.JSONDecodeError, ValueError):
                        pass
                except Exception as exc:
                    result_str = f"Tool error: {exc}"
                    logger.warning("Tool %s failed: %s", tc["name"], exc)

            messages.append(ToolMessage(content=result_str, tool_call_id=tc["id"]))

    return messages[-1].content if hasattr(messages[-1], "content") else "", last_tool_result
