"""
Two-phase LangChain agent for traffic camera chat.

Phase 1 — Text-only LLM with structured output:
  Classifies view_type and decides which gov-data API to call.

Phase 2 — Vision LLM (parallelised):
  Downloads each camera image, base64-encodes it, sends to Ollama qwen3.5 vision,
  parses structured JSON analysis, then synthesises a corridor-level summary.
"""

import asyncio
import base64
import io
import json
import logging
import time
import uuid
from typing import Any, Dict, Literal, Optional

import httpx
from PIL import Image
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI
from pydantic import BaseModel

from app.models import CameraAnalysis, CameraDetail
from app.services.geocoding import geocode_place
from app.domains.traffic.tools import (
    fetch_all_cameras,
    fetch_camera_detail,
    fetch_expressway,
    fetch_nearby,
    search_cameras,
)
from app.memory.client import MemoryClient
from app.memory.events import EventCollector, EventType
from app.memory.injector import build_hint_block
from app.memory.pipeline import post_request_pipeline
from app.memory.registry import HintRegistry

logger = logging.getLogger(__name__)

_mem_client = MemoryClient()
_registry   = HintRegistry(_mem_client)


# ─── Rate limiter (token bucket) ─────────────────────────────────────────────

class _RateLimiter:
    """Token-bucket rate limiter: at most `rate` calls per `period` seconds."""

    def __init__(self, rate: int, period: float = 60.0) -> None:
        self._rate = rate
        self._period = period
        self._tokens = float(rate)
        self._last_refill = time.monotonic()
        self._lock = asyncio.Lock()

    async def acquire(self) -> None:
        async with self._lock:
            now = time.monotonic()
            elapsed = now - self._last_refill
            self._tokens = min(
                self._rate,
                self._tokens + elapsed * (self._rate / self._period),
            )
            self._last_refill = now
            if self._tokens < 1:
                wait = (1 - self._tokens) / (self._rate / self._period)
                await asyncio.sleep(wait)
                self._tokens = 0.0
            else:
                self._tokens -= 1


# 20 vision calls per minute — well within gpt-4o-mini's default RPM tier.
_vision_limiter = _RateLimiter(rate=20, period=60.0)


# ─── Exponential backoff wrapper ──────────────────────────────────────────────

async def _with_backoff(coro_fn, *, retries: int = 4, base_delay: float = 1.0):
    """Call coro_fn(), retrying on 429/rate-limit errors with exponential backoff."""
    for attempt in range(retries + 1):
        try:
            return await coro_fn()
        except Exception as exc:
            is_rate_limit = "429" in str(exc) or "rate limit" in str(exc).lower()
            if not is_rate_limit or attempt == retries:
                raise
            delay = base_delay * (2 ** attempt)
            logger.warning("Rate limit hit, retrying in %.1fs (attempt %d/%d)", delay, attempt + 1, retries)
            await asyncio.sleep(delay)


# ─── Phase 1 structured output ───────────────────────────────────────────────

ViewType = Literal["camera_map", "corridor", "camera_detail", "snapshot", "alerts"]
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
snapshot      → "Show Woodlands at 8am", historical snapshot
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

_NEEDS_VISION: set[str] = {"corridor", "camera_detail", "snapshot", "alerts"}


# ─── Phase 1 ─────────────────────────────────────────────────────────────────

async def _classify(user_message: str, hints: list[str]) -> Phase1Result:
    llm = ChatOpenAI(model="gpt-4o-mini", temperature=0)
    structured = llm.with_structured_output(Phase1Result)
    messages = [
        SystemMessage(content=_PHASE1_SYSTEM + build_hint_block(hints)),
        HumanMessage(content=user_message),
    ]
    return await structured.ainvoke(messages)


async def _fetch_cameras(
    decision: Phase1Result,
    collector: EventCollector,
) -> list[CameraDetail]:
    tool = decision.tool
    collector.emit(EventType.TOOL_CALL, 1, tool=tool, args=decision.model_dump())

    cameras: list[CameraDetail] = []
    try:
        if tool == "fetch_all_cameras":
            cameras = await fetch_all_cameras()
        elif tool == "fetch_camera_detail":
            cameras = [await fetch_camera_detail(decision.camera_id)]
        elif tool == "fetch_expressway":
            cameras = await fetch_expressway(decision.expressway_code)
        elif tool == "fetch_nearby":
            lat, lng = decision.lat, decision.lng
            if (lat is None or lng is None) and decision.place_name:
                geo = geocode_place.invoke(decision.place_name)
                try:
                    after_lat = geo.split("lat=")[1]
                    lat_str, lng_str = after_lat.split(", lng=")
                    lat, lng = float(lat_str), float(lng_str)
                except (IndexError, ValueError):
                    logger.error("Geocoding failed: %s", geo)
            cameras = await fetch_nearby(lat, lng, decision.radius)
        elif tool == "search_cameras":
            cameras = await search_cameras(decision.search_query)

        success = len(cameras) > 0
        collector.emit(EventType.TOOL_RESULT, 1, tool=tool, success=success,
                       error=None if success else "No cameras found")
    except Exception as exc:
        collector.emit(EventType.TOOL_RESULT, 1, tool=tool, success=False, error=str(exc))
        raise

    return cameras


# ─── Phase 2 ─────────────────────────────────────────────────────────────────

async def _analyze_camera(
        camera: CameraDetail,
        llm: ChatOpenAI,
        expressway_code: str = "",
        collector: Optional[EventCollector] = None,
) -> CameraDetail:
    """Download camera image, base64-encode it, send to Ollama vision, return camera with analysis."""
    if not camera.latestImage:
        return camera

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            img_resp = await client.get(camera.latestImage)
            img_resp.raise_for_status()
        img = Image.open(io.BytesIO(img_resp.content)).convert("RGB")
        img.thumbnail((640, 480))
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=85)
        image_b64 = base64.b64encode(buf.getvalue()).decode("utf-8")
    except Exception as exc:
        logger.error("Failed to download image for camera %s: %s", camera.cameraId, exc)
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
            {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{image_b64}"}},
        ])
    ]

    if collector:
        collector.emit(EventType.TOOL_CALL, 2, tool="analyze_camera",
                       args={"camera_id": camera.cameraId})
    try:
        structured_llm = llm.with_structured_output(CameraAnalysis)
        analysis: CameraAnalysis = await _with_backoff(
            lambda: structured_llm.ainvoke(messages)
        )
        if collector:
            collector.emit(EventType.TOOL_RESULT, 2, tool="analyze_camera",
                           success=True, error=None)
    except Exception as exc:
        logger.error("Vision analysis failed for camera %s: %s", camera.cameraId, exc)
        if collector:
            collector.emit(EventType.TOOL_RESULT, 2, tool="analyze_camera",
                           success=False, error=str(exc))
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


# ─── analyze-camera endpoint (Phase 2 only) ──────────────────────────────────

async def analyze_camera_from_url(
        image_url: str,
        camera_id: str = "",
        location_name: str = "",
) -> CameraAnalysis:
    """Fetch image from URL, analyze it — no Phase 1, no gov-data fetch."""
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            img_resp = await client.get(image_url)
            img_resp.raise_for_status()
        img = Image.open(io.BytesIO(img_resp.content)).convert("RGB")
        img.thumbnail((640, 480))
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=85)
        image_b64 = base64.b64encode(buf.getvalue()).decode("utf-8")
    except Exception as exc:
        raise ValueError(f"Could not fetch or decode image: {exc}") from exc

    prompt = _VISION_PROMPT.format(
        camera_id=camera_id or "N/A",
        location_name=location_name or "Unknown location",
        expressway_code="N/A",
        timestamp="N/A",
    )

    messages = [
        HumanMessage(content=[
            {"type": "text", "text": prompt},
            {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{image_b64}"}},
        ])
    ]

    llm = ChatOpenAI(model="gpt-4o-mini", temperature=0, max_retries=6)
    structured_llm = llm.with_structured_output(CameraAnalysis)
    return await structured_llm.ainvoke(messages)


# ─── Public entry point ───────────────────────────────────────────────────────

async def run_traffic_chat(
    user_message: str,
    request_id: str | None = None,
) -> Dict[str, Any]:
    """Run the two-phase traffic chat pipeline and return the response dict."""
    request_id = request_id or str(uuid.uuid4())

    hints_injected = await _registry.get_active_hints("camera", user_message)
    collector = EventCollector(request_id=request_id, agent="camera")

    try:
        result = await _run_pipeline(user_message, hints_injected, collector)
    finally:
        asyncio.create_task(post_request_pipeline(
            request_id, "camera", user_message,
            collector, hints_injected, _registry, _mem_client,
        ))

    return result


async def _run_pipeline(
    user_message: str,
    hints: list[str],
    collector: EventCollector,
) -> Dict[str, Any]:
    # Phase 1: classify + fetch
    decision: Phase1Result = await _classify(user_message, hints)
    logger.info("Phase 1 → view_type=%s  tool=%s", decision.view_type, decision.tool)

    cameras = await _fetch_cameras(decision, collector)
    logger.info("Fetched %d cameras", len(cameras))

    # Skip Phase 2 when vision is not needed or there are no cameras
    if decision.view_type not in _NEEDS_VISION or not cameras:
        collector.emit(EventType.FINAL_ANSWER, 1, iterations_used=1)
        answer = (
            f"Showing {len(cameras)} cameras."
            if cameras
            else "No cameras found for your query."
        )
        return {"answer": answer, "view_type": decision.view_type, "cameras": cameras}

    # Phase 2: vision analysis (parallelised) + synthesis
    # num_predict=256 caps output (JSON is ~100 tokens); keep_alive=-1 keeps model hot in memory
    vision_llm = ChatOpenAI(model="gpt-4o-mini", temperature=0, max_retries=6)
    # vision_llm = ChatOllama(model="qwen3.5", temperature=0, reasoning=False, num_predict=256, keep_alive=-1)
    expressway_code = decision.expressway_code or ""

    async def _analyze_with_limit(cam: CameraDetail) -> CameraDetail:
        await _vision_limiter.acquire()
        return await _analyze_camera(cam, vision_llm, expressway_code, collector)

    analyzed = list(await asyncio.gather(
        *[_analyze_with_limit(cam) for cam in cameras]
    ))

    answer = await _synthesize(user_message, analyzed)
    collector.emit(EventType.FINAL_ANSWER, 2, iterations_used=2)

    return {"answer": answer, "view_type": decision.view_type, "cameras": analyzed}
