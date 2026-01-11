"""
Query model + helpers for listing/searching registered government APIs.
"""
from __future__ import annotations

from typing import Any, Dict, Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


ALLOWED_SORT_FIELDS = {
    "id",
    "name",
    "baseUrl",
    "httpMethod",
    "description",
    "status",
    "createdAt",
}


class GovApiCatalogQuery(BaseModel):
    """
    Client-side representation of the `/api/v1/gov/apis` query parameters.

    Notes:
    - When `id` is provided, other filters are ignored and we only send `id`.
    - `filters` is a future-proof container; keys are not validated here.
    """

    model_config = ConfigDict(extra="ignore")

    id: Optional[UUID] = None
    description: Optional[str] = None
    page: int = Field(default=0, ge=0)
    size: int = Field(default=20, ge=1, le=100)
    sort: Optional[str] = None
    filters: Optional[Dict[str, Any]] = None

    @field_validator("description")
    @classmethod
    def validate_description(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        trimmed = value.strip()
        if len(trimmed) < 3:
            raise ValueError("description length must be \u2265 3")
        return trimmed

    @field_validator("sort")
    @classmethod
    def validate_sort(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        text = value.strip()
        if not text:
            raise ValueError("sort must be '<field>,<asc|desc>'")
        if "," not in text:
            raise ValueError("sort must be '<field>,<asc|desc>'")
        field, direction = (part.strip() for part in text.split(",", 1))
        if field not in ALLOWED_SORT_FIELDS:
            raise ValueError(f"Unknown sort field: {field}")
        direction_lower = direction.lower()
        if direction_lower not in {"asc", "desc"}:
            raise ValueError("sort direction must be 'asc' or 'desc'")
        return f"{field},{direction_lower}"

    @model_validator(mode="after")
    def validate_id_precedence(self):
        # Server-side contract says id takes precedence; keep the query object valid
        # but do not send other filters when id is present.
        return self

    def to_query_params(self) -> Dict[str, Any]:
        if self.id is not None:
            return {"id": str(self.id)}

        params: Dict[str, Any] = {"page": self.page, "size": self.size}
        if self.description:
            params["description"] = self.description
        if self.sort:
            params["sort"] = self.sort
        if self.filters:
            for key, value in self.filters.items():
                params[f"filters[{key}]"] = value
        return params

