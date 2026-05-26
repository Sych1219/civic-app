"""
Unified chat router — uses a dynamic Context Loader + LLM Decision Layer to
assemble skill-based context and decide whether to answer directly, dispatch
to one domain agent, or fan out to multiple agents and synthesise.

Skills are loaded from memory/skills/*.md; experience from memory/long_term/.
Domain agents are still registered via app/domains/*/DOMAIN.md at startup.
"""

import asyncio
import json
import logging
import time
import uuid
from typing import TYPE_CHECKING, AsyncGenerator, Optional

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI
from pydantic import BaseModel

from app.models import Artifact, ChatResponse
from app.memory.context_loader import build_context_prompt
from app.utils.raw_capture import serialize_messages

if TYPE_CHECKING:
    from app.domains.scanner import DomainDef

logger = logging.getLogger(__name__)
trace = logging.getLogger("trace")


def _sep(label: str = "", width: int = 60) -> None:
    if label:
        pad = width - len(label) - 4
        trace.info("┌── %s %s", label, "─" * max(pad, 0), stacklevel=2)
    else:
        trace.info("└%s", "─" * (width - 1), stacklevel=2)


# ─── Plan types ───────────────────────────────────────────────────────────────

class SubTask(BaseModel):
    agent: str
    question: str


class Plan(BaseModel):
    direct_answer: Optional[str] = None  # set when LLM can answer without any agent
    tasks: list[SubTask] = []


# ─── Planner ──────────────────────────────────────────────────────────────────

async def _plan(
    message: str,
    agents: dict,
    session_id: str = "default",
    officer_id: Optional[str] = None,
) -> tuple[Plan, dict]:
    context_text, matched_agents = build_context_prompt(
        message, domains=agents, session_id=session_id, officer_id=officer_id
    )

    # Always expose all registered agents — skill context guides the LLM on when to use each
    agent_list_text = "\n".join(
        f"- `{name}`: {defn.description}" for name, defn in agents.items()
    )

    context_section = f"\n\n{context_text}" if context_text else ""

    system = f"""You are an intelligent routing assistant. Given the user's question, decide the best way to answer it.

You have THREE options:

A) **Direct answer** — if the question requires no external data or tools (e.g. general knowledge, coding questions, greetings), set `direct_answer` to your response and leave `tasks` empty.

B) **Single agent** — if the question needs data from exactly one domain, create one entry in `tasks`.

C) **Multiple agents** — if the question benefits from combining multiple domains (e.g. congestion questions benefit from BOTH traffic cameras AND taxi density), create multiple entries in `tasks`.

Registered agents:
{agent_list_text}

Rules:
- At most ONE subtask per agent.
- Only include agents genuinely needed — never force-fit unrelated domains.
- If the question has nothing to do with any available agent, use option A.
- IMPORTANT: Never use previous answers from conversation history to answer real-time data questions (taxi counts, traffic, live sensor data, etc.). Always dispatch to the relevant agent to fetch fresh data.{context_section}"""

    _sep("PLANNER")
    trace.info("│ User query : %s", message)
    trace.info("│ Matched skills → agents: %s", matched_agents or "(none, showing all)")
    trace.info("│ Calling LLM to decide routing...")
    _sep()

    from app.sessions.manager import session_manager as _sm
    history_dicts = _sm.load_session_for_agent(session_id)
    history_msgs = [
        HumanMessage(content=m["content"]) if m["role"] == "user" else AIMessage(content=m["content"])
        for m in history_dicts
    ]

    input_msgs = [SystemMessage(content=system), *history_msgs, HumanMessage(content=message)]

    llm = ChatOpenAI(model="gpt-4o-mini", temperature=0)
    structured = llm.with_structured_output(Plan)
    t0 = time.monotonic()
    try:
        plan = await structured.ainvoke(input_msgs)
    except Exception as exc:
        _sep("PLAN FAILED")
        trace.info("│ LLM planning call raised: %s: %s", type(exc).__name__, exc)
        _sep()
        raise

    elapsed = time.monotonic() - t0
    _sep("PLAN RESULT")
    if plan.direct_answer:
        trace.info("│ LLM responded in %.2fs — DIRECT ANSWER", elapsed)
        trace.info("│  %s", plan.direct_answer[:120])
    else:
        trace.info("│ LLM responded in %.2fs — %d agent task(s):", elapsed, len(plan.tasks))
        for i, task in enumerate(plan.tasks, 1):
            trace.info("│  Step %d: agent=%s  question=%s", i, task.agent, task.question)
    _sep()

    llm_call = {
        "phase": "planner",
        "model": "gpt-4o-mini",
        "temperature": 0,
        "duration_ms": int(elapsed * 1000),
        "messages": serialize_messages(input_msgs, history_count=len(history_msgs)),
        "output_structured": plan.model_dump(),
    }
    return plan, llm_call


# ─── Executor ─────────────────────────────────────────────────────────────────

async def _execute(plan: Plan, agents: dict) -> list[tuple[str, str, Artifact]]:
    """Run all subtasks in parallel. Returns list of (agent_name, answer, artifact)."""
    _sep("EXECUTOR")
    trace.info("│ Dispatching %d task(s) in parallel:", len(plan.tasks))
    for t in plan.tasks:
        trace.info("│   → [%s] %s", t.agent, t.question)
    _sep()

    async def run_one(task: SubTask) -> tuple[str, str, Artifact]:
        defn = agents.get(task.agent)
        if defn is None:
            logger.warning("Planner requested unknown agent '%s', skipping", task.agent)
            trace.info("[%s] ✗ Unknown agent — skipping", task.agent)
            return task.agent, f"No agent available for '{task.agent}'.", Artifact(type="error", data={})

        kwargs: dict = {"message": task.question}
        if defn.supports_request_id:
            kwargs["request_id"] = str(uuid.uuid4())
        if defn.system_notes:
            kwargs["system_notes"] = defn.system_notes

        t0 = time.monotonic()
        answer, artifact = await defn.handler(**kwargs)
        elapsed = time.monotonic() - t0
        trace.info("[%s] ✓ Done in %.2fs", task.agent, elapsed)
        return task.agent, answer, artifact

    return list(await asyncio.gather(*[run_one(t) for t in plan.tasks]))


# ─── Synthesizer ──────────────────────────────────────────────────────────────

async def _synthesize(original_question: str, results: list[tuple[str, str, Artifact]]) -> tuple[str, dict]:
    _sep("SYNTHESIZER")
    if len(results) == 1:
        trace.info("│ Single result — no synthesis needed, returning directly.")
        _sep()
        skipped_call = {
            "phase": "synthesizer",
            "model": "gpt-4o-mini",
            "messages": [],
            "skipped_reason": "single agent result — synthesizer not invoked",
        }
        return results[0][1], skipped_call

    trace.info("│ Combining %d domain answers into one response:", len(results))
    for agent, answer, _ in results:
        preview = answer[:120].replace("\n", " ")
        trace.info("│   [%s] %s%s", agent, preview, "…" if len(answer) > 120 else "")
    _sep()

    parts = "\n\n".join(
        f"[{agent}]\n{answer}" for agent, answer, _ in results
    )
    system = (
        "You are a synthesis assistant. Combine the following domain-specific answers "
        "into one coherent, concise response that directly addresses the user's original question. "
        "Highlight any correlations or insights that span multiple domains."
    )
    input_msgs = [
        SystemMessage(content=system),
        HumanMessage(content=f"Original question: {original_question}\n\n{parts}"),
    ]
    llm = ChatOpenAI(model="gpt-4o-mini", temperature=0)
    t0 = time.monotonic()
    response = await llm.ainvoke(input_msgs)
    elapsed = time.monotonic() - t0

    llm_call = {
        "phase": "synthesizer",
        "model": "gpt-4o-mini",
        "temperature": 0,
        "duration_ms": int(elapsed * 1000),
        "messages": serialize_messages(input_msgs),
        "output": response.content,
    }
    return response.content, llm_call


# ─── Title generator ─────────────────────────────────────────────────────────

async def _generate_title(message: str) -> tuple[str, dict]:
    input_msgs = [
        SystemMessage(content="Generate a concise title (≤8 words) for the following user query. Output the title only, no quotes."),
        HumanMessage(content=message),
    ]
    llm = ChatOpenAI(model="gpt-4o-mini", temperature=0)
    t0 = time.monotonic()
    resp = await llm.ainvoke(input_msgs)
    elapsed = time.monotonic() - t0
    title = resp.content.strip()

    llm_call = {
        "phase": "title",
        "model": "gpt-4o-mini",
        "temperature": 0,
        "duration_ms": int(elapsed * 1000),
        "messages": serialize_messages(input_msgs),
        "output": title,
    }
    return title, llm_call


# ─── Public entry point (non-streaming) ──────────────────────────────────────

async def route_and_execute(
    message: str,
    agents: dict,
    session_id: str = "default",
    officer_id: Optional[str] = None,
) -> ChatResponse:
    from app.sessions.manager import session_manager

    t_start = time.monotonic()
    _sep("REQUEST START", width=60)
    trace.info("│ %s", message)
    _sep()

    is_first = len(session_manager.load_session(session_id).get("messages", [])) == 0

    plan, _ = await _plan(message, agents, session_id=session_id, officer_id=officer_id)

    if plan.direct_answer:
        answer = plan.direct_answer
        artifacts: list[Artifact] = []
    else:
        results = await _execute(plan, agents)
        answer, _ = await _synthesize(message, results)
        artifacts = [artifact for _, _, artifact in results]

    elapsed = time.monotonic() - t_start
    _sep("FINAL ANSWER")
    trace.info("│ %s", answer[:200].replace("\n", " "))
    trace.info("│ Total time: %.2fs", elapsed)
    _sep()

    await session_manager.append_turn(
        session_id,
        user_content=message,
        assistant_segments=[{
            "content": answer,
            "artifacts": [{"type": a.type, "data": a.data} for a in artifacts],
        }],
    )

    if is_first:
        title, _ = await _generate_title(message)
        session_manager.update_title(session_id, title)

    return ChatResponse(answer=answer, artifacts=artifacts)


# ─── Streaming entry point (SSE) ─────────────────────────────────────────────

async def route_and_execute_streaming(
    message: str,
    agents: dict,
    session_id: str = "default",
    officer_id: Optional[str] = None,
) -> AsyncGenerator[dict, None]:
    from app.sessions.manager import session_manager

    is_first = len(session_manager.load_session(session_id).get("messages", [])) == 0

    plan, planner_call = await _plan(message, agents, session_id=session_id, officer_id=officer_id)
    yield {"type": "llm_call", "call": planner_call}

    # Direct answer — no agent needed
    if plan.direct_answer:
        answer = plan.direct_answer
        words = answer.split(" ")
        for i, word in enumerate(words):
            yield {"type": "token", "content": word if i == 0 else " " + word}
        await session_manager.append_turn(session_id, user_content=message, assistant_segments=[{
            "content": answer,
            "artifacts": [],
        }])
        if is_first:
            title, title_call = await _generate_title(message)
            session_manager.update_title(session_id, title)
            yield {"type": "llm_call", "call": title_call}
            yield {"type": "title", "session_id": session_id, "title": title}
        yield {"type": "done", "session_id": session_id, "artifacts": [], "answer": answer}
        return

    if len(plan.tasks) == 0:
        yield {"type": "error", "error": "No agents selected for this query."}
        return

    # For multi-task plans, fall back to non-streaming execution
    if len(plan.tasks) > 1:
        results = await _execute(plan, agents)
        answer, synth_call = await _synthesize(message, results)
        yield {"type": "llm_call", "call": synth_call}
        artifacts = [artifact for _, _, artifact in results]
        saved = await session_manager.append_turn(session_id, user_content=message, assistant_segments=[{
            "content": answer,
            "artifacts": [{"type": a.type, "data": a.data} for a in artifacts],
        }])
        if is_first:
            title, title_call = await _generate_title(message)
            session_manager.update_title(session_id, title)
            yield {"type": "llm_call", "call": title_call}
            yield {"type": "title", "session_id": session_id, "title": title}
        yield {"type": "done", "session_id": session_id, "artifacts": saved, "answer": answer}
        return

    task = plan.tasks[0]
    defn = agents.get(task.agent)
    if defn is None:
        yield {"type": "error", "error": f"No agent available for '{task.agent}'."}
        return

    kwargs: dict = {"message": task.question}
    if defn.system_notes:
        kwargs["system_notes"] = defn.system_notes
    if officer_id:
        kwargs["officer_id"] = officer_id

    collected_answer = ""
    artifact: Optional[Artifact] = None

    if defn.streaming_handler is not None:
        async for event in defn.streaming_handler(**kwargs):
            if event.get("type") == "final":
                collected_answer = event.get("content", "")
                locations = event.get("locations", {})
                raw = event.get("raw")
                artifact = Artifact(type="taxi_data", data={"raw": raw, "locations": locations})
            elif event.get("type") == "llm_call":
                # Agent emitted its own llm_call capture — tag with agent name and forward
                call = event["call"]
                call["agent"] = task.agent
                yield {"type": "llm_call", "call": call}
            else:
                yield event
    else:
        # Non-streaming fallback: emit synthetic start/done events
        yield {"type": "tool_start", "tool": task.agent, "input": {}}
        if defn.supports_request_id:
            kwargs["request_id"] = str(uuid.uuid4())
        collected_answer, artifact = await defn.handler(**kwargs)
        yield {"type": "tool_end", "tool": task.agent, "output": collected_answer[:200]}

    artifacts = [artifact] if artifact else []
    saved = await session_manager.append_turn(session_id, user_content=message, assistant_segments=[{
        "content": collected_answer,
        "artifacts": [{"type": a.type, "data": a.data} for a in artifacts],
    }])

    # Single-agent synthesizer skipped — emit skipped call for completeness
    _, synth_call = await _synthesize(message, [(task.agent, collected_answer, artifacts[0] if artifacts else Artifact(type="error", data={}))])
    yield {"type": "llm_call", "call": synth_call}

    if is_first:
        title, title_call = await _generate_title(message)
        session_manager.update_title(session_id, title)
        yield {"type": "llm_call", "call": title_call}
        yield {"type": "title", "session_id": session_id, "title": title}

    yield {"type": "done", "session_id": session_id, "artifacts": saved, "answer": collected_answer}
