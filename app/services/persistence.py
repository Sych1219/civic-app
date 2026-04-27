import logging
import os

import httpx

from app.models import CameraAnalysis

logger = logging.getLogger(__name__)


async def persist_analysis(camera_id: str, analysis: CameraAnalysis) -> None:
    java_api_base = os.environ.get("JAVA_BACKEND_API_URL", "http://localhost:8080")
    payload = {
        "congestion": analysis.congestion,
        "vehicleDensity": analysis.vehicle_density,
        "incidents": analysis.incidents,
        "weather": analysis.weather,
        "roadSurface": analysis.road_surface,
        "summary": analysis.summary,
    }
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(
                f"{java_api_base}/api/cameras/{camera_id}/analysis",
                json=payload,
            )
            resp.raise_for_status()
            logger.info("Persisted analysis for camera %s", camera_id)
    except Exception as exc:
        logger.warning("Failed to persist analysis for camera %s: %s", camera_id, exc)
