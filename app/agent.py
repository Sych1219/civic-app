import os
import logging

import httpx
from langchain.agents import create_agent
from langchain_community.agent_toolkits.openapi import planner
from langchain_community.agent_toolkits.openapi.spec import reduce_openapi_spec
from langchain_community.utilities.requests import TextRequestsWrapper
from langchain_core.tools import tool
from langchain_openai import ChatOpenAI

from app.tools import geocode_place

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """You are a helpful assistant for querying real-time Singapore taxi availability data.

DATA:
- Source: data.gov.sg, refreshed every 30 s by the Java service.
- Each record is an anonymous (lat, lng) for one available taxi.
- NO taxi IDs, NO speed, NO heading. All taxis returned are available (not occupied).

TOOLS:
- geocode_place: Resolves a Singapore place name or address to lat/lng coordinates.
- query_taxi_api: A hierarchical planner-controller agent that automatically plans and
  executes the right REST API calls against the taxi service. Pass it a complete,
  self-contained question that includes any resolved coordinates.

AVAILABLE ENDPOINTS (handled internally by query_taxi_api):
  GET  nearby/count       : count taxis within radius metres of (lat, lng)
  GET  nearby             : list taxis as GeoJSON (up to limit)
  GET  nearest            : closest N taxis to a point, each with distance_m
  GET  zone/{name}/count  : count taxis inside a named planning area
  POST polygon/count      : count taxis inside a GeoJSON Polygon body
  GET  road/{name}/count  : count taxis within buffer_m metres of a named road
  POST route/count        : count taxis within buffer_m of a GeoJSON LineString body
  GET  history/snapshots  : per-minute counts for start→end (ISO-8601), optional zone
  GET  history/recent     : delta over last N minutes, optional zone

UNITS: Always convert km → metres before passing to query_taxi_api (e.g. 3 km = 3000).

STEP ORDER — choose the pattern that fits the question:

  Place-name (radius / nearest / road):
    1. geocode_place → get lat, lng
    2. query_taxi_api with the question, substituting the resolved coordinates

  Named zone (zone/{name}/count):
    1. query_taxi_api directly — no geocoding needed
    (Planning areas: Tampines, Jurong West, Bedok, Woodlands, Hougang, Sengkang,
     Ang Mo Kio, Toa Payoh, Downtown Core, Orchard, Marina South, Queenstown,
     Clementi, Yishun, Geylang)

  Polygon / Route (POST endpoints):
    1. geocode_place for any mentioned place
    2. query_taxi_api with resolved coordinates and GeoJSON shape description

  Historical (history/snapshots, history/recent):
    1. query_taxi_api directly with the time range or minutes

ANSWERING: Always include the snapshot_time from the API response in your final answer
(e.g. "as of 14:30 SGT"). If the field is absent, omit it.

GEOCODING FAILURE: If geocode_place returns "Could not geocode", ask the user to clarify
the location or provide coordinates directly. Do not call query_taxi_api.

AMBIGUOUS — place name + radius: When the user gives a place name (e.g. "Punggol") together
with a radius (e.g. "5 km"), the intent is ambiguous. Do NOT call any tool yet. Ask:
  "Did you mean:
   (A) Within [radius] of the centre of [place]? (a circle around one point)
   (B) Within the [place] planning-area boundary? (uses the official zone shape, ignores the radius)"
Wait for the user's choice, then proceed:
  - Choice A → geocode_place → query_taxi_api using nearby/count with the given radius
  - Choice B → query_taxi_api using zone/{name}/count directly (no geocoding, no radius)

UNSUPPORTED — respond without calling any tool and explain why:
  Tracking a specific taxi, speed/heading queries, ETA, trajectory, or demand inference.
"""

_agent = None


def _build_agent(java_api_base: str):
    raw_spec = httpx.get(f"{java_api_base}/api-docs", timeout=10.0).json()
    api_spec = reduce_openapi_spec(raw_spec)

    llm = ChatOpenAI(model="gpt-4o-mini", temperature=0)
    requests_wrapper = TextRequestsWrapper(headers={"Accept": "application/json"})

    # Inner: hierarchical planner-controller agent for OpenAPI querying
    openapi_agent = planner.create_openapi_agent(
        api_spec,
        requests_wrapper,
        llm,
        allow_dangerous_requests=True,
        verbose=True,
    )

    @tool
    def query_taxi_api(question: str) -> str:
        """Query the Singapore taxi availability REST API using a hierarchical
        planner-controller. The planner decides which endpoints to call; the
        controller executes them. Pass a self-contained question that includes
        any already-resolved coordinates (lat/lng) or named planning areas."""
        result = openapi_agent.invoke({"input": question})
        return result.get("output", str(result))

    # Outer: LangGraph agent — geocodes place names, then delegates API calls
    return create_agent(
        model=llm,
        tools=[geocode_place, query_taxi_api],
        system_prompt=SYSTEM_PROMPT,
    )


def get_agent():
    """Lazily initialise and return the singleton LangGraph agent."""
    global _agent
    if _agent is None:
        java_api_base = os.environ.get("JAVA_SPATIAL_API_URL", "http://localhost:8080")
        logger.info("Initialising planner agent against %s", java_api_base)
        _agent = _build_agent(java_api_base)
        logger.info("Agent ready.")
    return _agent
