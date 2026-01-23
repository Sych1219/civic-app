"""
Service that collects available APIs so other agents can choose one.
Queries the Gov API registry to list/search registered APIs.
"""
from __future__ import annotations

from pydantic import ValidationError

from app.shared.catalog import GovApiCatalogQuery
from app.shared.clients import GovApiRegistryClient
from app.shared.state import GovApiState, GraphConfig


class ApiCatalogService:
    def __init__(self, *, client: GovApiRegistryClient | None = None):
        self.client = client or GovApiRegistryClient()

    def run(self, state: GovApiState, config: GraphConfig | None = None) -> GovApiState:
        """
        Uses the registry's GET `/api/v1/gov/apis` endpoint.

        Input:
        - `state["metadata"]["catalog_query"]` (optional) should be a dict compatible with `GovApiCatalogQuery`.
          Example: {"description": "school", "page": 0, "size": 20, "sort": "createdAt,desc"}.
        """

        config = config or {}
        dry_run = bool(config.get("dry_run", False))
        metadata = state.get("metadata") or {}
        raw_query = metadata.get("catalog_query") or {}

        try:
            query = GovApiCatalogQuery.model_validate(raw_query)
        except ValidationError as exc:
            errors = list(state.get("validation_errors", []))
            errors.append(f"Catalog query validation failed: {exc}")
            return {"validation_errors": errors}

        try:
            response = self.client.list_apis(query=query, dry_run=dry_run)
        except Exception as exc:
            errors = list(state.get("validation_errors", []))
            errors.append(f"Registry catalog lookup failed: {exc}")
            return {"validation_errors": errors}

        return {"catalog_response": response}
