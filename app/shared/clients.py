"""
Shared clients for external services.
"""
from __future__ import annotations

import json
import logging
from uuid import uuid4

import httpx

from app.shared.models import GovApiContract
from app.shared.catalog import GovApiCatalogQuery

logger = logging.getLogger(__name__)


class GovApiRegistryClient:
    """
    Facilitates calls to POST /api/v1/gov/apis with helpful error surface area.
    """

    def __init__(self, base_url: str = "http://localhost:8080/api/v1/gov/apis", timeout: float = 20.0):
        self._client = httpx.Client(timeout=timeout)
        self._base_url = base_url

    def register(self, contract: GovApiContract, *, dry_run: bool = False) -> dict:
        payload = json.loads(contract.model_dump_json(exclude_none=True))
        if dry_run:
            logger.info("Dry-run mode: skipping POST to %s", self._base_url)
            return {"status": "DRY_RUN", "payload": payload}
        response = self._client.post(self._base_url, json=payload)
        try:
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            logger.error(
                "Registry submission failed with %s: %s",
                exc.response.status_code,
                exc.response.text,
            )
            raise
        return response.json()

    def list_apis(
        self,
        *,
        query: GovApiCatalogQuery | None = None,
        dry_run: bool = False,
        request_id: str | None = None,
    ) -> dict:
        """
        Calls GET /api/v1/gov/apis with validated, extensible query parameters.
        """

        query = query or GovApiCatalogQuery()
        params = query.to_query_params()
        request_id = request_id or str(uuid4())
        headers = {"X-Request-Id": request_id}

        if dry_run:
            logger.info("Dry-run mode: skipping GET to %s", self._base_url)
            return {"status": "DRY_RUN", "params": params, "requestId": request_id}

        response = self._client.get(self._base_url, params=params, headers=headers)
        try:
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            logger.error(
                "Registry lookup failed with %s: %s",
                exc.response.status_code,
                exc.response.text,
            )
            raise

        payload = response.json()
        # Surface correlation id to downstream agents regardless of server behavior.
        if isinstance(payload, dict) and "requestId" not in payload:
            payload["requestId"] = response.headers.get("X-Request-Id", request_id)
        return payload
