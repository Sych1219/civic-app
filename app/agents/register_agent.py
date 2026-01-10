"""
Agent that turns pasted API docs into a validated (and optionally registered) contract.
"""
from __future__ import annotations

from app.components.chunk import ChunkComponent
from app.components.draft import DraftComponent
from app.components.normalize import NormalizeComponent
from app.components.register import RegisterComponent
from app.components.validate import ValidateComponent
from app.shared.state import GovApiState, GraphConfig


class RegisterAgent:
    def __init__(
        self,
        *,
        normalize: NormalizeComponent | None = None,
        chunk: ChunkComponent | None = None,
        draft: DraftComponent | None = None,
        validate: ValidateComponent | None = None,
        register: RegisterComponent | None = None,
    ):
        self.normalize = normalize or NormalizeComponent()
        self.chunk = chunk or ChunkComponent()
        self.draft = draft or DraftComponent()
        self.validate = validate or ValidateComponent()
        self.register = register or RegisterComponent()

    def run(self, state: GovApiState, config: GraphConfig | None = None) -> GovApiState:
        working: GovApiState = dict(state)

        for step in (self.normalize, self.chunk, self.draft, self.validate):
            update = step.run(working)  # type: ignore[arg-type]
            working.update(update)
            if working.get("validation_errors"):
                return working

        # Optional submission step.
        if working.get("auto_register", True):
            update = self.register.run(working, config)
            working.update(update)
        return working
