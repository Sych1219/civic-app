import asyncio
import json
import logging
import uuid
from datetime import datetime, timezone, timedelta
from typing import AsyncGenerator, Optional

from langchain_core.messages import HumanMessage, SystemMessage, ToolMessage
from langchain_openai import ChatOpenAI

from app.services.geocoding import geocode_place
from app.domains.taxi.store import LocationStore, location_store_var
from app.domains.taxi.tools import (
    count_taxis_in_zone,
    count_taxis_nearby,
    count_taxis_near_road,
    find_nearest_taxis,
    get_recent_taxi_activity,
    get_taxi_history,
    resolve_zone,
)
from app.tools.common import read_file
from app.memory.client import MemoryClient
from app.memory.events import EventCollector, EventType, collector_var
from app.memory.injector import build_hint_block
from app.memory.pipeline import post_request_pipeline
from app.memory.registry import HintRegistry

logger = logging.getLogger(__name__)
trace = logging.getLogger("trace")

_RESULT_PREVIEW_LEN = 200
_SGT = timezone(timedelta(hours=8))

_mem_client = MemoryClient()
_registry   = HintRegistry(_mem_client)


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
    read_file,
]

_TOOL_MAP = {t.name: t for t in _TOOLS}


def _build_system_prompt(
    hints: list[str],
    system_notes: str = "",
    officer_index: str = "",
) -> str:
    from app.memory.file_memory import file_memory_manager
    from app.memory.injector import build_hint_block

    now_sgt = datetime.now(_SGT)
    base = f"""\
You are a taxi availability assistant for Singapore.
Always call a tool to get real data — never invent taxi counts.

Current date and time (SGT): {now_sgt.strftime("%Y-%m-%d %H:%M %Z")}
Use this as the reference when interpreting relative times like "yesterday", "last hour", "this morning".

Tool selection guide:
- Named zone/district (Punggol, CBD, Changi, Tampines…) → count_taxis_in_zone
- Place name needing coordinates → geocode_place first, then count_taxis_nearby
- Road or expressway (PIE, CTE, AYE, Orchard Road…) → count_taxis_near_road
- Nearest taxi to a location → geocode_place first, then find_nearest_taxis
- Historical or trend question → get_taxi_history or get_recent_taxi_activity
- Unsure about a zone name → resolve_zone first
- Need full memory or officer details → read_file\
"""

    notes_section = f"\n\n## Domain Notes\n{system_notes}" if system_notes else ""
    officer_section = f"\n\n## Officer Context\n{officer_index}" if officer_index else ""
    memory_index = file_memory_manager.read_index()
    memory_section = f"\n\n{memory_index}" if memory_index else ""

    return base + notes_section + officer_section + memory_section + build_hint_block(hints)


async def run_taxi_agent(
    message: str,
    request_id: Optional[str] = None,
    system_notes: str = "",
    officer_id: Optional[str] = None,
) -> tuple[str, Optional[dict], dict[str, dict]]:
    """Run the tools-based taxi agent.

    Returns:
        answer:    LLM-generated text answer.
        last_raw:  Last tool result as a dict.
        locations: Mapping of ref_id → GeoJsonFeatureCollection dict.
    """
    from app.officers.manager import officer_manager

    request_id = request_id or str(uuid.uuid4())
    officer_index = officer_manager.load_index(officer_id)

    trace.info("[taxi] Sub-question: %s", message)
    trace.info("[taxi] Available tools: %s", [t.name for t in _TOOLS])

    hints_injected = await _registry.get_active_hints("taxi", message)

    store    = LocationStore()
    ls_tok   = location_store_var.set(store)

    collector = EventCollector(request_id=request_id, agent="taxi")
    coll_tok  = collector_var.set(collector)

    try:
        answer, last_raw, locations = await _run(
            message, store, hints_injected, system_notes, officer_index
        )
    finally:
        location_store_var.reset(ls_tok)
        collector_var.reset(coll_tok)
        asyncio.create_task(post_request_pipeline(
            request_id, "taxi", message,
            collector, hints_injected, _registry, _mem_client,
        ))

    return answer, last_raw, locations


async def _run(
    message: str,
    store: LocationStore,
    hints: list[str],
    system_notes: str = "",
    officer_index: str = "",
) -> tuple[str, Optional[dict], dict[str, dict]]:
    llm = ChatOpenAI(model="gpt-4o-mini", temperature=0)
    llm_with_tools = llm.bind_tools(_TOOLS)

    messages = [
        SystemMessage(content=_build_system_prompt(hints, system_notes, officer_index)),
        HumanMessage(content=message),
    ]

    last_raw: Optional[dict] = None
    max_iters = 5
    collector = collector_var.get()

    for iteration in range(1, max_iters + 1):
        trace.info("[taxi] ── Iteration %d/%d: calling LLM...", iteration, max_iters)
        response = await llm_with_tools.ainvoke(messages)
        messages.append(response)

        if collector:
            collector.emit(EventType.LLM_DECISION, iteration,
                has_tool_calls=bool(response.tool_calls),
                tools=[tc["name"] for tc in response.tool_calls],
            )

        if not response.tool_calls:
            trace.info("[taxi] ── LLM decision: no tool calls → generating final answer")
            trace.info("[taxi] ── Answer: %s", _preview(response.content))
            if collector:
                collector.emit(EventType.FINAL_ANSWER, iteration, iterations_used=iteration)
            return response.content, last_raw, store.collect()

        trace.info(
            "[taxi] ── LLM decision: call %d tool(s): %s",
            len(response.tool_calls),
            [tc["name"] for tc in response.tool_calls],
        )

        for tc in response.tool_calls:
            tool_fn = _TOOL_MAP.get(tc["name"])
            args_str = json.dumps(tc["args"], ensure_ascii=False)
            trace.info("[taxi]    ▶ %s(%s)", tc["name"], args_str)

            if collector:
                collector.emit(EventType.TOOL_CALL, iteration, tool=tc["name"], args=tc["args"])

            if tool_fn is None:
                llm_content = f"Unknown tool: {tc['name']}"
                trace.info("[taxi]    ✗ Unknown tool")
                if collector:
                    collector.emit(EventType.TOOL_RESULT, iteration,
                        tool=tc["name"], success=False, error="Unknown tool")
            else:
                try:
                    result = await tool_fn.ainvoke(tc["args"])
                    if hasattr(result, "model_dump_json"):
                        llm_content = result.model_dump_json()
                        last_raw = result.model_dump()
                    else:
                        llm_content = str(result)
                        try:
                            last_raw = json.loads(llm_content)
                        except (json.JSONDecodeError, ValueError):
                            pass
                    trace.info("[taxi]    ← %s", _preview(llm_content))
                    if collector:
                        collector.emit(EventType.TOOL_RESULT, iteration,
                            tool=tc["name"], success=True, error=None)
                except Exception as exc:
                    llm_content = f"Tool error: {exc}"
                    logger.warning("Tool %s failed: %s", tc["name"], exc)
                    trace.info("[taxi]    ✗ Tool error: %s", exc)
                    if collector:
                        collector.emit(EventType.TOOL_RESULT, iteration,
                            tool=tc["name"], success=False, error=str(exc))

            messages.append(ToolMessage(content=llm_content, tool_call_id=tc["id"]))

    trace.info("[taxi] ── Reached max iterations (%d), returning last message", max_iters)
    last_content = messages[-1].content if hasattr(messages[-1], "content") else ""
    return last_content, last_raw, store.collect()


# ─── Streaming version (Phase 5 — SSE) ───────────────────────────────────────

async def run_taxi_agent_streaming(
    message: str,
    system_notes: str = "",
    officer_id: Optional[str] = None,
) -> AsyncGenerator[dict, None]:
    from app.officers.manager import officer_manager

    officer_index = officer_manager.load_index(officer_id)
    hints_injected = await _registry.get_active_hints("taxi", message)

    store  = LocationStore()
    ls_tok = location_store_var.set(store)
    try:
        async for event in _run_streaming(message, store, hints_injected, system_notes, officer_index):
            yield event
    finally:
        location_store_var.reset(ls_tok)


async def _run_streaming(
    message: str,
    store: LocationStore,
    hints: list[str],
    system_notes: str = "",
    officer_index: str = "",
) -> AsyncGenerator[dict, None]:
    llm = ChatOpenAI(model="gpt-4o-mini", temperature=0)
    llm_with_tools = llm.bind_tools(_TOOLS)

    messages = [
        SystemMessage(content=_build_system_prompt(hints, system_notes, officer_index)),
        HumanMessage(content=message),
    ]

    last_raw: Optional[dict] = None
    max_iters = 5
    last_streamed_content = ""

    for iteration in range(1, max_iters + 1):
        chunks: list = []
        has_tool_calls = False
        streamed_content = ""

        async for chunk in llm_with_tools.astream(messages):
            chunks.append(chunk)
            if chunk.tool_call_chunks:
                has_tool_calls = True
            if chunk.content and not has_tool_calls:
                yield {"type": "token", "content": chunk.content}
                streamed_content += chunk.content

        response = chunks[0]
        for c in chunks[1:]:
            response = response + c
        messages.append(response)
        last_streamed_content = streamed_content

        if not has_tool_calls:
            yield {"type": "final", "content": streamed_content, "locations": store.collect(), "raw": last_raw}
            return

        for tc in response.tool_calls:
            yield {"type": "tool_start", "tool": tc["name"], "input": tc["args"]}
            tool_fn = _TOOL_MAP.get(tc["name"])

            if tool_fn is None:
                llm_content = f"Unknown tool: {tc['name']}"
                yield {"type": "tool_end", "tool": tc["name"], "output": llm_content}
            else:
                try:
                    result = await tool_fn.ainvoke(tc["args"])
                    if hasattr(result, "model_dump_json"):
                        llm_content = result.model_dump_json()
                        last_raw = result.model_dump()
                    else:
                        llm_content = str(result)
                    yield {"type": "tool_end", "tool": tc["name"], "output": llm_content[:200]}
                except Exception as exc:
                    llm_content = f"Tool error: {exc}"
                    yield {"type": "tool_end", "tool": tc["name"], "output": llm_content}

            messages.append(ToolMessage(content=llm_content, tool_call_id=tc["id"]))

        yield {"type": "new_response"}

    if not last_streamed_content:
        last_streamed_content = messages[-1].content if hasattr(messages[-1], "content") else ""
        yield {"type": "token", "content": last_streamed_content}
    yield {"type": "final", "content": last_streamed_content, "locations": store.collect(), "raw": last_raw}
