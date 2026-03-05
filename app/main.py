import logging
import os
import time
from contextlib import asynccontextmanager
from typing import Any, Dict

import httpx
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from app.agent import get_agent
from app.models import HealthResponse, QueryRequest, QueryResponse

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
        # LangGraph agents use message-based I/O
        result = await agent.ainvoke({"messages": [("human", request.query)]})
    except Exception as exc:
        logger.error("Agent invocation failed: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc))

    elapsed_ms = int((time.monotonic() - t0) * 1000)

    # Extract final answer from the last AI message
    messages = result.get("messages", [])
    answer = ""
    for msg in reversed(messages):
        if getattr(msg, "type", None) == "ai" and msg.content:
            answer = msg.content if isinstance(msg.content, str) else str(msg.content)
            break

    # Extract raw data from the last tool message (best-effort)
    import json
    raw_data: Dict[str, Any] | None = None
    for msg in reversed(messages):
        if getattr(msg, "type", None) == "tool":
            try:
                parsed = json.loads(msg.content)
                raw_data = parsed.get("raw_data")
            except (json.JSONDecodeError, ValueError, TypeError):
                pass
            break

    return QueryResponse(
        answer=answer,
        data=raw_data,
        metadata={"execution_time_ms": elapsed_ms},
    )


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
