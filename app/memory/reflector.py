from typing import Optional
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI
from pydantic import BaseModel

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


class FeedbackReflection(BaseModel):
    hint: str
    experience_slug: str
    experience_body: str


_FB_SYSTEM = """\
You are a domain knowledge extractor for an urban analytics AI assistant.
Given an analyst's question, the AI's answer, and optional analyst feedback on what was wrong,
produce the following:

1. hint: ONE actionable rule (≤2 sentences) about TOOL SELECTION STRATEGY,
   generalizable to similar queries. Written as a tip for the agent, e.g.
   "When querying weekend patterns, filter by day-of-week before aggregating..."
   Must be about PROCESS (which tool / filter to apply first), not the answer content.

2. experience_slug: a kebab-case filename slug (lowercase, hyphens only, no numbers, no .md),
   e.g. "weekend-traffic-pattern"

3. experience_body: 1-3 paragraphs of domain knowledge a future agent should know about
   this topic area. Focus on the domain insight, not the specific tool failure.
"""


async def reflect_from_user_feedback(
    question: str,
    answer: str,
    comment: str | None,
) -> FeedbackReflection:
    user_msg = f"Question: {question}\n\nAI Answer: {answer}"
    if comment:
        user_msg += f"\n\nAnalyst feedback: {comment}"
    llm = ChatOpenAI(model="gpt-4o-mini", temperature=0)
    return await llm.with_structured_output(FeedbackReflection).ainvoke([
        SystemMessage(content=_FB_SYSTEM),
        HumanMessage(content=user_msg),
    ])
