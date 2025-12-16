"""
Utility classes (fetchers, validators, registry client) for the Gov API workflow.
"""
from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from typing import Iterable, List, Optional

import httpx
from bs4 import BeautifulSoup
from readability import Document
from pydantic import BaseModel, Field, HttpUrl, ValidationError, field_validator, model_validator

logger = logging.getLogger(__name__)

HTTPS_PATTERN = re.compile(r"^https://[A-Za-z0-9.-]+.*")
ALLOWED_METHODS = {"GET", "POST", "PUT", "PATCH", "DELETE"}
ALLOWED_PARAM_TYPES = {"STRING", "INTEGER", "FLOAT", "BOOLEAN", "OBJECT", "ARRAY"}


class Header(BaseModel):
    key: str
    value: str


class Parameter(BaseModel):
    key: str
    type: str = Field(..., description="STRING, INTEGER, FLOAT, BOOLEAN, OBJECT, or ARRAY")
    description: str
    exampleValue: Optional[str] = None
    children: List["Parameter"] = Field(default_factory=list)

    @field_validator("type")
    @classmethod
    def validate_type(cls, value: str) -> str:
        upper = value.upper()
        if upper not in ALLOWED_PARAM_TYPES:
            raise ValueError(f"type must be one of {sorted(ALLOWED_PARAM_TYPES)}, got {value}")
        return upper


Parameter.model_rebuild()


class GovApiContract(BaseModel):
    name: str
    baseUrl: HttpUrl
    httpMethod: str
    headers: List[Header] = Field(default_factory=list)
    queryParams: List[Parameter] = Field(default_factory=list)
    bodyParams: List[Parameter] = Field(default_factory=list)
    description: str

    @field_validator("httpMethod")
    @classmethod
    def validate_method(cls, value: str) -> str:
        normalized = value.upper()
        if normalized not in ALLOWED_METHODS:
            raise ValueError(f"httpMethod must be one of {sorted(ALLOWED_METHODS)}, got {value}")
        return normalized

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
            logger.debug("Schema validation failed: %s", exc)
            raise ContractValidationError(exc.errors(include_url=False, include_context=True)) from exc


class DocumentFetcher:
    """
    Retrieves HTML/PDF documentation and converts it into clean markdown.
    """

    def __init__(
        self,
        timeout: float = 20.0,
        max_bytes: int = 2_000_000,
        user_agent: str = "civic-app-fetcher/0.1 (+https://civic.example.com)",
    ):
        self._timeout = timeout
        self._max_bytes = max_bytes
        self._client = httpx.Client(timeout=timeout, headers={"User-Agent": user_agent})

    def fetch(self, url: str) -> str:
        response = self._client.get(url)
        response.raise_for_status()
        if len(response.content) > self._max_bytes:
            raise ValueError(f"Document exceeds max download size ({self._max_bytes} bytes)")
        return self._html_to_text(response.text, base_url=url)

    @staticmethod
    def _html_to_text(html: str, base_url: str) -> str:
        readable_html = Document(html, url=base_url).summary()
        soup = BeautifulSoup(readable_html, "html.parser")
        for script in soup(["script", "style"]):
            script.decompose()
        lines = [line.strip() for line in soup.get_text(separator="\n").splitlines()]
        text = "\n".join(line for line in lines if line)
        return text


class TextChunker:
    """
    Splits documentation text into roughly 2k token chunks with slight overlaps.
    """

    def __init__(self, chunk_size: int = 4000, overlap: int = 400):
        self._chunk_size = chunk_size
        self._overlap = overlap

    def split(self, document: str) -> List[str]:
        if not document:
            return []
        chunks: List[str] = []
        start = 0
        length = len(document)
        while start < length:
            end = min(start + self._chunk_size, length)
            chunks.append(document[start:end].strip())
            if end >= length:
                break
            start = max(end - self._overlap, 0)
        return [chunk for chunk in chunks if chunk]


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


@dataclass
class PromptBuilder:
    """
    Generates prompts for the LLM using system + human message templates.
    """

    guardrails: str = (
        "You convert government API documentation into registry payloads. Follow the schema exactly. "
        "Use HTTPS base URLs, uppercase HTTP verbs, and include Accept headers when the docs specify response types."
    )

    def build(self, chunks: Iterable[str]) -> str:
        snippet = "\n\n---\n\n".join(chunks)
        schema = json.dumps(GovApiContract.model_json_schema(), indent=2)
        instructions = (
            "Respond with JSON that strictly matches the following schema. "
            "Prefer the endpoint that best matches the operator intent. "
            "If information is missing, make explicit TODO notes in the description field."
        )
        return f"{self.guardrails}\n\nSchema:\n{schema}\n\nDocumentation Snippets:\n{snippet}\n\n{instructions}"
