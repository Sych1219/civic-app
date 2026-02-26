"""
LLM Summarizer and Session Store for conversational data summaries.

Always active on every POST /api/query request:
- SessionStore: manages conversation history keyed by session_id (UUID v4)
- LLMSummarizer: generates plain-English summaries from QueryResponse data
"""

import uuid
import logging
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional, Any

from langchain_openai import ChatOpenAI
from langchain_core.prompts import ChatPromptTemplate

from .models import QueryResponse, ChatHistoryEntry

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────
# Session Store
# ─────────────────────────────────────────────

class SessionStore:
    """
    In-memory conversation store keyed by session_id (UUID v4).

    Rules (from architecture-overview.md):
    - Auto-generated UUID v4 when session_id is omitted in the request.
    - Last 10 turns (5 user + 5 assistant) supplied to the LLM per call.
    - Only ChatHistoryEntry is stored — full QueryResponse JSON is NOT stored.
    - Sessions expire after 24 hours of inactivity.
    - MVP backend: in-memory dict; migrate to Redis / PostgreSQL for production.
    """

    SESSION_EXPIRY_HOURS = 24
    MAX_HISTORY_TURNS = 10  # 5 user + 5 assistant

    def __init__(self) -> None:
        # session_id -> {"history": [ChatHistoryEntry, ...], "last_active": datetime}
        self._sessions: Dict[str, Dict[str, Any]] = {}

    # ── public API ──────────────────────────────

    def resolve_session_id(self, session_id: Optional[str]) -> str:
        """Return existing session_id or create a new UUID v4."""
        if session_id and session_id in self._sessions:
            self._touch(session_id)
            return session_id
        new_id = session_id or str(uuid.uuid4())
        self._sessions[new_id] = {
            "history": [],
            "last_active": datetime.now(timezone.utc),
        }
        return new_id

    def get_history(self, session_id: str) -> List[ChatHistoryEntry]:
        """Return the last MAX_HISTORY_TURNS entries for the session."""
        self._expire_stale_sessions()
        session = self._sessions.get(session_id)
        if not session:
            return []
        return session["history"][-self.MAX_HISTORY_TURNS:]

    def add_user_turn(self, session_id: str, query: str) -> str:
        """Persist a user turn and return the generated message_id."""
        message_id = str(uuid.uuid4())
        entry = ChatHistoryEntry(
            role="user",
            message_id=message_id,
            content=query,
            timestamp=datetime.now(timezone.utc).isoformat(),
        )
        self._append(session_id, entry)
        return message_id

    def add_assistant_turn(
        self,
        session_id: str,
        message_id: str,
        content: str,
    ) -> None:
        """Persist an assistant turn."""
        entry = ChatHistoryEntry(
            role="assistant",
            message_id=message_id,
            content=content,
            timestamp=datetime.now(timezone.utc).isoformat(),
        )
        self._append(session_id, entry)

    # ── internal helpers ────────────────────────

    def _append(self, session_id: str, entry: ChatHistoryEntry) -> None:
        session = self._sessions.get(session_id)
        if session is None:
            session = {"history": [], "last_active": datetime.now(timezone.utc)}
            self._sessions[session_id] = session
        session["history"].append(entry)
        self._touch(session_id)

    def _touch(self, session_id: str) -> None:
        if session_id in self._sessions:
            self._sessions[session_id]["last_active"] = datetime.now(timezone.utc)

    def _expire_stale_sessions(self) -> None:
        cutoff = datetime.now(timezone.utc) - timedelta(hours=self.SESSION_EXPIRY_HOURS)
        expired = [
            sid for sid, data in self._sessions.items()
            if data["last_active"] < cutoff
        ]
        for sid in expired:
            del self._sessions[sid]
            logger.info(f"Expired session {sid}")


# ─────────────────────────────────────────────
# LLM Summarizer
# ─────────────────────────────────────────────

class LLMSummarizer:
    """
    Generate plain-English summaries from QueryResponse data + session history.

    Always active — runs on every POST /api/query after data processing.
    Uses GPT-4 via LangChain; selects a visualization-type-specific data block.

    | visualization_type | Data fed to LLM                                          |
    |--------------------|----------------------------------------------------------|
    | time_series        | summary_stats, record count, y_label, user query         |
    | map                | features_count, bounds, layer_label, user query          |
    | map_temporal       | features_count, first/last temporal values, unit, query  |
    | generic            | First 5 data.records, user query                         |
    | error              | error string, available endpoint topics, user query      |
    """

    def __init__(self, available_topics: Optional[List[str]] = None) -> None:
        self.llm = ChatOpenAI(model="gpt-5-mini", temperature=0.3)
        self.available_topics = available_topics or []

    def set_available_topics(self, topics: List[str]) -> None:
        """Update the list of available endpoint descriptions (for error messages)."""
        self.available_topics = topics

    async def summarize(
        self,
        query_response: QueryResponse,
        user_query: str,
        history: List[ChatHistoryEntry],
    ) -> str:
        """
        Produce a single plain-English paragraph — no markdown, no invented numbers.

        Args:
            query_response: The fully-formed QueryResponse (after step 6).
            user_query: Original natural-language query from the user.
            history: Recent conversation history entries.

        Returns:
            Plain-English summary string.
        """
        viz_type = query_response.visualization_type

        # Build conversation context from history
        history_text = self._format_history(history)
        data = query_response.data
        # Feed data directly into the data block
        if viz_type == "error":
            data_block = self._error_block(query_response.error)
        else:
            data_block = (
                f"Visualization: {viz_type}\n"
                f"Layer: {query_response.layer_label or 'N/A'}\n"
                f"Data: {data}"
            )

        prompt = ChatPromptTemplate.from_messages([
            (
                "system",
                (
                    "You are a helpful data assistant for Singapore government datasets. "
                    "Produce a single concise plain-English paragraph summarizing the data below. "
                    "Do NOT use markdown formatting. Do NOT invent numbers that are not in the data. "
                    "If the data is an error, apologize and suggest alternative queries.\n\n"
                    "Conversation so far:\n{history}\n\n"
                    "Data context:\n{data_block}"
                ),
            ),
            ("human", "{user_query}"),
        ])

        chain = prompt | self.llm

        try:
            result = await chain.ainvoke({
                "history": history_text,
                "data_block": data_block,
                "user_query": user_query,
            })
            return result.content.strip()
        except Exception as e:
            logger.error(f"LLM summarization failed: {e}", exc_info=True)
            # Graceful fallback — never let the summary block the response
            return self._fallback_summary(viz_type, data, query_response.error)

    # ── data-block builders ─────────────────────

    def _error_block(self, error: Optional[str]) -> str:
        topics = ", ".join(self.available_topics[:10]) if self.available_topics else "various government data"
        return (
            f"Visualization: error\n"
            f"Error: {error}\n"
            f"Available topics the user could ask about: {topics}"
        )

    # ── helpers ─────────────────────────────────

    def _format_history(self, history: List[ChatHistoryEntry]) -> str:
        if not history:
            return "(no prior conversation)"
        lines = []
        for entry in history:
            role = entry.role.capitalize()
            lines.append(f"{role}: {entry.content}")
        return "\n".join(lines)

    @staticmethod
    def _fallback_summary(
        viz_type: str,
        data: Dict[str, Any],
        error: Optional[str],
    ) -> str:
        """Deterministic fallback when the LLM call fails."""
        if viz_type == "error":
            return (
                "I'm sorry, I couldn't find a matching dataset for that question. "
                "Try asking: 'Show me air temperature', "
                "'What are PM2.5 levels today?', or "
                "'Where are taxis right now?'"
            )
        if viz_type == "time_series":
            stats = data.get("summary_stats", {})
            record_count = len(data.get("records", []))
            return f"Retrieved {record_count} records with summary statistics: {stats}."
        if viz_type in ("map", "map_temporal"):
            count = data.get("features_count", "multiple")
            return f"Map data loaded with {count} features across Singapore."
        return "Data retrieved successfully."
