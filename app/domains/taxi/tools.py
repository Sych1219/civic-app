import json
import logging
import os
from typing import Optional

import httpx
from langchain_core.tools import tool

logger = logging.getLogger(__name__)


def _java_base() -> str:
    return os.environ.get("JAVA_BACKEND_API_URL", "http://localhost:8080")


def _unwrap(response: dict) -> dict:
    """Strip the Java API success envelope — return the data field."""
    if isinstance(response, dict) and "data" in response:
        return response["data"]
    return response


@tool
async def resolve_zone(name: str) -> str:
    """Fuzzy-match a Singapore place name to a canonical zone name and recommended API endpoint.
    Use when unsure whether a name is a district, road, or highway.
    """
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.get(f"{_java_base()}/api/v1/zones/resolve", params={"name": name})
        resp.raise_for_status()
        return json.dumps(_unwrap(resp.json()))


@tool
async def count_taxis_in_zone(zone_name: str, datetime: Optional[str] = None) -> str:
    """Count available taxis inside a named Singapore zone or district
    (e.g. 'Punggol', 'CBD', 'Changi', 'Tampines', 'Orchard').
    Use for questions like 'How many taxis in Punggol?'
    """
    params: dict = {"zoneName": zone_name}
    if datetime:
        params["datetime"] = datetime
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.get(f"{_java_base()}/api/v1/taxis/zone/count", params=params)
        resp.raise_for_status()
        return json.dumps(_unwrap(resp.json()))


@tool
async def count_taxis_nearby(
    lat: float,
    lon: float,
    radius_m: int = 1000,
    limit: int = 100,
    datetime: Optional[str] = None,
) -> str:
    """Count taxis within radius_m metres of a lat/lon coordinate.
    Use after geocode_place for questions like 'taxis near [place name]'.
    """
    params: dict = {"lat": lat, "lon": lon, "radius": radius_m, "limit": limit}
    if datetime:
        params["datetime"] = datetime
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.get(f"{_java_base()}/api/v1/taxis/nearby", params=params)
        resp.raise_for_status()
        return json.dumps(_unwrap(resp.json()))


@tool
async def find_nearest_taxis(
    lat: float,
    lon: float,
    limit: int = 5,
    datetime: Optional[str] = None,
) -> str:
    """Find the N nearest taxis to a lat/lon coordinate, with distances.
    Use for 'nearest taxi to [place]' questions after geocoding.
    """
    params: dict = {"lat": lat, "lon": lon, "limit": limit}
    if datetime:
        params["datetime"] = datetime
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.get(f"{_java_base()}/api/v1/taxis/nearest", params=params)
        resp.raise_for_status()
        return json.dumps(_unwrap(resp.json()))


@tool
async def count_taxis_near_road(
    road_name: str,
    buffer_m: int = 100,
    datetime: Optional[str] = None,
) -> str:
    """Count taxis within buffer_m metres of a named road or expressway
    (e.g. 'PIE', 'CTE', 'AYE', 'BKE', 'Orchard Road').
    Use for 'taxis near [road]' questions.
    """
    params: dict = {"roadName": road_name, "buffer_m": buffer_m}
    if datetime:
        params["datetime"] = datetime
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.get(f"{_java_base()}/api/v1/taxis/road/count", params=params)
        resp.raise_for_status()
        return json.dumps(_unwrap(resp.json()))


@tool
async def get_taxi_history(start: str, end: str, zone: Optional[str] = None) -> str:
    """Get historical taxi snapshots between start and end times (ISO-8601 SGT).
    Optionally filter to a named zone. Use for 'taxis at [time]' or trend questions.
    start and end must be within a 7-day range.
    """
    params: dict = {"start": start, "end": end}
    if zone:
        params["zone"] = zone
    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.get(f"{_java_base()}/api/v1/taxis/history/snapshots", params=params)
        resp.raise_for_status()
        return json.dumps(_unwrap(resp.json()))


@tool
async def get_recent_taxi_activity(minutes: int = 15) -> str:
    """Get taxi activity over the last N minutes (default 15, max 1440).
    Use for recent trend or 'past hour' questions.
    """
    async with httpx.AsyncClient(timeout=15.0) as client:
        resp = await client.get(
            f"{_java_base()}/api/v1/taxis/history/recent",
            params={"minutes": minutes},
        )
        resp.raise_for_status()
        return json.dumps(_unwrap(resp.json()))
