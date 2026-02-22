"""Data processor for transforming API responses into visualization-ready formats."""

import pandas as pd
from typing import Dict, Any, List, Optional, Literal
import json
from pydantic import BaseModel, Field


class TemporalAttribute(BaseModel):
    """Metadata for a temporal attribute in GeoJSON properties."""
    unit: str = Field(default="", description="Unit of measurement")
    time_range: Optional[List[str]] = Field(default=None, description="[min_time, max_time]")
    data_points: int = Field(description="Number of data points in the series")


class GeoJSONMetadata(BaseModel):
    """Metadata for the GeoJSON response."""
    timestamp: Optional[str] = Field(default=None, description="When the API was invoked")
    endpoint_id: Optional[str] = Field(default=None, description="ID of the endpoint")


class GeoJSONProcessedResponse(BaseModel):
    """Processed GeoJSON response with visualization metadata."""
    data_type: Literal['geojson'] = Field(default='geojson', description="Data type identifier")
    geojson: Dict[str, Any] = Field(description="GeoJSON FeatureCollection")
    features_count: int = Field(description="Number of features in the collection")
    bounds: Optional[List[List[float]]] = Field(default=None, description="[[min_lat, min_lon], [max_lat, max_lon]]")
    property_type: Literal['temporal', 'static'] = Field(description="Type of properties in features")
    temporal_attributes: Optional[Dict[str, TemporalAttribute]] = Field(
        default=None, 
        description="Metadata for temporal attributes (only present for temporal property_type)"
    )
    metadata: GeoJSONMetadata = Field(description="Response metadata")


class DataProcessor:
    """Process API responses into visualization-ready formats."""
    
    def process_response(self, api_response: Dict[str, Any]) -> Dict[str, Any]:
        """
        Process API response based on data type.
        
        Args:
            api_response: Raw API response from trigger endpoint
            
        Returns:
            Processed data with metadata for visualization
        """
        response_body = api_response.get('responseBody', {})
        endpoint_id = api_response.get('endpointId', '')
        
        # Determine processing strategy based on endpoint or data structure
        if self._is_geojson(response_body):
            return self.process_geojson(response_body, api_response)
        elif self._has_geo_location_data(response_body):
            # Convert any geo-location data to GeoJSON
            geojson_data = self._convert_to_geojson(response_body)
            return self.process_geojson(geojson_data, api_response)
        elif 'readings' in response_body or 'data' in response_body:
            return self.process_time_series(response_body, api_response)
        else:
            return self.process_generic(response_body, api_response)
    
    def _is_geojson(self, data: Dict) -> bool:
        """Check if data is GeoJSON format."""
        return data.get('type') in ['FeatureCollection', 'Feature']
    
    def _has_geo_location_data(self, data: Dict) -> bool:
        """
        Check if data contains geographic location information that can be converted to GeoJSON.
        
        Detects various patterns:
        - 'stations' with location objects
        - 'locations' array with lat/lon
        - 'items' or 'data' arrays with embedded location info
        - Any nested structure with latitude/longitude or lat/lng pairs
        
        Args:
            data: Response data to check
            
        Returns:
            True if data contains geographic location information
        """
        # Check at current level
        location_keys = ['stations', 'locations', 'items', 'data', 'results', 'features']
        
        for key in location_keys:
            if key in data:
                items = data[key]
                if isinstance(items, list) and len(items) > 0:
                    if self._has_location_fields(items[0]):
                        return True
        
        # Check if data itself is an array with locations
        if isinstance(data, list) and len(data) > 0:
            if self._has_location_fields(data[0]):
                return True
        
        # Recursively check nested objects (one level deep to avoid performance issues)
        for key, value in data.items():
            if isinstance(value, dict):
                # Check if this nested object has location arrays
                for nested_key in location_keys:
                    if nested_key in value:
                        nested_items = value[nested_key]
                        if isinstance(nested_items, list) and len(nested_items) > 0:
                            if self._has_location_fields(nested_items[0]):
                                return True
        
        return False
    
    def _has_location_fields(self, item: Any) -> bool:
        """
        Check if an item contains location fields.
        
        Supports various formats:
        - {"location": {"latitude": ..., "longitude": ...}}
        - {"latitude": ..., "longitude": ...}
        - {"lat": ..., "lon": ...} or {"lat": ..., "lng": ...}
        - {"coordinates": [lon, lat]}
        
        Args:
            item: Item to check
            
        Returns:
            True if item has location fields
        """
        if not isinstance(item, dict):
            return False
        
        # Check nested location object
        if 'location' in item:
            location = item['location']
            if isinstance(location, dict):
                if ('latitude' in location and 'longitude' in location):
                    return True
                if ('lat' in location and ('lon' in location or 'lng' in location)):
                    return True
        
        # Check direct latitude/longitude
        if ('latitude' in item and 'longitude' in item):
            return True
        
        # Check lat/lon or lat/lng
        if ('lat' in item and ('lon' in item or 'lng' in item)):
            return True
        
        # Check coordinates array
        if 'coordinates' in item:
            coords = item['coordinates']
            if isinstance(coords, list) and len(coords) >= 2:
                return True
        
        return False
    
    def _convert_to_geojson(self, data: Dict) -> Dict:
        """
        Convert any data with geographic location information to GeoJSON format.
        
        Supports multiple input patterns:
        
        Pattern 1 - Station-based with time-series:
        {
          "stations": [{"id": "S109", "name": "...", "location": {"latitude": 1.3764, "longitude": 103.8492}}],
          "readings": [{"timestamp": "...", "data": [{"stationId": "S109", "value": 28.3}]}],
          "readingType": "DBT 1M F",
          "readingUnit": "deg C"
        }
        
        Pattern 2 - Direct location array:
        {
          "locations": [{"name": "Place A", "lat": 1.3764, "lon": 103.8492, "value": 28.3}]
        }
        
        Pattern 3 - Items with embedded location:
        {
          "items": [{"name": "POI", "latitude": 1.3764, "longitude": 103.8492, "properties": {...}}]
        }
        
        Returns GeoJSON with MultiPoint geometry containing all coordinates:
        {
          "type": "FeatureCollection",
          "features": [
            {
              "type": "Feature",
              "geometry": {
                "type": "MultiPoint",
                "coordinates": [[103.8492, 1.3764], [103.9673, 1.4168], ...]
              },
              "properties": {
                "static": {...},
                "temporal": {...}
              }
            }
          ]
        }
        
        Args:
            data: Station-based time-series data
            
        Returns:
            GeoJSON FeatureCollection with MultiPoint geometry
        """
        # Detect which pattern we're dealing with
        geo_items = []
        readings = data.get('readings', [])
        reading_type = data.get('readingType', 'value')
        reading_unit = data.get('readingUnit', '')
        
        # Try different keys for geo-location data at top level
        location_keys = ['stations', 'locations', 'items', 'data', 'results', 'features']
        for key in location_keys:
            if key in data:
                items = data[key]
                if isinstance(items, list) and len(items) > 0:
                    if self._has_location_fields(items[0]):
                        geo_items = items
                        break
        
        # If not found at top level, check nested objects (one level deep)
        if not geo_items:
            for key, value in data.items():
                if isinstance(value, dict):
                    for nested_key in location_keys:
                        if nested_key in value:
                            items = value[nested_key]
                            if isinstance(items, list) and len(items) > 0:
                                if self._has_location_fields(items[0]):
                                    geo_items = items
                                    # Also check for nested readings
                                    if 'readings' in value:
                                        readings = value.get('readings', readings)
                                    if 'readingType' in value:
                                        reading_type = value.get('readingType', reading_type)
                                    if 'readingUnit' in value:
                                        reading_unit = value.get('readingUnit', reading_unit)
                                    break
                    if geo_items:
                        break
        
        # If data itself is an array with locations
        if not geo_items and isinstance(data, list) and len(data) > 0:
            if self._has_location_fields(data[0]):
                geo_items = data
        
        # Collect all coordinates and aggregate properties
        all_coordinates = []
        aggregated_static = {}
        aggregated_temporal = {}
        
        # Create a mapping of item ID -> item metadata
        item_map = {}
        for item in geo_items:
            # Try to find an ID field
            item_id = item.get('id', item.get('stationId', item.get('deviceId', 
                      item.get('name', f"item_{len(item_map)}"))))
            item_map[item_id] = item
        
        # Group readings by item ID (if readings exist)
        item_readings = {}
        if readings:
            for reading_entry in readings:
                # Format 1: Nested structure with timestamp at top level
                # {"timestamp": "...", "data": [{"stationId": "S001", "value": 15.5}]}
                if 'data' in reading_entry:
                    timestamp = reading_entry.get('timestamp', '')
                    data_points = reading_entry.get('data', [])
                    
                    for point in data_points:
                        # Try different ID field names
                        item_id = point.get('stationId', point.get('id', point.get('itemId', '')))
                        value = point.get('value')
                        
                        if item_id not in item_readings:
                            item_readings[item_id] = []
                        
                        item_readings[item_id].append({
                            'time': timestamp,
                            'value': value
                        })
                
                # Format 2: Flat structure with timestamp and ID at same level
                # {"stationId": "S001", "timestamp": "...", "value": 15.5}
                elif 'timestamp' in reading_entry:
                    timestamp = reading_entry.get('timestamp', '')
                    item_id = reading_entry.get('stationId', reading_entry.get('id', reading_entry.get('itemId', '')))
                    value = reading_entry.get('value')
                    
                    if item_id and value is not None:
                        if item_id not in item_readings:
                            item_readings[item_id] = []
                        
                        item_readings[item_id].append({
                            'time': timestamp,
                            'value': value
                        })
        
        # Process all items to collect coordinates and aggregate data
        for item_id, item_info in item_map.items():
            # Extract coordinates from various formats
            lat, lon = self._extract_coordinates(item_info)
            
            if lat is None or lon is None:
                continue
            
            # Add coordinates to the list
            all_coordinates.append([lon, lat])  # GeoJSON uses [lon, lat]
            
            # Aggregate static properties
            excluded_keys = ['location', 'latitude', 'longitude', 'lat', 'lon', 'lng', 
                           'coordinates', 'geometry', 'readings', 'data']
            for k, v in item_info.items():
                if k not in excluded_keys and not isinstance(v, (dict, list)):
                    if k not in aggregated_static:
                        aggregated_static[k] = []
                    aggregated_static[k].append(v)
            
            # Aggregate temporal data
            if item_id in item_readings:
                # Sort readings by time (descending - most recent first)
                series = sorted(
                    item_readings[item_id],
                    key=lambda x: x['time'],
                    reverse=True
                )
                
                # Use reading_type as attribute name (clean it up)
                attr_name = reading_type.lower().replace(' ', '_')
                if not attr_name:
                    attr_name = 'value'
                
                if attr_name not in aggregated_temporal:
                    aggregated_temporal[attr_name] = {
                        'unit': reading_unit,
                        'series': []
                    }
                aggregated_temporal[attr_name]['series'].extend(series)
            
            # Check for embedded time-series data
            elif 'timeSeries' in item_info or 'series' in item_info:
                series_data = item_info.get('timeSeries', item_info.get('series', []))
                if series_data and isinstance(series_data, list):
                    attr_name = item_info.get('measurementType', 'value').lower().replace(' ', '_')
                    if attr_name not in aggregated_temporal:
                        aggregated_temporal[attr_name] = {
                            'unit': item_info.get('unit', ''),
                            'series': []
                        }
                    aggregated_temporal[attr_name]['series'].extend(series_data)
        
        # Create single feature with MultiPoint geometry
        feature = {
            'type': 'Feature',
            'geometry': {
                'type': 'MultiPoint',
                'coordinates': all_coordinates
            },
            'properties': {
                'static': aggregated_static
            }
        }
        
        # Only add temporal if we have time-series data
        if aggregated_temporal:
            feature['properties']['temporal'] = aggregated_temporal
        
        return {
            'type': 'FeatureCollection',
            'features': [feature]
        }
    
    def _extract_coordinates(self, item: Dict) -> tuple:
        """
        Extract latitude and longitude from various data formats.
        
        Args:
            item: Item containing location data
            
        Returns:
            Tuple of (latitude, longitude) or (None, None)
        """
        # Check nested location object
        if 'location' in item:
            location = item['location']
            if isinstance(location, dict):
                lat = location.get('latitude', location.get('lat'))
                lon = location.get('longitude', location.get('lon', location.get('lng')))
                if lat is not None and lon is not None:
                    return lat, lon
        
        # Check direct latitude/longitude
        lat = item.get('latitude', item.get('lat'))
        lon = item.get('longitude', item.get('lon', item.get('lng')))
        if lat is not None and lon is not None:
            return lat, lon
        
        # Check coordinates array [lon, lat] (GeoJSON format)
        if 'coordinates' in item:
            coords = item['coordinates']
            if isinstance(coords, list) and len(coords) >= 2:
                return coords[1], coords[0]  # GeoJSON is [lon, lat], we return [lat, lon]
        
        return None, None
    
    def process_geojson(
        self, 
        geojson_data: Dict, 
        full_response: Dict
    ) -> GeoJSONProcessedResponse:
        """
        Process GeoJSON data for map visualization.
        Supports both temporal (time-series) and static properties.
        
        Args:
            geojson_data: GeoJSON formatted data
            full_response: Full API response with metadata
            
        Returns:
            GeoJSONProcessedResponse with structure: {
                'data_type': 'geojson',
                'geojson': <processed GeoJSON>,
                'features_count': int,
                'bounds': [[lat, lon], [lat, lon]],
                'property_type': 'temporal' or 'static',
                'temporal_attributes': {...},  # Only for temporal
                'metadata': {...}
            }
        """
        features = geojson_data.get('features', [])
        
        # Extract coordinates for bounds calculation
        coords = []
        for feature in features:
            if feature.get('geometry', {}).get('type') == 'Point':
                coords.append(feature['geometry']['coordinates'])
        
        bounds = self._calculate_bounds(coords) if coords else None
        
        # Detect property type (temporal vs. static)
        property_type = 'static'
        temporal_attributes = None
        
        if features:
            first_feature = features[0]
            properties = first_feature.get('properties', {})
            
            # Check if properties contain 'temporal' key
            if 'temporal' in properties:
                property_type = 'temporal'
                temporal_attributes = self._extract_temporal_metadata(properties['temporal'])
        
        return GeoJSONProcessedResponse(
            data_type='geojson',
            geojson=geojson_data,
            features_count=len(features),
            bounds=bounds,
            property_type=property_type,
            temporal_attributes=temporal_attributes,
            metadata=GeoJSONMetadata(
                timestamp=full_response.get('invokedAt'),
                endpoint_id=full_response.get('endpointId')
            )
        )
    
    def _extract_temporal_metadata(self, temporal_data: Dict) -> Dict[str, TemporalAttribute]:
        """
        Extract metadata from temporal properties.
        
        Args:
            temporal_data: The 'temporal' object from GeoJSON properties
            
        Returns:
            Dictionary mapping attribute names to TemporalAttribute models
        """
        metadata = {}
        
        for attr_name, attr_data in temporal_data.items():
            series = attr_data.get('series', [])
            
            if series:
                time_values = [entry['time'] for entry in series if 'time' in entry]
                
                metadata[attr_name] = TemporalAttribute(
                    unit=attr_data.get('unit', ''),
                    time_range=[min(time_values), max(time_values)] if time_values else None,
                    data_points=len(series)
                )
        
        return metadata
    
    def process_time_series(
        self, 
        response_data: Dict, 
        full_response: Dict
    ) -> Dict[str, Any]:
        """
        Process time-series data (e.g., temperature readings).
        
        Args:
            response_data: Response body containing readings/data
            full_response: Full API response with metadata
            
        Returns:
            {
                'data_type': 'time_series',
                'dataframe': pd.DataFrame,
                'summary_stats': {...},
                'metadata': {...}
            }
        """
        # Extract readings/data
        readings = response_data.get('readings', response_data.get('data', []))
        
        if not readings:
            return self.process_generic(response_data, full_response)
        
        # Convert to DataFrame
        df = pd.json_normalize(readings)
        
        # Process timestamps if present
        timestamp_cols = [col for col in df.columns if 'time' in col.lower() or 'date' in col.lower()]
        for col in timestamp_cols:
            try:
                df[col] = pd.to_datetime(df[col])
            except:
                pass
        
        # Calculate summary statistics for numeric columns
        numeric_cols = df.select_dtypes(include=['number']).columns
        summary_stats = {}
        
        for col in numeric_cols:
            if len(df[col].dropna()) > 0:
                summary_stats[col] = {
                    'mean': float(df[col].mean()),
                    'min': float(df[col].min()),
                    'max': float(df[col].max()),
                    'std': float(df[col].std()) if len(df[col]) > 1 else 0.0
                }
        
        return {
            'data_type': 'time_series',
            'dataframe': df,
            'summary_stats': summary_stats,
            'metadata': {
                'timestamp': full_response.get('invokedAt'),
                'endpoint_id': full_response.get('endpointId'),
                'record_count': len(df)
            }
        }
    
    def process_generic(
        self, 
        response_data: Dict, 
        full_response: Dict
    ) -> Dict[str, Any]:
        """
        Process generic/unknown data structure.
        
        Args:
            response_data: Response body
            full_response: Full API response with metadata
            
        Returns:
            {
                'data_type': 'generic',
                'data': response_data,
                'metadata': {...}
            }
        """
        return {
            'data_type': 'generic',
            'data': response_data,
            'metadata': {
                'timestamp': full_response.get('invokedAt'),
                'endpoint_id': full_response.get('endpointId')
            }
        }
    
    def _calculate_bounds(self, coords: List[List[float]]) -> Optional[List[List[float]]]:
        """
        Calculate bounding box for coordinates [lon, lat].
        
        Args:
            coords: List of [longitude, latitude] pairs
            
        Returns:
            [[min_lat, min_lon], [max_lat, max_lon]] or None
        """
        if not coords:
            return None
        
        lons = [c[0] for c in coords]
        lats = [c[1] for c in coords]
        
        return [
            [min(lats), min(lons)],  # Southwest
            [max(lats), max(lons)]   # Northeast
        ]
