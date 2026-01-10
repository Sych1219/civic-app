"""
Agent that would collect available APIs so other agents can choose one.
Currently a placeholder for future implementation.
"""
from __future__ import annotations

from app.shared.state import GovApiState, GraphConfig


class ApiCatalogAgent:
    def run(self, state: GovApiState, config: GraphConfig | None = None) -> GovApiState:
        # Placeholder: in a future version, this would query a registry or docs source.
        errors = list(state.get("validation_errors", []))
        errors.append("ApiCatalogAgent is not implemented yet.")
        return {"validation_errors": errors}
