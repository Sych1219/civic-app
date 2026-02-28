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
natural-language questions, uses a LangChain agent (GPT-4o-mini) to select and invoke the right
spatial query tool via the Java REST API, and returns a natural-language answer.

**Data ingestion and all spatial SQL** are handled by the **Java service**, which also exposes a
REST API. This Python app never connects to the database — tools call the Java REST endpoints.

**Key design principles:**

- The raw data contains **anonymous coordinate-timestamp tuples only** — no taxi IDs, no status,
  no speed, no heading. Every supported query is answerable purely from set-of-points-at-a-time
  analysis.
- **The LLM NEVER generates SQL.** It selects a tool and provides parameters; the tool calls the
  Java spatial REST API which executes the parameterised PostGIS query.
- **MVP scope:** LLM agent + 3 spatial tools, hardcoded location gazetteer, single Docker service,
  3 query types, 3 API endpoints.

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

Landmarks are resolved from a hardcoded Python dictionary before the tool makes its REST call.
For regions (QT-03), the region name string is passed directly to the Java service.

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

For regions (QT-03), the region name is passed as-is to the Java REST endpoint.

**Supported planning areas (QT-03):** Tampines, Jurong West, Bedok, Woodlands, Hougang, Sengkang,
Ang Mo Kio, Toa Payoh, Downtown Core, Orchard, Marina South, Queenstown, Clementi, Yishun, Geylang.

**Removed from MVP:** `pg_trgm` extension, GIN text-search index, OneMap API fallback,
6-step resolution pipeline.

---

## 6. LLM Agent

This Python project is the **LLM + tool-call layer only**. The agent receives a user question,
selects the appropriate spatial tool, executes it against PostGIS, and returns a natural-language
answer.

### 6.1 Architecture Flow

```
User question
      ↓
LLM Agent (GPT-4o-mini)        ← decides which tool to call
      ↓
Tool called with parameters
      ↓
Java Spatial REST API          ← HTTP call (httpx); no SQL in Python
      ↓
PostGIS (parameterised SQL)    ← owned entirely by Java service
      ↓
JSON result returned to tool
      ↓
LLM composes natural-language answer
```

### 6.2 Agent Setup

```python
from langchain_openai import ChatOpenAI
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from langchain.agents import create_tool_calling_agent, AgentExecutor

llm = ChatOpenAI(model="gpt-4o-mini", temperature=0)

tools = [count_taxis_in_radius, find_nearest_taxis, count_taxis_in_region]

prompt = ChatPromptTemplate.from_messages([
    ("system", SYSTEM_PROMPT),
    ("human", "{input}"),
    MessagesPlaceholder(variable_name="agent_scratchpad"),
])

agent = create_tool_calling_agent(llm, tools, prompt)
agent_executor = AgentExecutor(agent=agent, tools=tools, verbose=False)

# Usage:
result = await agent_executor.ainvoke({"input": user_query})
answer = result["output"]
```

### 6.3 System Prompt

```python
SYSTEM_PROMPT = """You are a helpful assistant for querying real-time Singapore taxi distribution data.

DATA SOURCE:
- Taxi positions are ingested from data.gov.sg every 30 seconds by a separate Java service.
- Available data: anonymous (latitude, longitude) per available taxi, per snapshot.
- NO taxi IDs, NO speed, NO heading. All taxis in the data are available (not occupied).

YOU HAVE THREE TOOLS — always call a tool before answering a count or location question:
- count_taxis_in_radius: count taxis within N km of a named landmark or coordinate
- find_nearest_taxis: find the K nearest taxis to a coordinate
- count_taxis_in_region: count taxis in a named Singapore URA planning area

LANDMARKS you can use with count_taxis_in_radius:
Changi Airport, Jewel Changi, Marina Bay Sands, Sentosa, Raffles Place, HarbourFront,
Woodlands Checkpoint, Tuas Checkpoint, NUS, NTU, Gardens by the Bay, Singapore Zoo,
VivoCity, ION Orchard, Bugis Junction, Orchard Road.

PLANNING AREAS you can use with count_taxis_in_region:
Tampines, Jurong West, Bedok, Woodlands, Hougang, Sengkang, Ang Mo Kio, Toa Payoh,
Downtown Core, Orchard, Marina South, Queenstown, Clementi, Yishun, Geylang.

UNSUPPORTED — respond without calling a tool and explain why:
- Tracking a specific taxi, speed/heading queries, ETA, trajectory, or demand inference.
"""
```

---

## 7. Tools (Geo Query Layer)

Each tool is a LangChain `@tool` with a typed Pydantic input schema. Tools call the
**Java spatial REST API** via `httpx`. **This Python service never connects to the database
directly** — all SQL and PostGIS logic lives in the Java service.

```python
import httpx
import os

JAVA_API_BASE = os.environ["JAVA_SPATIAL_API_URL"]  # e.g. http://java-service:8080
```

### 7.1 `count_taxis_in_radius` (QT-01)

```python
from pydantic import BaseModel, Field
from langchain_core.tools import tool

class RadiusCountInput(BaseModel):
    landmark_or_location: str = Field(
        description="Landmark name (e.g. 'Changi Airport') or 'lat,lng' coordinate string"
    )
    radius_km: float = Field(description="Search radius in kilometres")

@tool("count_taxis_in_radius", args_schema=RadiusCountInput)
async def count_taxis_in_radius(landmark_or_location: str, radius_km: float) -> str:
    """Count available taxis within radius_km of a landmark or coordinate (QT-01)."""
    lat, lng = resolve_location(landmark_or_location)  # looks up LANDMARK_COORDS dict
    async with httpx.AsyncClient() as client:
        resp = await client.get(
            f"{JAVA_API_BASE}/api/spatial/radius-count",
            params={"lat": lat, "lng": lng, "radius_km": radius_km},
        )
        resp.raise_for_status()
        count = resp.json()["taxi_count"]
    return f"{count} taxis within {radius_km} km of {landmark_or_location}."
```

### 7.2 `find_nearest_taxis` (QT-02)

```python
class NearestKInput(BaseModel):
    latitude: float = Field(description="Latitude of the reference point")
    longitude: float = Field(description="Longitude of the reference point")
    k: int = Field(default=5, description="Number of nearest taxis to return (default 5)")

@tool("find_nearest_taxis", args_schema=NearestKInput)
async def find_nearest_taxis(latitude: float, longitude: float, k: int = 5) -> str:
    """Find the K nearest available taxis to a coordinate (QT-02)."""
    async with httpx.AsyncClient() as client:
        resp = await client.get(
            f"{JAVA_API_BASE}/api/spatial/nearest",
            params={"lat": latitude, "lng": longitude, "k": k},
        )
        resp.raise_for_status()
        taxis = resp.json()["taxis"]  # [{"lat": ..., "lng": ..., "distance_m": ...}, ...]
    results = [
        f"({t['lat']:.4f}, {t['lng']:.4f}) — {t['distance_m']:.0f} m" for t in taxis
    ]
    return f"Nearest {k} taxis:\n" + "\n".join(results)
```

### 7.3 `count_taxis_in_region` (QT-03)

```python
class RegionCountInput(BaseModel):
    region_name: str = Field(
        description="Name of a Singapore URA planning area, e.g. 'Tampines', 'Downtown Core'"
    )

@tool("count_taxis_in_region", args_schema=RegionCountInput)
async def count_taxis_in_region(region_name: str) -> str:
    """Count available taxis in a named Singapore planning region (QT-03)."""
    async with httpx.AsyncClient() as client:
        resp = await client.get(
            f"{JAVA_API_BASE}/api/spatial/region-count",
            params={"region": region_name},
        )
        if resp.status_code == 404:
            return f"Region '{region_name}' not found."
        resp.raise_for_status()
        count = resp.json()["taxi_count"]
    return f"{count} taxis currently in {region_name}."
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
