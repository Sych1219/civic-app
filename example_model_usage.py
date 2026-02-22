"""
Example: Using the GeoJSON Pydantic Models

This demonstrates how to work with the typed GeoJSON response models.
"""

from app.data_processor import (
    DataProcessor, 
    GeoJSONProcessedResponse
)


def example_usage():
    """Show how to use the GeoJSON models."""
    
    # Initialize processor
    processor = DataProcessor()
    
    # Sample data with nested structure and time-series
    sample_data = {
        "responseBody": {
            "response": {  # Nested one level deep
                "stations": [
                    {
                        "stationId": "S001",
                        "name": "Downtown Station",
                        "location": {
                            "latitude": 37.7749,
                            "longitude": -122.4194
                        }
                    }
                ],
                "readings": [  # Flat readings format
                    {
                        "stationId": "S001",
                        "timestamp": "2024-01-01T10:00:00Z",
                        "value": 15.5
                    },
                    {
                        "stationId": "S001",
                        "timestamp": "2024-01-01T11:00:00Z",
                        "value": 16.2
                    }
                ],
                "readingType": "temperature",
                "readingUnit": "°C"
            }
        },
        "invokedAt": "2024-01-01T12:00:00Z",
        "endpointId": "weather-api"
    }
    
    # Process the data - returns GeoJSONProcessedResponse model
    result: GeoJSONProcessedResponse = processor.process_response(sample_data)
    
    print("=" * 80)
    print("PYDANTIC MODEL USAGE EXAMPLE")
    print("=" * 80)
    
    # Access properties directly (no dictionary keys!)
    print(f"\n✅ Data Type: {result.data_type}")
    print(f"✅ Features Count: {len(result.geojson.features)}")
    
    # Access the actual GeoJSON data
    print(f"\n🗺️  GeoJSON Type: {result.geojson.type}")
    if result.geojson.features:
        first_feature = result.geojson.features[0]
        if first_feature.properties and first_feature.properties.static:
            print(f"   First Feature ID: {first_feature.properties.static.get('stationId')}")
    
    # Convert to dictionary if needed (for JSON serialization)
    result_dict = result.model_dump()
    print(f"\n📦 Can convert to dict: {type(result_dict).__name__}")
    print(f"   Keys: {list(result_dict.keys())}")
    
    # Model validation - Pydantic will validate types automatically
    print("\n✅ Type validation:")
    print(f"   data_type must be 'geojson': {result.data_type == 'geojson'}")
    print(f"   geojson is FeatureCollection: {result.geojson.type == 'FeatureCollection'}")
    
    print("\n" + "=" * 80)
    print("✅ All model access patterns demonstrated!")
    print("=" * 80)


def example_direct_model_creation():
    """Show how to create models directly."""
    
    print("\n" + "=" * 80)
    print("DIRECT MODEL CREATION")
    print("=" * 80)
    
    # Create full response (with minimal GeoJSON)
    response = GeoJSONProcessedResponse(
        geojson={
            "type": "FeatureCollection",
            "features": []
        }
    )
    
    print(f"\n✅ Created GeoJSONProcessedResponse:")
    print(f"   Type: {response.data_type}")
    print(f"   Features: {len(response.geojson.get('features', []))}")


if __name__ == "__main__":
    example_usage()
    example_direct_model_creation()
