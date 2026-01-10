"""
Shared models for describing government API contracts.
"""
from __future__ import annotations

import re
from typing import List, Optional

from pydantic import BaseModel, Field, HttpUrl, ValidationError, field_validator, model_validator

HTTPS_PATTERN = re.compile(r"^https://[A-Za-z0-9.-]+.*")
ALLOWED_METHODS = {"GET", "POST", "PUT", "PATCH", "DELETE"}
ALLOWED_PARAM_TYPES = {"STRING", "INTEGER", "FLOAT", "BOOLEAN", "OBJECT", "ARRAY"}
PLACEHOLDER_SECRET_PATTERN = re.compile(r"\bYOUR[-_A-Z0-9]*\b", re.IGNORECASE)


class Header(BaseModel):
    key: str
    value: str

    @model_validator(mode="after")
    def drop_placeholder(self):
        if PLACEHOLDER_SECRET_PATTERN.search(self.value):
            raise ValueError("Headers with placeholder secrets must be omitted entirely")
        return self


class Parameter(BaseModel):
    key: str
    type: str = Field(..., description="STRING, INTEGER, FLOAT, BOOLEAN, OBJECT, or ARRAY")
    description: str
    exampleValue: Optional[str] = None
    children: Optional[List["Parameter"]] = Field(
        default=None,
        description="Nested parameters for OBJECT types; omit when empty.",
    )

    @field_validator("type")
    @classmethod
    def validate_type(cls, value: str) -> str:
        upper = value.upper()
        if upper not in ALLOWED_PARAM_TYPES:
            raise ValueError(f"type must be one of {sorted(ALLOWED_PARAM_TYPES)}, got {value}")
        return upper

    @field_validator("children", mode="before")
    @classmethod
    def normalize_empty_children(cls, value):
        if value == []:
            return None
        return value

    @model_validator(mode="after")
    def validate_children(self):
        """Only OBJECT parameters can declare children, and only when non-empty."""
        if self.type != "OBJECT" and self.children:
            raise ValueError(f"{self.type} parameters cannot define children")
        return self


Parameter.model_rebuild()


class GovApiContract(BaseModel):
    name: str
    baseUrl: HttpUrl
    httpMethod: str
    headers: List[Header] = Field(default_factory=list)
    queryParams: Optional[List[Parameter]] = Field(
        default=None, description="Omit entirely if the endpoint has no query parameters."
    )
    bodyParams: Optional[List[Parameter]] = Field(
        default=None, description="Omit entirely if the endpoint has no body parameters."
    )
    description: str

    @field_validator("httpMethod")
    @classmethod
    def validate_method(cls, value: str) -> str:
        normalized = value.upper()
        if normalized not in ALLOWED_METHODS:
            raise ValueError(f"httpMethod must be one of {sorted(ALLOWED_METHODS)}, got {value}")
        return normalized

    @field_validator("queryParams", "bodyParams")
    @classmethod
    def validate_param_lists(cls, value: Optional[List[Parameter]]):
        if value is not None and len(value) == 0:
            raise ValueError("query/body parameters must be omitted or contain at least one entry")
        return value

    @model_validator(mode="after")
    def enforce_https(self):
        if not HTTPS_PATTERN.match(str(self.baseUrl)):
            raise ValueError("baseUrl must be an https:// endpoint")
        return self


class ContractValidationError(Exception):
    """Raised when payloads fail schema validation."""


class GovApiSchemaValidator:
    """
    Thin wrapper over the Pydantic schema to provide reusable error strings.
    """

    def validate(self, payload: dict) -> GovApiContract:
        try:
            return GovApiContract.model_validate(payload)
        except ValidationError as exc:
            raise ContractValidationError(exc.errors(include_url=False, include_context=True)) from exc
