# Civic App — Architecture Overview

> Backend API that enables external frontends to access Singapore government data APIs through natural language queries.

## Table of Contents

- [System Architecture](#system-architecture)
- [Request Lifecycle](#request-lifecycle)
- [Component Responsibilities](#component-responsibilities)
- [Technology Stack](#technology-stack)
- [Project Structure](#project-structure)
- [Performance Characteristics](#performance-characteristics)
- [Future Enhancements](#future-enhancements)

---

## System Architecture

```
                    ┌─────────────────────────┐
                    │   Frontend (External)   │
                    │  Streamlit / React App  │
                    └───────────┬─────────────┘
                                │ HTTP/REST
                                ▼
┌─────────────────────────────────────────────────────────────────┐
│  1. BACKEND API LAYER          (app/main.py, app/models.py)    │
│     FastAPI routes · Request validation · CORS                  │
└────────────────────────────┬────────────────────────────────────┘
                             │
                             ▼
┌─────────────────────────────────────────────────────────────────┐
│  2. ENDPOINT SELECTION LAYER   (app/endpoint_matcher.py)       │
│     Semantic search (embeddings) → LLM parameter extraction    │
└────────────────────────────┬────────────────────────────────────┘
                             │
                             ▼
┌─────────────────────────────────────────────────────────────────┐
│  3. QUERY BUILDING LAYER       (app/utils.py → QueryBuilder)   │
│     Parameter validation · Type conversion · Schema compliance │
└────────────────────────────┬────────────────────────────────────┘
                             │
                             ▼
┌─────────────────────────────────────────────────────────────────┐
│  4. API TRIGGER LAYER          (app/api_client.py)             │
│     httpx async client · Error handling · Retry logic          │
└────────────────────────────┬────────────────────────────────────┘
                             │
                             ▼
┌─────────────────────────────────────────────────────────────────┐
│  5. DATA PROCESSING LAYER      (app/data_processor.py)         │
│     GeoJSON conversion · Time-series stats · Format detection  │
└────────────────────────────┬────────────────────────────────────┘
                             │
                             ▼
┌─────────────────────────────────────────────────────────────────┐
│  6. RESPONSE FORMATTING        (app/utils.py → ResponseFormatter)│
│     Visualization hints · Chart configs · Map metadata         │
└─────────────────────────────────────────────────────────────────┘
```

---

## Request Lifecycle

A single `POST /api/query` request flows through six stages:

| Step | Component | What Happens |
|------|-----------|--------------|
| **1** | `main.py` | Validate `QueryRequest`, extract natural-language query |
| **2** | `EndpointMatcher` | Embed query → cosine similarity against endpoint descriptions → LLM extracts params from top-k matches |
| **3** | `QueryBuilder` | Validate & type-cast extracted params against endpoint schema |
| **4** | `APITrigger` | `POST` to external trigger API with constructed payload |
| **5** | `DataProcessor` | Detect data type → convert to GeoJSON / DataFrame / generic |
| **6** | `ResponseFormatter` | Attach visualization hints, chart configs, and map metadata |

> Confidence threshold: if Step 2 returns `confidence < 0.5`, the request short-circuits with an error asking the user to rephrase.

---

## Component Responsibilities

### EndpointMatcher (`app/endpoint_matcher.py`)

Two-stage approach optimised for cost and latency:

1. **Stage 1 — Semantic search** (no LLM tokens): pre-computed OpenAI embeddings for every endpoint description; cosine similarity picks top-k candidates.
2. **Stage 2 — Parameter extraction** (LLM): a focused prompt sends only the matched schemas to GPT-4, which returns `endpoint_id`, `query_params`, `body_params`, `confidence`, and `reasoning`.

| Metric | Naïve (send all schemas) | Two-Stage | Improvement |
|--------|--------------------------|-----------|-------------|
| Prompt tokens / query | 2,000–5,000 | 500–1,000 | **75–80 %** ↓ |
| Cost per 1 000 queries | $10–25 | $2.50–5.00 | **~80 %** ↓ |
| Latency | ~2–3 s | ~1 s | **2–3×** faster |
| Scalability | 10–20 endpoints | 100+ endpoints | **10×** better |

### QueryBuilder (`app/utils.py`)

Validates extracted parameters against the endpoint's JSON schema — enforces required fields, converts types (`string`, `integer`, `boolean`), and separates query vs. body params.

### APITrigger (`app/api_client.py`)

Async `httpx` client that calls the external trigger URL:

```
POST {base_url}/api/v2/gov/apis/endpoints/{endpoint_id}/trigger
```

Raises `APIError` on HTTP errors or non-`SUCCESS` status in the response body.

### DataProcessor (`app/data_processor.py`)

Detects data shape and applies the right strategy:

| Detection Rule | Strategy | Output |
|----------------|----------|--------|
| `type` is `FeatureCollection` or `Feature` | Process as-is | `GeoJSONProcessedResponse` (Pydantic) |
| Any array whose items contain lat/lon fields | Auto-convert → MultiPoint GeoJSON | `GeoJSONProcessedResponse` |
| Contains `readings` or `data` key | Time-series | `dict` with DataFrame + summary stats |
| Anything else | Generic passthrough | `dict` with raw data |

> See [data-processing-strategies.md](data-processing-strategies.md) for format details and examples.

### ResponseFormatter (`app/utils.py`)

Maps processed data to a `QueryResponse` with a `visualization_type` hint:

| `data_type` | `visualization_type` | Extra Fields |
|-------------|----------------------|--------------|
| `geojson` (temporal) | `map_temporal` | `temporal`, `bounds`, `center` |
| `geojson` (static) | `map` | `bounds`, `center`, `features_count` |
| `time_series` | `time_series` | `chart_configs`, `summary_stats` |
| `generic` | `generic` | raw data passthrough |

---

## Technology Stack

### Core

| Layer | Library | Why |
|-------|---------|-----|
| Web framework | FastAPI ≥ 0.109 | Async, auto-generated OpenAPI docs, Pydantic integration |
| ASGI server | Uvicorn ≥ 0.27 | Production-grade, supports `--reload` for dev |
| Validation | Pydantic ≥ 2.7 | Request/response models, GeoJSON models |
| LLM orchestration | LangChain ≥ 0.3, langchain-openai ≥ 0.2 | Prompt chaining, output parsing |
| HTTP client | httpx ≥ 0.27 | Async requests to external APIs |
| Data processing | pandas ≥ 2.0, numpy ≥ 1.24 | DataFrames, aggregations |
| Semantic search | scikit-learn ≥ 1.3 | Cosine similarity for embeddings |
| Config | python-dotenv ≥ 1.0 | `.env` file loading |

### Infrastructure

| Concern | Tool |
|---------|------|
| Containerisation | Docker + docker-compose |
| Deployment options | Docker/K8s, AWS ECS/EKS, GCP Cloud Run, Azure Container Apps |

---

## Project Structure

```
civic-app/
├── app/
│   ├── __init__.py
│   ├── main.py                    # FastAPI app + lifespan init
│   ├── models.py                  # Pydantic request/response models
│   ├── endpoint_matcher.py        # Semantic search + LLM param extraction
│   ├── api_client.py              # External API trigger (httpx)
│   ├── data_processor.py          # GeoJSON/time-series/generic processing
│   └── utils.py                   # QueryBuilder + ResponseFormatter
│
├── design_docs/
│   ├── civic-app-architecture.md  # Index → links to sub-docs
│   ├── architecture-overview.md   # ← you are here
│   ├── api-contract.md            # REST API contract & models
│   ├── data-processing-strategies.md
│   ├── endpoint-schema-api-response.json
│   └── data-gov-apis-definations/
│
├── notebooks/
├── requirements.txt
├── Dockerfile
├── docker-compose.yml
└── README.md
```

---

## Performance Characteristics

| Concern | Approach |
|---------|----------|
| Embedding computation | One-time on startup; cached in memory |
| LLM calls | Only 1 per request (parameter extraction) |
| Async I/O | `httpx.AsyncClient` for external API calls |
| Large datasets | Pagination, gzip compression |
| Abuse prevention | Rate limiting (to be added) |

---

## Future Enhancements

Ordered by expected impact:

1. **Session management** — conversation memory via session IDs for multi-turn queries.
2. **WebSocket streaming** — real-time data push for live weather / transport feeds.
3. **Batch query endpoint** — process multiple queries in a single request to reduce round-trips.
