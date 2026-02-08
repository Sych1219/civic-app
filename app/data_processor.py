"""Data processor for transforming API responses into visualization-ready formats."""

import pandas as pd
from typing import Dict, Any, List, Optional
import json


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
        elif 'readings' in response_body or 'data' in response_body:
            return self.process_time_series(response_body, api_response)
        else:
            return self.process_generic(response_body, api_response)
    
    def _is_geojson(self, data: Dict) -> bool:
        """Check if data is GeoJSON format."""
        return data.get('type') in ['FeatureCollection', 'Feature']
    
    def process_geojson(
        self, 
        geojson_data: Dict, 
        full_response: Dict
    ) -> Dict[str, Any]:
        """
        Process GeoJSON data for map visualization.
        
        Args:
            geojson_data: GeoJSON formatted data
            full_response: Full API response with metadata
            
        Returns:
            {
                'data_type': 'geojson',
                'geojson': <processed GeoJSON>,
                'features_count': int,
                'bounds': [[lat, lon], [lat, lon]],
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
        
        return {
            'data_type': 'geojson',
            'geojson': geojson_data,
            'features_count': len(features),
            'bounds': bounds,
            'metadata': {
                'timestamp': full_response.get('invokedAt'),
                'endpoint_id': full_response.get('endpointId')
            }
        }
    
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
