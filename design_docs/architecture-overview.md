# Civic App — Architecture Overview

> Backend API that enables external frontends to access Singapore government data APIs through natural language queries.

## Table of Contents

- [System Architecture](#system-architecture)
- [Request Lifecycle](#request-lifecycle)
- [Component Responsibilities](#component-responsibilities)
  - [LLMSummarizer](#llmsummarizer-appchatpy--always-active)
  - [SessionStore](#sessionstore-appchatpy--always-active)
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

### Chat Mode (always active)

After step 6, two additional stages always run:

```
┌─────────────────────────────────────────────────────────────────┐
│  7. LLM SUMMARIZER             (app/chat.py → LLMSummarizer)  │
│     Builds prompt from QueryResponse + session history         │
│     → GPT-4 produces plain-English assistant_message.content   │
└────────────────────────────┬────────────────────────────────────┘
                             │
                             ▼
┌─────────────────────────────────────────────────────────────────┐
│  8. SESSION STORE              (app/chat.py → SessionStore)    │
│     Load history before step 2 · Persist user + assistant      │
│     turns after step 7 · Manage 24-hour session expiry         │
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

### Chat Mode — Additional Steps (always active)

Steps 0, 7, and 8 always run on every request:

| Step | Component | What Happens |
|------|-----------|--------------|
| **0** | `SessionStore` | Load last 10 turns; auto-create session UUID if `session_id` omitted on first call |
| **1–6** | *(core pipeline)* | Endpoint matching, query building, API trigger, data processing, response formatting |
| **7** | `LLMSummarizer` | Build prompt from `QueryResponse` + session history → GPT-4 → `content` field in response |
| **8** | `SessionStore` | Persist `ChatHistoryEntry` for this query + response turn |

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
| `geojson` (temporal) | `map_temporal` | `layer_id`, `layer_label`, `temporal`, `bounds`, `center` |
| `geojson` (static) | `map` | `layer_id`, `layer_label`, `bounds`, `center`, `features_count` |
| `time_series` | `time_series` | `chart_configs`, `summary_stats` |
| `generic` | `generic` | raw data passthrough |

### LLMSummarizer (`app/chat.py`) — *always active* and generates a natural-language summary:

- **Input:** `QueryResponse`, user query string, and the last 10 turns of session history.
- **Prompt construction:** Selects a `visualization_type`-specific data block (stats for `time_series`, bounds/count for `map`, etc.) and injects it into a structured system prompt.
- **Output:** A single plain-English paragraph — no markdown, no invented numbers.
- **Model:** GPT-4 via LangChain (`langchain-openai`).

| `visualization_type` | Data fed to LLM |
|----------------------|-----------------|
| `time_series` | `summary_stats`, record count, `y_label`, user query |
| `map` | `features_count`, `bounds`, `layer_label`, user query |
| `map_temporal` | `features_count`, first/last temporal values, `unit`, user query |
| `generic` | First 5 `data.records`, user query |
| `error` | `error` string, available endpoint topics, user query |

### SessionStore (`app/chat.py`) — *always active*

In-memory conversation store keyed by `session_id` (UUID v4):

| Rule | Detail |
|------|--------|
| **Creation** | Auto-generated UUID v4 when `session_id` is omitted in the request |
| **History window** | Last 10 turns (5 user + 5 assistant) supplied to the LLM per call |
| **Storage** | `ChatHistoryEntry` only (role, message_id, content, timestamp) — `query_response` JSON is **not** stored |
| **Expiry** | Sessions expire after 24 hours of inactivity |
| **MVP backend** | In-memory dict; migrate to Redis / PostgreSQL for production persistence |

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
│   ├── utils.py                   # QueryBuilder + ResponseFormatter
│   └── chat.py                    # LLMSummarizer + SessionStore (always active on every request)
│
├── design_docs/
│   ├── civic-app-architecture.md  # Index → links to sub-docs
│   ├── architecture-overview.md   # ← you are here
│   ├── api-contract.md            # REST API contract, models, LLM summary fields, session semantics
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
| LLM calls | Always 2 per request: parameter extraction (step 2) + LLM summarisation (step 7) |
| Async I/O | `httpx.AsyncClient` for external API calls |
| Large datasets | Pagination, gzip compression |
| Abuse prevention | Rate limiting (to be added) |

---

## Future Enhancements

Ordered by expected impact:

1. **Session management** ✅ — `POST /api/query` delivers server-managed conversation history when `session_id` is supplied (in-memory MVP); migrate to Redis / PostgreSQL for production persistence.
2. **WebSocket streaming** — real-time data push for live weather / transport feeds.
3. **Batch query endpoint** — process multiple queries in a single request to reduce round-trips.
