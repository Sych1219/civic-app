"""
Component to validate a contract against the shared schema.
"""
from __future__ import annotations

from app.shared.models import ContractValidationError, GovApiSchemaValidator
from app.shared.state import GovApiState


class ValidateComponent:
    def __init__(self, validator: GovApiSchemaValidator | None = None):
        self.validator = validator or GovApiSchemaValidator()

    def run(self, state: GovApiState) -> GovApiState:
        if not state.get("contract"):
            errors = list(state.get("validation_errors", []))
            errors.append("LLM contract missing; cannot validate.")
            return {"validation_errors": errors}
        try:
            contract = self.validator.validate(state["contract"])
        except ContractValidationError as exc:
            errors = list(state.get("validation_errors", []))
            errors.append(f"Validation failed: {exc}")
            return {"validation_errors": errors}
        return {"contract": contract.model_dump(mode="python", exclude_none=True)}
