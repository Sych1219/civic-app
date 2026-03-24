"""
Two-phase LangChain agent for traffic camera chat.

Phase 1 — Text-only LLM with structured output:
  Classifies view_type and decides which gov-data API to call.

Phase 2 — Vision LLM (parallelised):
  Sends each camera image to OpenAI Vision, parses structured JSON analysis,
  then synthesises a corridor-level summary.
"""

import asyncio
import json
import logging
from typing import Any, Dict, Literal, Optional

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI
from pydantic import BaseModel

from app.models import CameraAnalysis, CameraDetail
from app.tools import geocode_place
from app.traffic_tools import (
    fetch_all_cameras,
    fetch_camera_detail,
    fetch_expressway,
    fetch_nearby,
    search_cameras,
)

logger = logging.getLogger(__name__)

# ─── Phase 1 structured output ───────────────────────────────────────────────

ViewType = Literal["camera_map", "corridor", "camera_detail", "replay", "alerts"]
ToolName = Literal[
    "fetch_all_cameras",
    "fetch_camera_detail",
    "fetch_expressway",
    "fetch_nearby",
    "search_cameras",
]


class Phase1Result(BaseModel):
    view_type: ViewType
    tool: ToolName
    # tool parameters (all optional — only the relevant ones are filled in)
    camera_id: Optional[str] = None
    expressway_code: Optional[str] = None
    lat: Optional[float] = None
    lng: Optional[float] = None
    radius: int = 1000
    search_query: Optional[str] = None
    # if tool=fetch_nearby but lat/lng are unknown, supply the place name instead
    place_name: Optional[str] = None


_PHASE1_SYSTEM = """You are a Singapore traffic assistant that routes user queries to the correct data source.

Determine:
1. view_type — which frontend component to show
2. tool — which API to call
3. Any parameters the tool needs

=== view_type values ===
camera_map    → "Show all cameras", "Which cameras are online?", general map
corridor      → "Is CTE jammed?", "BKE cameras", any expressway corridor
camera_detail → "Show camera 1005", specific camera ID
replay        → "Show Woodlands at 8am", historical replay
alerts        → "Any incidents right now?", accident scanning

=== tools ===
fetch_all_cameras  — no params. Use for camera_map and alerts.
fetch_camera_detail — camera_id required. Use for camera_detail.
fetch_expressway   — expressway_code required (e.g. "CTE", "BKE", "PIE"). Use for corridor.
fetch_nearby       — lat + lng required (floats), radius optional (metres, default 1000).
                     If the user names a place without coordinates, set place_name instead.
search_cameras     — search_query required. Use when user names a specific location.

Singapore expressways: CTE, PIE, AYE, BKE, KPE, SLE, TPE, MCE, ECP, KJE, NYCH, TUAS."""

_VISION_PROMPT = """You are a Singapore traffic analyst. Analyze this traffic camera image.

Camera: {camera_id} — {location_name}
Expressway: {expressway_code}
Time: {timestamp}

Respond with ONLY a JSON object:
{{
  "congestion": "free_flow | light | moderate | heavy | standstill",
  "vehicle_density": "empty | sparse | normal | dense | packed",
  "incidents": "none | accident | breakdown | obstruction | roadworks",
  "weather": "clear | rain | heavy_rain | fog",
  "road_surface": "dry | wet | flooded | construction",
  "summary": "One sentence describing what you see."
}}"""

_SYNTHESIS_PROMPT = """You are a Singapore traffic assistant answering a user's query.

User: {user_message}

Per-camera analyses:
{analyses}

Write a concise, helpful natural-language response that directly answers the user's question."""

_NEEDS_VISION: set[str] = {"corridor", "camera_detail", "replay", "alerts"}


# ─── Phase 1 ─────────────────────────────────────────────────────────────────

async def _classify(user_message: str) -> Phase1Result:
    llm = ChatOpenAI(model="gpt-4o-mini", temperature=0)
    structured = llm.with_structured_output(Phase1Result)
    messages = [
        SystemMessage(content=_PHASE1_SYSTEM),
        HumanMessage(content=user_message),
    ]
    return await structured.ainvoke(messages)


async def _fetch_cameras(decision: Phase1Result) -> list[CameraDetail]:
    tool = decision.tool

    if tool == "fetch_all_cameras":
        return await fetch_all_cameras()

    if tool == "fetch_camera_detail":
        return [await fetch_camera_detail(decision.camera_id)]

    if tool == "fetch_expressway":
        return await fetch_expressway(decision.expressway_code)

    if tool == "fetch_nearby":
        lat, lng = decision.lat, decision.lng
        if (lat is None or lng is None) and decision.place_name:
            geo = geocode_place.invoke(decision.place_name)
            # geo format: "place_name: lat=X, lng=Y"
            try:
                after_lat = geo.split("lat=")[1]
                lat_str, lng_str = after_lat.split(", lng=")
                lat, lng = float(lat_str), float(lng_str)
            except (IndexError, ValueError):
                logger.error("Geocoding failed: %s", geo)
                return []
        return await fetch_nearby(lat, lng, decision.radius)

    if tool == "search_cameras":
        return await search_cameras(decision.search_query)

    return []


# ─── Phase 2 ─────────────────────────────────────────────────────────────────

async def _analyze_camera(
        camera: CameraDetail,
        llm: ChatOpenAI,
        expressway_code: str = "",
) -> CameraDetail:
    """Send one camera image to the vision LLM and return the camera with analysis populated."""
    if not camera.latestImage:
        return camera

    prompt = _VISION_PROMPT.format(
        camera_id=camera.cameraId,
        location_name=camera.locationName or "Unknown location",
        expressway_code=expressway_code or "N/A",
        timestamp=camera.timestamp,
    )

    messages = [
        HumanMessage(content=[
            {"type": "text", "text": prompt},
            {"type": "image_url", "image_url": {"url": camera.latestImage}},
        ])
    ]

    try:
        structured_llm = llm.with_structured_output(CameraAnalysis)
        analysis:CameraAnalysis = await structured_llm.ainvoke(messages)

    except Exception as exc:
        logger.error("Vision analysis failed for camera %s: %s", camera.cameraId, exc)
        analysis = CameraAnalysis(
            congestion="unknown",
            vehicle_density="unknown",
            incidents="Analysis unavailable",
            weather="unknown",
            road_surface="unknown",
            summary="Could not analyse this camera.",
        )

    return camera.model_copy(update={"analysis": analysis})


async def _synthesize(
        user_message: str,
        analyzed_cameras: list[CameraDetail],
) -> str:
    analyses_text = "\n\n".join(
        "Camera {id} ({name}):\n{analysis}".format(
            id=cam.cameraId,
            name=cam.locationName or "",
            analysis=json.dumps(cam.analysis.model_dump() or {}, indent=2),
        )
        for cam in analyzed_cameras
    )

    llm = ChatOpenAI(model="gpt-4o-mini", temperature=0, max_retries=6)
    response = await llm.ainvoke([
        HumanMessage(content=_SYNTHESIS_PROMPT.format(
            user_message=user_message,
            analyses=analyses_text,
        ))
    ])
    return response.content


# ─── Public entry point ───────────────────────────────────────────────────────

async def run_traffic_chat(user_message: str) -> Dict[str, Any]:
    """Run the two-phase traffic chat pipeline and return the response dict."""

    # Phase 1: classify + fetch
    decision: Phase1Result = await _classify(user_message)
    logger.info("Phase 1 → view_type=%s  tool=%s", decision.view_type, decision.tool)

    cameras = await _fetch_cameras(decision)
    logger.info("Fetched %d cameras", len(cameras))

    # Skip Phase 2 when vision is not needed or there are no cameras
    if decision.view_type not in _NEEDS_VISION or not cameras:
        answer = (
            f"Showing {len(cameras)} cameras."
            if cameras
            else "No cameras found for your query."
        )
        return {"answer": answer, "view_type": decision.view_type, "cameras": cameras}

    # Phase 2: vision analysis (parallelised, semaphore-throttled) + synthesis
    # max_retries=6 gives exponential backoff up to ~60s, enough for TPM window recovery
    vision_llm = ChatOpenAI(model="gpt-4o-mini", temperature=0, max_retries=6)
    expressway_code = decision.expressway_code or ""
    sem = asyncio.Semaphore(3)

    async def _bounded(cam: CameraDetail) -> CameraDetail:
        async with sem:
            return await _analyze_camera(cam, vision_llm, expressway_code)

    analyzed = list(await asyncio.gather(*[_bounded(cam) for cam in cameras]))

    answer = await _synthesize(user_message, analyzed)

    return {"answer": answer, "view_type": decision.view_type, "cameras": analyzed}
