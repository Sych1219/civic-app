import logging
import os

import httpx

from app.models import CameraDetail

logger = logging.getLogger(__name__)

JAVA_BACKEND_API_URL = os.environ.get("JAVA_BACKEND_API_URL", "http://localhost:8080")
_TIMEOUT = 15.0


async def fetch_all_cameras() -> list[CameraDetail]:
    """Fetch all cameras with their latest snapshots."""
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        resp = await client.get(f"{JAVA_BACKEND_API_URL}/api/cameras")
        resp.raise_for_status()
        return [CameraDetail(**c) for c in resp.json()["data"]["cameras"]]


async def fetch_camera_detail(camera_id: str) -> CameraDetail:
    """Fetch a single camera by ID with its latest snapshot."""
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        resp = await client.get(f"{JAVA_BACKEND_API_URL}/api/cameras/{camera_id}")
        resp.raise_for_status()
        return CameraDetail(**resp.json()["data"])


async def fetch_expressway(code: str) -> list[CameraDetail]:
    """Fetch all cameras along a given expressway corridor (e.g. CTE, BKE, PIE)."""
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        resp = await client.get(f"{JAVA_BACKEND_API_URL}/api/cameras/expressway/{code}")
        resp.raise_for_status()
        return [CameraDetail(**c) for c in resp.json()["data"]["cameras"]]


async def fetch_nearby(lat: float, lng: float, radius: int = 1000) -> list[CameraDetail]:
    """Fetch cameras within `radius` metres of the given GPS coordinate."""
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        resp = await client.get(
            f"{JAVA_BACKEND_API_URL}/api/cameras/nearby",
            params={"lat": lat, "lng": lng, "radius": radius},
        )
        resp.raise_for_status()
        return [CameraDetail(**c) for c in resp.json()["data"]["cameras"]]


async def search_cameras(query: str) -> list[CameraDetail]:
    """Search cameras by location name."""
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        resp = await client.get(
            f"{JAVA_BACKEND_API_URL}/api/cameras/search",
            params={"q": query},
        )
        resp.raise_for_status()
        return [CameraDetail(**c) for c in resp.json()["data"]["cameras"]]
