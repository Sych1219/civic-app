"""
Shared state definitions for the Gov API registration workflows.
"""
from __future__ import annotations

from typing import Any, Dict, List, TypedDict


class GovApiListItem(TypedDict, total=False):
    """
    Single registered API entry as returned by list/search endpoint.
    Mirrors the contract in design_docs/data-gov-apis-definations/list-gov-api.md.
    """

    id: str
    name: str
    baseUrl: str
    httpMethod: str
    headers: List[Dict[str, str]]
    queryParams: List[Dict[str, Any]]
    bodyParams: List[Dict[str, Any]]
    description: str
    status: str
    createdAt: str


class GovApiListResponse(TypedDict, total=False):
    """
    Envelope for GET /api/v1/gov/apis responses.
    """

    items: List[GovApiListItem]
    page: int
    size: int
    totalItems: int
    totalPages: int
    error: str
    message: str
    requestId: str


class GovApiState(TypedDict, total=False):
    """
    Shared state that flows through graphs and agents.

    Keys are optional because graphs/agents progressively add data.
    """

    source_text: str
    cleaned_document: str
    context_chunks: List[str]
    llm_response: str
    contract: Dict[str, Any]
    validation_errors: List[str]
    registry_response: Dict[str, Any]
    catalog_response: GovApiListResponse
    trigger_response: Dict[str, Any]
    trigger_request: Dict[str, Any]
    trigger_summary: str
    auto_register: bool
    metadata: Dict[str, Any]


class GraphConfig(TypedDict, total=False):
    """
    Runtime configuration toggles for graph execution.
    """

    langsmith_project: str
    langsmith_run_name: str
    dry_run: bool
