import json
import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path

import httpx
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse

from app.routers.chat import route_and_execute, route_and_execute_streaming
from app.models import AnalyzeCameraRequest, AnalyzeCameraResponse, ChatRequest, ChatResponse
from app.services.persistence import persist_analysis
from app.domains.traffic.camera_pipeline import analyze_camera_from_url

load_dotenv()

logging.basicConfig(
    level=os.environ.get("LOG_LEVEL", "INFO").upper(),
    format="%(asctime)s %(levelname)s %(name)s — %(message)s",
)

_trace_handler = logging.StreamHandler()
_trace_handler.setFormatter(
    logging.Formatter("%(filename)s:%(funcName)s:%(lineno)-4d %(message)s")
)
_trace_logger = logging.getLogger("trace")
_trace_logger.addHandler(_trace_handler)
_trace_logger.setLevel(logging.INFO)
_trace_logger.propagate = False

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Scan and load domain plugins
    from app.domains.scanner import scan_domains
    domains_path = Path(__file__).parent / "domains"
    app.state.domains = scan_domains(domains_path)
    logger.info("Loaded %d domains: %s", len(app.state.domains), list(app.state.domains))

    # Initialise session manager
    from app.sessions.manager import _init
    _sm = _init(Path(__file__).parent.parent / "sessions")
    logger.info("SessionManager initialised at: %s", _sm.sessions_dir)

    yield


app = FastAPI(
    title="Civic App — Singapore",
    version="2.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Register sessions router
from app.routers import sessions as sessions_router
app.include_router(sessions_router.router)


def _load_mock_chat_response() -> ChatResponse:
    mock_path = os.path.join(os.path.dirname(__file__), "mock_chat_response.json")
    with open(mock_path, encoding="utf-8") as f:
        return ChatResponse.model_validate_json(f.read())

_MOCK_CHAT_RESPONSE = _load_mock_chat_response()

_SSE_ENABLED = os.environ.get("SSE_ENABLED", "true").lower() == "true"


@app.post("/api/v1/chat")
async def chat(request: ChatRequest, req: Request):
    """Natural language query — routes to the appropriate domain agent."""
    if os.environ.get("MOCK_CHAT", "").lower() == "true":
        logger.info("MOCK_CHAT enabled — returning hardcoded response")
        return _MOCK_CHAT_RESPONSE

    agents = req.app.state.domains

    if _SSE_ENABLED:
        async def _event_stream():
            try:
                async for event in route_and_execute_streaming(
                    request.message,
                    agents,
                    session_id=request.session_id,
                    officer_id=request.officer_id,
                ):
                    yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
            except Exception as exc:
                logger.error("Streaming chat failed: %s", exc, exc_info=True)
                yield f"data: {json.dumps({'type': 'error', 'error': str(exc)})}\n\n"

        return StreamingResponse(
            _event_stream(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    try:
        return await route_and_execute(
            request.message,
            agents,
            session_id=request.session_id,
            officer_id=request.officer_id,
        )
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
