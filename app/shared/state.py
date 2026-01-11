"""
Shared state definitions for the Gov API registration workflows.
"""
from __future__ import annotations

from typing import Any, Dict, List, TypedDict


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
    catalog_response: Dict[str, Any]
    trigger_response: Dict[str, Any]
    trigger_request: Dict[str, Any]
    auto_register: bool
    metadata: Dict[str, Any]


class GraphConfig(TypedDict, total=False):
    """
    Runtime configuration toggles for graph execution.
    """

    langsmith_project: str
    langsmith_run_name: str
    dry_run: bool
