"""Utility functions and classes for the civic app."""

from typing import Dict, Any
import pandas as pd
from models import QueryResponse


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
    
    def format_response(self, processed_data: Dict[str, Any], user_query: str) -> QueryResponse:
        """
        Format processed data into API response.
        
        Args:
            processed_data: Processed data from DataProcessor
            user_query: Original user query
            
        Returns:
            QueryResponse with formatted data and visualization hints
        """
        
        data_type = processed_data['data_type']
        
        if data_type == 'geojson':
            return self.format_map_response(processed_data)
        elif data_type == 'time_series':
            return self.format_time_series_response(processed_data, user_query)
        else:
            return self.format_generic_response(processed_data)
    
    def format_map_response(self, data: Dict[str, Any]) -> QueryResponse:
        """
        Format GeoJSON data for map visualization.
        
        Args:
            data: Processed GeoJSON data
            
        Returns:
            QueryResponse with map visualization hints
        """
        
        geojson_data = data['geojson']
        bounds = data.get('bounds')
        
        # Calculate map center
        if bounds:
            center_lat = (bounds[0][0] + bounds[1][0]) / 2
            center_lon = (bounds[0][1] + bounds[1][1]) / 2
        else:
            # Default to Singapore
            center_lat, center_lon = 1.3521, 103.8198
        
        return QueryResponse(
            status="success",
            data={
                "geojson": geojson_data,
                "bounds": bounds,
                "center": {"lat": center_lat, "lon": center_lon},
                "features_count": data['features_count']
            },
            visualization_type="map",
            metadata=data['metadata']
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
            visualization_type="time_series",
            metadata=data['metadata']
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
            visualization_type="generic",
            metadata=data['metadata']
        )
