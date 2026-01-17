"""
Response models for registry endpoints.

These mirror the contracts in design_docs/data-gov-apis-definations/list-gov-api.md.
"""
from __future__ import annotations

from typing import List, Optional

from pydantic import BaseModel, Field


class GovApiListItemResponse(BaseModel):
    id: str
    name: str
    baseUrl: str
    httpMethod: str
    headers: List[dict] = Field(default_factory=list)
    queryParams: List[dict] = Field(default_factory=list)
    bodyParams: List[dict] = Field(default_factory=list)
    description: str
    status: str
    createdAt: str


class GovApiListResponse(BaseModel):
    items: List[GovApiListItemResponse] = Field(default_factory=list)
    page: int
    size: int
    totalItems: int
    totalPages: int
    # Optional fields the server may include
    error: Optional[str] = None
    message: Optional[str] = None
    requestId: Optional[str] = None
