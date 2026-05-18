import logging
from typing import Optional
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI
from .client import MemoryClient
from .embedder import embed, top_k_hints

logger = logging.getLogger(__name__)

CONFIDENCE_THRESHOLD   = 3
MIN_OBSERVATIONS       = 20
ITER_REGRESS_THRESHOLD = 0.5


class HintRegistry:
    def __init__(self, client: MemoryClient):
        self._client = client

    async def submit(self, agent: str, candidate: str) -> None:
        existing = await self._find_similar(agent, candidate)
        if existing:
            new_count = existing["seenCount"] + 1
            updates: dict = {"seen_count": new_count}
            if existing["status"] == "pending" and new_count >= CONFIDENCE_THRESHOLD:
                updates["status"] = "active"
                logger.info("[memory] hint promoted to active: %.80s", existing["body"])
            await self._client.update_hint(existing["id"], **updates)
        else:
            embedding = await embed(candidate)
            await self._client.insert_hint(agent, candidate, embedding)

    async def get_active_hints(self, agent: str, question: str) -> list[str]:
        hints = await self._client.get_all_hints(agent)
        active = [h for h in hints if h["status"] == "active"]
        if not active:
            return []
        question_emb = await embed(question)
        return top_k_hints(question_emb, active)

    async def record_observation(
        self,
        agent: str,
        request_id: str,
        hints_injected: list[str],
        iterations: int,
        success: bool,
    ) -> None:
        all_hints = await self._client.get_all_hints(agent)
        for h in all_hints:
            if h["status"] != "active":
                continue
            present = h["body"] in hints_injected
            await self._client.insert_observation(
                h["id"], request_id, present, iterations, success,
            )

    async def prune_underperforming(self, agent: str) -> None:
        hints = await self._client.get_all_hints(agent)
        for h in hints:
            if h["status"] != "active":
                continue
            obs = await self._client.get_observations(h["id"])
            if len(obs) < MIN_OBSERVATIONS:
                continue
            present = [o for o in obs if o["hintPresent"]]
            absent  = [o for o in obs if not o["hintPresent"]]
            if len(present) < 5 or len(absent) < 5:
                continue
            avg_p = sum(o["iterations"] for o in present) / len(present)
            avg_a = sum(o["iterations"] for o in absent)  / len(absent)
            if avg_p > avg_a + ITER_REGRESS_THRESHOLD:
                await self._client.update_hint(h["id"], status="retired")
                logger.info("[memory] hint retired (avg_iters %.1f vs %.1f): %.80s",
                            avg_p, avg_a, h["body"])

    _DEDUP_SYSTEM = """\
Given an existing set of agent hints and a candidate hint, decide if the candidate
is semantically equivalent to any existing hint.
Reply with the INDEX (0-based) of the matching hint, or -1 if it's novel.
Reply with a single integer only."""

    async def _find_similar(self, agent: str, candidate: str) -> Optional[dict]:
        hints = await self._client.get_all_hints(agent)
        pending_active = [h for h in hints if h["status"] in ("pending", "active")]
        if not pending_active:
            return None

        existing_text = "\n".join(
            f"{i}. {h['body']}" for i, h in enumerate(pending_active)
        )
        llm = ChatOpenAI(model="gpt-4o-mini", temperature=0)
        resp = await llm.ainvoke([
            SystemMessage(content=self._DEDUP_SYSTEM),
            HumanMessage(content=f"Existing hints:\n{existing_text}\n\nCandidate:\n{candidate}"),
        ])
        try:
            idx = int(resp.content.strip())
        except ValueError:
            return None
        if 0 <= idx < len(pending_active):
            return pending_active[idx]
        return None
