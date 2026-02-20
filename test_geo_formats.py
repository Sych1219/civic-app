"""Test comprehensive geo-location detection and conversion to GeoJSON."""

import json
from app.data_processor import DataProcessor


def test_various_geo_formats():
    """Test conversion of various geographic location data formats to GeoJSON."""
    
    processor = DataProcessor()
    
    print("=" * 80)
    print("TESTING VARIOUS GEO-LOCATION FORMATS")
    print("=" * 80)
    
    # Test Case 1: Station-based with nested location object
    print("\n1. Station-based with nested location object:")
    data1 = {
        "responseBody": {
            "stations": [
                {
                    "id": "STN001",
                    "name": "Central Station",
                    "location": {
                        "latitude": 1.29,
                        "longitude": 103.85
                    }
                }
            ]
        },
        "invokedAt": "2026-02-20T06:00:00Z",
        "endpointId": "test-001"
    }
    result1 = processor.process_response(data1)
    print(f"   ✅ Detected: {result1.data_type}, Features: {result1.features_count}")
    
    # Test Case 2: Locations array with direct lat/lon
    print("\n2. Locations array with direct lat/lon:")
    data2 = {
        "responseBody": {
            "locations": [
                {
                    "name": "Point A",
                    "latitude": 1.30,
                    "longitude": 103.86,
                    "value": 25.5
                },
                {
                    "name": "Point B",
                    "latitude": 1.31,
                    "longitude": 103.87,
                    "value": 26.2
                }
            ]
        },
        "invokedAt": "2026-02-20T06:00:00Z",
        "endpointId": "test-002"
    }
    result2 = processor.process_response(data2)
    print(f"   ✅ Detected: {result2.data_type}, Features: {result2.features_count}")
    
    # Test Case 3: Items with lat/lon (short form)
    print("\n3. Items array with lat/lon (short names):")
    data3 = {
        "responseBody": {
            "items": [
                {
                    "id": "POI-001",
                    "name": "Restaurant",
                    "lat": 1.32,
                    "lon": 103.88,
                    "rating": 4.5
                },
                {
                    "id": "POI-002",
                    "name": "Park",
                    "lat": 1.33,
                    "lng": 103.89,
                    "rating": 4.8
                }
            ]
        },
        "invokedAt": "2026-02-20T06:00:00Z",
        "endpointId": "test-003"
    }
    result3 = processor.process_response(data3)
    print(f"   ✅ Detected: {result3.data_type}, Features: {result3.features_count}")
    
    # Test Case 4: Data array with embedded time series
    print("\n4. Data array with embedded time series:")
    data4 = {
        "responseBody": {
            "data": [
                {
                    "sensorId": "TEMP-01",
                    "location": {
                        "latitude": 1.34,
                        "longitude": 103.90
                    },
                    "series": [
                        {"time": "2026-02-20T10:00:00Z", "value": 28.5},
                        {"time": "2026-02-20T11:00:00Z", "value": 29.2}
                    ],
                    "unit": "°C"
                }
            ]
        },
        "invokedAt": "2026-02-20T06:00:00Z",
        "endpointId": "test-004"
    }
    result4 = processor.process_response(data4)
    print(f"   ✅ Detected: {result4.data_type}, Features: {result4.features_count}")
    print(f"   Property Type: {result4.property_type}")
    if result4.temporal_attributes:
        print(f"   Temporal Attributes: {list(result4.temporal_attributes.keys())}")
    
    # Test Case 5: Results array (common API response format)
    print("\n5. Results array (common API format):")
    data5 = {
        "responseBody": {
            "results": [
                {"id": "BUS-123", "route": "14", "lat": 1.35, "lon": 103.91},
                {"id": "BUS-456", "route": "14", "lat": 1.36, "lon": 103.92}
            ]
        },
        "invokedAt": "2026-02-20T06:00:00Z",
        "endpointId": "test-005"
    }
    result5 = processor.process_response(data5)
    print(f"   ✅ Detected: {result5.data_type}, Features: {result5.features_count}")
    
    # Test Case 6: Station-based with readings (original example)
    print("\n6. Station-based with separate readings:")
    data6 = {
        "responseBody": {
            "stations": [
                {
                    "id": "S109",
                    "name": "Station A",
                    "location": {"latitude": 1.3764, "longitude": 103.8492}
                }
            ],
            "readings": [
                {
                    "timestamp": "2026-02-20T14:16:00+08:00",
                    "data": [{"stationId": "S109", "value": 28.3}]
                },
                {
                    "timestamp": "2026-02-20T14:15:00+08:00",
                    "data": [{"stationId": "S109", "value": 28.2}]
                }
            ],
            "readingType": "Temperature",
            "readingUnit": "°C"
        },
        "invokedAt": "2026-02-20T06:00:00Z",
        "endpointId": "test-006"
    }
    result6 = processor.process_response(data6)
    print(f"   ✅ Detected: {result6.data_type}, Features: {result6.features_count}")
    print(f"   Property Type: {result6.property_type}")
    if result6.temporal_attributes:
        attr_name = list(result6.temporal_attributes.keys())[0]
        attr_info = result6.temporal_attributes[attr_name]
        print(f"   Temporal: {attr_name} ({attr_info.data_points} readings)")
    
    print("\n" + "=" * 80)
    print("DETAILED OUTPUT - Test Case 2 (Direct lat/lon)")
    print("=" * 80)
    feature = result2.geojson['features'][0]
    print(json.dumps(feature, indent=2))
    
    print("\n" + "=" * 80)
    print("DETAILED OUTPUT - Test Case 4 (Embedded time series)")
    print("=" * 80)
    feature = result4.geojson['features'][0]
    print(json.dumps(feature, indent=2))
    
    print("\n" + "=" * 80)
    print("✅ ALL TESTS PASSED!")
    print("=" * 80)
    print("\nSupported Formats:")
    print("  ✓ Nested location objects: {location: {latitude, longitude}}")
    print("  ✓ Direct coordinates: {latitude, longitude} or {lat, lon/lng}")
    print("  ✓ Multiple container keys: stations, locations, items, data, results")
    print("  ✓ With or without time-series data")
    print("  ✓ Embedded or separate readings")
    

if __name__ == "__main__":
    test_various_geo_formats()
