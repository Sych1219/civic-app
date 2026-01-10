"""
Component to submit a validated contract to the registry.
"""
from __future__ import annotations

from app.shared.clients import GovApiRegistryClient
from app.shared.models import ContractValidationError, GovApiSchemaValidator
from app.shared.state import GovApiState, GraphConfig


class RegisterComponent:
    def __init__(
        self,
        *,
        client: GovApiRegistryClient | None = None,
        validator: GovApiSchemaValidator | None = None,
    ):
        self.client = client or GovApiRegistryClient()
        self.validator = validator or GovApiSchemaValidator()

    def run(self, state: GovApiState, config: GraphConfig | None = None) -> GovApiState:
        config = config or {}
        dry_run = bool(config.get("dry_run", False))
        dry_run = dry_run or not state.get("auto_register", True)
        contract_payload = state.get("contract")
        if not contract_payload:
            errors = list(state.get("validation_errors", []))
            errors.append("No contract payload available for registry submission.")
            return {"validation_errors": errors}

        try:
            contract = self.validator.validate(contract_payload)
        except ContractValidationError as exc:
            errors = list(state.get("validation_errors", []))
            errors.append(f"Validation failed prior to submission: {exc}")
            return {"validation_errors": errors}

        try:
            response = self.client.register(contract, dry_run=dry_run)
        except Exception as exc:
            errors = list(state.get("validation_errors", []))
            errors.append(f"Registry submission failed: {exc}")
            return {"validation_errors": errors}

        return {"registry_response": response}
