# MVP Design: Taxi Spatial Q&A System — Singapore

> **Cross-repo docs** — when updating this file, also check:
> - `gov-data` → `docs/design-doc.md` — upstream REST endpoints, response envelope `{success, data, error}`, `data.type` and `context.type` unions
> - `gov-data` → `docs/zone-init-design.md` — zone names list must match PLANNING AREAS in system prompt (§6.3)
> - `civic-frontend` → `docs/apis-data-contract.md` — downstream consumer of `{answer, data, metadata}` response
> - `civic-frontend` → `docs/design.md` — `POST /api/v1/query` endpoint (§Data Flow), `{answer, data, metadata}` envelope, `data.type` (visualisation mode), `context.type` (label derivation), `layer_id`/`layer_label` fields
> - Full index: `civic-frontend/docs/cross-repo-index.md`

| Field           | Value                                                      |
| --------------- | ---------------------------------------------------------- |
| **Document ID** | MVP-TAXI-SG-2026-001                                       |
| **Version**     | 1.1                                                        |
| **Date**        | 2026-03-14                                                 |
| **Status**      | Active                                                     |
| **Replaces**    | PRD-TAXI-SG-2026-001, ARCH-TAXI-SG-2026-001                |

Full-scope originals archived in [`full-scope/`](full-scope/).

---

## 1. Overview & Design Principles

This Python project is the **LLM + tool-call layer** of the taxi spatial Q&A system. It receives
natural-language questions, uses a LangChain OpenAPI **planner agent** (GPT-4o-mini) to discover
the right Java service endpoint, call it, and return a natural-language answer.

**Data ingestion and all spatial SQL** are handled by the **Java service**, which also exposes a
REST API. This Python app never connects to the database — tools call the Java REST endpoints.

**Key design principles:**

- The raw data contains **anonymous coordinate-timestamp tuples only** — no taxi IDs, no status,
  no speed, no heading. Every supported query is answerable purely from set-of-points-at-a-time
  analysis.
- **The LLM NEVER generates SQL.** It selects a tool and provides parameters; the tool calls the
  Java spatial REST API which executes the parameterised PostGIS query.
- **MVP scope:** OpenAPI planner agent, OneMap geocoding, single Docker service, 9 query types, 8 API endpoints.

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
| QT-01 | Radius count      | "How many taxis within 3 km of Changi Airport?"                  | GET /nearby                     | Integer count + GeoJSON FeatureCollection|
| QT-02 | Nearest-K         | "Nearest 5 taxis to 1.3521, 103.8198"                            | GET /nearest                    | K coordinate pairs + distances (metres)  |
| QT-03 | Zone count        | "How many taxis are in Tampines?"                                | GET /zone/{zoneName}/count      | Count for the named zone                 |
| QT-04 | Nearby list       | "List taxis within 500 m of Raffles Place"                       | GET /nearby                     | Integer count + GeoJSON FeatureCollection|
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

Place names are resolved to `(lat, lng)` coordinates by a synchronous **`geocode_place`** LangChain
`@tool` that the agent calls before invoking any spatial endpoint. Implementation: `app/tools.py`.

- **Provider:** OneMap Singapore API (free, no API key required, Singapore-specific).
- **Endpoint:** `https://www.onemap.gov.sg/api/common/elastic/search`
- **Timeout:** 10 seconds. Returns structured error messages on timeout or HTTP errors.
- **Returns:** First result's latitude and longitude as a formatted string.

**Alternative considered:** Google Places API (`GooglePlacesTool`) — rejected for MVP due to billing
and lower accuracy for Singapore-specific names.

**Supported planning areas (QT-03):** Tampines, Jurong West, Bedok, Woodlands, Hougang, Sengkang,
Ang Mo Kio, Toa Payoh, Downtown Core, Orchard, Marina South, Queenstown, Clementi, Yishun, Geylang.

**Removed from MVP:** `pg_trgm` extension, GIN text-search index, 6-step resolution pipeline.

---

## 6. LLM Agent

This Python project is the **LLM + tool-call layer only**. Implementation: `app/agent.py`.

### 6.1 Architecture Flow

```
User question
      ↓
FastAPI POST /api/v1/query
      ↓
OpenAPI Planner Agent (GPT-4o-mini)
      ↓
   ↙     ↓          ↘
geocode   api_planner  api_controller
_place    (select       (execute call
           endpoint)     via CapturingRequestsWrapper)
      ↓
Java Spatial REST API  (no SQL in Python; PostGIS owned by Java service)
      ↓
JSON result captured by CapturingRequestsWrapper
      ↓
LLM composes natural-language answer
      ↓
get_last_raw_data() strips {success,data,error} envelope
      ↓
QueryResponse {answer, data, metadata}
```

### 6.2 Agent Setup

- **Module:** `langchain_community.agent_toolkits.openapi.planner`
- **LLM:** GPT-4o-mini, temperature 0
- **OpenAPI spec:** Fetched from `{JAVA_SPATIAL_API_URL}/api-docs` at startup, reduced via `reduce_openapi_spec()`
- **HTTP wrapper:** `CapturingRequestsWrapper` — extends `RequestsWrapper` to record the last raw
  HTTP response text. After agent invocation, `get_last_raw_data()` parses this response, strips
  the Java service's `{success, data, error}` envelope, and returns only the `data` object.
- **Agent creation:** `planner.create_openapi_agent(api_spec, wrapper, llm, extra_tools=[geocode_place])`
- **Flags:** `allow_dangerous_requests=True` (required for HTTP calls), `handle_parsing_errors=True`, `verbose=True`
- **Lifecycle:** Singleton pattern — agent is lazily initialised once and reused across requests.
  Pre-warmed on FastAPI startup (non-blocking if Java service is unreachable).

### 6.3 System Prompt

The current implementation does **not** pass a custom system prompt (`prefix`) to the planner
agent. The agent relies on the built-in LangChain OpenAPI planner prompt, which instructs the LLM
to explore the spec, plan the API call, and execute it.

**Post-MVP consideration:** A custom prefix can be added to improve accuracy for edge cases
(unit conversion km→m, planning-area matching, geocoding-failure handling, unsupported query
rejection).

---

## 7. Tools (Geo Query Layer)

The agent has **two tool sources**: one custom geocoding tool, and the OpenAPI planner module
which internally creates two composite tools:

| Tool | Source | What the agent uses it for |
| ---- | ------ | -------------------------- |
| `geocode_place` | Custom synchronous `@tool` in `app/tools.py` (OneMap API, §5) | Resolve any Singapore place name or address to `lat`/`lng` |
| `api_planner` | `planner.create_openapi_agent` (generated) | Read the reduced OpenAPI spec and select the correct endpoint + parameters |
| `api_controller` | `planner.create_openapi_agent` (generated) | Execute the planned HTTP call via `CapturingRequestsWrapper` and return the response |

The planner agent works in a two-phase loop: `api_planner` identifies which endpoint to call and
with what parameters, then `api_controller` executes the request.

### 7.1 Java Service OpenAPI Spec

The Java service exposes its spec at `GET /api-docs` (Swagger UI at `/swagger-ui.html`). MVP endpoints under `/api/v1/taxis`:

All Java service responses share the envelope `{ "success": bool, "data": { ... }, "error": null | {...} }`.
For spatial queries `data.type = "spatial_query"` and carries a `context` object echoing the query params.
For history queries `data.type = "timeline"`. The agent must navigate to `data.*` fields, not the envelope root.

| Endpoint | Key params | `data` shape |
| -------- | ---------- | ------------ |
| `GET /nearby` | `lat`, `lon`, `radius` (metres), `limit` | `type:"spatial_query"`, `taxi_count`, `snapshot_time`, `context:{type:"radius", lat, lon, radius_m}`, `locations` (GeoJSON FeatureCollection) |
| `GET /nearest` | `lat`, `lon`, `limit` (int) | `type:"spatial_query"`, `taxi_count`, `snapshot_time`, `context:{type:"nearest", lat, lon, limit}`, `locations` (FeatureCollection; each feature has `properties.distance_m`) |
| `GET /zone/{zoneName}/count` | path: `zoneName` | `type:"spatial_query"`, `taxi_count`, `snapshot_time`, `context:{type:"zone", zone_name, category}`, `locations` (FeatureCollection) |
| `POST /polygon/count` | body: GeoJSON Polygon | `type:"spatial_query"`, `taxi_count`, `snapshot_time`, `context:{type:"polygon", polygon}`, `locations` (FeatureCollection) |
| `GET /road/{roadName}/count` | path: `roadName`, `buffer_m` | `type:"spatial_query"`, `taxi_count`, `snapshot_time`, `context:{type:"road", road_name, category, buffer_m}`, `locations` (FeatureCollection) |
| `POST /route/count` | body: GeoJSON LineString, `buffer_m` | `type:"spatial_query"`, `taxi_count`, `snapshot_time`, `context:{type:"route", route, buffer_m}`, `locations` (FeatureCollection) |
| `GET /history/snapshots` | `start`, `end` (ISO-8601), optional `zone` | `type:"timeline"`, `from_time`, `to_time`, `snapshots:[{timestamp, taxi_count, locations (FeatureCollection)}]` |
| `GET /history/recent` | `minutes` (int), optional `zone` | `type:"timeline"`, `from_time`, `to_time`, `window_minutes`, `snapshots:[{timestamp, taxi_count, locations (FeatureCollection)}]` |

### 7.2 Example Planner Agent Trace (QT-01 with geocoding)

```
User: "How many taxis are within 3 km of Changi Airport?"

→ geocode_place("Changi Airport Singapore")
  ← Changi Airport: lat=1.3644, lng=103.9893

→ api_planner("Find taxis within 3000 metres of lat=1.3644, lon=103.9893")
  ← 1) GET /api/v1/taxis/nearby with params lat=1.3644, lon=103.9893, radius=3000

→ api_controller("1) GET /api/v1/taxis/nearby with params lat=1.3644, lon=103.9893, radius=3000")
  ← {"success": true, "data": {"taxi_count": 142, "snapshot_time": "2026-02-28T06:30:00+08:00", ...}}

Final Answer: There are 142 available taxis within 3 km of Changi Airport as of 06:30 UTC.
```

---

## 8. API Design

Implementation: `app/main.py` (FastAPI), `app/models.py` (Pydantic models).

**MVP endpoints:**

| Method | Path                      | Description                  |
| ------ | ------------------------- | ---------------------------- |
| POST   | `/api/v1/query`           | Natural language Q&A         |
| GET    | `/api/v1/snapshot/latest` | Latest snapshot metadata (proxied from Java service) |
| GET    | `/api/v1/health`          | Health check                 |

**CORS:** All origins, methods, and headers allowed.

**Request — `POST /api/v1/query`:**

```json
{ "query": "How many taxis are within 3km of Changi Airport?" }
```

**Response — `POST /api/v1/query`:**

The `data` field is extracted from the Java service's last HTTP response via `CapturingRequestsWrapper`.
The `{success, error}` envelope is stripped; `data.type` and `data.context` are preserved for
frontend rendering.

```json
{
    "answer": "There are 142 available taxis within 3 km of Changi Airport as of 14:30 SGT.",
    "data": {
        "type": "spatial_query",
        "taxi_count": 142,
        "snapshot_time": "2026-02-28T06:30:00+08:00",
        "context": { "type": "radius", "lat": 1.3644, "lon": 103.9893, "radius_m": 3000 },
        "locations": {
            "type": "FeatureCollection",
            "features": [
                { "type": "Feature", "geometry": { "type": "Point", "coordinates": [103.992, 1.361] }, "properties": null },
                { "type": "Feature", "geometry": { "type": "Point", "coordinates": [103.987, 1.365] }, "properties": null }
            ]
        }
    },
    "metadata": {
        "execution_time_ms": 87,
        "llm_latency_ms": 450
    }
}
```

> **Note:** `llm_latency_ms` is currently always `null` — only `execution_time_ms` (total
> wall-clock time for agent invocation) is measured. Per-LLM-call latency tracking is post-MVP.

**Response — `GET /api/v1/health`:**

```json
{ "status": "ok", "service": "taxi-spatial-qa", "version": "1.0.0" }
```

**Error responses:**

| Status | Condition | Detail |
| ------ | --------- | ------ |
| 503    | Agent not initialised (Java service unreachable) | "Agent unavailable — Java service may not be running" |
| 500    | Agent invocation failure | Error message from exception |
| 502    | `/snapshot/latest` proxy failure | "Could not reach Java service" |

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
- Custom system prompt for the planner agent (unit conversion, geocoding-failure handling)
- `llm_latency_ms` tracking in response metadata
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
