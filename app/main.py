import logging
import os
from contextlib import asynccontextmanager

import httpx
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from app.routers.chat import route_and_execute
from app.models import AnalyzeCameraRequest, AnalyzeCameraResponse, ChatRequest, ChatResponse
from app.services.persistence import persist_analysis
from app.domains.traffic.camera_pipeline import analyze_camera_from_url

load_dotenv()

logging.basicConfig(
    level=os.environ.get("LOG_LEVEL", "INFO").upper(),
    format="%(asctime)s %(levelname)s %(name)s — %(message)s",
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
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


@app.post("/api/v1/chat", response_model=ChatResponse)
async def chat(request: ChatRequest):
    """Natural language query — routes to the appropriate domain agent."""
    try:
        return await route_and_execute(request.message)
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc))
    except Exception as exc:
        logger.error("Chat failed: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail=str(exc))


@app.post("/api/analyze-camera", response_model=AnalyzeCameraResponse)
async def analyze_camera(request: AnalyzeCameraRequest):
    """Analyze a single camera image by URL."""
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
        await persist_analysis(request.camera_id, analysis)

    return AnalyzeCameraResponse(analysis=analysis)


@app.get("/api/v1/snapshot/latest")
async def snapshot_latest():
    """Return metadata about the latest taxi snapshot from the Java service."""
    java_api_base = os.environ.get("JAVA_BACKEND_API_URL", "http://localhost:8080")
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
