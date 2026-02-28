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

| Code  | Query Type   | Example                                          | Output                          |
| ----- | ------------ | ------------------------------------------------ | ------------------------------- |
| QT-01 | Radius count | "How many taxis within 3 km of Changi Airport?"  | Integer count                   |
| QT-02 | Nearest-K    | "Nearest 5 taxis to 1.3521, 103.8198"            | K coordinate pairs + distances  |
| QT-03 | Region count | "How many taxis are in Tampines?"                | Count for the named region      |

All other query types (QT-04 through QT-10) are deferred to the [Post-MVP Roadmap](#11-post-mvp-roadmap).

---

## 4. Data Model

> Owned entirely by the Java service. See the Java service documentation for table definitions,
> indexes, and migration scripts. This Python app has no database connection.

---

## 5. Location Resolution

Landmark coordinates are embedded directly in the agent's system prompt (see §6.3). The ReAct
agent reads them from context and passes `lat`/`lng` when calling the Java REST endpoint.
No Python resolver function is invoked.

```python
LANDMARK_COORDS: dict[str, tuple[float, float]] = {
    # name: (lat, lng)
    "Changi Airport":       (1.3644, 103.9893),
    "Jewel Changi":         (1.3601, 103.9894),
    "Marina Bay Sands":     (1.2838, 103.8607),
    "Sentosa":              (1.2494, 103.8303),
    "Raffles Place":        (1.2843, 103.8514),
    "HarbourFront":         (1.2647, 103.8199),
    "Woodlands Checkpoint": (1.4473, 103.7691),
    "Tuas Checkpoint":      (1.3458, 103.6367),
    "NUS":                  (1.2966, 103.7764),
    "NTU":                  (1.3483, 103.6831),
    "Gardens by the Bay":   (1.2816, 103.8636),
    "Singapore Zoo":        (1.4043, 103.7930),
    "VivoCity":             (1.2643, 103.8200),
    "ION Orchard":          (1.3040, 103.8318),
    "Bugis Junction":       (1.2993, 103.8554),
    "Orchard Road":         (1.3048, 103.8318),
}
```

**Supported planning areas (QT-03):** Tampines, Jurong West, Bedok, Woodlands, Hougang, Sengkang,
Ang Mo Kio, Toa Payoh, Downtown Core, Orchard, Marina South, Queenstown, Clementi, Yishun, Geylang.

**Removed from MVP:** `pg_trgm` extension, GIN text-search index, OneMap API fallback,
6-step resolution pipeline.

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

agent_executor = create_openapi_agent(
    llm=llm,
    toolkit=toolkit,
    prefix=SYSTEM_PROMPT,   # see §6.3
    verbose=False,
    max_iterations=5,
)

# Usage:
result = await agent_executor.ainvoke({"input": user_query})
answer = result["output"]
```

### 6.3 System Prompt

Passed as `prefix` to `create_openapi_agent`. Landmark coordinates are embedded here so the
ReAct agent can supply `lat`/`lng` directly when constructing endpoint URLs.

```python
SYSTEM_PROMPT = """You are a helpful assistant for querying real-time Singapore taxi distribution data.
Use the OpenAPI tools to inspect the Java service spec, then call the correct endpoint.

DATA SOURCE:
- Taxi positions are ingested from data.gov.sg every 30 seconds by the Java service.
- Available data: anonymous (latitude, longitude) per available taxi, per snapshot.
- NO taxi IDs, NO speed, NO heading. All taxis in the data are available (not occupied).

THE API EXPOSES THREE SPATIAL ENDPOINTS — inspect the spec to find exact paths and parameters:
- radius count  : count taxis within N km of a (lat, lng) coordinate
- nearest-K     : find the K nearest taxis to a (lat, lng) coordinate
- region count  : count taxis in a named Singapore URA planning area

LANDMARK COORDINATES — pass these directly when calling coordinate-based endpoints:
  Changi Airport        lat=1.3644  lng=103.9893
  Jewel Changi          lat=1.3601  lng=103.9894
  Marina Bay Sands      lat=1.2838  lng=103.8607
  Sentosa               lat=1.2494  lng=103.8303
  Raffles Place         lat=1.2843  lng=103.8514
  HarbourFront          lat=1.2647  lng=103.8199
  Woodlands Checkpoint  lat=1.4473  lng=103.7691
  Tuas Checkpoint       lat=1.3458  lng=103.6367
  NUS                   lat=1.2966  lng=103.7764
  NTU                   lat=1.3483  lng=103.6831
  Gardens by the Bay    lat=1.2816  lng=103.8636
  Singapore Zoo         lat=1.4043  lng=103.7930
  VivoCity              lat=1.2643  lng=103.8200
  ION Orchard           lat=1.3040  lng=103.8318
  Bugis Junction        lat=1.2993  lng=103.8554
  Orchard Road          lat=1.3048  lng=103.8318

PLANNING AREAS for region count:
  Tampines, Jurong West, Bedok, Woodlands, Hougang, Sengkang, Ang Mo Kio, Toa Payoh,
  Downtown Core, Orchard, Marina South, Queenstown, Clementi, Yishun, Geylang.

UNSUPPORTED — respond without calling any tool and explain why:
  Tracking a specific taxi, speed/heading queries, ETA, trajectory, or demand inference.
"""
```

---

## 7. Tools (Geo Query Layer)

Tools are **not written by hand** in this Python service. An `OpenAPIToolkit` loads the Java
service's OpenAPI spec at startup and hands the ReAct agent two runtime tools. The agent
discovers and calls the correct endpoint autonomously — no hardcoded paths, no Pydantic
schemas, no `@tool` functions.

| Runtime tool | What the agent uses it for |
| ------------ | -------------------------- |
| `json_spec_tool` | Read the spec to discover endpoint paths, HTTP methods, parameter names, and response schemas |
| `requests_get` | Make HTTP GET calls to the discovered endpoints with resolved parameters |

### 7.1 Java Service OpenAPI Spec

The Java service exposes its spec at `GET /v3/api-docs`. The three MVP endpoints the agent
discovers and calls at runtime:

| Endpoint | Query params | Response field |
| -------- | ------------ | -------------- |
| `GET /api/spatial/radius-count` | `lat` (float), `lng` (float), `radius_km` (float) | `taxi_count` (int) |
| `GET /api/spatial/nearest` | `lat` (float), `lng` (float), `k` (int) | `taxis` (array of `{lat, lng, distance_m}`) |
| `GET /api/spatial/region-count` | `region` (string) | `taxi_count` (int) |

### 7.2 Example ReAct Trace (QT-01)

```
User: "How many taxis are within 3 km of Changi Airport?"

Thought: I need a radius count. Let me check the spec for the right endpoint.
Action: json_spec_tool
Action Input: {"query": "radius count"}
Observation: GET /api/spatial/radius-count — params: lat (float), lng (float), radius_km (float)
             Returns: {"taxi_count": integer, "snapshot_time": string}

Thought: Changi Airport is at lat=1.3644, lng=103.9893 per the system context.
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

- **QT-04** Road buffer count (`sg_road_corridors` table + `ST_DWithin` on linestring)
- **QT-05** Density ranking (region count / area)
- **QT-06** Time-window count (count per 30 s snapshot over a range)
- **QT-07** Trend analysis (linear regression on snapshot counts)
- **QT-08** Statistical aggregation (`taxi_agg_hourly` materialised view)
- **QT-09** Snapshot comparison
- **QT-10** Heatmap data (hex grid or KDE via scipy)
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
