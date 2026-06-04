import asyncio
import json
from typing import Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

router = APIRouter(prefix="/api/sessions", tags=["sessions"])

_FEEDBACK_AGENT = "civic"


def _mgr():
    from app.sessions.manager import session_manager
    if session_manager is None:
        raise HTTPException(status_code=503, detail="Session manager not initialised")
    return session_manager


class FeedbackRequest(BaseModel):
    rating: Literal["up", "down"]
    comment: str | None = None


class FeedbackResponse(BaseModel):
    ok: bool
    hint_generated: bool
    experience_written: str | None


@router.get("")
async def list_sessions():
    return _mgr().list_sessions()


@router.get("/{session_id}")
async def get_session(session_id: str):
    return _mgr().load_session(session_id)


@router.delete("/{session_id}")
async def delete_session(session_id: str):
    _mgr().delete_session(session_id)
    return {"ok": True}


@router.get("/{session_id}/artifacts/{artifact_id}")
async def get_artifact(session_id: str, artifact_id: str):
    mgr = _mgr()
    path = mgr._artifact_path(session_id, artifact_id)
    if not path.exists():
        raise HTTPException(status_code=404, detail="Artifact not found")
    return json.loads(path.read_text(encoding="utf-8"))


@router.post("/{session_id}/messages/{msg_index}/feedback", response_model=FeedbackResponse)
async def submit_feedback(
    session_id: str,
    msg_index: int,
    body: FeedbackRequest,
) -> FeedbackResponse:
    mgr = _mgr()
    if not mgr._path(session_id).exists():
        raise HTTPException(status_code=404, detail="SESSION_NOT_FOUND")
    data = mgr.load_session(session_id)

    messages = data["messages"]
    if msg_index < 0 or msg_index >= len(messages):
        raise HTTPException(status_code=404, detail="MESSAGE_NOT_FOUND")

    msg = messages[msg_index]
    if msg.get("role") != "assistant":
        raise HTTPException(status_code=400, detail="NOT_ASSISTANT_MESSAGE")
    if msg.get("feedback") is not None:
        raise HTTPException(status_code=409, detail="FEEDBACK_ALREADY_SUBMITTED")

    mgr.update_message_feedback(session_id, msg_index, body.rating, body.comment)

    if body.rating != "down":
        return FeedbackResponse(ok=True, hint_generated=False, experience_written=None)

    # Derive the question from the preceding user message
    question = ""
    for i in range(msg_index - 1, -1, -1):
        if messages[i].get("role") == "user":
            question = messages[i].get("content", "")
            break

    answer = msg.get("content", "")

    from app.memory.reflector import reflect_from_user_feedback
    from app.memory.registry import HintRegistry
    from app.memory.client import MemoryClient
    from app.memory.file_memory import file_memory_manager
    from app.memory.embedder import embed

    reflection = await reflect_from_user_feedback(question, answer, body.comment)
    experience_emb = await embed(reflection.experience_body)

    registry = HintRegistry(MemoryClient())
    experience_filename, _ = await asyncio.gather(
        asyncio.to_thread(
            file_memory_manager.write_experience,
            reflection.experience_slug,
            reflection.experience_body,
            experience_emb,
        ),
        registry.submit(_FEEDBACK_AGENT, reflection.hint, force_active=True),
    )

    return FeedbackResponse(ok=True, hint_generated=True, experience_written=experience_filename)


@router.post("/{session_id}/compress")
async def compress_session(session_id: str):
    """Debug: manually trigger session compression."""
    mgr = _mgr()
    data = mgr.load_session(session_id)
    if len(data.get("messages", [])) < 4:
        raise HTTPException(400, "At least 4 messages required to compress")
    await mgr._compress(session_id, data)
    return {"ok": True}
