# Civic App - System Architecture & Design

## Overview

This document describes the end-to-end architecture for the Civic App, which provides a conversational interface for accessing Singapore government data APIs and visualizing the results.

---

## System Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                         USER INTERFACE                          │
│                   (Streamlit / React Frontend)                  │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                   CHAT/QUERY PROCESSING LAYER                   │
│         (LangChain + LLM for Intent Recognition)                │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                   ENDPOINT SELECTION LAYER                      │
│              (Schema Matcher + Query Builder)                   │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                       API TRIGGER LAYER                         │
│              (HTTP Client + Response Handler)                   │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                   DATA PROCESSING LAYER                         │
│           (Pandas + Data Transformation)                        │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                    VISUALIZATION LAYER                          │
│      (Plotly/Altair for Charts, Folium/Deck.gl for Maps)      │
└─────────────────────────────────────────────────────────────────┘
```

---

## Detailed Workflow

### Step 1: User Input Processing

**Components:**
- Streamlit chat input widget or React-based chat component
- LangChain conversation memory

**Process:**
1. User enters natural language query (e.g., "What's the temperature in Singapore today?")
2. Store query in conversation history
3. Pass query to intent recognition layer

**Example Input:**
```python
user_query = "Show me air temperature for today"
```

---

### Step 2: Endpoint Selection & Parameter Extraction

**Components:**
- LangChain LLM with function calling
- Schema loader from `endpoint-schema-api-response.json`
- Intent classifier

**Process:**
1. Load all available endpoint schemas
2. Use LLM to analyze user intent and match to appropriate endpoint
3. Extract relevant parameters from user query (dates, times, locations, etc.)
4. Validate extracted parameters against schema requirements

**Implementation:**

```python
from langchain_openai import ChatOpenAI
from langchain.prompts import ChatPromptTemplate
from langchain_core.output_parsers import JsonOutputParser
import json
from datetime import datetime
from typing import Dict, Optional

class EndpointMatcher:
    def __init__(self, schema_file_path: str):
        self.llm = ChatOpenAI(model="gpt-4", temperature=0)
        with open(schema_file_path, 'r') as f:
            self.schemas = json.load(f)['schemas']
    
    def match_endpoint(self, user_query: str) -> Dict:
        """Match user query to appropriate endpoint and extract parameters."""
        
        # Create prompt with all available schemas
        prompt = ChatPromptTemplate.from_messages([
            ("system", """You are an API endpoint matcher. Given a user query and available API endpoints, 
            determine which endpoint to use and extract the necessary parameters.
            
            Available endpoints:
            {schemas}
            
            Return a JSON object with:
            - endpoint_id: The ID of the matching endpoint
            - query_params: Dict of query parameters to send
            - body_params: Dict of body parameters to send (if applicable)
            - reasoning: Brief explanation of your choice
            
            For date/time parameters:
            - If user says "today", use current date: {current_date}
            - If user says "now", use current datetime: {current_datetime}
            - Parse relative dates (yesterday, last week, etc.)
            """),
            ("human", "{query}")
        ])
        
        chain = prompt | self.llm | JsonOutputParser()
        
        result = chain.invoke({
            "schemas": json.dumps(self.schemas, indent=2),
            "query": user_query,
            "current_date": datetime.now().strftime("%Y-%m-%d"),
            "current_datetime": datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
        })
        
        return result

# Example usage:
# matcher = EndpointMatcher("design_docs/endpoint-schema-api-response.json")
# result = matcher.match_endpoint("What's the temperature today?")
# Output:
# {
#   "endpoint_id": "3a5f2831-815b-4a0a-bbc6-38e54598c8d9",
#   "query_params": {"date": "2026-02-01"},
#   "body_params": {},
#   "reasoning": "User asked for temperature data for today"
# }
```

---

### Step 3: Query Parameter Construction

**Components:**
- Parameter validator
- Date/time parser
- Schema validator using Pydantic

**Process:**
1. Take extracted parameters from Step 2
2. Format parameters according to endpoint schema requirements
3. Validate data types and required fields
4. Handle default values and optional parameters

**Implementation:**

```python
from pydantic import BaseModel, Field, validator
from typing import Optional, Dict, Any
from datetime import datetime

class QueryBuilder:
    def __init__(self, endpoint_schema: Dict):
        self.schema = endpoint_schema
    
    def build_request_payload(self, query_params: Dict, body_params: Dict) -> Dict:
        """Build the final request payload for the trigger API."""
        
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
        """Validate parameters against schema."""
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

# Example usage:
# builder = QueryBuilder(matched_endpoint_schema)
# payload = builder.build_request_payload(
#     query_params={"date": "2026-02-01"},
#     body_params={}
# )
# Output:
# {
#   "queryParams": {
#     "date": "2026-02-01"
#   }
# }
```

---

### Step 4: API Trigger Execution

**Components:**
- HTTP client (httpx for async support)
- Error handler
- Response validator

**Process:**
1. Construct full API URL with endpoint ID
2. Send POST request to trigger API with constructed payload
3. Handle HTTP errors and retries
4. Parse and validate response

**Implementation:**

```python
import httpx
from typing import Dict, Any
import logging

class APITrigger:
    def __init__(self, base_url: str, timeout: int = 30):
        self.base_url = base_url.rstrip('/')
        self.timeout = timeout
        self.logger = logging.getLogger(__name__)
    
    async def trigger_endpoint(
        self, 
        endpoint_id: str, 
        payload: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Trigger the external API endpoint.
        
        Args:
            endpoint_id: UUID of the endpoint to trigger
            payload: Request payload with queryParams and/or bodyParams
            
        Returns:
            API response data
        """
        url = f"{self.base_url}/api/v2/gov/apis/endpoints/{endpoint_id}/trigger"
        
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            try:
                self.logger.info(f"Triggering endpoint {endpoint_id}")
                self.logger.debug(f"Payload: {payload}")
                
                response = await client.post(
                    url,
                    json=payload,
                    headers={
                        "Content-Type": "application/json",
                        "Accept": "application/json"
                    }
                )
                
                response.raise_for_status()
                
                result = response.json()
                
                # Check if the external API call was successful
                if result.get('status') == 'SUCCESS':
                    self.logger.info(f"Successfully triggered endpoint {endpoint_id}")
                    return result
                else:
                    self.logger.error(f"External API returned non-success status: {result.get('status')}")
                    raise APIError(f"API call failed: {result.get('message', 'Unknown error')}")
                    
            except httpx.HTTPStatusError as e:
                self.logger.error(f"HTTP error occurred: {e}")
                raise APIError(f"HTTP {e.response.status_code}: {e.response.text}")
            except httpx.RequestError as e:
                self.logger.error(f"Request error occurred: {e}")
                raise APIError(f"Request failed: {str(e)}")
    
    def trigger_endpoint_sync(
        self, 
        endpoint_id: str, 
        payload: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Synchronous version of trigger_endpoint."""
        import asyncio
        return asyncio.run(self.trigger_endpoint(endpoint_id, payload))


class APIError(Exception):
    """Custom exception for API errors."""
    pass

# Example usage:
# trigger = APITrigger(base_url="https://api.example.com")
# response = trigger.trigger_endpoint_sync(
#     endpoint_id="3a5f2831-815b-4a0a-bbc6-38e54598c8d9",
#     payload={"queryParams": {"date": "2026-02-01"}}
# )
```

---

### Step 5: Data Processing & Transformation

**Components:**
- Pandas for data manipulation
- Custom processors for different data types
- GeoJSON parser for location data

**Process:**
1. Extract `responseBody` from API response
2. Identify data type (time-series, geospatial, tabular)
3. Transform data into visualization-ready format
4. Calculate aggregations, statistics, or derived metrics

**Implementation:**

```python
import pandas as pd
from typing import Dict, Any, List, Optional
import json

class DataProcessor:
    """Process API responses into visualization-ready formats."""
    
    def process_response(self, api_response: Dict[str, Any]) -> Dict[str, Any]:
        """
        Process API response based on data type.
        
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
            summary_stats[col] = {
                'mean': float(df[col].mean()),
                'min': float(df[col].min()),
                'max': float(df[col].max()),
                'std': float(df[col].std())
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
        """Process generic/unknown data structure."""
        return {
            'data_type': 'generic',
            'data': response_data,
            'metadata': {
                'timestamp': full_response.get('invokedAt'),
                'endpoint_id': full_response.get('endpointId')
            }
        }
    
    def _calculate_bounds(self, coords: List[List[float]]) -> List[List[float]]:
        """Calculate bounding box for coordinates [lon, lat]."""
        if not coords:
            return None
        
        lons = [c[0] for c in coords]
        lats = [c[1] for c in coords]
        
        return [
            [min(lats), min(lons)],  # Southwest
            [max(lats), max(lons)]   # Northeast
        ]

# Example usage:
# processor = DataProcessor()
# processed = processor.process_response(api_response)
# 
# if processed['data_type'] == 'time_series':
#     df = processed['dataframe']
#     stats = processed['summary_stats']
#     # Pass to visualization layer
```

---

### Step 6: Visualization & Frontend Display

**For Streamlit (Recommended for Rapid Development):**

```python
import streamlit as st
import plotly.express as px
import plotly.graph_objects as go
import folium
from streamlit_folium import st_folium
import pandas as pd

class StreamlitVisualizer:
    """Render visualizations in Streamlit."""
    
    def render(self, processed_data: Dict[str, Any], user_query: str):
        """Render appropriate visualization based on data type."""
        
        data_type = processed_data['data_type']
        
        if data_type == 'geojson':
            self.render_map(processed_data)
        elif data_type == 'time_series':
            self.render_time_series(processed_data, user_query)
        else:
            self.render_generic(processed_data)
    
    def render_map(self, data: Dict[str, Any]):
        """Render GeoJSON data on an interactive map."""
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
        """Render time-series data as charts."""
        st.subheader("📈 Temperature Data")
        
        df = data['dataframe']
        stats = data['summary_stats']
        
        # Display summary statistics
        col1, col2, col3, col4 = st.columns(4)
        
        # Assuming temperature column exists
        temp_col = [col for col in df.columns if 'temp' in col.lower() or 'value' in col.lower()]
        
        if temp_col and temp_col[0] in stats:
            temp_stats = stats[temp_col[0]]
            col1.metric("Average", f"{temp_stats['mean']:.1f}°C")
            col2.metric("Minimum", f"{temp_stats['min']:.1f}°C")
            col3.metric("Maximum", f"{temp_stats['max']:.1f}°C")
            col4.metric("Std Dev", f"{temp_stats['std']:.2f}")
        
        # Line chart
        if not df.empty:
            # Find time and value columns
            time_col = next((col for col in df.columns if 'time' in col.lower() or 'date' in col.lower()), None)
            value_col = next((col for col in df.columns if 'value' in col.lower() or 'temp' in col.lower()), None)
            
            if time_col and value_col:
                fig = px.line(
                    df, 
                    x=time_col, 
                    y=value_col,
                    title='Temperature Over Time',
                    labels={value_col: 'Temperature (°C)', time_col: 'Time'}
                )
                st.plotly_chart(fig, use_container_width=True)
            
            # Station-wise comparison (if station column exists)
            station_col = next((col for col in df.columns if 'station' in col.lower()), None)
            
            if station_col and value_col:
                fig_bar = px.bar(
                    df.groupby(station_col)[value_col].mean().reset_index(),
                    x=station_col,
                    y=value_col,
                    title='Average Temperature by Station'
                )
                st.plotly_chart(fig_bar, use_container_width=True)
        
        # Show raw data
        with st.expander("📋 View Raw Data"):
            st.dataframe(df, use_container_width=True)
    
    def render_generic(self, data: Dict[str, Any]):
        """Render generic data as JSON."""
        st.subheader("📄 Data")
        st.json(data['data'])


# Main Streamlit App
def main():
    st.set_page_config(page_title="Civic App", page_icon="🏙️", layout="wide")
    
    st.title("🏙️ Singapore Civic Data Assistant")
    st.markdown("Ask questions about Singapore government data in natural language")
    
    # Initialize session state
    if 'messages' not in st.session_state:
        st.session_state.messages = []
    
    # Chat interface
    for message in st.session_state.messages:
        with st.chat_message(message["role"]):
            st.markdown(message["content"])
            if "visualization" in message:
                visualizer = StreamlitVisualizer()
                visualizer.render(message["visualization"], message["content"])
    
    # Chat input
    if prompt := st.chat_input("Ask about Singapore data..."):
        # Add user message
        st.session_state.messages.append({"role": "user", "content": prompt})
        
        with st.chat_message("user"):
            st.markdown(prompt)
        
        # Process query
        with st.chat_message("assistant"):
            with st.spinner("Processing your request..."):
                try:
                    # Step 1: Match endpoint
                    matcher = EndpointMatcher("design_docs/endpoint-schema-api-response.json")
                    endpoint_match = matcher.match_endpoint(prompt)
                    
                    # Step 2: Build payload
                    # (You'd need to load the schema for the matched endpoint)
                    builder = QueryBuilder(endpoint_match)
                    payload = builder.build_request_payload(
                        endpoint_match.get('query_params', {}),
                        endpoint_match.get('body_params', {})
                    )
                    
                    # Step 3: Trigger API
                    trigger = APITrigger(base_url=st.secrets["API_BASE_URL"])
                    response = trigger.trigger_endpoint_sync(
                        endpoint_match['endpoint_id'],
                        payload
                    )
                    
                    # Step 4: Process data
                    processor = DataProcessor()
                    processed = processor.process_response(response)
                    
                    # Step 5: Visualize
                    st.markdown(f"Here's what I found:")
                    visualizer = StreamlitVisualizer()
                    visualizer.render(processed, prompt)
                    
                    # Save to session
                    st.session_state.messages.append({
                        "role": "assistant",
                        "content": "Here's what I found:",
                        "visualization": processed
                    })
                    
                except Exception as e:
                    st.error(f"Error: {str(e)}")
                    st.session_state.messages.append({
                        "role": "assistant",
                        "content": f"Sorry, I encountered an error: {str(e)}"
                    })

if __name__ == "__main__":
    main()
```

---

## Recommended Technology Stack

### Backend Framework
**Primary: FastAPI + LangChain**

**Rationale:**
- **FastAPI**: Modern, async-capable Python framework with automatic API documentation
- **LangChain**: Excellent for LLM orchestration, chain composition, and conversation memory
- **Async Support**: Both support async/await for efficient API calls
- **Type Safety**: Strong typing with Pydantic models

**Alternative: Flask + LangChain**
- Simpler if async is not critical
- More mature ecosystem

### Frontend Options

#### Option 1: Streamlit (Recommended for MVP)
**Pros:**
- Rapid development (entire app in ~300 lines)
- Built-in chat interface
- Native Python (no JavaScript needed)
- Easy deployment
- Rich widget library

**Cons:**
- Less customizable UI
- Not ideal for complex interactions
- Limited mobile optimization

#### Option 2: React + FastAPI Backend
**Pros:**
- Full UI control and customization
- Better performance for complex UIs
- Mobile-responsive
- Industry standard

**Cons:**
- Longer development time
- Requires JavaScript expertise
- More complex deployment

### Key Python Libraries

```python
# Core Framework
streamlit>=1.31.0          # Frontend (if using Streamlit)
fastapi>=0.109.0           # API backend (if separating frontend)
uvicorn>=0.27.0            # ASGI server

# LLM & AI
langchain>=0.3.0
langchain-openai>=0.2.1
langchain-community>=0.3.0
langgraph>=0.2.14          # For complex workflows

# HTTP & API
httpx>=0.27.2              # Async HTTP client
pydantic>=2.7.4            # Data validation

# Data Processing
pandas>=2.0.0              # Data manipulation
numpy>=1.24.0              # Numerical operations

# Visualization
plotly>=5.18.0             # Interactive charts
folium>=0.15.0             # Maps
streamlit-folium>=0.16.0   # Folium + Streamlit integration

# Utilities
python-dotenv>=1.0.1       # Environment variables
jmespath>=1.0.1            # JSON querying
```

### Infrastructure & Deployment

**Development:**
```bash
# Local development
streamlit run app/main.py

# Or with FastAPI
uvicorn app.main:app --reload
```

**Production:**
- **Streamlit Cloud**: Free hosting for Streamlit apps
- **Heroku/Railway**: Easy deployment with git push
- **AWS ECS/Lambda**: For FastAPI backend
- **Docker**: Containerization for consistent deployment

---

## Project Structure

```
civic-app/
├── app/
│   ├── __init__.py
│   ├── main.py                    # Streamlit main app
│   ├── api_client.py              # API trigger logic
│   ├── endpoint_matcher.py        # LLM-based endpoint matching
│   ├── data_processor.py          # Data transformation
│   ├── visualizers.py             # Visualization components
│   └── utils.py                   # Helper functions
│
├── design_docs/
│   ├── civic-app-architecture.md  # This document
│   ├── endpoint-schema-api-response.json
│   └── data-gov-apis-definations/
│
├── notebooks/
│   ├── data_exploration.ipynb     # EDA and testing
│   └── llm_prompt_engineering.ipynb
│
├── tests/
│   ├── test_endpoint_matcher.py
│   ├── test_data_processor.py
│   └── test_api_client.py
│
├── .env.example                   # Environment variables template
├── .gitignore
├── requirements.txt
├── README.md
└── streamlit_config.toml          # Streamlit configuration
```

---

## Data Processing Strategies by Data Type

### 1. Temperature Data (Time-Series)

**Input Structure:**
```json
{
  "readings": [
    {
      "station_id": "S50",
      "timestamp": "2026-02-01T10:00:00+08:00",
      "value": 28.5
    }
  ]
}
```

**Processing:**
- Convert to pandas DataFrame
- Parse timestamps
- Calculate statistics (mean, min, max, std)
- Group by station/time period

**Visualizations:**
- Line chart: Temperature over time
- Bar chart: Average by station
- Heatmap: Temperature distribution by hour/day
- Summary cards: Current, min, max, avg

### 2. Bus Location Data (GeoJSON)

**Input Structure:**
```json
{
  "type": "FeatureCollection",
  "features": [
    {
      "type": "Feature",
      "geometry": {
        "type": "Point",
        "coordinates": [103.8198, 1.3521]
      },
      "properties": {
        "bus_number": "123",
        "timestamp": "2026-02-01T10:00:00"
      }
    }
  ]
}
```

**Processing:**
- Validate GeoJSON structure
- Extract coordinates for bounds
- Parse properties for tooltips

**Visualizations:**
- Interactive map with markers
- Cluster markers for dense areas
- Color-code by bus route
- Show bus details on click

### 3. Generic Tabular Data

**Processing:**
- Detect data structure automatically
- Infer column types
- Handle missing values
- Create pivot tables if needed

**Visualizations:**
- Data table with search/filter
- Bar/pie charts for categorical data
- Scatter plots for correlations
- Summary statistics

---

## Error Handling & Edge Cases

### User Input Errors
- **Ambiguous queries**: Ask clarifying questions
- **Multiple intents**: Decompose into separate API calls
- **Out-of-scope**: Provide list of available data types

### API Errors
- **Network failures**: Retry with exponential backoff
- **Rate limiting**: Queue requests and throttle
- **Invalid parameters**: Show user-friendly error message
- **Empty results**: Explain why no data is available

### Data Processing Errors
- **Malformed JSON**: Log and show raw data
- **Missing fields**: Use defaults or mark as N/A
- **Type mismatches**: Attempt conversion or skip

---

## Performance Optimization

### Caching Strategy
```python
import streamlit as st
from functools import lru_cache

@st.cache_data(ttl=60)  # Cache for 60 seconds
def fetch_and_process_data(endpoint_id: str, params: dict):
    # Expensive API call and processing
    pass
```

### Async Processing
```python
import asyncio

async def process_multiple_queries(queries: List[str]):
    tasks = [process_single_query(q) for q in queries]
    results = await asyncio.gather(*tasks)
    return results
```

### Progressive Loading
- Show skeleton/loading state immediately
- Stream data as it becomes available
- Lazy load visualizations for large datasets

---

## Security Considerations

1. **API Key Management**: Store in environment variables, never commit
2. **Input Validation**: Sanitize all user inputs before processing
3. **Rate Limiting**: Implement user-side rate limiting
4. **CORS**: Configure properly if using separate frontend/backend
5. **Data Privacy**: Don't log sensitive user queries

---

## Future Enhancements

1. **Multi-turn Conversations**: Remember context across queries
2. **Comparative Analysis**: "Compare temperature today vs last week"
3. **Alerts & Notifications**: Set up triggers for specific conditions
4. **Export Options**: Download data as CSV/Excel
5. **Voice Input**: Speech-to-text for queries
6. **Multilingual Support**: Support for Chinese, Malay, Tamil
7. **Historical Analysis**: Trend detection and forecasting
8. **Custom Dashboards**: Save favorite views and queries

---

## Getting Started Checklist

- [ ] Set up Python environment (3.10+)
- [ ] Install dependencies from requirements.txt
- [ ] Configure OpenAI API key in .env
- [ ] Load endpoint schemas
- [ ] Test endpoint matcher with sample queries
- [ ] Implement API trigger client
- [ ] Build data processor for each data type
- [ ] Create Streamlit visualizations
- [ ] Add error handling
- [ ] Test end-to-end workflow
- [ ] Deploy to Streamlit Cloud

---

## Conclusion

This architecture provides a flexible, scalable foundation for the Civic App. The LangChain-powered endpoint matching layer enables natural language queries, while the modular design allows easy addition of new data sources and visualizations.

**Recommended Starting Point**: Begin with Streamlit for rapid prototyping, then migrate to React + FastAPI if more UI customization is needed.
