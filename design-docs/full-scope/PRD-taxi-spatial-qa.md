# Product Requirements Document (PRD)

## Taxi Spatial Distribution Q&A System — Singapore

| Field           | Value                                      |
| --------------- | ------------------------------------------ |
| **Document ID** | PRD-TAXI-SG-2026-001                       |
| **Version**     | 1.0                                        |
| **Date**        | 2026-02-28                                 |
| **Author**      | System Architect                           |
| **Status**      | Draft                                      |

---

## 1. Executive Summary

The Taxi Spatial Distribution Q&A System is a production-grade platform that ingests real-time taxi coordinate snapshots published by the Singapore government open-data portal (data.gov.sg) every 30 seconds, stores them in a spatially-indexed PostgreSQL + PostGIS database, and exposes a natural-language Q&A interface powered by LLM intent parsing layered on top of deterministic spatial SQL execution.

**Key design principle:** The raw data contains **anonymous coordinate-timestamp tuples only** — no taxi IDs, no status, no speed, no heading. The system therefore provides **spatial distribution analytics**, not individual vehicle tracking.

---

## 2. Problem Statement

Urban transport planners, ride-hailing operators, and researchers need real-time and historical answers to questions like:

- *"How many taxis are within 2 km of Changi Airport right now?"*
- *"Which planning area had the highest taxi density last Friday between 18:00–19:00?"*
- *"Is the taxi count near Marina Bay Sands increasing or decreasing over the past 30 minutes?"*

Currently, answering such questions requires manual GIS work or custom scripts. This system democratises access via a natural language interface while maintaining spatial precision.

---

## 3. Target Users

| Persona                   | Need                                                         |
| ------------------------- | ------------------------------------------------------------ |
| Transport Planner         | Region-level density analysis, time-of-day patterns          |
| Data Analyst / Researcher | Historical trend queries, statistical aggregations           |
| Operations Manager        | Real-time supply monitoring near key locations               |
| General Public / Citizen  | Simple "How many taxis near me?" queries                     |
| API Consumer (Machine)    | Programmatic access for dashboards, alerting, ML pipelines   |

---

## 4. Data Source & Constraints

### 4.1 Data Source

**data.gov.sg — Taxi Availability API**

- Endpoint: `https://api.data.gov.sg/v1/transport/taxi-availability`
- Update frequency: **every 30 seconds**
- Returns a JSON array of `{ latitude, longitude }` for every available taxi.

### 4.2 Data Record Schema

Each ingested snapshot produces records with **exactly** these fields:

| Field       | Type              | Source     | Description                              |
| ----------- | ----------------- | ---------- | ---------------------------------------- |
| `latitude`  | `double precision` | API        | WGS 84 latitude of one taxi             |
| `longitude` | `double precision` | API        | WGS 84 longitude of one taxi            |
| `timestamp` | `timestamptz`     | Ingestion  | UTC timestamp when snapshot was captured |

### 4.3 What the Data Does NOT Contain

| Missing Field | Implication                                                                 |
| ------------- | --------------------------------------------------------------------------- |
| `taxi_id`     | Cannot track an individual taxi across snapshots                            |
| `status`      | Cannot distinguish available vs. occupied (LTA API only returns available)  |
| `speed`       | Cannot infer movement velocity                                              |
| `heading`     | Cannot infer travel direction                                               |

> **Critical design constraint:** Every query the system supports must be answerable purely from **set-of-points-at-a-time** analysis. No trajectory-based or identity-based queries are possible.

---

## 5. Functional Requirements

### 5.1 Data Ingestion

| ID      | Requirement                                                                                   | Priority |
| ------- | --------------------------------------------------------------------------------------------- | -------- |
| FR-DI-1 | Poll LTA Taxi Availability API every 30 seconds.                                              | P0       |
| FR-DI-2 | Convert each coordinate to a PostGIS `POINT(lng, lat)` geometry (SRID 4326).                  | P0       |
| FR-DI-3 | Assign a snapshot `batch_id` (UUID) to all records from the same API call.                    | P0       |
| FR-DI-4 | Bulk-insert all records in a single transaction (target < 200 ms for ~10 000 points).          | P0       |
| FR-DI-5 | Implement retry with exponential backoff on API failure.                                      | P0       |
| FR-DI-6 | Log ingestion metrics: record count, latency, errors.                                         | P1       |
| FR-DI-7 | Provide a data retention policy: hot (7 days raw), warm (90 days 1-min aggregates), cold (S3). | P1       |

### 5.2 Natural Language Q&A

| ID      | Requirement                                                                 | Priority |
| ------- | --------------------------------------------------------------------------- | -------- |
| FR-QA-1 | Accept free-form English natural language queries.                          | P0       |
| FR-QA-2 | Parse intent into one of the defined query types (§5.3).                    | P0       |
| FR-QA-3 | Resolve Singapore place names to coordinates / geometries (§6.1).           | P0       |
| FR-QA-4 | Execute the resolved spatial query against PostGIS.                         | P0       |
| FR-QA-5 | Return results as structured JSON + human-readable summary.                 | P0       |
| FR-QA-6 | Return an "unsupported query" response for trajectory / identity queries.   | P0       |
| FR-QA-7 | Support conversation context (follow-up refinement within session).         | P2       |

### 5.3 Supported Query Types

| Code   | Query Type                   | Example                                                  | Output                                     |
| ------ | ---------------------------- | -------------------------------------------------------- | ------------------------------------------ |
| QT-01  | Radius count                 | "How many taxis within 3 km of Changi Airport?"          | Integer count + optional coordinate list   |
| QT-02  | Nearest-K                    | "Nearest 5 taxis to 1.3521, 103.8198"                   | K coordinate pairs with distances          |
| QT-03  | Region count                 | "How many taxis are in Tampines?"                        | Count per specified region                  |
| QT-04  | Road buffer count            | "Taxis along Orchard Road"                               | Count within buffer zone along linestring  |
| QT-05  | Density ranking              | "Which region has the highest taxi density?"             | Ranked list of regions by count/area       |
| QT-06  | Time-window count            | "Taxi count near CBD in the last 10 minutes"             | Count per snapshot in time window           |
| QT-07  | Trend analysis               | "Is taxi count increasing near Marina Bay?"              | Direction + slope over recent window        |
| QT-08  | Statistical aggregation      | "Average taxis per region per hour today"                | Table of region × hour averages            |
| QT-09  | Snapshot comparison          | "Compare taxi distribution now vs 1 hour ago"            | Side-by-side region counts                 |
| QT-10  | Heatmap data                 | "Show density heatmap for current snapshot"              | Grid-cell counts for visualisation         |

### 5.4 Location Resolution

The system must resolve at minimum the following Singapore landmarks and areas:

**Landmarks / POIs:**
Changi Airport, Marina Bay Sands, Sentosa, Orchard Road, Raffles Place, HarbourFront, Woodlands Checkpoint, Tuas Checkpoint, NUS, NTU, Jewel Changi, Gardens by the Bay, Singapore Zoo, ION Orchard, Bugis Junction, VivoCity.

**URA Planning Areas (55 areas):**
Tampines, Jurong West, Bedok, Woodlands, Hougang, Sengkang, Ang Mo Kio, Bukit Merah, Toa Payoh, Queenstown, Clementi, Bishan, Yishun, Bukit Batok, Choa Chu Kang, Geylang, Kallang, Marine Parade, Pasir Ris, Punggol, Sembawang, Serangoon, Downtown Core, Orchard, Marina South, Novena, Newton, Tanglin, Bukit Timah, Rochor, River Valley, Outram, Museum, Singapore River, Straits View, and others.

**Road Corridors:**
Orchard Road, East Coast Parkway (ECP), Pan Island Expressway (PIE), Central Expressway (CTE), Ayer Rajah Expressway (AYE), Tampines Expressway (TPE), Bukit Timah Road, Victoria Street.

---

## 6. Non-Functional Requirements

| ID       | Requirement                                                                   | Target               |
| -------- | ----------------------------------------------------------------------------- | --------------------- |
| NFR-01   | Query response latency (p95, current-snapshot queries)                        | < 500 ms             |
| NFR-02   | Query response latency (p95, 24-hour historical queries)                      | < 3 s                |
| NFR-03   | Ingestion throughput                                                          | ≥ 15 000 points / s  |
| NFR-04   | Data freshness (time from API poll to queryable)                              | < 5 s                |
| NFR-05   | System uptime                                                                 | 99.5 %               |
| NFR-06   | Storage: retain raw points for 7 days                                         | ~120 GB / week       |
| NFR-07   | Concurrent query users                                                        | ≥ 50                 |
| NFR-08   | LLM intent parsing latency                                                    | < 2 s (p95)          |
| NFR-09   | Horizontal scalability for query layer                                        | Stateless workers    |

---

## 7. Explicit Limitations

These limitations stem directly from the data constraints and **must** be communicated to users:

| #  | Limitation                                                                                       |
| -- | ------------------------------------------------------------------------------------------------ |
| L1 | **No individual taxi tracking.** No taxi IDs → cannot follow one taxi over time.                 |
| L2 | **No available vs. busy distinction.** LTA only returns available taxis; occupied taxis are invisible. |
| L3 | **No speed or heading.** Cannot answer "How fast are taxis moving?" or "Which direction?"        |
| L4 | **No trajectory reconstruction.** Cannot answer "Where did the taxi near MBS go?"                |
| L5 | **No ETA estimation.** Requires trajectory + speed, neither available.                           |
| L6 | **No demand inference.** Only supply (available taxis) is visible; passenger demand is unknown.   |
| L7 | **Snapshot granularity is 30 s.** Sub-30-second trends are not observable.                        |
| L8 | **Potential double-counting risk.** In time-window aggregate queries spanning multiple snapshots, the same physical taxi may appear in multiple snapshots. Counts are **point-in-time** counts, not unique-vehicle counts. |
| L9 | **Location resolution depends on geocoding quality.** Ambiguous place names may resolve incorrectly. |
| L10 | **LLM parsing is probabilistic.** Edge-case natural language may be misinterpreted; structured fallback is provided. |

---

## 8. Success Metrics

| Metric                              | Target          |
| ----------------------------------- | --------------- |
| Query intent classification accuracy | ≥ 95 %         |
| Spatial query correctness            | 100 % (deterministic SQL) |
| Mean user satisfaction (1–5)         | ≥ 4.2           |
| P95 end-to-end latency (simple)      | < 3 s           |
| Data ingestion uptime                | > 99.5 %        |

---

## 9. Milestones

| Phase   | Deliverable                                    | Duration   |
| ------- | ---------------------------------------------- | ---------- |
| Phase 1 | Data model + ingestion pipeline + raw queries  | 3 weeks    |
| Phase 2 | LLM intent parser + query planner              | 3 weeks    |
| Phase 3 | Location resolver + road geometry + regions    | 2 weeks    |
| Phase 4 | API layer + response formatter                 | 2 weeks    |
| Phase 5 | Aggregation engine + trend analysis            | 2 weeks    |
| Phase 6 | Load testing + optimisation + production deploy| 2 weeks    |

---

## 10. Open Questions

| #  | Question                                                                 | Status |
| -- | ------------------------------------------------------------------------ | ------ |
| 1  | Should we integrate OneMap API for geocoding or maintain a local gazetteer? | Open   |
| 2  | What LLM model to use? (GPT-4o-mini for cost vs GPT-4o for accuracy)    | Open   |
| 3  | Should heatmap visualisation be server-side rendered or data-only?       | Open   |
| 4  | Is there budget for a read-replica for heavy analytical queries?         | Open   |

---

*End of PRD*
