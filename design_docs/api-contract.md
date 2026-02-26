# Civic App — API Contract

> Defines every REST endpoint, request/response shapes, and error semantics.

## Table of Contents

- [Base URL](#base-url)
- [Endpoints](#endpoints)
  - [POST /api/query](#post-apiquery)
  - [GET /api/endpoints](#get-apiendpoints)
  - [GET /health](#get-health)
  - [GET /](#get-)
- [Models](#models)
  - [QueryRequest](#queryrequest)
  - [QueryResponse](#queryresponse)
  - [DataContext](#datacontext)
  - [HealthResponse](#healthresponse)
  - [GeoJSON Models](#geojson-models-in-appdataprocessorpy)
- [Error Handling](#error-handling)
- [Interactive Docs](#interactive-docs)

---

## Base URL

```
http://localhost:8000      # local development
https://<deployed-host>    # production
```

---

## Endpoints

### `POST /api/query`

Process a natural-language query and return structured, visualisation-ready data. LLM summarisation and conversation history are always active. On the first call `session_id` may be omitted; the server generates one and returns it. The frontend must echo it on every subsequent request.

**Request**

```jsonc
// Content-Type: application/json
{
  "query": "Show me air temperature for today",   // required
  "session_id": "session-uuid-123",               // omit only on the very first call; server creates one
  "context": {}                                    // optional
}
```

**Response — success (time-series)**

```json
{
  "status": "success",
  "data": {
    "records": [
      {"station_id": "S50", "timestamp": "2026-02-22T10:00:00+08:00", "value": 28.5}
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
  "error": null,
  "session_id": "session-uuid-123",
  "message_id": "msg-uuid-001",
  "content": "Across 60 weather stations in Singapore, the air temperature is currently averaging 28.5 °C, ranging from 26.0 °C to 31.0 °C.",
  "data_context": {
    "endpoint_id": "3a5f2831-815b-4a0a-bbc6-38e54598c8d9",
    "endpoint_description": "Get real-time air temperature readings from weather stations",
    "confidence": 0.94,
    "triggered_at": "2026-02-22T10:00:00+08:00"
  }
}
```

**Response — success (map / GeoJSON)**

```json
{
  "status": "success",
  "data": {
    "geojson": {"type": "FeatureCollection", "features": ["..."]},
    "bounds": [[1.2, 103.7], [1.4, 103.9]],
    "center": {"lat": 1.3521, "lon": 103.8198},
    "features_count": 12,
    "property_type": "temporal",
    "temporal": {
      "series": [
        {"time": "2026-02-22T14:16:00+08:00", "value": 28.3, "attribute": "dbt_1m_f"}
      ],
      "unit": "deg C"
    }
  },
  "visualization_type": "map_temporal",
  "layer_id": "temperature",
  "layer_label": "Air Temperature",
  "error": null,
  "session_id": "session-uuid-123",
  "message_id": "msg-uuid-002",
  "content": "Air temperature readings are available across 12 stations in Singapore, with the latest value at 28.3 °C.",
  "data_context": {
    "endpoint_id": "3a5f2831-815b-4a0a-bbc6-38e54598c8d9",
    "endpoint_description": "Get real-time air temperature readings from weather stations",
    "confidence": 0.94,
    "triggered_at": "2026-02-22T14:16:00+08:00"
  }
}
```

**Response — error**

```json
{
  "status": "error",
  "data": {},
  "visualization_type": "error",
  "error": "Could not understand the query. Please try rephrasing your question.",
  "session_id": "session-uuid-123",
  "message_id": "msg-uuid-003",
  "content": "I'm sorry, I couldn't find a matching dataset for that question. Try asking: 'Show me air temperature', 'What are PM2.5 levels today?', or 'Where are taxis right now?'",
  "data_context": null
}
```

---

### `GET /api/endpoints`

List all available Singapore government data API endpoints loaded from the schema file.

**Response**

```json
{
  "total": 15,
  "endpoints": [
    {
      "id": "3a5f2831-815b-4a0a-bbc6-38e54598c8d9",
      "description": "Get real-time air temperature readings from weather stations",
      "parameters": [
        {"name": "date", "type": "string", "location": "query", "required": false}
      ]
    }
  ]
}
```

---

### `GET /health`

Health-check endpoint for load balancers and monitoring.

**Response**

```json
{
  "status": "healthy",
  "service": "civic-app-backend",
  "version": "1.0.0"
}
```

---

### `GET /`

Root endpoint returning service metadata.

**Response**

```json
{
  "service": "Civic App Backend API",
  "version": "1.0.0",
  "status": "running",
  "docs": "/docs",
  "health": "/health"
}
```

---

## Models

All models are defined in `app/models.py` using Pydantic v2.

### `QueryRequest`

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `query` | `str` | ✅ | Natural-language query from user |
| `session_id` | `str \| null` | ❌ on first call only | Server auto-creates and returns one if omitted; must be echoed on all subsequent requests |
| `context` | `dict \| null` | ❌ | Optional context data |

### `QueryResponse`

| Field | Type | Description |
|-------|------|-------------|
| `status` | `str` | `"success"` or `"error"` |
| `data` | `dict` | Processed data ready for visualisation |
| `visualization_type` | `str` | One of: `map`, `map_temporal`, `time_series`, `generic`, `error` |
| `layer_id` | `str \| null` | Stable machine identifier for the layer (e.g. `"temperature"`, `"taxi"`, `"pm25"`). Used as the key in the Dashboard `layers` state and as the prefix for all Mapbox source/layer IDs. Present only when `visualization_type` is `map` or `map_temporal`; `null` otherwise. |
| `layer_label` | `str \| null` | Human-readable layer name shown in the `LayerToggle` panel (e.g. `"Air Temperature"`). Present only when `visualization_type` is `map` or `map_temporal`; `null` otherwise. |
| `error` | `str \| null` | Error message when `status` is `"error"` |
| `session_id` | `str` | Echoed or newly created session UUID. Always present; auto-created on first call. |
| `message_id` | `str` | Server-generated UUID v4 for this response turn. Always present. |
| `content` | `str` | LLM-generated plain-English summary; an LLM apology when `status` is `"error"`. Always present. |
| `data_context` | `DataContext \| null` | API call metadata (matched endpoint, confidence). Always present; `null` when `status` is `"error"`. |

### `HealthResponse`

| Field | Type | Description |
|-------|------|-------------|
| `status` | `str` | `"healthy"` |
| `service` | `str` | `"civic-app-backend"` |
| `version` | `str` | Semver string |

### GeoJSON Models (in `app/data_processor.py`)

| Model | Purpose |
|-------|---------|
| `PointGeometry` | `{"type": "Point", "coordinates": [lon, lat]}` |
| `MultiPointGeometry` | `{"type": "MultiPoint", "coordinates": [[lon, lat], ...]}` |
| `TemporalProperty` | `{"series": [...], "unit": "deg C"}` |
| `Properties` | `{"static": {...}, "temporal": TemporalProperty \| null}` |
| `Feature` | Standard GeoJSON Feature with typed geometry & properties |
| `FeatureCollection` | Standard GeoJSON FeatureCollection |
| `GeoJSONProcessedResponse` | Wrapper: `{"data_type": "geojson", "geojson": FeatureCollection}` |

### `DataContext`

Sub-model nested in `QueryResponse.data_context`. Always present when `status` is `"success"`; `null` when `status` is `"error"`.

| Field | Type | Description |
|-------|------|-------------|
| `endpoint_id` | `str` | UUID of the matched gov API endpoint |
| `endpoint_description` | `str` | Human-readable description from the schema |
| `confidence` | `float` | Matching confidence score `[0, 1]` |
| `triggered_at` | `str` | ISO-8601 timestamp of the external API call |

---

## Error Handling

Errors are returned **inside** a `QueryResponse` (HTTP 200) so the frontend always receives a predictable shape.

| Scenario | `error` message | Trigger |
|----------|----------------|---------|
| Low confidence match | `"Could not understand the query…"` | `confidence < 0.5` |
| External API failure | `"External API error: HTTP 502…"` | `APIError` from `api_client.py` |
| Missing required param | `"Validation error: Required parameter 'date' is missing"` | `ValueError` from `QueryBuilder` |
| Unexpected failure | `"Internal server error: …"` | Catch-all `Exception` |

> **Note:** The `GET /api/endpoints` route raises `HTTPException(500)` on failure instead of the `QueryResponse` envelope because it is an admin/introspection endpoint.

---

## Interactive Docs

FastAPI auto-generates interactive documentation:

| URL | Format |
|-----|--------|
| `/docs` | Swagger UI |
| `/redoc` | ReDoc |
