"""Utility functions and classes for the civic app."""

from typing import Dict, Any, Union
import pandas as pd
from .models import QueryResponse
from .data_processor import GeoJSONProcessedResponse


class QueryBuilder:
    """Build API request payloads from extracted parameters."""
    
    def __init__(self, endpoint_schema: Dict):
        """
        Initialize the query builder.
        
        Args:
            endpoint_schema: Endpoint schema definition
        """
        self.schema = endpoint_schema
    
    def build_request_payload(self, query_params: Dict, body_params: Dict) -> Dict:
        """
        Build the final request payload for the trigger API.
        
        Args:
            query_params: Query parameters extracted from user query
            body_params: Body parameters extracted from user query
            
        Returns:
            Formatted payload for API trigger
        """
        
        payload = {}
        
        # Add query parameters if present
        if query_params:
            # Validate and format query params
            validated_query = self._validate_params(
                query_params, 
                location="query"
            )
            if validated_query:
                payload["queryParams"] = validated_query
        
        # Add body parameters if present
        if body_params:
            validated_body = self._validate_params(
                body_params, 
                location="body"
            )
            if validated_body:
                payload["bodyParams"] = validated_body
        
        return payload
    
    def _validate_params(self, params: Dict, location: str) -> Dict:
        """
        Validate parameters against schema.
        
        Args:
            params: Parameters to validate
            location: Parameter location ('query' or 'body')
            
        Returns:
            Validated and formatted parameters
            
        Raises:
            ValueError: If required parameter is missing
        """
        schema_params = [
            p for p in self.schema.get('parameters', [])
            if p.get('location') == location
        ]
        
        validated = {}
        
        for schema_param in schema_params:
            param_name = schema_param['name']
            
            if param_name in params:
                value = params[param_name]
                
                # Type conversion based on schema
                param_type = schema_param.get('type', 'string')
                
                if param_type == 'string':
                    validated[param_name] = str(value)
                elif param_type == 'integer':
                    validated[param_name] = int(value)
                elif param_type == 'boolean':
                    validated[param_name] = bool(value)
                else:
                    validated[param_name] = value
            elif schema_param.get('required', False):
                raise ValueError(f"Required parameter '{param_name}' is missing")
        
        return validated


class ResponseFormatter:
    """Format processed data into API response models."""
    
    def format_response(self, processed_data: Union[Dict[str, Any], Any], user_query: str) -> QueryResponse:
        """
        Format processed data into API response.
        
        Args:
            processed_data: Processed data from DataProcessor (dict or Pydantic model)
            user_query: Original user query
            
        Returns:
            QueryResponse with formatted data and visualization hints
        """
        
        # Handle both Pydantic model and dict
        if hasattr(processed_data, 'data_type'):
            data_type = processed_data.data_type
        else:
            data_type = processed_data.get('data_type', 'generic')
        
        if data_type == 'geojson':
            return self.format_map_response(processed_data)
        elif data_type == 'time_series':
            return self.format_time_series_response(processed_data, user_query)
        else:
            return self.format_generic_response(processed_data)
    
    def format_map_response(self, data: Union[Dict[str, Any], GeoJSONProcessedResponse]) -> QueryResponse:
        """
        Format GeoJSON data for map visualization.
        Supports both temporal and static GeoJSON properties.
        
        Args:
            data: Processed GeoJSON data (can be dict or GeoJSONProcessedResponse model)
            
        Returns:
            QueryResponse with map visualization hints
        """
        
        # Handle both dict and Pydantic model
        if isinstance(data, GeoJSONProcessedResponse):
            # geojson is a FeatureCollection Pydantic model
            geojson_model = data.geojson
            # Extract metadata from GeoJSON
            features = geojson_model.features if hasattr(geojson_model, 'features') else []
            features_count = len(features)
            
            # Calculate bounds from features
            bounds = None
            if features:
                lats = []
                lons = []
                for feature in features:
                    # Feature is also a Pydantic model
                    geom = feature.geometry if hasattr(feature, 'geometry') else None
                    if geom and geom.type == 'Point':
                        coords = geom.coordinates
                        if coords and len(coords) >= 2:
                            lons.append(coords[0])
                            lats.append(coords[1])
                if lats and lons:
                    bounds = [[min(lats), min(lons)], [max(lats), max(lons)]]
            
            # Check for temporal properties
            property_type = 'static'
            temporal_attributes = None
            if features:
                props = features[0].properties
                if props is not None and props.temporal:
                    property_type = 'temporal'
                    temporal_attributes = props.temporal
            
            # Convert FeatureCollection model to dict for response
            geojson_data = geojson_model.model_dump() if hasattr(geojson_model, 'model_dump') else geojson_model
        else:
            # Legacy dict format
            geojson_data = data['geojson']
            bounds = data.get('bounds')
            property_type = data.get('property_type', 'static')
            features_count = data['features_count']
            temporal_attributes = data.get('temporal')
        
        
        # Calculate map center
        if bounds:
            center_lat = (bounds[0][0] + bounds[1][0]) / 2
            center_lon = (bounds[0][1] + bounds[1][1]) / 2
        else:
            # Default to Singapore
            center_lat, center_lon = 1.3521, 103.8198
        
        response_data = {
            "geojson": geojson_data,
            "bounds": bounds,
            "center": {"lat": center_lat, "lon": center_lon},
            "features_count": features_count,
            "property_type": property_type
        }
        
        # Add temporal metadata if present
        if property_type == 'temporal' and temporal_attributes:
            # Convert Pydantic models to dicts if needed
            if isinstance(temporal_attributes, dict):
                response_data['temporal'] = {
                    k: v.model_dump() if hasattr(v, 'model_dump') else v 
                    for k, v in temporal_attributes.items()
                }
            else:
                response_data['temporal'] = temporal_attributes.model_dump() if hasattr(temporal_attributes, 'model_dump') else temporal_attributes
        
        # Determine visualization type based on property type
        visualization_type = "map_temporal" if property_type == 'temporal' else "map"
        
        return QueryResponse(
            status="success",
            data=response_data,
            visualization_type=visualization_type
        )
    
    def format_time_series_response(self, data: Dict[str, Any], query: str) -> QueryResponse:
        """
        Format time-series data for chart visualization.
        
        Args:
            data: Processed time-series data
            query: Original user query
            
        Returns:
            QueryResponse with time-series visualization hints
        """
        
        df = data['dataframe']
        stats = data['summary_stats']
        
        # Convert DataFrame to JSON-serializable format
        records = df.to_dict('records')
        
        # Convert timestamp columns to string format
        for record in records:
            for key, value in record.items():
                if pd.api.types.is_datetime64_any_dtype(type(value)):
                    record[key] = str(value)
        
        # Find relevant columns
        time_col = next((col for col in df.columns if 'time' in col.lower() or 'date' in col.lower()), None)
        value_col = next((col for col in df.columns if 'value' in col.lower() or 'temp' in col.lower()), None)
        station_col = next((col for col in df.columns if 'station' in col.lower()), None)
        
        # Prepare chart configurations
        chart_configs = []
        
        if time_col and value_col:
            chart_configs.append({
                "type": "line",
                "title": "Temperature Over Time",
                "x_axis": time_col,
                "y_axis": value_col,
                "x_label": "Time",
                "y_label": "Temperature (°C)"
            })
        
        if station_col and value_col:
            # Calculate aggregated data
            aggregated = df.groupby(station_col)[value_col].mean().to_dict()
            chart_configs.append({
                "type": "bar",
                "title": "Average Temperature by Station",
                "data": aggregated,
                "x_label": "Station",
                "y_label": "Average Temperature (°C)"
            })
        
        return QueryResponse(
            status="success",
            data={
                "records": records,
                "summary_stats": stats,
                "chart_configs": chart_configs,
                "columns": list(df.columns)
            },
            visualization_type="time_series"
        )
    
    def format_generic_response(self, data: Dict[str, Any]) -> QueryResponse:
        """
        Format generic data response.
        
        Args:
            data: Processed generic data
            
        Returns:
            QueryResponse with generic data
        """
        return QueryResponse(
            status="success",
            data=data['data'],
            visualization_type="generic"
        )
