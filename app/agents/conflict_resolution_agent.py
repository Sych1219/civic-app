"""
Agent that handles duplicate/conflict scenarios (e.g., HTTP 409).
Currently a placeholder for future implementation.
"""
from __future__ import annotations

from app.shared.state import GovApiState, GraphConfig


class ConflictResolutionAgent:
    def run(self, state: GovApiState, config: GraphConfig | None = None) -> GovApiState:
        errors = list(state.get("validation_errors", []))
        errors.append("ConflictResolutionAgent is not implemented yet.")
        return {"validation_errors": errors}
