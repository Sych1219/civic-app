# Technical Architecture Document

## Taxi Spatial Distribution Q&A System — Singapore

| Field           | Value                                      |
| --------------- | ------------------------------------------ |
| **Document ID** | ARCH-TAXI-SG-2026-001                      |
| **Version**     | 1.0                                        |
| **Date**        | 2026-02-28                                 |
| **Companion**   | PRD-TAXI-SG-2026-001                       |
| **Status**      | Draft                                      |

---

## Table of Contents

1. [System Architecture Overview](#1-system-architecture-overview)
2. [Architecture Diagram (Text)](#2-architecture-diagram-text)
3. [Data Model Design](#3-data-model-design)
4. [Spatial Index Strategy](#4-spatial-index-strategy)
5. [Data Ingestion Pipeline](#5-data-ingestion-pipeline)
6. [Location Resolution Subsystem](#6-location-resolution-subsystem)
7. [LLM Intent Parsing Layer](#7-llm-intent-parsing-layer)
8. [Spatial Query Execution Engine](#8-spatial-query-execution-engine)
9. [Query Flow (End-to-End)](#9-query-flow-end-to-end)
10. [Time-Window Aggregation](#10-time-window-aggregation)
11. [Spatial Density Analysis](#11-spatial-density-analysis)
12. [API Design](#12-api-design)
13. [Performance Considerations](#13-performance-considerations)
14. [Scaling Strategy](#14-scaling-strategy)
15. [Limitations & Constraints](#15-limitations--constraints)
16. [Technology Stack](#16-technology-stack)
17. [Deployment Architecture](#17-deployment-architecture)
18. [Monitoring & Observability](#18-monitoring--observability)
19. [Security Considerations](#19-security-considerations)
20. [Appendix: Reference SQL Queries](#20-appendix-reference-sql-queries)

---

## 1. System Architecture Overview

The system follows a **layered architecture** with strict separation between:

1. **Data Ingestion Layer** — Polls LTA API, normalises, bulk-inserts into PostGIS.
2. **Storage Layer** — PostgreSQL + PostGIS with partitioned tables and spatial indexes.
3. **Location Resolution Layer** — Geocodes place names to geometries (local gazetteer + OneMap fallback).
4. **LLM Intent Parsing Layer** — Converts natural language to a structured `QueryPlan` (JSON).
5. **Spatial Query Execution Layer** — Translates `QueryPlan` into parameterised PostGIS SQL; executes.
6. **Response Formatting Layer** — Converts raw query results into human-readable + structured JSON.
7. **API Layer** — FastAPI endpoints for Q&A, health, admin.

**Core design principle: The LLM NEVER touches SQL or the database directly.** It produces a typed intent object; deterministic code converts that to safe, parameterised SQL.

---

## 2. Architecture Diagram (Text)

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                          CLIENT LAYER                                       │
│                                                                             │
│   ┌──────────────┐  ┌──────────────┐  ┌──────────────┐                     │
│   │  Web Chat UI │  │  REST Client │  │  Dashboard   │                     │
│   └──────┬───────┘  └──────┬───────┘  └──────┬───────┘                     │
│          │                 │                 │                               │
└──────────┼─────────────────┼─────────────────┼──────────────────────────────┘
           │                 │                 │
           ▼                 ▼                 ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                          API GATEWAY (FastAPI)                               │
│                                                                             │
│   POST /api/v1/query     GET /api/v1/health     GET /api/v1/snapshot/latest │
│   POST /api/v1/query/structured                  GET /api/v1/regions        │
└─────────────────────────────┬───────────────────────────────────────────────┘
                              │
           ┌──────────────────┼──────────────────┐
           │                  │                  │
           ▼                  ▼                  ▼
┌────────────────┐  ┌─────────────────┐  ┌────────────────────┐
│  LLM INTENT    │  │  LOCATION       │  │  RESPONSE          │
│  PARSER        │  │  RESOLVER       │  │  FORMATTER         │
│                │  │                 │  │                    │
│ NL → QueryPlan │  │ "Changi" →      │  │ SQL results →      │
│ (GPT-4o-mini)  │  │ POINT(103.98,   │  │ human summary +    │
│                │  │       1.36)     │  │ structured JSON    │
│ • intent type  │  │                 │  │                    │
│ • parameters   │  │ • Local gazet.  │  │ • Jinja templates  │
│ • time window  │  │ • URA polygons  │  │ • Chart-ready data │
│ • location ref │  │ • Road lines    │  │                    │
└───────┬────────┘  └────────┬────────┘  └─────────┬──────────┘
        │                    │                     │
        ▼                    ▼                     │
┌─────────────────────────────────────────┐        │
│     SPATIAL QUERY EXECUTION ENGINE      │        │
│                                         │        │
│  QueryPlan + resolved geometries        │        │
│       → parameterised PostGIS SQL       │        │
│       → execute via asyncpg             │◄───────┘
│       → return typed result set         │
└────────────────────┬────────────────────┘
                     │
                     ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                      STORAGE LAYER (PostgreSQL 16 + PostGIS 3.4)            │
│                                                                             │
│  ┌──────────────────────┐  ┌──────────────────────┐  ┌──────────────────┐  │
│  │  taxi_positions      │  │  snapshot_metadata   │  │  sg_regions      │  │
│  │  (range-partitioned  │  │                      │  │  (URA planning   │  │
│  │   by timestamp,      │  │  batch_id, ts,       │  │   area polygons) │  │
│  │   GIST spatial idx)  │  │  count, ingest_ms    │  │                  │  │
│  └──────────────────────┘  └──────────────────────┘  └──────────────────┘  │
│                                                                             │
│  ┌──────────────────────┐  ┌──────────────────────┐  ┌──────────────────┐  │
│  │  sg_landmarks        │  │  sg_road_corridors   │  │  taxi_agg_hourly │  │
│  │  (POI name → point)  │  │  (road → linestring) │  │  (materialised   │  │
│  │                      │  │                      │  │   aggregation)   │  │
│  └──────────────────────┘  └──────────────────────┘  └──────────────────┘  │
└─────────────────────────────────────────────────────────────────────────────┘

           ┌──────────────────────────────────────┐
           │      DATA INGESTION PIPELINE         │
           │                                      │
           │  ┌────────────┐    ┌──────────────┐  │
           │  │ LTA Poller │───▶│ Bulk Inserter│  │
           │  │ (30s cron) │    │ (asyncpg)    │  │
           │  └────────────┘    └──────────────┘  │
           │                                      │
           │  ┌────────────┐    ┌──────────────┐  │
           │  │ Retry Mgr  │    │ Metrics Emit │  │
           │  └────────────┘    └──────────────┘  │
           └──────────────────────────────────────┘
```

---

## 3. Data Model Design

### 3.1 Core Table: `taxi_positions`

This is the central fact table. It is **range-partitioned by timestamp** (daily partitions) for efficient time-based queries and partition pruning.

```sql
-- Enable PostGIS
CREATE EXTENSION IF NOT EXISTS postgis;

-- ============================================================
-- Core table: one row per taxi coordinate per snapshot
-- ============================================================
CREATE TABLE taxi_positions (
    id          BIGINT GENERATED ALWAYS AS IDENTITY,
    batch_id    UUID            NOT NULL,
    geom        GEOMETRY(Point, 4326) NOT NULL,
    captured_at TIMESTAMPTZ     NOT NULL,

    -- Composite primary key lives on each partition
    PRIMARY KEY (captured_at, id)
) PARTITION BY RANGE (captured_at);

-- Partition creation example (automated via pg_partman or cron):
CREATE TABLE taxi_positions_20260228
    PARTITION OF taxi_positions
    FOR VALUES FROM ('2026-02-28 00:00:00+00')
              TO   ('2026-03-01 00:00:00+00');

-- Repeat daily via pg_partman:
-- SELECT partman.create_parent(
--     'public.taxi_positions', 'captured_at', 'native', 'daily'
-- );

COMMENT ON TABLE taxi_positions IS
    'Each row = one anonymous taxi coordinate at one snapshot time. '
    'No taxi_id exists — rows cannot be joined across snapshots for the same vehicle.';
```

**Column rationale:**

| Column        | Rationale                                                            |
| ------------- | -------------------------------------------------------------------- |
| `id`          | Partition-local surrogate key for physical row identification.       |
| `batch_id`    | Groups all points from a single API call. Enables "snapshot" queries.|
| `geom`        | PostGIS Point geometry in WGS 84. Enables all spatial operations.    |
| `captured_at` | Partition key + time-based filtering. Indexed via B-tree partition.  |

**What is intentionally ABSENT:**

| Omitted Column | Reason                                                          |
| -------------- | --------------------------------------------------------------- |
| `taxi_id`      | Does not exist in source data.                                  |
| `status`       | Not available; all returned taxis are implicitly "available".   |
| `speed`        | Not available; cannot be derived without identity + trajectory. |
| `heading`      | Not available.                                                  |
| `region_id`    | Computed at query time via `ST_Contains`, not stored (avoids stale data if regions change). |

### 3.2 Snapshot Metadata Table

```sql
CREATE TABLE snapshot_metadata (
    batch_id       UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    captured_at    TIMESTAMPTZ NOT NULL,
    taxi_count     INTEGER     NOT NULL,
    ingestion_ms   INTEGER,          -- bulk insert latency in ms
    api_latency_ms INTEGER,          -- LTA API response time in ms
    created_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_snapshot_meta_captured ON snapshot_metadata (captured_at DESC);

COMMENT ON TABLE snapshot_metadata IS
    'One row per API poll. Used for monitoring, data quality checks, '
    'and fast "latest snapshot" lookups without scanning taxi_positions.';
```

### 3.3 Singapore Regions (URA Planning Areas)

```sql
CREATE TABLE sg_regions (
    id        SERIAL PRIMARY KEY,
    name      TEXT NOT NULL UNIQUE,        -- e.g. 'Tampines', 'Downtown Core'
    name_alt  TEXT,                         -- alternative names / abbreviations
    geom      GEOMETRY(MultiPolygon, 4326) NOT NULL,
    area_km2  DOUBLE PRECISION GENERATED ALWAYS AS (
                  ST_Area(geom::geography) / 1e6
              ) STORED
);

CREATE INDEX idx_sg_regions_geom ON sg_regions USING GIST (geom);

COMMENT ON TABLE sg_regions IS
    'URA Master Plan 2019 planning area polygons. Source: data.gov.sg';
```

### 3.4 Singapore Landmarks / POIs

```sql
CREATE TABLE sg_landmarks (
    id       SERIAL PRIMARY KEY,
    name     TEXT NOT NULL,
    aliases  TEXT[],                       -- e.g. {'MBS', 'Marina Bay Sands'}
    geom     GEOMETRY(Point, 4326) NOT NULL,
    category TEXT                           -- 'airport', 'mall', 'university', etc.
);

CREATE INDEX idx_sg_landmarks_geom ON sg_landmarks USING GIST (geom);
CREATE INDEX idx_sg_landmarks_name ON sg_landmarks USING GIN (
    to_tsvector('english', name || ' ' || COALESCE(array_to_string(aliases, ' '), ''))
);
```

### 3.5 Singapore Road Corridors

```sql
CREATE TABLE sg_road_corridors (
    id       SERIAL PRIMARY KEY,
    name     TEXT NOT NULL,                -- e.g. 'Orchard Road', 'PIE'
    aliases  TEXT[],
    geom     GEOMETRY(LineString, 4326) NOT NULL,
    buffer_m DOUBLE PRECISION DEFAULT 200  -- default buffer width in metres
);

CREATE INDEX idx_sg_roads_geom ON sg_road_corridors USING GIST (geom);
```

### 3.6 Materialised Aggregation: Hourly Region Counts

```sql
CREATE MATERIALIZED VIEW taxi_agg_hourly AS
SELECT
    r.name                                         AS region_name,
    date_trunc('hour', tp.captured_at)             AS hour,
    COUNT(*)                                       AS total_points,
    COUNT(DISTINCT tp.batch_id)                    AS snapshot_count,
    ROUND(COUNT(*)::numeric / NULLIF(COUNT(DISTINCT tp.batch_id), 0), 1)
                                                   AS avg_per_snapshot
FROM taxi_positions tp
JOIN sg_regions r ON ST_Contains(r.geom, tp.geom)
GROUP BY r.name, date_trunc('hour', tp.captured_at);

CREATE UNIQUE INDEX idx_agg_hourly_region_hour
    ON taxi_agg_hourly (region_name, hour);

-- Refresh strategy: every 5 minutes via pg_cron
-- SELECT cron.schedule('refresh_agg_hourly', '*/5 * * * *',
--     $$REFRESH MATERIALIZED VIEW CONCURRENTLY taxi_agg_hourly$$);
```

### 3.7 Entity-Relationship Summary

```
snapshot_metadata 1──────────M taxi_positions    (via batch_id)
sg_regions        1──────────M taxi_positions    (spatial: ST_Contains at query time)
sg_landmarks      ────────── (used by Location Resolver, not FK)
sg_road_corridors ────────── (used by Location Resolver, not FK)
taxi_agg_hourly   ────────── (derived from taxi_positions × sg_regions)
```

---

## 4. Spatial Index Strategy

### 4.1 Primary Spatial Index

```sql
CREATE INDEX idx_taxi_pos_geom ON taxi_positions USING GIST (geom);
```

- **Type:** GiST (Generalized Search Tree) — the standard PostGIS spatial index.
- **Scope:** Created on each partition automatically (partition-local indexes).
- **Supports:** `ST_DWithin`, `ST_Contains`, `ST_Intersects`, `<->` (KNN distance operator).

### 4.2 Time-Based Index (Partition Key)

```sql
-- Implicit from partitioning on captured_at
-- Each partition covers one day; queries with time predicates trigger partition pruning.
```

- Daily partitions give the planner a **direct mapping** from `WHERE captured_at BETWEEN ...` to a minimal set of partitions.

### 4.3 Composite Index for Time + Space Queries

```sql
CREATE INDEX idx_taxi_pos_time_geom ON taxi_positions
    USING GIST (geom)
    WHERE captured_at >= (now() - INTERVAL '1 hour');
-- Partial index for "recent" queries — most common use case.
```

**Alternative — BRIN index on captured_at:**

```sql
CREATE INDEX idx_taxi_pos_captured_brin ON taxi_positions
    USING BRIN (captured_at)
    WITH (pages_per_range = 32);
```

- BRIN is very compact and effective because `captured_at` is **monotonically increasing** (inserted in order). Combined with partition pruning, this provides two layers of time filtering before the GiST spatial index is consulted.

### 4.4 Index Usage by Query Type

| Query Type             | Indexes Used                                     |
| ---------------------- | ------------------------------------------------ |
| Radius count (QT-01)   | Partition pruning → BRIN → GiST (`ST_DWithin`)  |
| Nearest-K (QT-02)      | Partition pruning → GiST (KNN `<->` operator)   |
| Region count (QT-03)   | Partition pruning → GiST (`ST_Contains`)         |
| Road buffer (QT-04)    | Partition pruning → GiST (`ST_DWithin` on line)  |
| Density ranking (QT-05)| GiST join (regions × positions)                  |
| Time-window (QT-06)    | Partition pruning → BRIN → GiST                  |
| Trend analysis (QT-07) | Partition pruning → grouped aggregation           |
| Statistical agg (QT-08)| Materialised view `taxi_agg_hourly`               |

### 4.5 Index Maintenance

- **Autovacuum** tuned for high-insert workload: `autovacuum_vacuum_scale_factor = 0.01` on `taxi_positions`.
- **Partition drop** for expired data (> 7 days): `DROP TABLE taxi_positions_20260221;` — instant space reclaim, no vacuuming needed.
- **REINDEX** is unnecessary for dropped partitions; new partitions start fresh.

---

## 5. Data Ingestion Pipeline

### 5.1 Architecture

```
┌─────────┐    HTTPS     ┌─────────────┐   asyncpg    ┌────────────┐
│ LTA API │─────────────▶│ Poller Svc   │─────────────▶│ PostgreSQL │
│ (30s)   │              │ (Python)     │              │ + PostGIS  │
└─────────┘              └──────┬───────┘              └────────────┘
                                │
                         Prometheus metrics
                                │
                         ┌──────▼───────┐
                         │ Monitoring   │
                         └──────────────┘
```

### 5.2 Poller Service (Python, asyncio)

```python
# Pseudocode — ingestion loop
async def ingestion_loop():
    while True:
        start = time.monotonic()
        try:
            data = await fetch_lta_taxi_availability()  # httpx async
            batch_id = uuid4()
            captured_at = datetime.now(timezone.utc)

            records = [
                (batch_id, f"SRID=4326;POINT({row['longitude']} {row['latitude']})", captured_at)
                for row in data
            ]

            async with pool.acquire() as conn:
                await conn.copy_records_to_table(
                    'taxi_positions',
                    records=records,
                    columns=['batch_id', 'geom', 'captured_at']
                )
                await conn.execute(
                    "INSERT INTO snapshot_metadata (batch_id, captured_at, taxi_count, ingestion_ms, api_latency_ms) "
                    "VALUES ($1, $2, $3, $4, $5)",
                    batch_id, captured_at, len(records), ingestion_ms, api_latency_ms
                )

            emit_metrics(count=len(records), latency_ms=elapsed_ms(start))

        except Exception as e:
            log.error(f"Ingestion failed: {e}")
            await asyncio.sleep(backoff())

        await asyncio.sleep(max(0, 30 - elapsed(start)))
```

### 5.3 Bulk Insert Strategy

| Method              | Throughput       | Used When               |
| ------------------- | ---------------- | ----------------------- |
| `COPY ... FROM`     | ~50 000 rows/s   | Primary method          |
| Batch `INSERT`      | ~10 000 rows/s   | Fallback                |
| `unnest()` array    | ~30 000 rows/s   | Alternative             |

We use `asyncpg.copy_records_to_table()` which wraps PostgreSQL's binary `COPY` protocol — the fastest path for bulk loading.

### 5.4 Data Retention Policy

| Tier   | Data                     | Retention | Storage         |
| ------ | ------------------------ | --------- | --------------- |
| Hot    | Raw `taxi_positions`     | 7 days    | PostgreSQL SSD  |
| Warm   | `taxi_agg_hourly` (MV)   | 90 days   | PostgreSQL SSD  |
| Cold   | Exported Parquet files   | 2 years   | S3 / MinIO      |

Partition drop is the mechanism for hot-tier expiry — no `DELETE` required.

---

## 6. Location Resolution Subsystem

### 6.1 Overview

The Location Resolver converts natural language location references into PostGIS geometries:

| Input Type            | Example                    | Resolved To                              |
| --------------------- | -------------------------- | ---------------------------------------- |
| Landmark name         | "Changi Airport"           | `POINT(103.9893 1.3644)` from `sg_landmarks` |
| Planning area name    | "Tampines"                 | `MULTIPOLYGON(...)` from `sg_regions`     |
| Road corridor name    | "Orchard Road"             | `LINESTRING(...)` from `sg_road_corridors` |
| Raw coordinates       | "1.3521, 103.8198"         | `POINT(103.8198 1.3521)` pass-through     |
| Descriptive location  | "near the airport"         | Fuzzy match → `sg_landmarks`              |

### 6.2 Resolution Pipeline

```
User text fragment ──▶ [1] Regex: lat/lng extraction
                        │
                        ▼ (no match)
                       [2] Exact match in sg_landmarks.name / aliases
                        │
                        ▼ (no match)
                       [3] Exact match in sg_regions.name / name_alt
                        │
                        ▼ (no match)
                       [4] Exact match in sg_road_corridors.name / aliases
                        │
                        ▼ (no match)
                       [5] Trigram similarity search (pg_trgm)
                        │
                        ▼ (no match)
                       [6] OneMap Geocoding API fallback
                        │
                        ▼ (still no match)
                       [7] Return error: "Could not resolve location"
```

### 6.3 Fuzzy Matching

```sql
CREATE EXTENSION IF NOT EXISTS pg_trgm;

-- Example: fuzzy search across all location tables
SELECT name, similarity(name, 'changi airport') AS sim
FROM sg_landmarks
WHERE name % 'changi airport'
ORDER BY sim DESC
LIMIT 3;
```

### 6.4 Pre-Seeded Data Sources

| Table               | Source                                        | Record Count |
| ------------------- | --------------------------------------------- | ------------ |
| `sg_regions`        | URA Master Plan 2019 (data.gov.sg)            | ~55          |
| `sg_landmarks`      | Curated list + OneMap Search API               | ~100+        |
| `sg_road_corridors` | OpenStreetMap Overpass export + manual curation | ~50+         |

---

## 7. LLM Intent Parsing Layer

### 7.1 Design Philosophy

> **The LLM is a classifier and parameter extractor — not a SQL generator.**

The LLM receives the user's natural language query and outputs a **structured `QueryPlan` object**. It never sees the database schema, never generates SQL, and never accesses data directly. This design ensures:

- **Safety:** No SQL injection risk.
- **Determinism:** The same `QueryPlan` always produces the same SQL.
- **Testability:** Intent parsing can be unit-tested independently of the database.
- **Auditability:** The `QueryPlan` is logged and can be reviewed.

### 7.2 QueryPlan Schema

```python
from pydantic import BaseModel, Field
from typing import Optional, Literal
from datetime import datetime

class TimeWindow(BaseModel):
    start: Optional[datetime] = None       # None = use latest snapshot
    end: Optional[datetime] = None
    relative: Optional[str] = None         # e.g. "last 10 minutes", "last 1 hour"

class LocationReference(BaseModel):
    raw_text: str                           # original text from user
    type: Literal["landmark", "region", "road", "coordinate", "unknown"]
    coordinates: Optional[tuple[float, float]] = None  # (lat, lng) if provided
    resolved_name: Optional[str] = None    # normalised name after resolution

class QueryPlan(BaseModel):
    """Structured output from LLM intent parsing."""

    intent: Literal[
        "radius_count",          # QT-01
        "nearest_k",             # QT-02
        "region_count",          # QT-03
        "road_buffer_count",     # QT-04
        "density_ranking",       # QT-05
        "time_window_count",     # QT-06
        "trend_analysis",        # QT-07
        "statistical_aggregation",# QT-08
        "snapshot_comparison",   # QT-09
        "heatmap_data",          # QT-10
        "unsupported"            # Query requires data we don't have
    ]

    location: Optional[LocationReference] = None
    radius_km: Optional[float] = None          # for radius_count, road_buffer
    k: Optional[int] = None                    # for nearest_k (default 5)
    time_window: Optional[TimeWindow] = None
    region_filter: Optional[str] = None        # specific region name
    aggregation: Optional[Literal["count", "avg", "max", "min"]] = "count"
    group_by: Optional[Literal["region", "hour", "region_hour"]] = None

    # If intent is "unsupported", explain why
    unsupported_reason: Optional[str] = None

    confidence: float = Field(ge=0.0, le=1.0)  # Model's self-assessed confidence
```

### 7.3 LLM Prompt Strategy

```python
SYSTEM_PROMPT = """You are a query intent parser for a Singapore taxi spatial distribution system.

AVAILABLE DATA:
- Anonymous taxi coordinates (latitude, longitude) captured every 30 seconds
- NO taxi IDs, NO status, NO speed, NO heading
- Each coordinate = one available taxi at that timestamp

SUPPORTED INTENTS:
- radius_count: Count taxis within N km of a point
- nearest_k: Find K nearest taxis to a point
- region_count: Count taxis in a named Singapore region (URA planning area)
- road_buffer_count: Count taxis along a named road corridor
- density_ranking: Rank regions by taxi density (count / area)
- time_window_count: Count taxis in an area over a time range
- trend_analysis: Detect if taxi count is increasing/decreasing over time
- statistical_aggregation: Aggregate stats (avg, count) by region and/or hour
- snapshot_comparison: Compare two time points
- heatmap_data: Grid-based density data

UNSUPPORTED (mark as "unsupported" with reason):
- Tracking a specific taxi ("Where did taxi X go?")
- Speed or heading queries ("How fast are taxis moving?")
- Available vs busy distinction ("How many taxis are occupied?")
- Trajectory queries ("Show me the route of a taxi")
- ETA estimation ("How long until a taxi reaches me?")
- Demand inference ("Where do people need taxis?")

SINGAPORE LOCATIONS you should recognise:
Regions: Tampines, Jurong West, Bedok, Woodlands, Downtown Core, Orchard, Marina South, ...
Landmarks: Changi Airport, Marina Bay Sands, Sentosa, Raffles Place, NUS, NTU, ...
Roads: Orchard Road, ECP, PIE, CTE, AYE, Bukit Timah Road, ...

Output a JSON object matching the QueryPlan schema. Set confidence between 0 and 1.
If the user provides coordinates, extract them. If they name a place, set the type appropriately.
For time references like "now", "last 10 minutes", "this morning", convert to relative time strings.
"""
```

### 7.4 LLM Integration (LangChain)

```python
from langchain_openai import ChatOpenAI
from langchain_core.prompts import ChatPromptTemplate

llm = ChatOpenAI(model="gpt-4o-mini", temperature=0)
structured_llm = llm.with_structured_output(QueryPlan)

prompt = ChatPromptTemplate.from_messages([
    ("system", SYSTEM_PROMPT),
    ("human", "{user_query}")
])

chain = prompt | structured_llm

# Usage:
query_plan: QueryPlan = await chain.ainvoke({"user_query": user_input})
```

### 7.5 Guardrails

| Guardrail                   | Implementation                                              |
| --------------------------- | ----------------------------------------------------------- |
| Unsupported query detection | LLM sets `intent="unsupported"` + `unsupported_reason`      |
| Low confidence handling     | If `confidence < 0.7`, ask user for clarification            |
| Schema validation           | Pydantic model validates all LLM output                      |
| Fallback                    | If LLM fails/times out, return structured error (no crash)   |
| Token limit                 | Input truncated to 500 tokens (queries should be short)      |

---

## 8. Spatial Query Execution Engine

### 8.1 QueryPlan → SQL Translation

The engine is a **pattern-matching translator**: each `intent` maps to a parameterised SQL template.

```python
class SpatialQueryExecutor:
    """Translates QueryPlan → parameterised PostGIS SQL → executes → returns results."""

    async def execute(self, plan: QueryPlan, resolved_geom: Optional[str]) -> QueryResult:
        match plan.intent:
            case "radius_count":
                return await self._radius_count(plan, resolved_geom)
            case "nearest_k":
                return await self._nearest_k(plan, resolved_geom)
            case "region_count":
                return await self._region_count(plan)
            case "road_buffer_count":
                return await self._road_buffer_count(plan, resolved_geom)
            case "density_ranking":
                return await self._density_ranking(plan)
            case "time_window_count":
                return await self._time_window_count(plan, resolved_geom)
            case "trend_analysis":
                return await self._trend_analysis(plan, resolved_geom)
            case "statistical_aggregation":
                return await self._statistical_aggregation(plan)
            case "unsupported":
                return QueryResult(
                    success=False,
                    error=f"Unsupported query: {plan.unsupported_reason}"
                )
```

### 8.2 SQL Templates by Intent

Each template uses **`$1`, `$2`, ...** placeholders — never string interpolation.

**QT-01 Radius Count:**
```sql
SELECT COUNT(*) AS taxi_count
FROM taxi_positions tp
WHERE tp.captured_at >= $1 AND tp.captured_at <= $2
  AND ST_DWithin(tp.geom::geography, ST_SetSRID(ST_MakePoint($3, $4), 4326)::geography, $5);
-- $1=start_time, $2=end_time, $3=longitude, $4=latitude, $5=radius_metres
```

**QT-02 Nearest-K:**
```sql
SELECT
    ST_Y(tp.geom) AS latitude,
    ST_X(tp.geom) AS longitude,
    ST_Distance(tp.geom::geography, ST_SetSRID(ST_MakePoint($3, $4), 4326)::geography) AS distance_m
FROM taxi_positions tp
WHERE tp.captured_at >= $1 AND tp.captured_at <= $2
ORDER BY tp.geom <-> ST_SetSRID(ST_MakePoint($3, $4), 4326)
LIMIT $5;
-- $5 = K
```

**QT-03 Region Count:**
```sql
SELECT COUNT(*) AS taxi_count
FROM taxi_positions tp
JOIN sg_regions r ON ST_Contains(r.geom, tp.geom)
WHERE r.name = $1
  AND tp.captured_at >= $2 AND tp.captured_at <= $3;
```

**QT-04 Road Buffer Count:**
```sql
SELECT COUNT(*) AS taxi_count
FROM taxi_positions tp
JOIN sg_road_corridors rc ON ST_DWithin(
    tp.geom::geography,
    rc.geom::geography,
    rc.buffer_m
)
WHERE rc.name = $1
  AND tp.captured_at >= $2 AND tp.captured_at <= $3;
```

**QT-05 Density Ranking:**
```sql
SELECT
    r.name AS region,
    COUNT(*) AS taxi_count,
    r.area_km2,
    ROUND(COUNT(*)::numeric / r.area_km2, 2) AS density_per_km2
FROM taxi_positions tp
JOIN sg_regions r ON ST_Contains(r.geom, tp.geom)
WHERE tp.captured_at >= $1 AND tp.captured_at <= $2
GROUP BY r.name, r.area_km2
ORDER BY density_per_km2 DESC;
```

**QT-06 Time-Window Count:**
```sql
SELECT
    date_trunc('minute', tp.captured_at) AS time_bucket,
    COUNT(*) AS taxi_count
FROM taxi_positions tp
WHERE tp.captured_at >= $1 AND tp.captured_at <= $2
  AND ST_DWithin(tp.geom::geography, ST_SetSRID(ST_MakePoint($3, $4), 4326)::geography, $5)
GROUP BY time_bucket
ORDER BY time_bucket;
```

**QT-07 Trend Analysis:**
```sql
WITH snapshots AS (
    SELECT
        tp.batch_id,
        sm.captured_at,
        COUNT(*) AS taxi_count
    FROM taxi_positions tp
    JOIN snapshot_metadata sm ON tp.batch_id = sm.batch_id
    WHERE tp.captured_at >= $1 AND tp.captured_at <= $2
      AND ST_DWithin(tp.geom::geography, ST_SetSRID(ST_MakePoint($3, $4), 4326)::geography, $5)
    GROUP BY tp.batch_id, sm.captured_at
    ORDER BY sm.captured_at
),
trend AS (
    SELECT
        regr_slope(taxi_count, EXTRACT(EPOCH FROM captured_at)) AS slope,
        COUNT(*) AS data_points,
        MIN(taxi_count) AS min_count,
        MAX(taxi_count) AS max_count,
        AVG(taxi_count)::int AS avg_count
    FROM snapshots
)
SELECT
    CASE WHEN slope > 0.01 THEN 'increasing'
         WHEN slope < -0.01 THEN 'decreasing'
         ELSE 'stable' END AS trend,
    slope,
    data_points,
    min_count,
    max_count,
    avg_count
FROM trend;
```

**QT-08 Statistical Aggregation:**
```sql
SELECT
    region_name,
    date_trunc('hour', hour) AS hour,
    avg_per_snapshot AS avg_taxis
FROM taxi_agg_hourly
WHERE hour >= $1 AND hour <= $2
ORDER BY region_name, hour;
```

---

## 9. Query Flow (End-to-End)

```
User: "How many taxis are within 3km of Changi Airport right now?"
 │
 ▼
[1] API Layer (FastAPI)
    ─ Receives POST /api/v1/query { "query": "..." }
    ─ Rate limiting, auth check
 │
 ▼
[2] LLM Intent Parser
    ─ Input: raw query string
    ─ Output: QueryPlan {
        intent: "radius_count",
        location: { raw_text: "Changi Airport", type: "landmark" },
        radius_km: 3.0,
        time_window: { relative: "now" },
        confidence: 0.95
      }
 │
 ▼
[3] Confidence Check
    ─ confidence >= 0.7? → proceed
    ─ confidence <  0.7? → ask user for clarification
 │
 ▼
[4] Location Resolver
    ─ Input: "Changi Airport" (type: landmark)
    ─ Search sg_landmarks WHERE name ILIKE 'Changi Airport'
    ─ Output: POINT(103.9893 1.3644)
 │
 ▼
[5] Time Resolver
    ─ Input: relative="now"
    ─ Output: latest batch_id from snapshot_metadata
    ─ Compute: start_time = latest captured_at, end_time = latest captured_at
 │
 ▼
[6] Spatial Query Executor
    ─ Intent = "radius_count" → select SQL template
    ─ Bind parameters: lng=103.9893, lat=1.3644, radius=3000m,
                       start=..., end=...
    ─ Execute parameterised SQL via asyncpg
    ─ Result: { taxi_count: 142 }
 │
 ▼
[7] Response Formatter
    ─ Template: "There are {count} taxis within {radius} km of {location} as of {time}."
    ─ Output: {
        "answer": "There are 142 taxis within 3 km of Changi Airport as of 2026-02-28 14:30:00 SGT.",
        "data": { "taxi_count": 142, "radius_km": 3.0, "center": [1.3644, 103.9893] },
        "query_plan": { ... },
        "execution_time_ms": 87
      }
 │
 ▼
[8] API Response
    ─ HTTP 200 with JSON body
```

---

## 10. Time-Window Aggregation

### 10.1 Snapshot-Based Time Model

Time in this system is **discrete, not continuous**. Each API poll creates a snapshot. Aggregation works on snapshots.

```
Timeline:
  ──●──────●──────●──────●──────●──────●──────●──
  t0     t+30s   t+60s  t+90s  t+120s t+150s t+180s
  │  snapshot  │  snapshot  │  snapshot  │  ...

  A "last 5 minutes" query spans ~10 snapshots.
```

### 10.2 Aggregation Strategies

| Aggregation        | Method                                                                 |
| ------------------ | ---------------------------------------------------------------------- |
| **Latest snapshot**| `WHERE batch_id = (SELECT batch_id FROM snapshot_metadata ORDER BY captured_at DESC LIMIT 1)` |
| **Time range**     | `WHERE captured_at BETWEEN $start AND $end` — may span many snapshots  |
| **Per-snapshot**   | `GROUP BY batch_id` — gives one count per 30s snapshot                  |
| **Per-minute**     | `GROUP BY date_trunc('minute', captured_at)`                            |
| **Per-hour**       | Materialised view `taxi_agg_hourly`                                     |
| **Per-day**        | `GROUP BY date_trunc('day', captured_at)` on the hourly MV              |

### 10.3 Double-Counting Awareness

> **Critical:** In a time-range query, the same physical taxi may appear in multiple snapshots (it didn't move). The system counts **point-records**, not unique vehicles. All counts must be contextualised as "point observations" or "per-snapshot averages" — never "unique taxis".

The `avg_per_snapshot` column in `taxi_agg_hourly` provides the most meaningful metric for time-range queries.

---

## 11. Spatial Density Analysis

### 11.1 Region-Based Density

```sql
-- Density = taxi_count / area_km2
SELECT
    r.name,
    COUNT(*) AS taxi_count,
    r.area_km2,
    ROUND(COUNT(*) / r.area_km2, 2) AS density
FROM taxi_positions tp
JOIN sg_regions r ON ST_Contains(r.geom, tp.geom)
WHERE tp.batch_id = $1  -- latest snapshot
GROUP BY r.name, r.area_km2
ORDER BY density DESC;
```

### 11.2 Grid-Based Density (Heatmap)

For finer-grained analysis, overlay a regular grid:

```sql
-- Generate a 500m hex grid over Singapore's bounding box
-- and count taxis per cell
WITH grid AS (
    SELECT
        ST_HexagonGrid(0.005, ST_MakeEnvelope(103.6, 1.15, 104.1, 1.47, 4326)) AS cell
),
counts AS (
    SELECT
        (cell).geom AS cell_geom,
        COUNT(tp.id) AS taxi_count
    FROM grid
    LEFT JOIN taxi_positions tp
        ON ST_Contains((cell).geom, tp.geom)
       AND tp.batch_id = $1
    GROUP BY (cell).geom
)
SELECT
    ST_AsGeoJSON(cell_geom) AS geojson,
    taxi_count
FROM counts
WHERE taxi_count > 0
ORDER BY taxi_count DESC;
```

### 11.3 Kernel Density Estimation (KDE)

For smooth density surfaces, post-process in Python:

```python
from scipy.stats import gaussian_kde
import numpy as np

# coords = [(lng, lat), ...] from latest snapshot
coords = np.array(coords).T
kde = gaussian_kde(coords, bw_method=0.01)

# Evaluate on grid
x_grid = np.linspace(103.6, 104.1, 200)
y_grid = np.linspace(1.15, 1.47, 200)
X, Y = np.meshgrid(x_grid, y_grid)
Z = kde(np.vstack([X.ravel(), Y.ravel()])).reshape(X.shape)
```

---

## 12. API Design

### 12.1 Endpoints

```
POST   /api/v1/query                   # Natural language query
POST   /api/v1/query/structured        # Direct QueryPlan input (bypass LLM)
GET    /api/v1/snapshot/latest          # Latest snapshot metadata
GET    /api/v1/snapshot/{batch_id}      # Specific snapshot data
GET    /api/v1/regions                  # List all regions with geometry
GET    /api/v1/regions/{name}/count     # Current taxi count for a region
GET    /api/v1/health                   # Health check
GET    /api/v1/metrics                  # Prometheus metrics
```

### 12.2 Natural Language Query Request / Response

**Request:**
```json
POST /api/v1/query
{
    "query": "How many taxis are within 3km of Changi Airport?",
    "session_id": "optional-for-context"
}
```

**Response:**
```json
{
    "answer": "There are 142 available taxis within 3 km of Changi Airport as of 2026-02-28T06:30:00Z.",
    "data": {
        "taxi_count": 142,
        "center": { "latitude": 1.3644, "longitude": 103.9893 },
        "radius_km": 3.0,
        "snapshot_time": "2026-02-28T06:30:00Z",
        "batch_id": "a1b2c3d4-..."
    },
    "query_plan": {
        "intent": "radius_count",
        "location": { "raw_text": "Changi Airport", "type": "landmark" },
        "radius_km": 3.0,
        "confidence": 0.95
    },
    "metadata": {
        "execution_time_ms": 87,
        "llm_latency_ms": 450,
        "sql_latency_ms": 32
    }
}
```

### 12.3 Error Responses

```json
{
    "answer": "I'm sorry, I cannot track individual taxis. The system receives anonymous coordinate snapshots without taxi IDs, so trajectory or vehicle-specific queries are not possible.",
    "data": null,
    "query_plan": {
        "intent": "unsupported",
        "unsupported_reason": "Query requires taxi_id for trajectory tracking, which is not available in the data.",
        "confidence": 0.92
    }
}
```

---

## 13. Performance Considerations

### 13.1 Data Volume Estimation

| Metric                     | Value                                                     |
| -------------------------- | --------------------------------------------------------- |
| Taxis per snapshot         | ~8 000–12 000 (typical Singapore available taxi count)    |
| Snapshots per day          | 2 880 (every 30 seconds)                                 |
| Records per day            | ~29 million (10 000 × 2 880)                             |
| Records per week           | ~200 million                                              |
| Row size (approx.)         | ~80 bytes (id + uuid + point + timestamptz)               |
| Raw storage per day        | ~2.3 GB (before indexes)                                  |
| Raw storage per week       | ~16 GB (before indexes)                                   |
| With indexes               | ~25 GB / week                                             |

### 13.2 Query Performance Targets

| Query Type              | Expected Latency | Strategy                                           |
| ----------------------- | ---------------- | -------------------------------------------------- |
| Latest snapshot radius  | < 50 ms          | Single-partition scan + GiST                       |
| Latest snapshot nearest | < 30 ms          | KNN operator + GiST                                |
| Latest snapshot region  | < 100 ms         | Spatial join + GiST                                |
| All-regions density     | < 200 ms         | Pre-computed MV or single spatial join pass         |
| 10-minute time window   | < 200 ms         | ~20 snapshots × GiST                               |
| 24-hour aggregation     | < 2 s            | Materialised view                                   |
| 7-day aggregation       | < 5 s            | Materialised view                                   |
| Trend analysis (30 min) | < 300 ms         | ~60 snapshots, aggregate in SQL                     |

### 13.3 Optimisation Techniques

| Technique                          | Impact                                                    |
| ---------------------------------- | --------------------------------------------------------- |
| **Table partitioning (daily)**     | Partition pruning eliminates >85% of data for time queries|
| **GiST spatial index**             | Sub-linear spatial search; critical for all queries        |
| **BRIN index on captured_at**      | Tiny index for additional time filtering within partitions |
| **Partial index (last 1 hour)**    | Hot-path queries hit a tiny, cached index                  |
| **Materialised view (hourly agg)** | Pre-computed aggregates for historical queries             |
| **Connection pooling (pgbouncer)** | Reduces connection overhead for concurrent queries         |
| **asyncpg (binary protocol)**      | 2–3x faster than psycopg2 for bulk operations             |
| **Batch-id latest lookup**         | O(1) via `snapshot_metadata` instead of scanning positions |
| **Prepared statements**            | Avoid re-planning for repeated query patterns              |
| **Geography vs Geometry**          | Use `::geography` cast only in `ST_DWithin` (metre-based distance); keep storage as geometry (faster indexing) |

### 13.4 PostgreSQL Tuning (for 32 GB RAM, 8 cores)

```ini
# postgresql.conf
shared_buffers = 8GB
effective_cache_size = 24GB
work_mem = 256MB
maintenance_work_mem = 2GB
max_parallel_workers_per_gather = 4
random_page_cost = 1.1          # SSD
effective_io_concurrency = 200  # SSD
wal_level = replica
max_wal_size = 4GB
checkpoint_completion_target = 0.9

# Autovacuum tuning for high-insert table
# (set per-table via ALTER TABLE)
autovacuum_vacuum_scale_factor = 0.01
autovacuum_analyze_scale_factor = 0.005
```

---

## 14. Scaling Strategy

### 14.1 Vertical Scaling (Phase 1)

A single PostgreSQL instance with:
- 32 GB RAM, 8 cores, NVMe SSD
- Can handle ~200M rows (1 week) with sub-second queries
- Sufficient for initial production deployment

### 14.2 Horizontal Read Scaling (Phase 2)

```
                    ┌──────────────┐
                    │   Primary    │ ◄── Ingestion writes
                    │  PostgreSQL  │
                    └──────┬───────┘
                           │ streaming replication
                    ┌──────┴───────┐
              ┌─────┤              ├─────┐
              ▼     ▼              ▼     ▼
         ┌────────┐ ┌────────┐ ┌────────┐
         │Replica1│ │Replica2│ │Replica3│ ◄── Query reads
         └────────┘ └────────┘ └────────┘
```

- Ingestion writes go to primary only.
- All Q&A reads routed to replicas via PgBouncer.
- Replication lag < 1 second (acceptable for 30s data).

### 14.3 Sharding (Phase 3 — if needed)

If data exceeds single-node capacity:
- **TimescaleDB** hypertable with automatic chunking by time.
- Or **Citus** for distributed PostGIS (more complex).
- Partitioning + archival should delay this need significantly.

### 14.4 Application Layer Scaling

```
                    ┌─────────────┐
                    │ Load Balancer│
                    └──────┬──────┘
                           │
              ┌────────────┼────────────┐
              ▼            ▼            ▼
         ┌─────────┐ ┌─────────┐ ┌─────────┐
         │ FastAPI  │ │ FastAPI  │ │ FastAPI  │
         │ Worker 1 │ │ Worker 2 │ │ Worker 3 │
         └─────────┘ └─────────┘ └─────────┘
```

- FastAPI workers are stateless → horizontally scalable.
- Run behind Nginx/Caddy + uvicorn with `--workers N`.
- LLM calls are the bottleneck; add Redis cache for repeated intent patterns.

---

## 15. Limitations & Constraints

### 15.1 Data-Inherent Limitations

| #   | Limitation                        | Root Cause                        | Impact                                           |
| --- | --------------------------------- | --------------------------------- | ------------------------------------------------ |
| L1  | No individual taxi tracking       | No `taxi_id` in data              | Cannot answer "Where did taxi X go?"             |
| L2  | No available/busy distinction     | LTA only returns available taxis  | "Occupied taxis" are invisible to the system     |
| L3  | No speed data                     | No speed field; no ID for derivation | Cannot answer "How fast are taxis moving?"      |
| L4  | No heading data                   | No heading field                  | Cannot answer "Which way are taxis heading?"     |
| L5  | No trajectory reconstruction      | No ID → cannot link points across time | Cannot show routes or paths              |
| L6  | No ETA estimation                 | Requires trajectory + speed       | Cannot answer "When will a taxi arrive?"         |
| L7  | No demand visibility              | Only supply data (available taxis) | Cannot infer passenger demand                   |
| L8  | 30-second granularity             | API poll frequency                | Cannot detect sub-30s changes                    |
| L9  | Double-counting in time ranges    | Same taxi in multiple snapshots   | Time-range counts are observations, not unique vehicles |

### 15.2 System Limitations

| #    | Limitation                                      | Mitigation                                           |
| ---- | ----------------------------------------------- | ---------------------------------------------------- |
| S1   | LLM parsing is probabilistic                    | Confidence scoring + fallback to structured API      |
| S2   | Geocoding may fail for ambiguous names           | Fuzzy matching + user confirmation                   |
| S3   | Materialised views have refresh lag (5 min)      | Use real-time queries for current data; MV for history |
| S4   | Historical queries beyond 7 days hit cold storage| Return "data not available" or query Parquet via DuckDB |
| S5   | Concurrent heavy analytical queries may compete  | Read replicas + query timeout (30s)                   |

---

## 16. Technology Stack

| Layer                    | Technology                      | Version    | Rationale                                     |
| ------------------------ | ------------------------------- | ---------- | --------------------------------------------- |
| Database                 | PostgreSQL                      | 16         | Mature, PostGIS support, partitioning          |
| Spatial Extension        | PostGIS                         | 3.4        | Industry-standard spatial SQL                  |
| Partition Management     | pg_partman                      | 5.x        | Automated daily partition creation/drop        |
| Scheduled Jobs           | pg_cron                         | 1.6        | MV refresh, partition maintenance              |
| Application Framework    | FastAPI                         | 0.110+     | Async, OpenAPI docs, Pydantic integration      |
| ASGI Server              | Uvicorn                         | 0.27+      | High-performance async server                  |
| DB Driver                | asyncpg                         | 0.29+      | Binary protocol, COPY support, fastest driver  |
| Connection Pool          | PgBouncer                       | 1.22+      | Connection multiplexing                        |
| LLM Framework            | LangChain                       | 0.2+       | Structured output, prompt management           |
| LLM Model                | GPT-4o-mini (primary)           | —          | Cost-effective, fast, sufficient for intent parsing |
| LLM Model (fallback)     | GPT-4o                          | —          | Complex/ambiguous queries                      |
| Geocoding (fallback)     | OneMap API                      | —          | Singapore-specific geocoding                   |
| Task Scheduling          | APScheduler / asyncio           | —          | Ingestion loop, retention jobs                 |
| Monitoring               | Prometheus + Grafana            | —          | Metrics, dashboards, alerting                  |
| Logging                  | structlog + Loki                | —          | Structured JSON logging                        |
| Caching                  | Redis                           | 7+         | LLM response cache, rate limiting              |
| Containerisation         | Docker + Docker Compose         | —          | Reproducible deployment                        |
| CI/CD                    | GitHub Actions                  | —          | Automated testing and deployment               |

---

## 17. Deployment Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                     Docker Compose / K8s Cluster                │
│                                                                 │
│  ┌──────────────┐  ┌──────────────┐  ┌───────────────────────┐ │
│  │  FastAPI App  │  │  FastAPI App  │  │  Ingestion Worker    │ │
│  │  (replica 1)  │  │  (replica 2)  │  │  (single instance)   │ │
│  └──────┬───────┘  └──────┬───────┘  └──────────┬────────────┘ │
│         │                 │                      │              │
│         └────────┬────────┘                      │              │
│                  ▼                                ▼              │
│         ┌──────────────┐                ┌──────────────┐        │
│         │  PgBouncer   │                │  PostgreSQL   │        │
│         │  (pool)      │───────────────▶│  + PostGIS    │        │
│         └──────────────┘                └──────────────┘        │
│                                                                 │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐          │
│  │    Redis      │  │  Prometheus   │  │   Grafana    │          │
│  └──────────────┘  └──────────────┘  └──────────────┘          │
└─────────────────────────────────────────────────────────────────┘
```

### 17.1 Docker Compose Services

```yaml
services:
  db:
    image: postgis/postgis:16-3.4
    volumes:
      - pgdata:/var/lib/postgresql/data
    environment:
      POSTGRES_DB: taxi_sg
      POSTGRES_PASSWORD: ${DB_PASSWORD}
    ports:
      - "5432:5432"
    shm_size: '2g'

  pgbouncer:
    image: edoburu/pgbouncer
    depends_on: [db]

  redis:
    image: redis:7-alpine

  ingestion:
    build: .
    command: python -m app.ingestion.worker
    depends_on: [db]
    restart: always

  api:
    build: .
    command: uvicorn app.api.main:app --host 0.0.0.0 --port 8000
    depends_on: [db, redis]
    deploy:
      replicas: 2

  prometheus:
    image: prom/prometheus
    volumes:
      - ./monitoring/prometheus.yml:/etc/prometheus/prometheus.yml

  grafana:
    image: grafana/grafana
    depends_on: [prometheus]
    ports:
      - "3000:3000"
```

---

## 18. Monitoring & Observability

### 18.1 Key Metrics

| Metric                                  | Type      | Alert Threshold        |
| --------------------------------------- | --------- | ---------------------- |
| `ingestion_records_total`               | Counter   | —                      |
| `ingestion_duration_seconds`            | Histogram | p95 > 5s               |
| `ingestion_errors_total`                | Counter   | > 3 consecutive        |
| `ingestion_last_success_timestamp`      | Gauge     | now() - value > 120s   |
| `query_duration_seconds`                | Histogram | p95 > 3s               |
| `query_intent_type`                     | Counter   | —                      |
| `llm_parse_duration_seconds`            | Histogram | p95 > 2s               |
| `llm_parse_confidence`                  | Histogram | p50 < 0.7              |
| `db_connection_pool_active`             | Gauge     | > 80% of max           |
| `taxi_count_latest_snapshot`            | Gauge     | < 1000 (data quality)  |
| `partition_count`                       | Gauge     | > 10 (retention issue) |

### 18.2 Dashboards

1. **Ingestion Health:** Record counts, latency, error rate, data freshness.
2. **Query Performance:** Latency distribution by intent type, cache hit rate.
3. **Data Quality:** Taxi count trends (detect API outages), spatial distribution anomalies.
4. **System Resources:** CPU, memory, disk, connections.

---

## 19. Security Considerations

| Concern                | Mitigation                                                          |
| ---------------------- | ------------------------------------------------------------------- |
| SQL injection          | All queries use parameterised statements; LLM never generates SQL   |
| LLM prompt injection   | System prompt is fixed; user input is isolated in `{user_query}` slot |
| API abuse              | Rate limiting (Redis), API key authentication                       |
| Data privacy           | No PII in taxi data (anonymous coordinates)                         |
| LTA API key protection | Stored in environment variable / secrets manager; never logged       |
| Database access        | Network-restricted; application connects via PgBouncer only         |
| HTTPS                  | TLS termination at load balancer                                    |

---

## 20. Appendix: Reference SQL Queries

### A. Find Latest Batch ID

```sql
SELECT batch_id, captured_at, taxi_count
FROM snapshot_metadata
ORDER BY captured_at DESC
LIMIT 1;
```

### B. Taxis Near Changi Airport (3 km, Latest Snapshot)

```sql
WITH latest AS (
    SELECT batch_id FROM snapshot_metadata ORDER BY captured_at DESC LIMIT 1
)
SELECT COUNT(*) AS taxi_count
FROM taxi_positions tp
JOIN latest l ON tp.batch_id = l.batch_id
WHERE ST_DWithin(
    tp.geom::geography,
    ST_SetSRID(ST_MakePoint(103.9893, 1.3644), 4326)::geography,
    3000  -- metres
);
```

### C. Nearest 5 Taxis to a Point

```sql
WITH latest AS (
    SELECT batch_id FROM snapshot_metadata ORDER BY captured_at DESC LIMIT 1
)
SELECT
    ST_Y(tp.geom) AS latitude,
    ST_X(tp.geom) AS longitude,
    ST_Distance(tp.geom::geography, ST_SetSRID(ST_MakePoint(103.8198, 1.3521), 4326)::geography) AS distance_m
FROM taxi_positions tp
JOIN latest l ON tp.batch_id = l.batch_id
ORDER BY tp.geom <-> ST_SetSRID(ST_MakePoint(103.8198, 1.3521), 4326)
LIMIT 5;
```

### D. All-Region Density (Current Snapshot)

```sql
WITH latest AS (
    SELECT batch_id FROM snapshot_metadata ORDER BY captured_at DESC LIMIT 1
)
SELECT
    r.name,
    COUNT(tp.id) AS taxi_count,
    r.area_km2,
    ROUND(COUNT(tp.id)::numeric / r.area_km2, 2) AS density_per_km2
FROM sg_regions r
LEFT JOIN taxi_positions tp
    ON ST_Contains(r.geom, tp.geom)
   AND tp.batch_id = (SELECT batch_id FROM latest)
GROUP BY r.name, r.area_km2
ORDER BY density_per_km2 DESC;
```

### E. Hourly Trend for a Region (Last 24 Hours)

```sql
SELECT
    date_trunc('hour', captured_at) AS hour,
    COUNT(*) AS total_points,
    COUNT(DISTINCT batch_id) AS snapshots,
    ROUND(COUNT(*)::numeric / COUNT(DISTINCT batch_id), 0) AS avg_per_snapshot
FROM taxi_positions tp
JOIN sg_regions r ON ST_Contains(r.geom, tp.geom)
WHERE r.name = 'Downtown Core'
  AND tp.captured_at >= now() - INTERVAL '24 hours'
GROUP BY hour
ORDER BY hour;
```

### F. Taxis Along Orchard Road (200m Buffer)

```sql
WITH latest AS (
    SELECT batch_id FROM snapshot_metadata ORDER BY captured_at DESC LIMIT 1
)
SELECT COUNT(*) AS taxi_count
FROM taxi_positions tp
JOIN sg_road_corridors rc ON ST_DWithin(tp.geom::geography, rc.geom::geography, rc.buffer_m)
JOIN latest l ON tp.batch_id = l.batch_id
WHERE rc.name = 'Orchard Road';
```

### G. Data Quality Check: Snapshot Regularity

```sql
SELECT
    captured_at,
    taxi_count,
    EXTRACT(EPOCH FROM captured_at - LAG(captured_at) OVER (ORDER BY captured_at)) AS gap_seconds
FROM snapshot_metadata
WHERE captured_at >= now() - INTERVAL '1 hour'
ORDER BY captured_at DESC;
```

---

## 21. Project Directory Structure

```
civic-app/
├── app/
│   ├── __init__.py
│   ├── api/
│   │   ├── __init__.py
│   │   ├── main.py                  # FastAPI app factory
│   │   ├── routes/
│   │   │   ├── query.py             # POST /api/v1/query
│   │   │   ├── snapshot.py          # Snapshot endpoints
│   │   │   ├── regions.py           # Region endpoints
│   │   │   └── health.py            # Health check
│   │   └── middleware/
│   │       ├── rate_limit.py
│   │       └── error_handler.py
│   ├── core/
│   │   ├── config.py                # Settings (Pydantic BaseSettings)
│   │   ├── database.py              # asyncpg pool management
│   │   └── dependencies.py          # FastAPI dependency injection
│   ├── ingestion/
│   │   ├── __init__.py
│   │   ├── worker.py                # Polling loop
│   │   ├── lta_client.py            # LTA API client
│   │   └── bulk_inserter.py         # COPY-based bulk insert
│   ├── llm/
│   │   ├── __init__.py
│   │   ├── intent_parser.py         # LLM → QueryPlan
│   │   ├── prompts.py               # System prompts
│   │   └── schemas.py               # QueryPlan, LocationReference, etc.
│   ├── spatial/
│   │   ├── __init__.py
│   │   ├── query_executor.py        # QueryPlan → SQL → results
│   │   ├── sql_templates.py         # Parameterised SQL templates
│   │   ├── location_resolver.py     # Name → geometry
│   │   └── time_resolver.py         # Relative time → absolute
│   ├── formatting/
│   │   ├── __init__.py
│   │   └── response_formatter.py    # Results → human-readable
│   └── monitoring/
│       ├── __init__.py
│       └── metrics.py               # Prometheus metrics
├── db/
│   ├── migrations/
│   │   ├── 001_create_extensions.sql
│   │   ├── 002_create_taxi_positions.sql
│   │   ├── 003_create_snapshot_metadata.sql
│   │   ├── 004_create_sg_regions.sql
│   │   ├── 005_create_sg_landmarks.sql
│   │   ├── 006_create_sg_road_corridors.sql
│   │   ├── 007_create_aggregation_views.sql
│   │   └── 008_create_indexes.sql
│   └── seed/
│       ├── regions.geojson          # URA planning areas
│       ├── landmarks.json           # POIs with coordinates
│       └── roads.geojson            # Road corridor linestrings
├── tests/
│   ├── test_intent_parser.py
│   ├── test_location_resolver.py
│   ├── test_query_executor.py
│   └── test_api.py
├── monitoring/
│   ├── prometheus.yml
│   └── grafana/
│       └── dashboards/
├── docker-compose.yml
├── Dockerfile
├── requirements.txt
├── .env.example
└── README.md
```

---

*End of Technical Architecture Document*
