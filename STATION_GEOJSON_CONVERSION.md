# Geographic Location Data to GeoJSON Conversion

## Overview

The data processor automatically detects and converts **ANY data containing geographic location information** into standard GeoJSON format. This enables seamless visualization of location-based data on maps, regardless of the original data structure.

**Nested Structure Support:** The system checks up to **one level deep** for location data, so it can detect patterns like:
- ✅ Top level: `{stations: [...]}`
- ✅ One level nested: `{response: {stations: [...]}}`
- ❌ Two levels nested: `{data: {response: {stations: [...]}}}` (too deep)

## Supported Input Formats

The processor recognizes multiple patterns and field name variations:

### Pattern 1: Nested Location Object
```json
{
  "stations": [
    {
      "id": "STN001",
      "name": "Station Name",
      "location": {
        "latitude": 1.3764,
        "longitude": 103.8492
      }
    }
  ]
}
```

### Pattern 2: Direct Coordinates
```json
{
  "locations": [
    {
      "name": "Place A",
      "latitude": 1.3764,
      "longitude": 103.8492,
      "value": 28.3
    }
  ]
}
```

### Pattern 3: Short Field Names
```json
{
  "items": [
    {
      "id": "POI-001",
      "name": "Point of Interest",
      "lat": 1.3764,
      "lon": 103.8492
    }
  ]
}
```

### Pattern 4: With Time-Series Data
```json
{
  "data": [
    {
      "sensorId": "TEMP-01",
      "location": {"latitude": 1.3764, "longitude": 103.8492},
      "series": [
        {"time": "2026-02-20T10:00:00Z", "value": 28.5},
        {"time": "2026-02-20T11:00:00Z", "value": 29.2}
      ],
      "unit": "°C"
    }
  ]
}
```

### Pattern 5: Station-Based with Separate Readings
```json
{
  "stations": [
    {
      "id": "S109",
      "name": "Station Name",
      "location": {"latitude": 1.3764, "longitude": 103.8492}
    }
  ],
  "readings": [
    {
      "timestamp": "2026-02-20T14:16:00+08:00",
      "data": [{"stationId": "S109", "value": 28.3}]
    }
  ],
  "readingType": "Temperature",
  "readingUnit": "°C"
}
```

## Detection Capabilities

### Supported Container Keys
The system looks for these keys at **first or second level**:
- `stations`
- `locations`
- `items`
- `data`
- `results`
- `features`

**Examples:**
```json
// ✅ First level - Direct detection
{"stations": [...]}

// ✅ Second level - Nested detection (one level deep)
{"response": {"stations": [...]}}
{"apiData": {"locations": [...]}}

// ❌ Third level or deeper - NOT detected
{"outer": {"inner": {"stations": [...]}}}
```

### Supported Readings Formats
The system handles two common readings structures:

**Format 1: Nested structure** (original station-based format)
```json
{
  "stations": [...],
  "readings": [
    {
      "timestamp": "2024-01-01T10:00:00Z",
      "data": [
        {"stationId": "S001", "value": 15.5}
      ]
    }
  ]
}
```

**Format 2: Flat structure** (simpler format)
```json
{
  "stations": [...],
  "readings": [
    {
      "stationId": "S001",
      "timestamp": "2024-01-01T10:00:00Z",
      "value": 15.5
    }
  ]
}
```

### Supported Coordinate Field Names
- **Nested**: `location.latitude` & `location.longitude`
- **Full names**: `latitude` & `longitude`
- **Short names**: `lat` & `lon` or `lat` & `lng`
- **Array format**: `coordinates: [lon, lat]`

### Time-Series Support
- **Separate readings**: Linked by ID with timestamp arrays (both formats)
- **Embedded series**: `series` or `timeSeries` fields within items
- **Automatic temporal property creation**: Converts to GeoJSON temporal format

## Conversion Process

### 1. **Automatic Detection**
- Scans for common location container keys
- Checks items for location fields (various formats)
- Validates coordinate data existence

### 2. **Coordinate Extraction**
- Handles nested and direct location fields
- Supports multiple field name variations
- Extracts from arrays or objects

### 3. **Property Organization**
- **Static properties**: Non-location, non-temporal data
- **Temporal properties**: Time-series data grouped by attribute
- Preserves metadata (units, types, IDs)

### 4. **GeoJSON Generation**
- Creates FeatureCollection with Point geometries
- Organizes properties into static/temporal structure
- Calculates bounds and center point

```json
{
  "type": "FeatureCollection",
  "features": [
    {
      "type": "Feature",
      "geometry": {
        "type": "Point",
        "coordinates": [103.8492, 1.3764]
      },
      "properties": {
        "static": {
          "id": "S109",
          "name": "Station Name"
        },
        "temporal": {
          "temperature": {
            "unit": "deg C",
            "series": [
              {"time": "2026-02-20T14:16:00+08:00", "value": 28.3},
              {"time": "2026-02-20T14:15:00+08:00", "value": 28.2}
            ]
          }
        }
      }
    }
  ]
}
```

## API Response

When this conversion occurs, the response includes:

```json
{
  "status": "success",
  "data": {
    "geojson": { /* Converted GeoJSON */ },
    "bounds": [[1.3764, 103.8492], [1.4168, 103.9673]],
    "center": {"lat": 1.3966, "lon": 103.90825},
    "features_count": 2,
    "property_type": "temporal",
    "temporal_attributes": {
      "temperature": {
        "unit": "deg C",
        "time_range": ["2026-02-20T14:15:00+08:00", "2026-02-20T14:16:00+08:00"],
        "data_points": 2
      }
    }
  },
  "visualization_type": "map_temporal",
  "metadata": { /* ... */ }
}
```

## Frontend Visualization Options

With this temporal GeoJSON, frontends can create:

1. **Animated Maps**
   - Time slider to scrub through readings
   - Markers color-coded by current values
   - Play/pause controls

2. **Interactive Features**
   - Click station to see time-series chart
   - Hover for current value
   - Toggle between different temporal attributes

3. **Heatmap Views**
   - Interpolate values between stations
   - Color gradients based on measurements
   - Temporal animation

4. **Multi-Attribute Display**
   - If multiple measurements exist (temperature, humidity, etc.)
   - Switch between different data layers
   - Correlation visualizations

## Benefits

- ✅ **Automatic Detection**: No configuration needed
- ✅ **Preserves Metadata**: Station names, IDs, units maintained
- ✅ **Time-Series Ready**: Chronologically sorted readings
- ✅ **Standard Format**: Outputs GeoJSON compatible with all major mapping libraries
- ✅ **Flexible**: Supports any number of stations and readings
- ✅ **Type Indicators**: Frontend knows to render as animated map

## Testing

Run the test script to verify conversion:

```bash
python test_station_conversion.py
```

Expected output:
- Data type: `geojson`
- Property type: `temporal`
- Valid GeoJSON structure with temporal properties
- All verifications passed ✅

## Implementation Files

- `app/data_processor.py`: Core conversion logic
  - `_is_station_timeseries()`: Detection method
  - `_convert_stations_to_geojson()`: Transformation method
  
- `design_docs/civic-app-architecture.md`: Documentation updated with conversion examples

- `test_station_conversion.py`: Test script with sample data
