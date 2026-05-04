"""
Unified chat router — uses a Planner to decompose user queries into subtasks,
dispatches each to the right domain subagent in parallel, then synthesizes.

Adding a new domain:
  1. Write an async handler: async def _handle_X(msg) -> tuple[str, Artifact]
  2. Register it in _AGENTS with a clear description
"""

import asyncio
import logging
import os
from dataclasses import dataclass
from typing import Callable

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI
from pydantic import BaseModel

from app.models import Artifact, ChatResponse, CameraDetail
from app.services.persistence import persist_analysis

logger = logging.getLogger(__name__)

# ─── Plan types ───────────────────────────────────────────────────────────────

class SubTask(BaseModel):
    agent: str
    question: str


class Plan(BaseModel):
    tasks: list[SubTask]


# ─── Agent registry ───────────────────────────────────────────────────────────

@dataclass
class AgentDef:
    description: str
    handler: Callable


# ─── Domain handlers ──────────────────────────────────────────────────────────

async def _handle_taxi(message: str) -> tuple[str, Artifact]:
    from app.domains.taxi.agent import run_taxi_agent
    try:
        answer, data = await run_taxi_agent(message)
    except Exception as exc:
        raise RuntimeError(f"Taxi agent failed: {exc}") from exc
    return answer, Artifact(type="taxi_data", data={"raw": data})


_MOCK_TRAFFIC_RESPONSE = {
    "answer": "The CTE is not jammed. Traffic is flowing moderately in some areas, while other sections are experiencing free-flow conditions. Overall, vehicle density is normal, and there are no incidents reported.",
    "view_type": "corridor",
    "cameras": [
        {"cameraId": 1701, "locationName": None, "latitude": 1.32360482, "longitude": 103.8587802, "latestImage": "https://images.data.gov.sg/api/traffic-images/2026/03/6a959f48-4b32-463d-988a-d12576b38d6d.jpg", "timestamp": "2026-03-24T17:01:11+08:00", "resolution": "HD", "analysis": {"congestion": "moderate", "vehicleDensity": "normal", "incidents": "none", "weather": "clear", "roadSurface": "dry", "summary": "Traffic is flowing moderately on the CTE with a normal density of vehicles and clear weather conditions."}},
        {"cameraId": 1703, "locationName": None, "latitude": 1.32814722, "longitude": 103.86220328, "latestImage": "https://images.data.gov.sg/api/traffic-images/2026/03/1cb14b17-8ebb-49d9-847f-6f8fe2abc8de.jpg", "timestamp": "2026-03-24T17:01:11+08:00", "resolution": "HD", "analysis": {"congestion": "free_flow", "vehicleDensity": "normal", "incidents": "none", "weather": "clear", "roadSurface": "dry", "summary": "Traffic is flowing smoothly with a normal density of vehicles on the CTE expressway."}},
    ],
}


async def _handle_traffic_cameras(message: str) -> tuple[str, Artifact]:
    if os.environ.get("MOCK_TRAFFIC_CHAT", "").lower() == "true":
        logger.info("MOCK_TRAFFIC_CHAT enabled — returning hardcoded response")
        mock = _MOCK_TRAFFIC_RESPONSE
        return mock["answer"], Artifact(
            type="traffic_cameras",
            data={"view_type": mock["view_type"], "cameras": mock["cameras"]},
        )

    from app.domains.traffic.camera_pipeline import run_traffic_chat
    result = await run_traffic_chat(message)
    cameras: list[CameraDetail] = result.get("cameras", [])

    asyncio.gather(
        *[
            persist_analysis(str(cam.cameraId), cam.analysis)
            for cam in cameras
            if cam.analysis is not None
        ],
        return_exceptions=True,
    )

    return result["answer"], Artifact(
        type="traffic_cameras",
        data={
            "view_type": result["view_type"],
            "cameras": [c.model_dump(by_alias=True) for c in cameras],
        },
    )


# ─── Registry (add new domains here) ─────────────────────────────────────────

_AGENTS: dict[str, AgentDef] = {
    "taxi": AgentDef(
        description="taxi availability, counts, distribution, hotspots, historical trends by zone or location",
        handler=_handle_taxi,
    ),
    "traffic-cameras": AgentDef(
        description="traffic cameras, road conditions, congestion levels, expressway status, incidents",
        handler=_handle_traffic_cameras,
    ),
}

# ─── Planner ──────────────────────────────────────────────────────────────────

async def _plan(message: str) -> Plan:
    descriptions = "\n".join(
        f"- {name}: {defn.description}" for name, defn in _AGENTS.items()
    )
    system = f"""You are a query planner. Decompose the user's question into subtasks.
For each subtask, pick the most relevant agent and write a focused sub-question tailored to that agent.
Only include agents that are genuinely needed to answer the question.

Available agents:
{descriptions}"""

    llm = ChatOpenAI(model="gpt-4o-mini", temperature=0)
    structured = llm.with_structured_output(Plan)
    return await structured.ainvoke([
        SystemMessage(content=system),
        HumanMessage(content=message),
    ])


# ─── Executor ─────────────────────────────────────────────────────────────────

async def _execute(plan: Plan) -> list[tuple[str, str, Artifact]]:
    """Run all subtasks in parallel. Returns list of (agent_name, answer, artifact)."""
    async def run_one(task: SubTask) -> tuple[str, str, Artifact]:
        agent_def = _AGENTS.get(task.agent)
        if agent_def is None:
            logger.warning("Planner requested unknown agent '%s', skipping", task.agent)
            return task.agent, f"No agent available for '{task.agent}'.", Artifact(type="error", data={})
        answer, artifact = await agent_def.handler(task.question)
        return task.agent, answer, artifact

    return list(await asyncio.gather(*[run_one(t) for t in plan.tasks]))


# ─── Synthesizer ──────────────────────────────────────────────────────────────

async def _synthesize(original_question: str, results: list[tuple[str, str, Artifact]]) -> str:
    if len(results) == 1:
        return results[0][1]

    parts = "\n\n".join(
        f"[{agent}]\n{answer}" for agent, answer, _ in results
    )
    system = (
        "You are a synthesis assistant. Combine the following domain-specific answers "
        "into one coherent, concise response that directly addresses the user's original question. "
        "Highlight any correlations or insights that span multiple domains."
    )
    llm = ChatOpenAI(model="gpt-4o-mini", temperature=0)
    response = await llm.ainvoke([
        SystemMessage(content=system),
        HumanMessage(content=f"Original question: {original_question}\n\n{parts}"),
    ])
    return response.content


# ─── Public entry point ───────────────────────────────────────────────────────

async def route_and_execute(message: str) -> ChatResponse:
    plan = await _plan(message)
    logger.info("Plan: %s", [(t.agent, t.question) for t in plan.tasks])

    results = await _execute(plan)
    answer = await _synthesize(message, results)

    artifacts = [artifact for _, _, artifact in results]
    return ChatResponse(answer=answer, artifacts=artifacts)
