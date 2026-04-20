"""
Unified chat router — classifies the user message, dispatches to the right
domain handler, and returns a ChatResponse with typed artifacts.

Adding a new domain:
  1. Write an async handler: async def _handle_X(msg) -> tuple[str, Artifact]
  2. Register it: _HANDLERS["X"] = _handle_X
  3. Add "X" to _CLASSIFY_SYSTEM so the LLM knows it exists.
"""

import asyncio
import logging
import os
from typing import Literal

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI
from pydantic import BaseModel

from app.models import Artifact, ChatResponse, CameraDetail
from app.persistence import persist_analysis

logger = logging.getLogger(__name__)

# ─── Domain classification ────────────────────────────────────────────────────

DomainType = Literal["taxi", "traffic-cameras"]

_CLASSIFY_SYSTEM = """Classify the user's query into exactly one domain:
- taxi: taxi availability, taxi counts, taxis near a location
- traffic-cameras: traffic cameras, road conditions, congestion, expressway status"""


class _DomainClassification(BaseModel):
    domain: DomainType


async def _classify_domain(message: str) -> DomainType:
    llm = ChatOpenAI(model="gpt-4o-mini", temperature=0)
    structured = llm.with_structured_output(_DomainClassification)
    result = await structured.ainvoke([
        SystemMessage(content=_CLASSIFY_SYSTEM),
        HumanMessage(content=message),
    ])
    return result.domain


# ─── Domain handlers ──────────────────────────────────────────────────────────

async def _handle_taxi(message: str) -> tuple[str, Artifact]:
    from app.agent import run_taxi_agent
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

    from app.traffic_agent import run_traffic_chat
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

_HANDLERS = {
    "taxi": _handle_taxi,
    "traffic-cameras": _handle_traffic_cameras,
}


# ─── Public entry point ───────────────────────────────────────────────────────

async def route_and_execute(message: str) -> ChatResponse:
    domain = await _classify_domain(message)
    logger.info("Classified domain: %s", domain)
    answer, artifact = await _HANDLERS[domain](message)
    return ChatResponse(answer=answer, artifacts=[artifact])
