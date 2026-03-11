import json
import os
import logging
from typing import Any, Optional

import httpx
from langchain_community.agent_toolkits.openapi import planner
from langchain_community.agent_toolkits.openapi.spec import reduce_openapi_spec
from langchain_community.utilities.requests import RequestsWrapper
from langchain_openai import ChatOpenAI

from app.tools import geocode_place

logger = logging.getLogger(__name__)


class CapturingRequestsWrapper(RequestsWrapper):
    """RequestsWrapper that records the last raw HTTP response text."""

    last_raw_response: Optional[str] = None

    def get(self, url: str, **kwargs: Any) -> str:
        response = super().get(url, **kwargs)
        self.last_raw_response = response
        return response

    def post(self, url: str, data: Any, **kwargs: Any) -> str:
        response = super().post(url, data, **kwargs)
        self.last_raw_response = response
        return response


_agent = None
_capturing_wrapper: Optional[CapturingRequestsWrapper] = None


def _build_agent(java_api_base: str):
    global _capturing_wrapper

    raw_spec = httpx.get(f"{java_api_base}/api-docs", timeout=10.0).json()
    api_spec = reduce_openapi_spec(raw_spec)

    llm = ChatOpenAI(model="gpt-4o-mini", temperature=0)
    _capturing_wrapper = CapturingRequestsWrapper(headers={"Accept": "application/json"})

    return planner.create_openapi_agent(
        api_spec,
        _capturing_wrapper,
        llm,
        extra_tools=[geocode_place],
        agent_executor_kwargs={"handle_parsing_errors": True},
        allow_dangerous_requests=True,
        verbose=True,
    )


def get_agent():
    """Lazily initialise and return the singleton OpenAPI agent."""
    global _agent
    if _agent is None:
        java_api_base = os.environ.get("JAVA_SPATIAL_API_URL", "http://localhost:8080")
        logger.info("Initialising OpenAPI agent against %s", java_api_base)
        _agent = _build_agent(java_api_base)
        logger.info("Agent ready.")
    return _agent


def get_last_raw_data() -> Optional[dict]:
    """Return the Java service data payload from the most recent HTTP call (envelope stripped)."""
    if _capturing_wrapper is None or _capturing_wrapper.last_raw_response is None:
        return None
    try:
        parsed = json.loads(_capturing_wrapper.last_raw_response)
        if isinstance(parsed, dict) and "data" in parsed:
            return parsed["data"]
        return parsed
    except (json.JSONDecodeError, ValueError):
        return None
