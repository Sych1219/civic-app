"""Domain handler adapter — uniform (answer, Artifact) interface for the chat router."""

import logging
from typing import AsyncGenerator, Optional

from app.models import Artifact

logger = logging.getLogger(__name__)


async def handle(
    message: str,
    request_id: Optional[str] = None,
    system_notes: str = "",
    officer_id: Optional[str] = None,
) -> tuple[str, Artifact]:
    from app.domains.taxi.agent import run_taxi_agent
    try:
        answer, raw, locations = await run_taxi_agent(
            message,
            request_id=request_id,
            system_notes=system_notes,
            officer_id=officer_id,
        )
    except Exception as exc:
        raise RuntimeError(f"Taxi agent failed: {exc}") from exc
    return answer, Artifact(type="taxi_data", data={"raw": raw, "locations": locations})


async def handle_streaming(
    message: str,
    system_notes: str = "",
    officer_id: Optional[str] = None,
) -> AsyncGenerator[dict, None]:
    from app.domains.taxi.agent import run_taxi_agent_streaming
    async for event in run_taxi_agent_streaming(
        message,
        system_notes=system_notes,
        officer_id=officer_id,
    ):
        yield event
