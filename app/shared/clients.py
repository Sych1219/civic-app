"""
Shared clients for external services.
"""
from __future__ import annotations

import json
import logging
from uuid import UUID, uuid4

import httpx

from app.shared.catalog import GovApiCatalogQuery
from app.shared.models import GovApiContract
from app.shared.responses import GovApiListResponse
from app.shared.trigger import GovApiTriggerPayload

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
    ) -> GovApiListResponse:
        """
        Calls GET /api/v1/gov/apis with validated, extensible query parameters.
        """

        query = query or GovApiCatalogQuery()
        params = query.to_query_params()
        request_id = request_id or str(uuid4())
        headers = {"X-Request-Id": request_id}

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

        # Validate and normalize to the documented response contract
        try:
            return GovApiListResponse.model_validate(payload)
        except Exception as exc:
            # If the body doesn't match the expected schema, still return it for visibility
            logger.warning("Unexpected response schema from registry list endpoint: %s", payload)
            # Surface raw payload in the message field to keep return type consistent
            return GovApiListResponse(
                items=[],
                page=query.page,
                size=query.size,
                totalItems=0,
                totalPages=0,
                requestId=request_id,
                error="SCHEMA_MISMATCH",
                message=str(payload),
            )

    def trigger_api(
        self,
        *,
        api_id: UUID | str,
        payload: GovApiTriggerPayload,
        dry_run: bool = False,
        request_id: str | None = None,
    ) -> dict:
        """
        Calls POST /api/v1/gov/apis/{apiId}/trigger with validated payload.
        """

        url = f"{self._base_url}/{api_id}/trigger"
        payload_dict = payload.to_payload()
        header_request_id = (payload.headerOverrides or {}).get("X-Request-Id")
        final_request_id = request_id or header_request_id or str(uuid4())
        headers = {"X-Request-Id": final_request_id}

        if dry_run:
            logger.info("Dry-run mode: skipping trigger POST to %s", url)
            return {
                "status": "DRY_RUN",
                "apiId": str(api_id),
                "payload": payload_dict,
                "requestId": final_request_id,
                "url": url,
            }

        response = self._client.post(url, json=payload_dict, headers=headers)
        try:
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            logger.error("Trigger call failed for %s with %s: %s", api_id, exc.response.status_code, exc.response.text)
            raise

        body = response.json()
        if isinstance(body, dict) and "requestId" not in body:
            body["requestId"] = response.headers.get("X-Request-Id", final_request_id)
        return body
