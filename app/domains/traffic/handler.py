"""Domain handler adapter — uniform (answer, Artifact) interface for the chat router."""

import asyncio
import logging
import os
from typing import Optional

from app.models import Artifact, CameraDetail
from app.services.persistence import persist_analysis

logger = logging.getLogger(__name__)

_MOCK_TRAFFIC_RESPONSE = {
    "answer": "The CTE is not jammed. Traffic is flowing moderately in some areas, while other sections are experiencing free-flow conditions. Overall, vehicle density is normal, and there are no incidents reported.",
    "view_type": "corridor",
    "cameras": [
        {"cameraId": 1701, "locationName": None, "latitude": 1.32360482, "longitude": 103.8587802, "latestImage": "https://images.data.gov.sg/api/traffic-images/2026/03/6a959f48-4b32-463d-988a-d12576b38d6d.jpg", "timestamp": "2026-03-24T17:01:11+08:00", "resolution": "HD", "analysis": {"congestion": "moderate", "vehicleDensity": "normal", "incidents": "none", "weather": "clear", "roadSurface": "dry", "summary": "Traffic is flowing moderately on the CTE with a normal density of vehicles and clear weather conditions."}},
        {"cameraId": 1703, "locationName": None, "latitude": 1.32814722, "longitude": 103.86220328, "latestImage": "https://images.data.gov.sg/api/traffic-images/2026/03/1cb14b17-8ebb-49d9-847f-6f8fe2abc8de.jpg", "timestamp": "2026-03-24T17:01:11+08:00", "resolution": "HD", "analysis": {"congestion": "free_flow", "vehicleDensity": "normal", "incidents": "none", "weather": "clear", "roadSurface": "dry", "summary": "Traffic is flowing smoothly with a normal density of vehicles on the CTE expressway."}},
    ],
}


async def handle(
    message: str,
    system_notes: str = "",
    officer_id: Optional[str] = None,
) -> tuple[str, Artifact]:
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
