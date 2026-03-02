import os
import logging

import httpx
from langchain.agents import AgentType, initialize_agent
from langchain_community.agent_toolkits import OpenAPIToolkit
from langchain_community.agent_toolkits.openapi.spec import reduce_openapi_spec
from langchain_community.utilities.requests import TextRequestsWrapper
from langchain_openai import ChatOpenAI

from app.tools import geocode_place

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """You are a helpful assistant for querying real-time Singapore taxi availability data.

DATA:
- Source: data.gov.sg, refreshed every 30 s by the Java service.
- Each record is an anonymous (lat, lng) for one available taxi.
- NO taxi IDs, NO speed, NO heading. All taxis returned are available (not occupied).

ENDPOINTS under /api/v1/taxis — inspect the spec for exact paths and parameter names:
GET  nearby/count       : count taxis within radius metres of (lat, lng)
GET  nearby             : list taxis as GeoJSON (up to limit)
GET  nearest            : closest N taxis to a point, each with distance_m
GET  zone/{name}/count  : count taxis inside a named planning area
POST polygon/count      : count taxis inside a GeoJSON Polygon body
GET  road/{name}/count  : count taxis within buffer_m metres of a named road
POST route/count        : count taxis within buffer_m of a GeoJSON LineString body
GET  history/snapshots  : per-minute counts for start→end (ISO-8601), optional zone
GET  history/recent     : delta over last N minutes, optional zone

UNITS: Always convert km → metres before calling the API (e.g. 3 km = 3000, 500 m = 500).

STEP ORDER — choose the pattern that fits the question:

  Place-name (radius / nearest / road):
    1. geocode_place → get lat, lng
    2. json_spec_tool → confirm params
    3. requests_get with resolved coordinates

  Named zone (zone/{name}/count):
    1. Pick the zone name from PLANNING AREAS below (no geocoding needed)
    2. requests_get directly — skip json_spec_tool if zone param is obvious

  Polygon / Route (POST endpoints):
    1. geocode_place if a place is mentioned
    2. json_spec_tool → confirm the expected GeoJSON body schema
    3. requests_post with the GeoJSON body

  Historical (history/snapshots, history/recent):
    1. Parse time range or N minutes from the question
    2. requests_get with ISO-8601 start/end or minutes param

PLANNING AREAS for zone queries (pass name as-is, no geocoding needed):
  Tampines, Jurong West, Bedok, Woodlands, Hougang, Sengkang, Ang Mo Kio, Toa Payoh,
  Downtown Core, Orchard, Marina South, Queenstown, Clementi, Yishun, Geylang.

ANSWERING: Always include the snapshot_time from the API response in your final answer
(e.g. "as of 14:30 SGT"). If the field is absent, omit it.

GEOCODING FAILURE: If geocode_place returns "Could not geocode", ask the user to clarify
the location or provide coordinates directly. Do not call any spatial endpoint.

UNSUPPORTED — respond without calling any tool and explain why:
  Tracking a specific taxi, speed/heading queries, ETA, trajectory, or demand inference.
"""

_agent_executor = None


def _build_agent(java_api_base: str):
    raw_spec = httpx.get(f"{java_api_base}/api-docs", timeout=10.0).json()
    api_spec = reduce_openapi_spec(raw_spec)

    llm = ChatOpenAI(model="gpt-4o-mini", temperature=0)
    requests_wrapper = TextRequestsWrapper(headers={"Accept": "application/json"})
    toolkit = OpenAPIToolkit.from_llm(llm, api_spec, requests_wrapper, verbose=False)

    all_tools = toolkit.get_tools() + [geocode_place]

    return initialize_agent(
        tools=all_tools,
        llm=llm,
        agent=AgentType.ZERO_SHOT_REACT_DESCRIPTION,
        verbose=False,
        max_iterations=6,
        handle_parsing_errors=True,
        agent_kwargs={"prefix": SYSTEM_PROMPT},
        return_intermediate_steps=True,
    )


def get_agent():
    """Lazily initialise and return the singleton agent executor."""
    global _agent_executor
    if _agent_executor is None:
        java_api_base = os.environ.get("JAVA_SPATIAL_API_URL", "http://localhost:8080")
        logger.info("Initialising ReAct agent against %s", java_api_base)
        _agent_executor = _build_agent(java_api_base)
        logger.info("Agent ready.")
    return _agent_executor
