# Civic App — Chat Message Contract

> Defines the message shapes, session model, and LLM-summary pipeline for the conversational interface layered on top of the REST API.

## Table of Contents

- [Overview](#overview)
- [Message Flow](#message-flow)
- [Endpoint](#endpoint)
  - [POST /api/chat](#post-apichat)
- [Message Models](#message-models)
  - [ChatHistoryEntry](#chathistoryentry) *(server-internal)*
  - [ChatRequest](#chatrequest)
  - [ChatUserMessage](#chatusermessage)
  - [DataContext](#datacontext)
  - [ChatAssistantMessage](#chatassistantmessage)
  - [ChatResponse](#chatresponse)
- [LLM Summary Generation](#llm-summary-generation)
  - [Input Contract per Visualization Type](#input-contract-per-visualization-type)
  - [Prompt Template Skeleton](#prompt-template-skeleton)
- [End-to-End Examples](#end-to-end-examples)
  - [Example 1 — Time-series (temperature)](#example-1--time-series-temperature)
  - [Example 2 — Map / GeoJSON (taxi locations)](#example-2--map--geojson-taxi-locations)
  - [Example 3 — Error (unrecognised query)](#example-3--error-unrecognised-query)
- [Session Management](#session-management)
- [Relationship to REST API Contract](#relationship-to-rest-api-contract)

---

## Overview

The chat layer wraps the existing `POST /api/query` pipeline with two additions:

1. **AI text response** — an LLM reads the `QueryResponse` JSON and produces a short, human-readable summary (the `content` field of the assistant message).
2. **Conversation history** — the **backend** stores and manages the full message history per session. The frontend only sends a `session_id`; the server retrieves the relevant history automatically before each LLM call.

Every assistant message carries **both** the AI text and the full structured `query_response` object, so the frontend can render the visualization alongside the conversational reply.

---

## Message Flow

```
User types: "what is the current temperature?"
       │
       ▼
POST /api/chat  ─── ChatRequest ──────────────────────────────────────┐
       │            { message, session_id }                            │
       ▼                                                               │
[ 0 ] SessionStore    →  load history for session_id                  │
       │                  (create new session if omitted)              │
       ▼                                                               │
[ 1 ] EndpointMatcher  →  matched endpoint + confidence               │
       │                                                               │
       ▼                                                               │
[ 2 ] QueryBuilder     →  request payload                             │
       │                                                               │
       ▼                                                               │
[ 3 ] APITrigger       →  raw JSON from gov API                       │
       │                                                               │
       ▼                                                               │
[ 4 ] DataProcessor    →  visualization-ready QueryResponse           │
       │                                                               │
       ▼                                                               │
[ 5 ] LLMSummarizer    →  natural-language summary (content string)   │
       │                  (uses stored history for context)            │
       ▼                                                               │
[ 6 ] SessionStore    →  persist user + assistant messages            │
       │                                                               │
       ▼                                                               │
ChatResponse  ◄──────────────────────────────────────────────────────┘
  ├── user_message   (echoed back with generated message_id)
  └── assistant_message
        ├── content          ← LLM text summary
        └── query_response   ← full QueryResponse for visualization
```

---

## Endpoint

### `POST /api/chat`

Single conversational endpoint. Internally executes the full query pipeline and appends an LLM-generated summary.

**Request**

```jsonc
// Content-Type: application/json
{
  "message": "what is the current temperature?",   // required — user's raw text
  "session_id": "session-uuid-123"                 // optional — omit on first turn; server creates one
}
```

**Response — success**

```jsonc
// HTTP 200
{
  "session_id": "session-uuid-123",
  "user_message": {
    "role": "user",
    "message_id": "msg-ccc-003",
    "content": "what is the current temperature?",
    "timestamp": "2026-02-26T10:00:00+08:00"
  },
  "assistant_message": {
    "role": "assistant",
    "message_id": "msg-ddd-004",
    "content": "Across 60 weather stations in Singapore, the air temperature is currently averaging 28.5 °C. The coolest station is recording 26.0 °C and the warmest 31.0 °C (std dev 1.2 °C).",
    "query_response": {
      "status": "success",
      "data": { /* ... full QueryResponse.data ... */ },
      "visualization_type": "time_series",
      "layer_id": null,
      "layer_label": null,
      "error": null
    },
    "data_context": {
      "endpoint_id": "3a5f2831-815b-4a0a-bbc6-38e54598c8d9",
      "endpoint_description": "Get real-time air temperature readings from weather stations",
      "confidence": 0.94,
      "triggered_at": "2026-02-26T10:00:00+08:00"
    },
    "timestamp": "2026-02-26T10:00:01+08:00"
  }
}
```

**Response — error (unrecognised query or API failure)**

```jsonc
// HTTP 200 — errors are always surfaced inside the response envelope
{
  "session_id": "session-uuid-123",
  "user_message": {
    "role": "user",
    "message_id": "msg-eee-005",
    "content": "what is the weather on Mars?",
    "timestamp": "2026-02-26T10:01:00+08:00"
  },
  "assistant_message": {
    "role": "assistant",
    "message_id": "msg-fff-006",
    "content": "I'm sorry, I couldn't find a matching dataset for that question. Could you try rephrasing? For example: 'Show me air temperature', 'What are PM2.5 levels today?' or 'Where are taxis right now?'",
    "query_response": {
      "status": "error",
      "data": {},
      "visualization_type": "error",
      "error": "Could not understand the query. Please try rephrasing your question."
    },
    "data_context": null,
    "timestamp": "2026-02-26T10:01:01+08:00"
  }
}
```

---

## Message Models

### `ChatHistoryEntry`

Used **internally by the server** to represent a stored turn. Never sent by the client.

| Field | Type | Description |
|-------|------|-------------|
| `role` | `"user" \| "assistant"` | Speaker of this message |
| `message_id` | `str` | UUID of the message |
| `content` | `str` | Human-readable text only (no `query_response`) |
| `timestamp` | `str` | ISO-8601 timestamp |

---

### `ChatRequest`

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `message` | `str` | ✅ | Raw user input |
| `session_id` | `str \| null` | ❌ | Omit on first turn; server creates and returns one |

---

### `ChatUserMessage`

Echoed back in the response with a server-assigned `message_id` and `timestamp`.

| Field | Type | Description |
|-------|------|-------------|
| `role` | `"user"` | Always `"user"` |
| `message_id` | `str` | Server-generated UUID v4 |
| `content` | `str` | Verbatim copy of `ChatRequest.message` |
| `timestamp` | `str` | ISO-8601 with timezone (Asia/Singapore) |

---

### `DataContext`

Metadata about the API call that produced the response. `null` when `query_response.status == "error"`.

| Field | Type | Description |
|-------|------|-------------|
| `endpoint_id` | `str` | UUID of the matched gov API endpoint |
| `endpoint_description` | `str` | Human-readable description from the schema |
| `confidence` | `float` | Matching confidence score `[0, 1]` |
| `triggered_at` | `str` | ISO-8601 timestamp of the external API call |

---

### `ChatAssistantMessage`

| Field | Type | Description |
|-------|------|-------------|
| `role` | `"assistant"` | Always `"assistant"` |
| `message_id` | `str` | Server-generated UUID v4 |
| `content` | `str` | **LLM-generated** natural-language summary |
| `query_response` | `QueryResponse` | Full structured response (see [api-contract.md](api-contract.md)) |
| `data_context` | `DataContext \| null` | API call metadata; `null` on error |
| `timestamp` | `str` | ISO-8601 with timezone |

---

### `ChatResponse`

Top-level response envelope.

| Field | Type | Description |
|-------|------|-------------|
| `session_id` | `str` | Session UUID (server creates one if not supplied in the request) |
| `user_message` | `ChatUserMessage` | Echoed user turn |
| `assistant_message` | `ChatAssistantMessage` | AI reply with data |

---

## LLM Summary Generation

The LLM receives a **structured prompt** built from the `QueryResponse`. It must produce a single paragraph of plain prose — no markdown, no bullet lists — that:

- States the data topic and current values concisely.
- Highlights the key stat(s) relevant to the user's question.
- Never invents numbers — only what appears in `query_response.data`.
- Ends with an offer to dive deeper if `visualization_type` contains a chart or map.

### Input Contract per Visualization Type

| `visualization_type` | LLM receives | Expected summary focus |
|----------------------|-------------|------------------------|
| `time_series` | `summary_stats`, record count, `chart_configs[0].y_label`, user query | Mean / min / max with unit; time range if present |
| `map` | `features_count`, `bounds`, `layer_label`, user query | How many locations; geographic spread |
| `map_temporal` | `features_count`, `temporal.series` (first & last value, length), `temporal.unit`, `layer_label`, user query | Latest reading; trend direction if series ≥ 2 points |
| `generic` | `data.records` (truncated to 5 rows), user query | Factual summary of top rows |
| `error` | `error` string, user query, available endpoint descriptions | Polite apology + 2–3 example queries the system *can* answer |

### Prompt Template Skeleton

```
System:
You are a helpful civic data assistant for Singapore. Summarise the following
data in one short paragraph of plain English. Do not use markdown. Only use
numbers that appear in the data below.

User query: {user_query}

Data context:
  Endpoint: {endpoint_description}
  Visualization type: {visualization_type}
  {type_specific_data_block}

Conversation history (for reference only — do not repeat it):
{history_text}

Now write one plain-English paragraph summarising the data for the user.
```

#### `{type_specific_data_block}` examples

**time_series**
```
Record count: 60
Y-axis label: Temperature (°C)
Statistics: mean=28.5, min=26.0, max=31.0, std=1.2
```

**map_temporal**
```
Station count: 12
Layer: Air Temperature
Unit: deg C
Latest value: 28.3 at 2026-02-26T14:16:00+08:00
Earliest value: 27.1 at 2026-02-26T08:00:00+08:00
Series length: 48 readings
```

**error**
```
Error: Could not understand the query.
Available topics: air temperature, PM2.5, taxi locations, rainfall, UV index
```

---

## End-to-End Examples

### Example 1 — Time-series (temperature)

**Frontend sends:**
```json
{
  "message": "what is the current temperature?",
  "session_id": null
}
```

**Server pipeline:**
1. `EndpointMatcher` → temperature endpoint, confidence 0.94
2. `APITrigger` → 60 station readings from gov API
3. `DataProcessor` → `visualization_type: "time_series"`, `summary_stats`
4. `LLMSummarizer` → generates `content`

**Server responds:**
```json
{
  "session_id": "session-uuid-123",
  "user_message": {
    "role": "user",
    "message_id": "msg-001",
    "content": "what is the current temperature?",
    "timestamp": "2026-02-26T10:00:00+08:00"
  },
  "assistant_message": {
    "role": "assistant",
    "message_id": "msg-002",
    "content": "Across 60 weather stations in Singapore, the air temperature is currently averaging 28.5 °C, ranging from a low of 26.0 °C to a high of 31.0 °C (std dev 1.2 °C). A time-series chart is displayed below for a closer look.",
    "query_response": {
      "status": "success",
      "data": {
        "records": [
          {"station_id": "S50", "timestamp": "2026-02-26T10:00:00+08:00", "value": 28.5}
        ],
        "summary_stats": {
          "value": {"mean": 28.5, "min": 26.0, "max": 31.0, "std": 1.2}
        },
        "chart_configs": [
          {
            "type": "line",
            "title": "Temperature Over Time",
            "x_axis": "timestamp",
            "y_axis": "value",
            "x_label": "Time",
            "y_label": "Temperature (°C)"
          }
        ],
        "columns": ["station_id", "timestamp", "value"]
      },
      "visualization_type": "time_series",
      "layer_id": null,
      "layer_label": null,
      "error": null
    },
    "data_context": {
      "endpoint_id": "3a5f2831-815b-4a0a-bbc6-38e54598c8d9",
      "endpoint_description": "Get real-time air temperature readings from weather stations",
      "confidence": 0.94,
      "triggered_at": "2026-02-26T10:00:00+08:00"
    },
    "timestamp": "2026-02-26T10:00:01+08:00"
  }
}
```

---

### Example 2 — Map / GeoJSON (taxi locations)

**Frontend sends:**
```json
{
  "message": "where are taxis right now?",
  "session_id": "session-uuid-123"
}
```

**Server responds:**
```json
{
  "session_id": "session-uuid-123",
  "user_message": {
    "role": "user",
    "message_id": "msg-003",
    "content": "where are taxis right now?",
    "timestamp": "2026-02-26T10:02:00+08:00"
  },
  "assistant_message": {
    "role": "assistant",
    "message_id": "msg-004",
    "content": "There are currently 4,231 taxis available across Singapore. The highest concentrations are in the Central Business District and Orchard Road areas. A live map is shown below.",
    "query_response": {
      "status": "success",
      "data": {
        "geojson": {"type": "FeatureCollection", "features": ["..."]},
        "bounds": [[1.2, 103.7], [1.4, 103.9]],
        "center": {"lat": 1.3521, "lon": 103.8198},
        "features_count": 4231,
        "property_type": "static"
      },
      "visualization_type": "map",
      "layer_id": "taxi",
      "layer_label": "Taxi Availability",
      "error": null
    },
    "data_context": {
      "endpoint_id": "b2e91c40-...",
      "endpoint_description": "Get real-time taxi availability locations",
      "confidence": 0.97,
      "triggered_at": "2026-02-26T10:02:00+08:00"
    },
    "timestamp": "2026-02-26T10:02:01+08:00"
  }
}
```

---

### Example 3 — Error (unrecognised query)

**Frontend sends:**
```json
{
  "message": "what is the weather on Mars?",
  "session_id": "session-uuid-123"
}
```

**Server responds:**
```json
{
  "session_id": "session-uuid-123",
  "user_message": {
    "role": "user",
    "message_id": "msg-005",
    "content": "what is the weather on Mars?",
    "timestamp": "2026-02-26T10:03:00+08:00"
  },
  "assistant_message": {
    "role": "assistant",
    "message_id": "msg-006",
    "content": "I'm sorry, I couldn't find a matching dataset for that question. I can help with Singapore civic data — try asking: 'Show me air temperature', 'What are PM2.5 levels today?', or 'Where are taxis right now?'",
    "query_response": {
      "status": "error",
      "data": {},
      "visualization_type": "error",
      "error": "Could not understand the query. Please try rephrasing your question."
    },
    "data_context": null,
    "timestamp": "2026-02-26T10:03:01+08:00"
  }
}
```

---

## Session Management

| Rule | Detail |
|------|--------|
| **Session creation** | If `session_id` is omitted, the server generates a UUID v4, creates a new session record, and returns the ID in `ChatResponse.session_id`. The frontend must store and echo it on every subsequent request. |
| **History storage** | The server persists every `ChatHistoryEntry` (role, message_id, content, timestamp) in an **in-memory dict** keyed by `session_id` (MVP). `query_response` JSON is **not** stored — only the plain-text `content` is needed for LLM context. Migrate to a persistent store (Redis / PostgreSQL) post-MVP. |
| **History window** | Before each LLM call the server loads the last **10 turns** (5 user + 5 assistant) for the session. Older turns are excluded to stay within LLM context limits but remain in the store for audit/retrieval. |
| **History in request** | The client sends **only** `message` and `session_id` — no history payload. The server is the single source of truth for conversation state. |
| **Session expiry** | Sessions expire after **24 hours** of inactivity. Expired session IDs return a `session_expired` error; the frontend should start a new session. |
| **Message IDs** | Server generates a UUID v4 for each `user_message` and `assistant_message` in the response. The frontend uses these as React `key` props and for deduplication. |

---

## Relationship to REST API Contract

The chat endpoint is a **superset** of `POST /api/query`:

| Aspect | `POST /api/query` | `POST /api/chat` |
|--------|-------------------|-----------------|
| Input | `QueryRequest` (`query`, `session_id`, `context`) | `ChatRequest` (`message`, `session_id`, `history`) |
| Output | `QueryResponse` (structured JSON only) | `ChatResponse` (structured JSON **+** LLM text) |
| LLM summary | ❌ | ✅ `assistant_message.content` |
| Conversation history | ❌ | ✅ server-managed per session |
| Message envelope | ❌ | ✅ `user_message` + `assistant_message` |
| Visualization data | ✅ same `QueryResponse` shape | ✅ nested inside `assistant_message.query_response` |

The `QueryResponse` schema defined in [api-contract.md](api-contract.md) is **unchanged** — it is embedded verbatim as `assistant_message.query_response`. Frontend visualisation components that already consume `QueryResponse` require no modification.
