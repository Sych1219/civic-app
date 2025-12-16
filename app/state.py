"""
State definitions for the Gov API registration LangGraph.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, TypedDict


class GovApiState(TypedDict, total=False):
    """
    Shared state that flows through the LangGraph.

    Keys are optional because LangGraph nodes progressively add data.
    """

    request_url: str
    """URL provided by the operator that hosts the API documentation."""

    cleaned_document: str
    """Reduced, reader-friendly representation of the fetched documentation."""

    context_chunks: List[str]
    """List of text chunks that fit within the model context window."""

    llm_response: str
    """Raw text returned by the LLM before parsing."""

    contract: Dict[str, Any]
    """Validated payload that matches the registry schema."""

    validation_errors: List[str]
    """Human friendly descriptions of validation errors surfaced before submission."""

    registry_response: Dict[str, Any]
    """Server response from POST /api/v1/gov/apis."""

    auto_register: bool
    """Controls whether the workflow should automatically submit validated payloads."""

    metadata: Dict[str, Any]
    """Debug/trace metadata (timings, chunk sizes, csrf tokens, etc.)."""


class GraphConfig(TypedDict, total=False):
    """
    Runtime configuration toggles for the LangGraph execution.
    """

    langsmith_project: str
    langsmith_run_name: str
    dry_run: bool
