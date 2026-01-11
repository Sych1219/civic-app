"""
Agent that turns trigger API responses into short, readable summaries via LLM.
"""
from __future__ import annotations

import json
from datetime import datetime
from typing import Any, Dict

from langchain_openai import ChatOpenAI

from app.shared.state import GovApiState, GraphConfig


class TriggerSummaryAgent:
    def __init__(self, *, llm: ChatOpenAI | None = None):
        self.llm = llm or ChatOpenAI(model="gpt-4o-mini", temperature=0)

    def run(self, state: GovApiState, config: GraphConfig | None = None) -> GovApiState:
        """
        Generates a concise human-readable summary from `trigger_response` using an LLM.

        If no response is present or LLM fails, falls back to a minimal summary.
        """

        trigger_response: Dict[str, Any] = state.get("trigger_response") or {}
        if not trigger_response:
            return {"trigger_summary": "No trigger response available to summarize."}

        # Prepare a compact fallback summary in case LLM is unavailable.
        fallback_parts = []
        status = str(trigger_response.get("status") or "").upper()
        error = trigger_response.get("error")
        message = trigger_response.get("message")
        api_id = trigger_response.get("apiId") or trigger_response.get("id") or ""
        request_id = trigger_response.get("requestId") or trigger_response.get("request_id") or ""
        external_status = trigger_response.get("externalStatus") or trigger_response.get("statusCode")
        invoked_at = trigger_response.get("invokedAt") or trigger_response.get("timestamp")
        invoked_str = ""
        if invoked_at:
            try:
                invoked_str = datetime.fromisoformat(str(invoked_at).replace("Z", "+00:00")).isoformat()
            except Exception:
                invoked_str = str(invoked_at)
        if error:
            fallback_parts.append(f"Trigger failed [{error}]")
        elif status:
            fallback_parts.append(f"Trigger status: {status}")
        if api_id:
            fallback_parts.append(f"apiId={api_id}")
        if request_id:
            fallback_parts.append(f"requestId={request_id}")
        if external_status is not None:
            fallback_parts.append(f"upstream status={external_status}")
        if invoked_str:
            fallback_parts.append(f"invokedAt={invoked_str}")
        if message:
            fallback_parts.append(f"message={message}")
        fallback = " | ".join(fallback_parts) or "Trigger completed."

        # LLM prompt to translate JSON to a readable message aligned with catalog/trigger schema.
        prompt = (
            "You are a helpful assistant that summarizes trigger results for registered government APIs.\n"
            "Given the JSON payload below, produce a short, user-friendly message that includes:\n"
            "- overall status or error\n"
            "- apiId (if present)\n"
            "- upstream/external HTTP status (if present)\n"
            "- requestId (if present)\n"
            "- any message/description returned\n"
            "Keep it concise (1-2 sentences). Do not invent data.\n\n"
            f"Trigger response JSON:\n{json.dumps(trigger_response, indent=2)}\n\n"
            "Summary:"
        )

        try:
            completion = self.llm.invoke(prompt)
            summary = str(completion.content).strip()
            if not summary:
                summary = fallback
        except Exception:
            summary = fallback

        return {"trigger_summary": summary}
