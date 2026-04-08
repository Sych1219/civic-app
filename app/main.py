import asyncio
import logging
import os
import time
from contextlib import asynccontextmanager
from typing import Any, Dict

import httpx
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from app.agent import get_agent, get_last_raw_data
from app.models import AnalyzeCameraRequest, AnalyzeCameraResponse, CameraAnalysis, HealthResponse, QueryRequest, QueryResponse, TrafficChatRequest, TrafficChatResponse
from app.traffic_agent import analyze_camera_from_url, run_traffic_chat

load_dotenv()

logging.basicConfig(
    level=os.environ.get("LOG_LEVEL", "INFO").upper(),
    format="%(asctime)s %(levelname)s %(name)s — %(message)s",
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    java_api_base = os.environ.get("JAVA_SPATIAL_API_URL", "http://localhost:8080")
    try:
        get_agent()
        logger.info("Agent pre-warmed successfully.")
    except Exception as exc:
        logger.warning(
            "Agent pre-warm failed (Java service at %s may not be reachable yet): %s",
            java_api_base,
            exc,
        )
    yield


app = FastAPI(
    title="Taxi Spatial Q&A — Singapore",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.post("/api/v1/query", response_model=QueryResponse)
async def query(request: QueryRequest):
    """Answer a natural-language question about real-time Singapore taxi availability."""
    try:
        agent = get_agent()
    except Exception as exc:
        raise HTTPException(
            status_code=503,
            detail=f"Agent unavailable — Java service may not be running: {exc}",
        )

    t0 = time.monotonic()
    try:
        result = await agent.ainvoke({"input": request.query})
    except Exception as exc:
        logger.error("Agent invocation failed: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc))

    elapsed_ms = int((time.monotonic() - t0) * 1000)

    answer = result.get("output", "")

    raw_data: Dict[str, Any] | None = get_last_raw_data()

    return QueryResponse(
        answer=answer,
        data=raw_data,
        metadata={"execution_time_ms": elapsed_ms, "llm_latency_ms": None},
    )


_MOCK_TRAFFIC_RESPONSE = {
    "answer": "The CTE is not jammed. Traffic is flowing moderately in some areas, while other sections are experiencing free-flow conditions. Overall, vehicle density is normal, and there are no incidents reported.",
    "view_type": "corridor",
    "cameras": [
        {"cameraId": 1701, "locationName": None, "latitude": 1.32360482, "longitude": 103.8587802, "latestImage": "https://images.data.gov.sg/api/traffic-images/2026/03/6a959f48-4b32-463d-988a-d12576b38d6d.jpg", "timestamp": "2026-03-24T17:01:11+08:00", "resolution": "HD", "analysis": {"congestion": "moderate", "vehicle_density": "normal", "incidents": "none", "weather": "clear", "road_surface": "dry", "summary": "Traffic is flowing moderately on the CTE with a normal density of vehicles and clear weather conditions."}},
        {"cameraId": 1703, "locationName": None, "latitude": 1.32814722, "longitude": 103.86220328, "latestImage": "https://images.data.gov.sg/api/traffic-images/2026/03/1cb14b17-8ebb-49d9-847f-6f8fe2abc8de.jpg", "timestamp": "2026-03-24T17:01:11+08:00", "resolution": "HD", "analysis": {"congestion": "free_flow", "vehicle_density": "normal", "incidents": "none", "weather": "clear", "road_surface": "dry", "summary": "Traffic is flowing smoothly with a normal density of vehicles on the CTE expressway."}},
        {"cameraId": 1704, "locationName": None, "latitude": 1.28569399, "longitude": 103.83752451, "latestImage": "https://images.data.gov.sg/api/traffic-images/2026/03/0163fbd3-5784-48fa-b6d3-d181dc391086.jpg", "timestamp": "2026-03-24T17:01:11+08:00", "resolution": "HD", "analysis": {"congestion": "light", "vehicle_density": "normal", "incidents": "none", "weather": "clear", "road_surface": "dry", "summary": "Traffic is flowing smoothly with a normal density of vehicles on the expressway."}},
        {"cameraId": 1702, "locationName": None, "latitude": 1.34355015, "longitude": 103.8601984, "latestImage": "https://images.data.gov.sg/api/traffic-images/2026/03/c3308c3f-9300-4224-af9e-18211f065294.jpg", "timestamp": "2026-03-24T17:01:11+08:00", "resolution": "HD", "analysis": {"congestion": "moderate", "vehicle_density": "normal", "incidents": "none", "weather": "clear", "road_surface": "dry", "summary": "Traffic is moving at a moderate pace with a normal density of vehicles on the CTE."}},
        {"cameraId": 1706, "locationName": None, "latitude": 1.38861, "longitude": 103.85806, "latestImage": "https://images.data.gov.sg/api/traffic-images/2026/03/5371013e-388b-4720-a08d-5db5944b6b83.jpg", "timestamp": "2026-03-24T17:01:11+08:00", "resolution": "HD", "analysis": {"congestion": "free_flow", "vehicle_density": "normal", "incidents": "none", "weather": "clear", "road_surface": "dry", "summary": "Traffic is flowing smoothly with a normal density of vehicles on the expressway."}},
        {"cameraId": 1709, "locationName": None, "latitude": 1.31384232, "longitude": 103.84560303, "latestImage": "https://images.data.gov.sg/api/traffic-images/2026/03/3c6e66fc-5cca-4d3f-bfc8-90ddf7d07ad2.jpg", "timestamp": "2026-03-24T17:01:11+08:00", "resolution": "HD", "analysis": {"congestion": "free_flow", "vehicle_density": "normal", "incidents": "none", "weather": "clear", "road_surface": "dry", "summary": "Traffic is flowing smoothly with a normal density of vehicles on the expressway."}},
        {"cameraId": 1707, "locationName": None, "latitude": 1.28036584, "longitude": 103.83045115, "latestImage": "https://images.data.gov.sg/api/traffic-images/2026/03/ff0a6bea-f3a2-4e90-9381-ca73a1c09f5f.jpg", "timestamp": "2026-03-24T17:01:11+08:00", "resolution": "HD", "analysis": {"congestion": "free_flow", "vehicle_density": "sparse", "incidents": "none", "weather": "clear", "road_surface": "dry", "summary": "The traffic is flowing freely with a sparse vehicle presence on the road."}},
        {"cameraId": 1705, "locationName": None, "latitude": 1.37592502, "longitude": 103.8587986, "latestImage": "https://images.data.gov.sg/api/traffic-images/2026/03/b5672ee8-e115-4a37-bde7-f7a7bac0998e.jpg", "timestamp": "2026-03-24T17:01:11+08:00", "resolution": "HD", "analysis": {"congestion": "free_flow", "vehicle_density": "normal", "incidents": "none", "weather": "clear", "road_surface": "dry", "summary": "Traffic is flowing freely with a normal density of vehicles on a clear day."}},
        {"cameraId": 1711, "locationName": None, "latitude": 1.35296, "longitude": 103.85719, "latestImage": "https://images.data.gov.sg/api/traffic-images/2026/03/7fcb6cce-8deb-4b0f-96ca-4b0d369ca521.jpg", "timestamp": "2026-03-24T17:01:11+08:00", "resolution": "HD", "analysis": {"congestion": "light", "vehicle_density": "normal", "incidents": "none", "weather": "clear", "road_surface": "dry", "summary": "Traffic is flowing smoothly with a normal density of vehicles on the CTE."}},
    ],
}


@app.post("/api/traffic-chat", response_model=TrafficChatResponse)
async def traffic_chat(request: TrafficChatRequest):
    """Natural language query → LLM-powered traffic camera analysis."""
    if os.environ.get("MOCK_TRAFFIC_CHAT", "").lower() == "true":
        logger.info("MOCK_TRAFFIC_CHAT enabled — returning hardcoded response")
        return TrafficChatResponse(**_MOCK_TRAFFIC_RESPONSE)

    t0 = time.monotonic()
    try:
        result = await run_traffic_chat(request.message)
    except Exception as exc:
        logger.error("Traffic chat failed: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail=str(exc))

    elapsed_ms = int((time.monotonic() - t0) * 1000)
    logger.info("Traffic chat completed in %dms", elapsed_ms)

    cameras = result.get("cameras", [])
    asyncio.gather(
        *[
            _persist_analysis(str(cam.cameraId), cam.analysis)
            for cam in cameras
            if cam.analysis is not None
        ],
        return_exceptions=True,
    )

    return TrafficChatResponse(**result)


async def _persist_analysis(camera_id: str, analysis: CameraAnalysis) -> None:
    """Fire-and-forget: push analysis to gov-data for persistence."""
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


@app.post("/api/analyze-camera", response_model=AnalyzeCameraResponse)
async def analyze_camera(request: AnalyzeCameraRequest):
    """Analyze a single camera image by URL — Phase 2 only."""
    try:
        analysis = await analyze_camera_from_url(
            request.image_url,
            request.camera_id or "",
            request.location_name or "",
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    except Exception as exc:
        logger.error("analyze-camera failed: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail=str(exc))

    if request.camera_id:
        await _persist_analysis(request.camera_id, analysis)

    return AnalyzeCameraResponse(analysis=analysis)


@app.get("/api/v1/snapshot/latest")
async def snapshot_latest():
    """Return metadata about the latest taxi snapshot from the Java service."""
    java_api_base = os.environ.get("JAVA_SPATIAL_API_URL", "http://localhost:8080")
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(f"{java_api_base}/api/v1/taxis/snapshot/latest")
            resp.raise_for_status()
            return resp.json()
    except httpx.HTTPError as exc:
        raise HTTPException(
            status_code=502,
            detail=f"Could not reach Java service: {exc}",
        )


@app.get("/api/v1/health", response_model=HealthResponse)
async def health():
    """Health check."""
    return HealthResponse(status="ok", service="taxi-spatial-qa")
