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

Process a natural-language query and return structured, visualisation-ready data.

**Request**

```jsonc
// Content-Type: application/json
{
  "query": "Show me air temperature for today",   // required
  "session_id": "optional-session-uuid",           // optional
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
  "error": null
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
  "error": null
}
```

**Response — error**

```json
{
  "status": "error",
  "data": {},
  "visualization_type": "error",
  "error": "Could not understand the query. Please try rephrasing your question."
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
| `session_id` | `str \| null` | ❌ | Optional session ID for conversation tracking |
| `context` | `dict \| null` | ❌ | Optional context data |

### `QueryResponse`

| Field | Type | Description |
|-------|------|-------------|
| `status` | `str` | `"success"` or `"error"` |
| `data` | `dict` | Processed data ready for visualisation |
| `visualization_type` | `str` | One of: `map`, `map_temporal`, `time_series`, `generic`, `error` |
| `error` | `str \| null` | Error message when `status` is `"error"` |

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
