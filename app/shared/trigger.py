"""
Models and helpers for triggering registered government APIs.
"""
from __future__ import annotations

from typing import Any, Dict, Optional, Tuple
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator


class GovApiTriggerPayload(BaseModel):
    """
    Payload contract for POST /api/v1/gov/apis/{apiId}/trigger.
    """

    model_config = ConfigDict(extra="forbid")

    query: Optional[Dict[str, Any]] = None
    body: Optional[Dict[str, Any]] = None
    headerOverrides: Optional[Dict[str, str]] = Field(default=None, description="Runtime header overrides")
    useExampleDefaults: bool = Field(default=False, description="Whether to fill missing values from examples")

    @field_validator("query", "body", mode="before")
    @classmethod
    def normalize_object(cls, value):
        if value is None or value == {}:
            return None
        if not isinstance(value, dict):
            raise TypeError("must be an object")
        normalized: Dict[str, Any] = {}
        for key, val in value.items():
            key_str = str(key).strip()
            if not key_str:
                raise ValueError("keys must be non-empty strings")
            normalized[key_str] = val
        return normalized

    @field_validator("headerOverrides", mode="before")
    @classmethod
    def normalize_headers(cls, value):
        if value is None or value == {}:
            return None
        if not isinstance(value, dict):
            raise TypeError("headerOverrides must be an object")
        normalized: Dict[str, str] = {}
        for key, val in value.items():
            key_str = str(key).strip()
            if not key_str:
                raise ValueError("headerOverrides keys must be non-empty strings")
            normalized[key_str] = str(val)
        return normalized

    def to_payload(self) -> Dict[str, Any]:
        """Return a JSON-ready dict with empty sections removed."""
        return self.model_dump(exclude_none=True)


class InvalidTriggerRequest(Exception):
    """Raised when trigger inputs fail validation."""


class GovApiTriggerRequestValidator:
    """
    Validates trigger inputs before invoking the registry endpoint.
    """

    def validate(self, api_id: Any, payload: Dict[str, Any]) -> Tuple[UUID, GovApiTriggerPayload]:
        try:
            normalized_id = UUID(str(api_id))
        except (ValueError, TypeError) as exc:
            raise InvalidTriggerRequest(f"apiId must be a valid UUID: {api_id}") from exc

        try:
            body = GovApiTriggerPayload.model_validate(payload or {})
        except ValidationError as exc:
            details = "; ".join(f"{'/'.join(str(loc) for loc in error['loc'])}: {error['msg']}" for error in exc.errors())
            raise InvalidTriggerRequest(f"Trigger request validation failed: {details}") from exc
        return normalized_id, body
