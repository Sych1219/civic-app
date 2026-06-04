import json
import logging
import os
from dataclasses import asdict
from typing import Optional

import httpx

from .events import TrajectoryEvent

logger = logging.getLogger(__name__)

_BASE    = os.environ.get("GOV_DATA_URL", "http://localhost:8080")
_TIMEOUT = 5.0


class MemoryClient:
    """Async HTTP client wrapping the gov-data /api/v1/agent-memory endpoints."""

    async def save_trajectory(
        self,
        request_id: str,
        agent: str,
        question: str,
        events: list[TrajectoryEvent],
        iterations: int,
    ) -> None:
        events_json = json.dumps([
            {**asdict(e), "event_type": e.event_type.value}
            for e in events
        ])
        await self._post("/trajectories", {
            "id":         request_id,
            "agent":      agent,
            "question":   question,
            "eventsJson": events_json,
            "iterations": iterations,
        })

    async def get_hints(self, agent: str, status: str | None = None) -> list[dict]:
        params: dict = {"agent": agent}
        if status is not None:
            params["status"] = status
        async with httpx.AsyncClient(base_url=_BASE, timeout=_TIMEOUT) as http:
            resp = await http.get("/api/v1/agent-memory/hints", params=params)
            resp.raise_for_status()
            return resp.json()["data"]

    async def insert_hint(
        self, agent: str, body: str, embedding: list[float], status: str = "pending"
    ) -> str:
        payload: dict = {
            "agent":         agent,
            "body":          body,
            "embeddingJson": json.dumps(embedding),
        }
        if status != "pending":
            payload["status"] = status
        resp_data = await self._post("/hints", payload)
        return resp_data["id"]

    async def update_hint(self, hint_id: str, **fields) -> None:
        payload = {}
        if "status" in fields:
            payload["status"] = fields["status"]
        if "seen_count" in fields:
            payload["seenCount"] = fields["seen_count"]
        async with httpx.AsyncClient(base_url=_BASE, timeout=_TIMEOUT) as http:
            resp = await http.patch(
                f"/api/v1/agent-memory/hints/{hint_id}", json=payload
            )
            resp.raise_for_status()

    async def insert_observation(
        self,
        hint_id: str,
        request_id: str,
        hint_present: bool,
        iterations: int,
        success: bool,
    ) -> None:
        await self._post(f"/hints/{hint_id}/observations", {
            "requestId":   request_id,
            "hintPresent": hint_present,
            "iterations":  iterations,
            "success":     success,
        })

    async def get_observations(self, hint_id: str) -> list[dict]:
        async with httpx.AsyncClient(base_url=_BASE, timeout=_TIMEOUT) as http:
            resp = await http.get(
                f"/api/v1/agent-memory/hints/{hint_id}/observations"
            )
            resp.raise_for_status()
            return resp.json()["data"]

    async def _post(self, path: str, payload: dict) -> Optional[dict]:
        async with httpx.AsyncClient(base_url=_BASE, timeout=_TIMEOUT) as http:
            resp = await http.post(
                f"/api/v1/agent-memory{path}", json=payload
            )
            resp.raise_for_status()
            body = resp.json()
            return body.get("data")
