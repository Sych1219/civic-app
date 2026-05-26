"""
Session JSON persistence — file-based storage under data/sessions/.
Each session is a single JSON file: data/sessions/{session_id}.json
"""

import asyncio
import json
import logging
import time
import uuid
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

_SINGLETON: Optional["SessionManager"] = None


def _init(sessions_dir: Path) -> "SessionManager":
    global _SINGLETON
    sessions_dir.mkdir(parents=True, exist_ok=True)
    (sessions_dir / "archive").mkdir(exist_ok=True)
    _SINGLETON = SessionManager(sessions_dir)
    return _SINGLETON


@property  # type: ignore[misc]
def session_manager() -> "SessionManager":
    return _SINGLETON  # type: ignore[return-value]


# Re-expose as module attribute so `from app.sessions.manager import session_manager` works
class _SessionManagerProxy:
    """Lazy proxy that resolves to the singleton after _init() is called."""

    def __getattr__(self, name: str):
        if _SINGLETON is None:
            raise RuntimeError("SessionManager not initialised — call _init() first")
        return getattr(_SINGLETON, name)


session_manager = _SessionManagerProxy()  # type: ignore[assignment]

MAX_CONTEXT_TOKENS = 128_000
COMPRESSION_TRIGGER = 0.7


class SessionManager:
    def __init__(self, sessions_dir: Path) -> None:
        self.sessions_dir = sessions_dir

    # ── helpers ──────────────────────────────────────────────────────────────

    def _path(self, session_id: str) -> Path:
        return self.sessions_dir / f"{session_id}.json"

    def _load_raw(self, session_id: str) -> dict:
        p = self._path(session_id)
        if not p.exists():
            return {
                "session_id": session_id,
                "title": None,
                "created_at": time.time(),
                "updated_at": time.time(),
                "compressed_context": None,
                "messages": [],
            }
        return json.loads(p.read_text(encoding="utf-8"))

    def _save(self, session_id: str, data: dict) -> None:
        p = self._path(session_id)
        tmp = p.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(p)

    # ── public API ───────────────────────────────────────────────────────────

    def load_session(self, session_id: str) -> dict:
        return self._load_raw(session_id)

    def load_session_for_agent(self, session_id: str) -> list[dict]:
        """Return messages in LLM format: merge consecutive assistant turns, prepend summary."""
        data = self._load_raw(session_id)
        messages: list[dict] = []

        if data.get("compressed_context"):
            messages.append({
                "role": "assistant",
                "content": f"[Summary of previous conversation]\n{data['compressed_context']}",
            })

        for msg in data.get("messages", []):
            if msg["role"] == "user":
                messages.append({"role": "user", "content": msg["content"]})
            else:
                if messages and messages[-1]["role"] == "assistant":
                    messages[-1]["content"] += "\n" + msg["content"]
                else:
                    messages.append({"role": "assistant", "content": msg["content"]})

        return messages

    def list_sessions(self) -> list[dict]:
        results = []
        for p in self.sessions_dir.glob("*.json"):
            try:
                data = json.loads(p.read_text(encoding="utf-8"))
                results.append({
                    "session_id": data.get("session_id", p.stem),
                    "title": data.get("title"),
                    "updated_at": data.get("updated_at", 0),
                    "message_count": len(data.get("messages", [])),
                })
            except Exception as exc:
                logger.warning("Could not read session %s: %s", p, exc)
        results.sort(key=lambda x: x["updated_at"], reverse=True)
        return results

    def _artifact_path(self, session_id: str, artifact_id: str) -> Path:
        return self.sessions_dir / "artifacts" / session_id / f"{artifact_id}.json"

    def save_artifact(self, session_id: str, artifact_id: str, artifact_data: dict) -> None:
        p = self._artifact_path(session_id, artifact_id)
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_suffix(".tmp")
        tmp.write_text(json.dumps(artifact_data, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(p)
        logger.info("Saved artifact %s for session %s", artifact_id, session_id)

    async def append_turn(
        self,
        session_id: str,
        user_content: str,
        assistant_segments: list[dict],
    ) -> list[dict]:
        """Persist turn and return saved artifact records [{type, artifact_id}, ...]."""
        data = self._load_raw(session_id)
        now = time.time()

        data["messages"].append({"role": "user", "content": user_content, "ts": now})
        all_artifacts: list[dict] = []
        for seg in assistant_segments:
            saved_artifacts = []
            for art in seg.get("artifacts", []):
                artifact_id = str(uuid.uuid4())
                art_data = art.get("data")
                if art_data:
                    self.save_artifact(session_id, artifact_id, art_data)
                saved_artifacts.append({"type": art.get("type"), "artifact_id": artifact_id})
            data["messages"].append({
                "role": "assistant",
                "content": seg.get("content", ""),
                "artifacts": saved_artifacts,
                "ts": now,
            })
            all_artifacts.extend(saved_artifacts)

        data["updated_at"] = now
        self._save(session_id, data)

        total_chars = sum(len(m.get("content", "")) for m in data["messages"])
        if total_chars > MAX_CONTEXT_TOKENS * 4 * COMPRESSION_TRIGGER:
            asyncio.create_task(self._compress(session_id, data))

        return all_artifacts

    def update_title(self, session_id: str, title: str) -> None:
        data = self._load_raw(session_id)
        data["title"] = title
        self._save(session_id, data)

    def delete_session(self, session_id: str) -> None:
        p = self._path(session_id)
        if p.exists():
            p.unlink()

    async def _compress(self, session_id: str, data: dict) -> None:
        """Summarise the oldest half of messages and archive them."""
        from langchain_core.messages import HumanMessage, SystemMessage
        from langchain_openai import ChatOpenAI

        messages = data.get("messages", [])
        if len(messages) < 4:
            return

        cutoff = max(4, len(messages) // 2)
        to_compress = messages[:cutoff]

        conversation = "\n".join(
            f"{m['role'].upper()}: {m.get('content', '')}" for m in to_compress
        )
        try:
            llm = ChatOpenAI(model="gpt-4o-mini", temperature=0)
            resp = await llm.ainvoke([
                SystemMessage(content="Summarise the following conversation in ≤500 characters. Focus on facts and decisions."),
                HumanMessage(content=conversation),
            ])
            summary = resp.content.strip()
        except Exception as exc:
            logger.warning("Compression LLM call failed for %s: %s", session_id, exc)
            return

        # Archive original data
        archive_dir = self.sessions_dir / "archive"
        archive_dir.mkdir(exist_ok=True)
        ts = int(time.time())
        archive_path = archive_dir / f"{session_id}_{ts}.json"
        archive_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

        data["compressed_context"] = (data.get("compressed_context") or "") + "\n" + summary
        data["messages"] = messages[cutoff:]
        self._save(session_id, data)
        logger.info("Compressed session %s: archived %d messages", session_id, cutoff)
