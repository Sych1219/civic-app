"""
Agent that triggers a registered government API using its persisted contract.
"""
from __future__ import annotations

from app.shared.clients import GovApiRegistryClient
from app.shared.state import GovApiState, GraphConfig
from app.shared.trigger import GovApiTriggerRequestValidator, InvalidTriggerRequest


class ApiTriggerAgent:
    def __init__(
        self,
        *,
        client: GovApiRegistryClient | None = None,
        validator: GovApiTriggerRequestValidator | None = None,
    ):
        self.client = client or GovApiRegistryClient()
        self.validator = validator or GovApiTriggerRequestValidator()

    def run(self, state: GovApiState, config: GraphConfig | None = None) -> GovApiState:
        """
        Uses the registry's POST `/api/v1/gov/apis/{apiId}/trigger` endpoint.

        Input (from `state["metadata"]["trigger"]`):
        - `api_id` (or `apiId`): UUID string of the registration to trigger.
        - `request` (or `payload`): dict matching the trigger contract
          (query/body/headerOverrides/useExampleDefaults).
          As a convenience, query/body/headerOverrides/useExampleDefaults can also be
          provided directly under `trigger`.
        - `request_id` (optional): override for X-Request-Id header.
        """

        config = config or {}
        dry_run = bool(config.get("dry_run", False))
        metadata = state.get("metadata") or {}
        trigger_config = metadata.get("trigger") or {}
        api_id = trigger_config.get("api_id") or trigger_config.get("apiId")

        raw_request = trigger_config.get("request") or trigger_config.get("payload")
        if raw_request is None and any(key in trigger_config for key in ("query", "body", "headerOverrides", "useExampleDefaults")):
            raw_request = {
                key: trigger_config[key]
                for key in ("query", "body", "headerOverrides", "useExampleDefaults")
                if key in trigger_config
            }

        if api_id is None:
            errors = list(state.get("validation_errors", []))
            errors.append("Missing api_id for trigger request.")
            return {"validation_errors": errors}

        try:
            normalized_id, payload = self.validator.validate(api_id, raw_request or {})
        except InvalidTriggerRequest as exc:
            errors = list(state.get("validation_errors", []))
            errors.append(str(exc))
            return {"validation_errors": errors}

        request_id = trigger_config.get("request_id") or trigger_config.get("requestId")

        try:
            response = self.client.trigger_api(
                api_id=normalized_id,
                payload=payload,
                dry_run=dry_run,
                request_id=request_id,
            )
        except Exception as exc:
            errors = list(state.get("validation_errors", []))
            errors.append(f"Trigger call failed: {exc}")
            return {"validation_errors": errors}

        return {
            "trigger_request": payload.to_payload(),
            "trigger_response": response,
        }
