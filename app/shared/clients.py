"""
Shared clients for external services.
"""
from __future__ import annotations

import json
import logging

import httpx

from app.shared.models import GovApiContract

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
