import logging
import os
from typing import Optional

import httpx
from langchain_core.tools import tool

from app.domains.taxi.models import (
    SpatialQueryData,
    TimelineData,
    ZoneResolveResult,
)
from app.domains.taxi.store import location_store_var

logger = logging.getLogger(__name__)


def _java_base() -> str:
    return os.environ.get("JAVA_BACKEND_API_URL", "http://localhost:8080")


def _unwrap(response: dict) -> dict:
    """Strip the Java API success envelope — return the data field."""
    if isinstance(response, dict) and "data" in response:
        return response["data"]
    return response


def _offload_spatial(result: SpatialQueryData) -> SpatialQueryData:
    """Move locations out of the model and into the LocationStore.

    Returns a copy with locations=None and locations_ref set.
    If no store is active (e.g. in tests), returns the original unchanged.
    """
    if result.locations is None:
        return result
    try:
        store = location_store_var.get()
    except LookupError:
        return result
    ref_id = store.put(result.locations.model_dump())
    return result.model_copy(update={"locations": None, "locations_ref": ref_id})


def _offload_timeline(result: TimelineData) -> TimelineData:
    """Move per-snapshot locations into the LocationStore.

    Returns a copy where each SnapshotEntry has locations=None and locations_ref set.
    """
    try:
        store = location_store_var.get()
    except LookupError:
        return result
    new_snapshots = []
    for snapshot in result.snapshots:
        if snapshot.locations is not None:
            ref_id = store.put(snapshot.locations.model_dump())
            new_snapshots.append(
                snapshot.model_copy(update={"locations": None, "locations_ref": ref_id})
            )
        else:
            new_snapshots.append(snapshot)
    return result.model_copy(update={"snapshots": new_snapshots})


@tool
async def resolve_zone(name: str) -> ZoneResolveResult:
    """Fuzzy-match a Singapore place name to a canonical zone name and recommended API endpoint.
    Use when unsure whether a name is a district, road, or highway.
    """
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.get(f"{_java_base()}/api/v1/zones/resolve", params={"name": name})
        resp.raise_for_status()
        return ZoneResolveResult.model_validate(_unwrap(resp.json()))


@tool
async def count_taxis_in_zone(
    zone_name: str,
    datetime: Optional[str] = None,
) -> SpatialQueryData:
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
        data = _unwrap(resp.json())
        data.setdefault("context", {})["type"] = "zone"
        return _offload_spatial(SpatialQueryData.model_validate(data))


@tool
async def count_taxis_nearby(
    lat: float,
    lon: float,
    radius_m: int = 1000,
    limit: int = 100,
    datetime: Optional[str] = None,
) -> SpatialQueryData:
    """Count taxis within radius_m metres of a lat/lon coordinate.
    Use after geocode_place for questions like 'taxis near [place name]'.
    """
    params: dict = {"lat": lat, "lon": lon, "radius": radius_m, "limit": limit}
    if datetime:
        params["datetime"] = datetime
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.get(f"{_java_base()}/api/v1/taxis/nearby", params=params)
        resp.raise_for_status()
        data = _unwrap(resp.json())
        data.setdefault("context", {})["type"] = "radius"
        return _offload_spatial(SpatialQueryData.model_validate(data))


@tool
async def find_nearest_taxis(
    lat: float,
    lon: float,
    limit: int = 5,
    datetime: Optional[str] = None,
) -> SpatialQueryData:
    """Find the N nearest taxis to a lat/lon coordinate, with distances.
    Use for 'nearest taxi to [place]' questions after geocoding.
    """
    params: dict = {"lat": lat, "lon": lon, "limit": limit}
    if datetime:
        params["datetime"] = datetime
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.get(f"{_java_base()}/api/v1/taxis/nearest", params=params)
        resp.raise_for_status()
        data = _unwrap(resp.json())
        data.setdefault("context", {})["type"] = "nearest"
        return _offload_spatial(SpatialQueryData.model_validate(data))


@tool
async def count_taxis_near_road(
    road_name: str,
    buffer_m: int = 100,
    datetime: Optional[str] = None,
) -> SpatialQueryData:
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
        data = _unwrap(resp.json())
        data.setdefault("context", {})["type"] = "road"
        return _offload_spatial(SpatialQueryData.model_validate(data))


@tool
async def get_taxi_history(
    start: str,
    end: str,
    zone: Optional[str] = None,
) -> TimelineData:
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
        return _offload_timeline(TimelineData.model_validate(_unwrap(resp.json())))


@tool
async def get_recent_taxi_activity(minutes: int = 15) -> TimelineData:
    """Get taxi activity over the last N minutes (default 15, max 1440).
    Use for recent trend or 'past hour' questions.
    """
    async with httpx.AsyncClient(timeout=15.0) as client:
        resp = await client.get(
            f"{_java_base()}/api/v1/taxis/history/recent",
            params={"minutes": minutes},
        )
        resp.raise_for_status()
        return _offload_timeline(TimelineData.model_validate(_unwrap(resp.json())))
