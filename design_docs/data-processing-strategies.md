# Civic App — Data Processing Strategies

> How `DataProcessor` detects, converts, and normalises API responses into visualisation-ready formats.
>
> Implementation: `app/data_processor.py`
>
> The `QueryResponse` produced by this pipeline is always consumed by the `LLMSummarizer` on every call to `POST /api/query` — it reads `visualization_type`, `summary_stats`, and other visualization-specific fields directly from it. See [api-contract.md](api-contract.md) for the LLM input contract per visualization type.

## Table of Contents

- [Detection Flow](#detection-flow)
- [Strategy 1 — GeoJSON (native)](#strategy-1--geojson-native)
- [Strategy 2 — Geographic Location Data → GeoJSON](#strategy-2--geographic-location-data--geojson)
  - [Supported Input Patterns](#supported-input-patterns)
  - [Location Field Detection](#location-field-detection)
  - [Conversion Output: MultiPoint GeoJSON](#conversion-output-multipoint-geojson)
  - [Full Input → Output Example](#full-input--output-example)
- [Strategy 3 — Time-Series](#strategy-3--time-series)
- [Strategy 4 — Generic Passthrough](#strategy-4--generic-passthrough)
- [GeoJSON Property Model](#geojson-property-model)

---

## Detection Flow

`DataProcessor.process_response()` applies these rules **in order**:

```
responseBody
  │
  ├── type == "FeatureCollection" or "Feature"?
  │     YES → Strategy 1 (native GeoJSON)
  │
  ├── Any array whose items contain lat/lon fields?
  │     YES → Strategy 2 (auto-convert → MultiPoint GeoJSON)
  │
  ├── Contains "readings" or "data" key?
  │     YES → Strategy 3 (time-series DataFrame)
  │
  └── else → Strategy 4 (generic passthrough)
```

---

## Strategy 1 — GeoJSON (native)

**Trigger:** `responseBody.type` is `"FeatureCollection"` or `"Feature"`.

**Processing:** Wraps the data in a `FeatureCollection` Pydantic model and returns a `GeoJSONProcessedResponse`.

No transformation is applied — the data is already in the correct format.

---

## Strategy 2 — Geographic Location Data → GeoJSON

**Trigger:** `_has_geo_location_data()` finds at least one array (at the top level or one level deep) whose items contain recognisable location fields.

### Location Field Detection

The detector (`_has_location_fields`) recognises these patterns in each array item:

| Pattern | Example |
|---------|---------|
| Nested `location` object | `{"location": {"latitude": 1.37, "longitude": 103.84}}` |
| Nested `location` (short) | `{"location": {"lat": 1.37, "lon": 103.84}}` |
| Direct lat/lon | `{"latitude": 1.37, "longitude": 103.84}` |
| Direct short form | `{"lat": 1.37, "lon": 103.84}` or `{"lat": 1.37, "lng": 103.84}` |
| Coordinates array | `{"coordinates": [103.84, 1.37]}` (GeoJSON order) |

> The key name holding the array (`stations`, `busstops`, `sensors`, etc.) **does not matter** — detection is value-based.

### Supported Input Patterns

#### Pattern 1 — Station-based with time-series readings

```json
{
  "stations": [
    {"id": "S109", "name": "Ang Mo Kio", "location": {"latitude": 1.3764, "longitude": 103.8492}}
  ],
  "readings": [
    {"timestamp": "2026-02-20T14:16:00+08:00", "data": [{"stationId": "S109", "value": 28.3}]}
  ],
  "readingType": "DBT 1M F",
  "readingUnit": "deg C"
}
```

#### Pattern 2 — Direct location array

```json
{
  "locations": [
    {"name": "Place A", "lat": 1.3764, "lon": 103.8492, "value": 28.3}
  ]
}
```

#### Pattern 3 — Items with embedded coordinates

```json
{
  "items": [
    {"name": "POI", "latitude": 1.3764, "longitude": 103.8492, "properties": {}}
  ]
}
```

### Conversion Output: MultiPoint GeoJSON

All detected items are **merged into a single Feature** with `MultiPoint` geometry. Properties are split into `static` (scalar fields aggregated across items) and `temporal` (time-series readings merged with an `attribute` tag).

```json
{
  "type": "FeatureCollection",
  "features": [
    {
      "type": "Feature",
      "geometry": {
        "type": "MultiPoint",
        "coordinates": [[103.8492, 1.3764], [103.9673, 1.4168]]
      },
      "properties": {
        "static": {
          "id": ["S109", "S106"],
          "name": ["Ang Mo Kio Avenue 5", "Pulau Ubin"]
        },
        "temporal": {
          "series": [
            {"time": "2026-02-20T14:16:00+08:00", "value": 28.3, "attribute": "dbt_1m_f"},
            {"time": "2026-02-20T14:15:00+08:00", "value": 28.3, "attribute": "dbt_1m_f"},
            {"time": "2026-02-20T14:16:00+08:00", "value": 28.6, "attribute": "dbt_1m_f"},
            {"time": "2026-02-20T14:15:00+08:00", "value": 28.7, "attribute": "dbt_1m_f"}
          ],
          "unit": "deg C"
        }
      }
    }
  ]
}
```

> **Known limitation:** Because all stations are merged into one Feature, `bounds` will be `null` and `features_count` will be `1`. The `center` defaults to Singapore (1.3521, 103.8198).

### Full Input → Output Example

<details>
<summary>Input — station-based temperature readings</summary>

```json
{
  "stations": [
    {
      "id": "S109", "deviceId": "S109", "name": "Ang Mo Kio Avenue 5",
      "location": {"latitude": 1.3764, "longitude": 103.8492}
    },
    {
      "id": "S106", "name": "Pulau Ubin",
      "location": {"latitude": 1.4168, "longitude": 103.9673}
    }
  ],
  "readings": [
    {
      "timestamp": "2026-02-20T14:16:00+08:00",
      "data": [{"stationId": "S109", "value": 28.3}, {"stationId": "S106", "value": 28.6}]
    },
    {
      "timestamp": "2026-02-20T14:15:00+08:00",
      "data": [{"stationId": "S109", "value": 28.3}, {"stationId": "S106", "value": 28.7}]
    }
  ],
  "readingType": "DBT 1M F",
  "readingUnit": "deg C"
}
```

</details>

<details>
<summary>Output — API response</summary>

```json
{
  "status": "success",
  "data": {
    "geojson": {
      "type": "FeatureCollection",
      "features": [
        {
          "type": "Feature",
          "geometry": {
            "type": "MultiPoint",
            "coordinates": [[103.8492, 1.3764], [103.9673, 1.4168]]
          },
          "properties": {
            "static": {
              "id": ["S109", "S106"],
              "deviceId": ["S109", "S106"],
              "name": ["Ang Mo Kio Avenue 5", "Pulau Ubin"]
            },
            "temporal": {
              "series": [
                {"time": "2026-02-20T14:16:00+08:00", "value": 28.3, "attribute": "dbt_1m_f"},
                {"time": "2026-02-20T14:15:00+08:00", "value": 28.3, "attribute": "dbt_1m_f"},
                {"time": "2026-02-20T14:16:00+08:00", "value": 28.6, "attribute": "dbt_1m_f"},
                {"time": "2026-02-20T14:15:00+08:00", "value": 28.7, "attribute": "dbt_1m_f"}
              ],
              "unit": "deg C"
            }
          }
        }
      ]
    },
    "bounds": null,
    "center": {"lat": 1.3521, "lon": 103.8198},
    "features_count": 1,
    "property_type": "temporal",
    "temporal": {
      "series": [
        {"time": "2026-02-20T14:16:00+08:00", "value": 28.3, "attribute": "dbt_1m_f"},
        {"time": "2026-02-20T14:15:00+08:00", "value": 28.3, "attribute": "dbt_1m_f"},
        {"time": "2026-02-20T14:16:00+08:00", "value": 28.6, "attribute": "dbt_1m_f"},
        {"time": "2026-02-20T14:15:00+08:00", "value": 28.7, "attribute": "dbt_1m_f"}
      ],
      "unit": "deg C"
    }
  },
  "visualization_type": "map_temporal",
  "layer_id": "temperature",
  "layer_label": "Air Temperature",
  "error": null,
  "session_id": "session-uuid-123",
  "message_id": "msg-uuid-001",
  "content": "Air temperature readings are available across 2 stations in Singapore, with the latest value at 28.3 °C.",
  "data_context": {
    "endpoint_id": "3a5f2831-815b-4a0a-bbc6-38e54598c8d9",
    "endpoint_description": "Get real-time air temperature readings from weather stations",
    "confidence": 0.94,
    "triggered_at": "2026-02-20T14:16:00+08:00"
  }
}
```

</details>

---

## Strategy 3 — Time-Series

**Trigger:** `responseBody` contains a `readings` or `data` key (and is not geo-location data).

**Processing (`process_time_series`):**

1. Flatten readings with `pd.json_normalize`.
2. Auto-detect and parse timestamp columns.
3. Compute summary stats (`mean`, `min`, `max`, `std`) for every numeric column.
4. Return a dict with `dataframe` and `summary_stats`.

**Example input:**

```json
{
  "readings": [
    {"station_id": "S50", "timestamp": "2026-02-22T10:00:00+08:00", "value": 28.5},
    {"station_id": "S50", "timestamp": "2026-02-22T11:00:00+08:00", "value": 29.1}
  ]
}
```

**ResponseFormatter** then adds chart configs:

| Detected Columns | Chart Type |
|-------------------|-----------|
| time + value | Line chart (`"Temperature Over Time"`) |
| station + value | Bar chart (`"Average Temperature by Station"`) |

---

## Strategy 4 — Generic Passthrough

**Trigger:** None of the above rules matched.

**Processing:** Returns the raw `responseBody` as-is, wrapped in `{"data_type": "generic", "data": ...}`.

---

## GeoJSON Property Model

All GeoJSON features produced by this system use a two-level property structure:

```
properties
├── static    ← time-independent attributes (name, id, category, …)
└── temporal  ← time-series data (optional)
    ├── series: [{time, value, attribute}, …]
    └── unit: string
```

**Pydantic models** (defined in `app/data_processor.py`):

| Model | Fields |
|-------|--------|
| `TemporalProperty` | `series: list[dict]`, `unit: str \| None` |
| `Properties` | `static: dict \| None`, `temporal: TemporalProperty \| None` |
| `Feature` | `type`, `geometry` (Point \| MultiPoint), `properties` |
| `FeatureCollection` | `type`, `features: list[Feature]` |

**Temporal GeoJSON example:**

```json
{
  "type": "Feature",
  "geometry": {"type": "Point", "coordinates": [103.8519, 1.2902]},
  "properties": {
    "static": {"name": "Singapore", "station_id": "S50"},
    "temporal": {
      "series": [
        {"time": "2026-02-20T00:00:00Z", "value": 27.1, "attribute": "temperature"},
        {"time": "2026-02-20T00:00:00Z", "value": 85,   "attribute": "humidity"}
      ],
      "unit": "C"
    }
  }
}
```

**Static GeoJSON example:**

```json
{
  "type": "Feature",
  "geometry": {"type": "Point", "coordinates": [103.8519, 1.2902]},
  "properties": {
    "static": {
      "name": "Singapore",
      "population": 5927000,
      "climate_type": "Tropical rainforest"
    }
  }
}
```
