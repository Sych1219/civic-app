"""
Example: Using the GeoJSON Pydantic Models

This demonstrates how to work with the typed GeoJSON response models.
"""

from app.data_processor import (
    DataProcessor, 
    GeoJSONProcessedResponse, 
    TemporalAttribute, 
    GeoJSONMetadata
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
    print(f"✅ Property Type: {result.property_type}")
    print(f"✅ Features Count: {result.features_count}")
    print(f"✅ Bounds: {result.bounds}")
    
    # Type-safe access to metadata
    print(f"\n📋 Metadata:")
    print(f"   Timestamp: {result.metadata.timestamp}")
    print(f"   Endpoint ID: {result.metadata.endpoint_id}")
    
    # Access temporal attributes (typed!)
    if result.temporal_attributes:
        print(f"\n🕐 Temporal Attributes:")
        for attr_name, attr_info in result.temporal_attributes.items():
            # attr_info is a TemporalAttribute model
            print(f"   - {attr_name}:")
            print(f"     Unit: {attr_info.unit}")
            print(f"     Time Range: {attr_info.time_range}")
            print(f"     Data Points: {attr_info.data_points}")
    
    # Access the actual GeoJSON data (still a dict)
    print(f"\n🗺️  GeoJSON Type: {result.geojson['type']}")
    print(f"   First Feature ID: {result.geojson['features'][0]['properties']['static']['stationId']}")
    
    # Convert to dictionary if needed (for JSON serialization)
    result_dict = result.model_dump()
    print(f"\n📦 Can convert to dict: {type(result_dict).__name__}")
    print(f"   Keys: {list(result_dict.keys())}")
    
    # Model validation - Pydantic will validate types automatically
    print("\n✅ Type validation:")
    print(f"   data_type must be 'geojson': {result.data_type == 'geojson'}")
    print(f"   property_type must be 'temporal' or 'static': {result.property_type in ['temporal', 'static']}")
    print(f"   features_count is int: {isinstance(result.features_count, int)}")
    
    print("\n" + "=" * 80)
    print("✅ All model access patterns demonstrated!")
    print("=" * 80)


def example_direct_model_creation():
    """Show how to create models directly."""
    
    print("\n" + "=" * 80)
    print("DIRECT MODEL CREATION")
    print("=" * 80)
    
    # Create temporal attribute
    temp_attr = TemporalAttribute(
        unit="°C",
        time_range=["2024-01-01T10:00:00Z", "2024-01-01T12:00:00Z"],
        data_points=3
    )
    
    print(f"\n✅ Created TemporalAttribute:")
    print(f"   Unit: {temp_attr.unit}")
    print(f"   Data Points: {temp_attr.data_points}")
    
    # Create metadata
    metadata = GeoJSONMetadata(
        timestamp="2024-01-01T12:00:00Z",
        endpoint_id="test-endpoint"
    )
    
    print(f"\n✅ Created GeoJSONMetadata:")
    print(f"   Timestamp: {metadata.timestamp}")
    print(f"   Endpoint: {metadata.endpoint_id}")
    
    # Create full response (with minimal GeoJSON)
    response = GeoJSONProcessedResponse(
        geojson={
            "type": "FeatureCollection",
            "features": []
        },
        features_count=0,
        bounds=None,
        property_type="static",
        temporal_attributes=None,
        metadata=metadata
    )
    
    print(f"\n✅ Created GeoJSONProcessedResponse:")
    print(f"   Type: {response.data_type}")
    print(f"   Property Type: {response.property_type}")
    print(f"   Features: {response.features_count}")


if __name__ == "__main__":
    example_usage()
    example_direct_model_creation()
