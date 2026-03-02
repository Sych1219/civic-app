# MVP Design: Taxi Spatial Q&A System — Singapore

| Field           | Value                                                      |
| --------------- | ---------------------------------------------------------- |
| **Document ID** | MVP-TAXI-SG-2026-001                                       |
| **Version**     | 1.0                                                        |
| **Date**        | 2026-02-28                                                 |
| **Status**      | Active                                                     |
| **Replaces**    | PRD-TAXI-SG-2026-001, ARCH-TAXI-SG-2026-001                |

Full-scope originals archived in [`full-scope/`](full-scope/).

---

## 1. Overview & Design Principles

This Python project is the **LLM + tool-call layer** of the taxi spatial Q&A system. It receives
natural-language questions, uses a LangChain **ReAct agent** (GPT-4o-mini) to reason through
the Java service's OpenAPI spec, discover the right endpoint, call it, and return a natural-language answer.

**Data ingestion and all spatial SQL** are handled by the **Java service**, which also exposes a
REST API. This Python app never connects to the database — tools call the Java REST endpoints.

**Key design principles:**

- The raw data contains **anonymous coordinate-timestamp tuples only** — no taxi IDs, no status,
  no speed, no heading. Every supported query is answerable purely from set-of-points-at-a-time
  analysis.
- **The LLM NEVER generates SQL.** It selects a tool and provides parameters; the tool calls the
  Java spatial REST API which executes the parameterised PostGIS query.
- **MVP scope:** ReAct agent + OpenAPI-driven endpoint discovery, landmark coordinates embedded
  in system prompt, single Docker service, 3 query types, 3 API endpoints.

---

## 2. Data Source & Constraints

> **Ingestion is owned by the Java service.** This Python app only reads from the shared
> PostGIS database populated by that service.

**data.gov.sg — Taxi Availability API** (consumed by the Java ingestion service)

- Endpoint: `https://api.data.gov.sg/v1/transport/taxi-availability`
- Update frequency: every 30 seconds
- Returns a JSON array of `{ latitude, longitude }` for every currently **available** taxi.

**What the data does NOT contain:**

| Missing Field | Implication                                                              |
| ------------- | ------------------------------------------------------------------------ |
| `taxi_id`     | Cannot track an individual taxi across snapshots                         |
| `status`      | All returned taxis are implicitly available; occupied taxis are invisible |
| `speed`       | Cannot infer movement velocity                                           |
| `heading`     | Cannot infer travel direction                                            |

---

## 3. Supported Query Types (MVP)

| Code  | Query Type        | Example                                                          | Endpoint                        | Output                                   |
| ----- | ----------------- | ---------------------------------------------------------------- | ------------------------------- | ---------------------------------------- |
| QT-01 | Radius count      | "How many taxis within 3 km of Changi Airport?"                  | GET /nearby/count               | Integer count                            |
| QT-02 | Nearest-K         | "Nearest 5 taxis to 1.3521, 103.8198"                            | GET /nearest                    | K coordinate pairs + distances (metres)  |
| QT-03 | Zone count        | "How many taxis are in Tampines?"                                | GET /zone/{zoneName}/count      | Count for the named zone                 |
| QT-04 | Nearby list       | "List taxis within 500 m of Raffles Place"                       | GET /nearby                     | GeoJSON FeatureCollection (up to limit)  |
| QT-05 | Polygon count     | "How many taxis are inside this drawn area?"                     | POST /polygon/count             | Integer count inside ad-hoc polygon      |
| QT-06 | Road buffer count | "How many taxis are along Orchard Road?"                         | GET /road/{roadName}/count      | Integer count within buffer of road      |
| QT-07 | Route buffer count| "How many taxis are near this route?"                            | POST /route/count               | Integer count within buffer of LineString|
| QT-08 | Time-window count | "How many taxis were near CBD between 8 pm and 9 pm?"            | GET /history/snapshots          | Per-minute counts over a time range      |
| QT-09 | Recent delta      | "How has taxi supply in Orchard changed in the last 10 minutes?" | GET /history/recent             | Count delta over the last N minutes      |

All other query types (QT-10 and beyond) are deferred to the [Post-MVP Roadmap](#11-post-mvp-roadmap).

---

## 4. Data Model

> Owned entirely by the Java service. See the Java service documentation for table definitions,
> indexes, and migration scripts. This Python app has no database connection.

---

## 5. Location Resolution

Place names are resolved to `(lat, lng)` coordinates by a **geocoding tool** that the ReAct
agent calls before invoking any spatial endpoint. The hardcoded `LANDMARK_COORDS` dict is removed.

### Option A — Built-in LangChain: `GooglePlacesTool` *(requires Google API key)*

`langchain_community.tools.GooglePlacesTool` wraps the Google Places API. No custom code needed;
just add the tool to the agent's tool list.

```python
# pip install langchain-community googlemaps
from langchain_community.tools import GooglePlacesTool

geocode_tool = GooglePlacesTool()  # reads GPLACES_API_KEY from env
# Returns: place name, address, lat/lng, and other metadata as a string
```

**Env var required:** `GPLACES_API_KEY`

### Option B — OneMap Singapore API *(recommended, free, Singapore-specific)*

[OneMap](https://www.onemap.gov.sg/apidocs/) is the Singapore government’s authoritative
geocoding service. Better accuracy for local names and no billing. Wrapped as a LangChain `@tool`:

```python
import httpx
from langchain_core.tools import tool

@tool
async def geocode_place(place_name: str) -> str:
    """Resolve a Singapore place name or address to latitude and longitude."""
    async with httpx.AsyncClient() as client:
        resp = await client.get(
            "https://www.onemap.gov.sg/api/common/elastic/search",
            params={"searchVal": place_name, "returnGeom": "Y",
                    "getAddrDetails": "N", "pageNum": 1},
        )
        resp.raise_for_status()
        results = resp.json().get("results", [])
    if not results:
        return f"Could not geocode '{place_name}'."
    r = results[0]
    return f"{place_name}: lat={r['LATITUDE']}, lng={r['LONGITUDE']}"
```

**No API key required** for the search endpoint. **Option B is used in this MVP.**

**Supported planning areas (QT-03):** Tampines, Jurong West, Bedok, Woodlands, Hougang, Sengkang,
Ang Mo Kio, Toa Payoh, Downtown Core, Orchard, Marina South, Queenstown, Clementi, Yishun, Geylang.

**Removed from MVP:** `pg_trgm` extension, GIN text-search index, 6-step resolution pipeline.

---

## 6. LLM Agent

This Python project is the **LLM + tool-call layer only**. A ReAct agent receives a user
question, reasons step by step (Thought → Action → Observation), discovers the correct Java REST
endpoint from the OpenAPI spec, calls it, and returns a natural-language answer.

### 6.1 Architecture Flow

```
User question
      ↓
ReAct Agent (GPT-4o-mini)      ← reasons step-by-step: Thought → Action → Observation
      ↓
OpenAPI Toolkit                ← loads Java service's /v3/api-docs at startup
   ↙                 ↘
json_spec_tool    requests_get  ← explore spec / execute HTTP GET calls
      ↓
Java Spatial REST API          ← no SQL in Python; PostGIS owned by Java service
      ↓
JSON result observed by agent
      ↓
LLM composes natural-language answer
```

### 6.2 Agent Setup

```python
import os
import httpx
from langchain_openai import ChatOpenAI
from langchain_community.agent_toolkits.openapi.spec import reduce_openapi_spec
from langchain_community.agent_toolkits.openapi import create_openapi_agent
from langchain_community.agent_toolkits import OpenAPIToolkit
from langchain_community.utilities.requests import TextRequestsWrapper

JAVA_API_BASE = os.environ["JAVA_SPATIAL_API_URL"]  # e.g. http://java-service:8080

# Load and reduce the OpenAPI spec from the Java service at application startup
raw_spec = httpx.get(f"{JAVA_API_BASE}/v3/api-docs").json()
api_spec = reduce_openapi_spec(raw_spec)

llm = ChatOpenAI(model="gpt-4o-mini", temperature=0)
requests_wrapper = TextRequestsWrapper(headers={"Accept": "application/json"})
toolkit = OpenAPIToolkit.from_llm(llm, api_spec, requests_wrapper, verbose=False)

# Add the OneMap geocoding tool alongside the OpenAPI toolkit tools
extra_tools = [geocode_place]  # defined in §5 / §7.1

agent_executor = create_openapi_agent(
    llm=llm,
    toolkit=toolkit,
    extra_tools=extra_tools,
    prefix=SYSTEM_PROMPT,   # see §6.3
    verbose=False,
    max_iterations=6,       # +1 to allow a geocoding step
)

# Usage:
result = await agent_executor.ainvoke({"input": user_query})
answer = result["output"]
```

### 6.3 System Prompt

Passed as `prefix` to `create_openapi_agent`.

```python
SYSTEM_PROMPT = """You are a helpful assistant for querying real-time Singapore taxi distribution data.
Use the tools available to you: first geocode any place name, then inspect the OpenAPI spec to find
the correct Java spatial endpoint, then call it.

DATA SOURCE:
- Taxi positions are ingested from data.gov.sg every 30 seconds by the Java service.
- Available data: anonymous (latitude, longitude) per available taxi, per snapshot.
- NO taxi IDs, NO speed, NO heading. All taxis in the data are available (not occupied).

THE API EXPOSES NINE SPATIAL ENDPOINTS under /api/v1/taxis — inspect the spec for exact paths and params:
- nearby/count       : count taxis within radius metres of a (lat, lng) point
- nearby             : list those taxis as GeoJSON (up to limit)
- nearest            : closest N taxis to a point, each with distance in metres
- zone/{name}/count  : count taxis inside a named zone (e.g. cbd, tampines)
- polygon/count      : count taxis inside an ad-hoc GeoJSON Polygon (POST body)
- road/{name}/count  : count taxis within buffer_m metres of a named road
- route/count        : count taxis within buffer_m metres of a GeoJSON LineString route (POST body)
- history/snapshots  : per-minute counts over a start→end time range, optionally by zone
- history/recent     : delta — count change over the last N minutes, optionally by zone

STEP ORDER for place-name queries:
  1. Call geocode_place to resolve the place name to lat/lng.
  2. Call json_spec_tool to find the correct endpoint.
  3. Call requests_get with the resolved coordinates.

PLANNING AREAS for region count (pass the name directly, no geocoding needed):
  Tampines, Jurong West, Bedok, Woodlands, Hougang, Sengkang, Ang Mo Kio, Toa Payoh,
  Downtown Core, Orchard, Marina South, Queenstown, Clementi, Yishun, Geylang.

UNSUPPORTED — respond without calling any tool and explain why:
  Tracking a specific taxi, speed/heading queries, ETA, trajectory, or demand inference.
"""
```

---

## 7. Tools (Geo Query Layer)

The agent has **three runtime tools** — one custom geocoding tool plus two from the OpenAPI toolkit:

| Tool | Source | What the agent uses it for |
| ---- | ------ | -------------------------- |
| `geocode_place` | Custom `@tool` (OneMap API, §5) | Resolve any Singapore place name or address to `lat`/`lng` |
| `json_spec_tool` | `OpenAPIToolkit` | Read the Java service spec to discover endpoint paths, parameters, and response schemas |
| `requests_get` | `OpenAPIToolkit` | Make HTTP GET calls to the discovered Java spatial endpoints |

### 7.1 Java Service OpenAPI Spec

The Java service exposes its spec at `GET /v3/api-docs`. MVP endpoints under `/api/v1/taxis`:

| Endpoint | Key params | Response |
| -------- | ---------- | -------- |
| `GET /nearby/count` | `lat`, `lng`, `radius` (metres) | `taxi_count` (int) |
| `GET /nearby` | `lat`, `lng`, `radius`, `limit` | GeoJSON FeatureCollection |
| `GET /nearest` | `lat`, `lng`, `n` (int) | array of `{lat, lng, distance_m}` |
| `GET /zone/{zoneName}/count` | path: `zoneName` | `taxi_count` (int) |
| `POST /polygon/count` | body: GeoJSON Polygon | `taxi_count` (int) |
| `GET /road/{roadName}/count` | path: `roadName`, `buffer_m` | `taxi_count` (int) |
| `POST /route/count` | body: GeoJSON LineString, `buffer_m` | `taxi_count` (int) |
| `GET /history/snapshots` | `start`, `end` (ISO-8601), optional `zone` | array of `{timestamp, count}` |
| `GET /history/recent` | `minutes` (int), optional `zone` | `delta` (int), `from_count`, `to_count` |

### 7.2 Example ReAct Trace (QT-01 with geocoding)

```
User: "How many taxis are within 3 km of Changi Airport?"

Thought: I need to resolve 'Changi Airport' to coordinates first.
Action: geocode_place
Action Input: "Changi Airport Singapore"
Observation: Changi Airport: lat=1.3644, lng=103.9893

Thought: Now find the radius-count endpoint in the spec.
Action: json_spec_tool
Action Input: {"query": "radius count"}
Observation: GET /api/spatial/radius-count — params: lat (float), lng (float), radius_km (float)
             Returns: {"taxi_count": integer, "snapshot_time": string}

Thought: Call the endpoint with the resolved coordinates.
Action: requests_get
Action Input: {"url": "http://java-service:8080/api/spatial/radius-count?lat=1.3644&lng=103.9893&radius_km=3"}
Observation: {"taxi_count": 142, "snapshot_time": "2026-02-28T06:30:00Z"}

Thought: I have the answer.
Final Answer: There are 142 available taxis within 3 km of Changi Airport as of 06:30 UTC.
```

---

## 8. API Design

**MVP endpoints:**

| Method | Path                      | Description                  |
| ------ | ------------------------- | ---------------------------- |
| POST   | `/api/v1/query`           | Natural language Q&A         |
| GET    | `/api/v1/snapshot/latest` | Latest snapshot metadata     |
| GET    | `/api/v1/health`          | Health check                 |

**Request:**

```json
POST /api/v1/query
{
    "query": "How many taxis are within 3km of Changi Airport?"
}
```

**Response:**

```json
{
    "answer": "There are 142 available taxis within 3 km of Changi Airport as of 2026-02-28T06:30:00Z.",
    "data": {
        "taxi_count": 142,
        "radius_km": 3.0,
        "center": { "latitude": 1.3644, "longitude": 103.9893 },
        "snapshot_time": "2026-02-28T06:30:00Z",
        "batch_id": "a1b2c3d4-..."
    },
    "query_plan": {
        "intent": "radius_count",
        "confidence": 0.95
    },
    "metadata": {
        "execution_time_ms": 87,
        "llm_latency_ms": 450,
        "sql_latency_ms": 32
    }
}
```

**Removed for MVP:** `POST /api/v1/query/structured`, `GET /api/v1/snapshot/{batch_id}`,
`GET /api/v1/regions`, `GET /api/v1/regions/{name}/count`, `GET /api/v1/metrics`.

---

## 9. Limitations

| #  | Limitation                                                                                        |
| -- | ------------------------------------------------------------------------------------------------- |
| L1 | **No individual taxi tracking.** No taxi IDs → cannot follow one taxi over time.                  |
| L2 | **No available vs. busy distinction.** The API only returns available taxis; occupied taxis are invisible. |
| L3 | **No speed or heading.** Cannot answer "How fast are taxis moving?" or "Which direction?"         |
| L4 | **No trajectory reconstruction.** Cannot answer "Where did the taxi near MBS go?"                |
| L5 | **No ETA estimation.** Requires trajectory + speed, neither available.                            |
| L6 | **No demand inference.** Only supply (available taxis) is visible; passenger demand is unknown.   |
| L7 | **Snapshot granularity is 30 s.** Sub-30-second trends are not observable.                        |
| L8 | **Location resolution is exact-match only.** Fuzzy/alias matching is post-MVP.                   |
| L9 | **LLM parsing is probabilistic.** Edge-case natural language may be misinterpreted.               |

---

## 10. NFR Targets (MVP)

| Requirement                          | MVP Target                    |
| ------------------------------------ | ----------------------------- |
| p95 latency (current-snapshot query) | < 3 s                         |
| p95 LLM latency                      | < 3 s                         |
| Ingestion throughput                 | best-effort (Java service, asyncpg COPY) |
| Concurrent users                     | 1–5                           |
| Uptime SLA                           | none                          |
| Data retention                       | 24 hours                      |

---

## 11. Post-MVP Roadmap

- **QT-10** Density ranking (zone count / area km²)
- **QT-11** Statistical aggregation (`taxi_agg_hourly` materialised view — min/max/avg per hour)
- **QT-12** Trend analysis (linear regression on snapshot counts)
- **QT-13** Heatmap data (hex grid or KDE via scipy)
- Table partitioning (daily, via pg_partman)
- BRIN index + partial index on `captured_at`
- 3-tier data retention (hot/warm/cold + S3 Parquet)
- Fuzzy location matching (pg_trgm + OneMap API fallback)
- `sg_landmarks` DB table (replace hardcoded dict)
- Redis LLM response cache
- PgBouncer connection pooling
- Read replicas for heavy analytical queries
- Prometheus + Grafana observability stack
- Retry / exponential backoff in ingestion worker
- GPT-4o fallback for low-confidence intents
- Conversation context / follow-up queries (FR-QA-7)

---

*End of MVP Design Document*
