"""Streamlit visualizer for rendering data visualizations."""

import streamlit as st
import plotly.express as px
import plotly.graph_objects as go
import folium
from streamlit_folium import st_folium
import pandas as pd
from typing import Dict, Any


class StreamlitVisualizer:
    """Render visualizations in Streamlit."""
    
    def render(self, processed_data: Dict[str, Any], user_query: str):
        """
        Render appropriate visualization based on data type.
        
        Args:
            processed_data: Processed data from DataProcessor
            user_query: Original user query for context
        """
        
        data_type = processed_data['data_type']
        
        if data_type == 'geojson':
            self.render_map(processed_data)
        elif data_type == 'time_series':
            self.render_time_series(processed_data, user_query)
        else:
            self.render_generic(processed_data)
    
    def render_map(self, data: Dict[str, Any]):
        """
        Render GeoJSON data on an interactive map.
        
        Args:
            data: Processed GeoJSON data
        """
        st.subheader("📍 Map View")
        
        # Create Folium map
        geojson_data = data['geojson']
        bounds = data.get('bounds')
        
        # Initialize map
        if bounds:
            center_lat = (bounds[0][0] + bounds[1][0]) / 2
            center_lon = (bounds[0][1] + bounds[1][1]) / 2
            m = folium.Map(location=[center_lat, center_lon], zoom_start=12)
        else:
            # Default to Singapore
            m = folium.Map(location=[1.3521, 103.8198], zoom_start=11)
        
        # Add GeoJSON layer
        folium.GeoJson(
            geojson_data,
            name='Data Layer',
            tooltip=folium.GeoJsonTooltip(
                fields=['name', 'value'] if 'features' in geojson_data else [],
                aliases=['Name:', 'Value:']
            )
        ).add_to(m)
        
        # Display map
        st_folium(m, width=700, height=500)
        
        # Show metadata
        with st.expander("📊 Data Info"):
            st.write(f"**Features:** {data['features_count']}")
            st.write(f"**Timestamp:** {data['metadata']['timestamp']}")
    
    def render_time_series(self, data: Dict[str, Any], query: str):
        """
        Render time-series data as charts.
        
        Args:
            data: Processed time-series data
            query: Original user query
        """
        st.subheader("📈 Data Visualization")
        
        df = data['dataframe']
        stats = data['summary_stats']
        
        # Display summary statistics
        if stats:
            st.markdown("### Summary Statistics")
            
            cols = st.columns(min(4, len(stats)))
            
            # Find the main value column (likely temperature or other measurement)
            value_cols = [col for col in df.columns if 'value' in col.lower() or 'temp' in col.lower()]
            
            if value_cols and value_cols[0] in stats:
                main_col = value_cols[0]
                col_stats = stats[main_col]
                
                cols[0].metric("Average", f"{col_stats['mean']:.2f}")
                cols[1].metric("Minimum", f"{col_stats['min']:.2f}")
                cols[2].metric("Maximum", f"{col_stats['max']:.2f}")
                if len(cols) > 3:
                    cols[3].metric("Std Dev", f"{col_stats['std']:.2f}")
        
        # Line chart
        if not df.empty:
            # Find time and value columns
            time_col = next((col for col in df.columns if 'time' in col.lower() or 'date' in col.lower()), None)
            value_col = next((col for col in df.columns if 'value' in col.lower() or 'temp' in col.lower()), None)
            
            if time_col and value_col:
                st.markdown("### Time Series")
                fig = px.line(
                    df, 
                    x=time_col, 
                    y=value_col,
                    title='Measurements Over Time',
                    labels={value_col: 'Value', time_col: 'Time'}
                )
                st.plotly_chart(fig, use_container_width=True)
            
            # Station-wise comparison (if station column exists)
            station_col = next((col for col in df.columns if 'station' in col.lower() or 'location' in col.lower() or 'id' in col.lower()), None)
            
            if station_col and value_col and len(df[station_col].unique()) > 1:
                st.markdown("### Comparison by Location/Station")
                
                agg_df = df.groupby(station_col)[value_col].agg(['mean', 'min', 'max']).reset_index()
                
                fig_bar = px.bar(
                    agg_df,
                    x=station_col,
                    y='mean',
                    title='Average Values by Station/Location',
                    labels={station_col: 'Station/Location', 'mean': 'Average Value'}
                )
                st.plotly_chart(fig_bar, use_container_width=True)
        
        # Show raw data
        with st.expander("📋 View Raw Data"):
            st.dataframe(df, use_container_width=True)
            st.caption(f"Total records: {len(df)}")
    
    def render_generic(self, data: Dict[str, Any]):
        """
        Render generic data as JSON.
        
        Args:
            data: Processed generic data
        """
        st.subheader("📄 Data")
        st.json(data['data'])
        
        with st.expander("ℹ️ Metadata"):
            st.write(f"**Timestamp:** {data['metadata']['timestamp']}")
            st.write(f"**Endpoint ID:** {data['metadata']['endpoint_id']}")
