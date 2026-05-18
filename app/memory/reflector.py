from typing import Optional
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI

_SYSTEM = """\
You are an expert at analyzing AI agent execution traces and extracting reusable lessons.
Your output must be ONE actionable rule (≤ 2 sentences) about TOOL SELECTION STRATEGY.

Rules for your output:
- Must be GENERALIZABLE (applies to similar queries, not just this exact one).
- Must describe the PROCESS (which tool to call first, and why), not the answer.
- Written as a tip for the agent, e.g. "When the location may be a road, call resolve_zone first..."
- If the execution was already optimal (no failed steps), respond with exactly: OPTIMAL
- Do not mention specific place names or counts from this run.
"""

_USER_TEMPLATE = """\
Sub-question: {question}

Failed steps (wasted iterations):
{failed}

Successful path (what actually worked):
{success}
"""


async def reflect(question: str, extracted: dict) -> Optional[str]:
    """Returns a generalizable hint string, or None if execution was already optimal."""
    if not extracted["failed_steps"]:
        return None

    failed_str  = "\n".join(
        f"  - {s['tool']}() → error: {s['error']}" for s in extracted["failed_steps"]
    )
    success_str = "\n".join(
        f"  - {s['tool']}()" for s in extracted["success_path"]
    )

    llm = ChatOpenAI(model="gpt-4o-mini", temperature=0)
    response = await llm.ainvoke([
        SystemMessage(content=_SYSTEM),
        HumanMessage(content=_USER_TEMPLATE.format(
            question=question,
            failed=failed_str or "  (none)",
            success=success_str or "  (none)",
        )),
    ])
    hint = response.content.strip()
    return None if hint == "OPTIMAL" else hint
