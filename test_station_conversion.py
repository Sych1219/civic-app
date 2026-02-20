"""Test script to verify station-based time-series to GeoJSON conversion."""

import json
from app.data_processor import DataProcessor


def test_station_to_geojson_conversion():
    """Test conversion of station-based time-series data to temporal GeoJSON."""
    
    # Sample input data (like your example)
    sample_data = {
        "responseBody": {
            "stations": [
                {
                    "id": "S109",
                    "deviceId": "S109",
                    "name": "Ang Mo Kio Avenue 5",
                    "location": {
                        "latitude": 1.3764,
                        "longitude": 103.8492
                    }
                },
                {
                    "id": "S106",
                    "deviceId": "S106",
                    "name": "Pulau Ubin",
                    "location": {
                        "latitude": 1.4168,
                        "longitude": 103.9673
                    }
                }
            ],
            "readings": [
                {
                    "timestamp": "2026-02-20T14:16:00+08:00",
                    "data": [
                        {"stationId": "S109", "value": 28.3},
                        {"stationId": "S106", "value": 28.6}
                    ]
                },
                {
                    "timestamp": "2026-02-20T14:15:00+08:00",
                    "data": [
                        {"stationId": "S109", "value": 28.3},
                        {"stationId": "S106", "value": 28.7}
                    ]
                },
                {
                    "timestamp": "2026-02-20T14:14:00+08:00",
                    "data": [
                        {"stationId": "S109", "value": 28.3},
                        {"stationId": "S106", "value": 28.7}
                    ]
                },
                {
                    "timestamp": "2026-02-20T14:13:00+08:00",
                    "data": [
                        {"stationId": "S109", "value": 28.4},
                        {"stationId": "S106", "value": 28.6}
                    ]
                }
            ],
            "readingType": "DBT 1M F",
            "readingUnit": "deg C"
        },
        "invokedAt": "2026-02-20T06:23:52.78807Z",
        "endpointId": "3a5f2831-815b-4a0a-bbc6-38e54598c8d9"
    }
    
    # Initialize processor
    processor = DataProcessor()
    
    # Process the data
    result = processor.process_response(sample_data)
    
    # Print results
    print("=" * 80)
    print("CONVERSION TEST RESULTS")
    print("=" * 80)
    print(f"\nData Type: {result['data_type']}")
    print(f"Property Type: {result['property_type']}")
    print(f"Features Count: {result['features_count']}")
    print(f"Bounds: {result['bounds']}")
    
    if 'temporal_attributes' in result:
        print("\nTemporal Attributes:")
        for attr_name, attr_info in result['temporal_attributes'].items():
            print(f"  - {attr_name}:")
            print(f"    Unit: {attr_info['unit']}")
            print(f"    Time Range: {attr_info['time_range']}")
            print(f"    Data Points: {attr_info['data_points']}")
    
    print("\n" + "=" * 80)
    print("GENERATED GEOJSON (First Feature)")
    print("=" * 80)
    
    if result['geojson']['features']:
        first_feature = result['geojson']['features'][0]
        print(json.dumps(first_feature, indent=2))
    
    print("\n" + "=" * 80)
    print("VERIFICATION")
    print("=" * 80)
    
    # Verify structure
    assert result['data_type'] == 'geojson', "Should be geojson type"
    assert result['property_type'] == 'temporal', "Should be temporal type"
    assert result['features_count'] == 2, "Should have 2 features (2 stations)"
    assert result['bounds'] is not None, "Should have bounds"
    
    # Verify GeoJSON structure
    geojson = result['geojson']
    assert geojson['type'] == 'FeatureCollection', "Should be FeatureCollection"
    assert len(geojson['features']) == 2, "Should have 2 features"
    
    # Verify first feature
    feature = geojson['features'][0]
    assert feature['type'] == 'Feature', "Should be Feature type"
    assert feature['geometry']['type'] == 'Point', "Should be Point geometry"
    assert len(feature['geometry']['coordinates']) == 2, "Should have [lon, lat]"
    
    # Verify properties
    props = feature['properties']
    assert 'static' in props, "Should have static properties"
    assert 'temporal' in props, "Should have temporal properties"
    
    # Verify static properties
    assert 'id' in props['static'], "Should have station id"
    assert 'name' in props['static'], "Should have station name"
    
    # Verify temporal properties
    temporal = props['temporal']
    assert len(temporal) > 0, "Should have at least one temporal attribute"
    
    first_attr = list(temporal.values())[0]
    assert 'unit' in first_attr, "Should have unit"
    assert 'series' in first_attr, "Should have series"
    assert len(first_attr['series']) == 4, "Should have 4 readings"
    
    # Verify series entries
    series_entry = first_attr['series'][0]
    assert 'time' in series_entry, "Should have time"
    assert 'value' in series_entry, "Should have value"
    
    print("✅ All verifications passed!")
    print("\n✅ Conversion successful! Station-based data transformed to temporal GeoJSON.")
    

if __name__ == "__main__":
    test_station_to_geojson_conversion()
