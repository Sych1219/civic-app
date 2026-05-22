import json

from fastapi import APIRouter, HTTPException

router = APIRouter(prefix="/api/sessions", tags=["sessions"])


def _mgr():
    from app.sessions.manager import session_manager
    if session_manager is None:
        raise HTTPException(status_code=503, detail="Session manager not initialised")
    return session_manager


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


@router.post("/{session_id}/compress")
async def compress_session(session_id: str):
    """Debug: manually trigger session compression."""
    mgr = _mgr()
    data = mgr.load_session(session_id)
    if len(data.get("messages", [])) < 4:
        raise HTTPException(400, "At least 4 messages required to compress")
    await mgr._compress(session_id, data)
    return {"ok": True}
