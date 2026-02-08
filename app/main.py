"""
Civic App Backend API - Singapore Government Data Assistant

FastAPI backend that provides REST API endpoints for processing natural language
queries and returning structured data from Singapore government APIs.
"""

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from dotenv import load_dotenv
import logging
import os
from contextlib import asynccontextmanager

from models import QueryRequest, QueryResponse, HealthResponse
from endpoint_matcher import EndpointMatcher
from api_client import APITrigger, APIError
from data_processor import DataProcessor
from utils import QueryBuilder, ResponseFormatter

# Load environment variables
load_dotenv()

# Configure logging
log_level = os.getenv("LOG_LEVEL", "INFO")
logging.basicConfig(
    level=getattr(logging, log_level),
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Global components (initialized on startup)
components = {}


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialize components on startup and cleanup on shutdown."""
    logger.info("Initializing Civic App Backend...")
    
    # API base URL
    api_base_url = os.getenv("API_BASE_URL", "https://api.example.com")
    
    # Schema file path
    schema_path = os.path.join(
        os.path.dirname(__file__), 
        "..", 
        "design_docs", 
        "endpoint-schema-api-response.json"
    )
    
    try:
        # Initialize components
        components['matcher'] = EndpointMatcher(schema_path)
        components['trigger'] = APITrigger(api_base_url)
        components['processor'] = DataProcessor()
        components['formatter'] = ResponseFormatter()
        
        logger.info("✓ All components initialized successfully")
        
    except Exception as e:
        logger.error(f"Failed to initialize components: {e}", exc_info=True)
        raise
    
    yield
    
    # Cleanup (if needed)
    logger.info("Shutting down Civic App Backend...")


# Create FastAPI application
app = FastAPI(
    title="Civic App Backend API",
    description="Backend API for processing natural language queries to Singapore government data",
    version="1.0.0",
    lifespan=lifespan
)

# Configure CORS for MVP (allow all origins - restrict in production)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # For MVP - specify frontend domains in production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/", response_model=dict)
async def root():
    """Root endpoint with API information."""
    return {
        "service": "Civic App Backend API",
        "version": "1.0.0",
        "status": "running",
        "docs": "/docs",
        "health": "/health"
    }


@app.get("/health", response_model=HealthResponse)
async def health_check():
    """Health check endpoint."""
    return HealthResponse(
        status="healthy",
        service="civic-app-backend",
        version="1.0.0"
    )


@app.post("/api/query", response_model=QueryResponse)
async def process_query(request: QueryRequest):
    """
    Process a natural language query and return structured data.
    
    This endpoint:
    1. Matches the user query to the appropriate Singapore government data API
    2. Extracts parameters from the query
    3. Triggers the external API
    4. Processes the response into visualization-ready format
    5. Returns structured JSON with visualization hints
    
    Args:
        request: Query request containing user's natural language query
        
    Returns:
        QueryResponse with processed data and visualization hints
    """
    
    logger.info(f"Received query: {request.query}")
    
    try:
        # Step 1: Match endpoint and extract parameters
        logger.info("Step 1: Matching endpoint...")
        endpoint_match = components['matcher'].match_endpoint(request.query)
        
        logger.info(f"Matched endpoint: {endpoint_match.get('endpoint_id')}")
        logger.info(f"Confidence: {endpoint_match.get('confidence')}")
        
        # Check confidence threshold
        if endpoint_match.get('confidence', 0) < 0.5:
            return QueryResponse(
                status="error",
                data={},
                visualization_type="error",
                metadata={},
                error="Could not understand the query. Please try rephrasing your question."
            )
        
        # Step 2: Build request payload
        logger.info("Step 2: Building request payload...")
        endpoint_schema = components['matcher'].endpoint_index.get(
            endpoint_match['endpoint_id']
        )
        
        builder = QueryBuilder(endpoint_schema)
        payload = builder.build_request_payload(
            endpoint_match.get('query_params', {}),
            endpoint_match.get('body_params', {})
        )
        
        logger.debug(f"Payload: {payload}")
        
        # Step 3: Trigger external API
        logger.info("Step 3: Triggering external API...")
        response = await components['trigger'].trigger_endpoint(
            endpoint_match['endpoint_id'],
            payload
        )
        
        logger.info("API call successful")
        
        # Step 4: Process data
        logger.info("Step 4: Processing response data...")
        processed = components['processor'].process_response(response)
        
        logger.info(f"Data processed as type: {processed['data_type']}")
        
        # Step 5: Format response for frontend
        logger.info("Step 5: Formatting response...")
        result = components['formatter'].format_response(processed, request.query)
        
        logger.info("Query processed successfully")
        return result
        
    except APIError as e:
        logger.error(f"API error: {e}")
        return QueryResponse(
            status="error",
            data={},
            visualization_type="error",
            metadata={},
            error=f"External API error: {str(e)}"
        )
    
    except ValueError as e:
        logger.error(f"Validation error: {e}")
        return QueryResponse(
            status="error",
            data={},
            visualization_type="error",
            metadata={},
            error=f"Validation error: {str(e)}"
        )
    
    except Exception as e:
        logger.error(f"Unexpected error: {e}", exc_info=True)
        return QueryResponse(
            status="error",
            data={},
            visualization_type="error",
            metadata={},
            error=f"Internal server error: {str(e)}"
        )


@app.get("/api/endpoints", response_model=dict)
async def list_endpoints():
    """
    List all available Singapore government data API endpoints.
    
    Returns:
        Dictionary containing endpoint information
    """
    try:
        endpoints = []
        for endpoint_id, schema in components['matcher'].endpoint_index.items():
            endpoints.append({
                "id": endpoint_id,
                "description": schema.get('description', ''),
                "parameters": schema.get('parameters', [])
            })
        
        return {
            "total": len(endpoints),
            "endpoints": endpoints
        }
    except Exception as e:
        logger.error(f"Error listing endpoints: {e}")
        raise HTTPException(status_code=500, detail=str(e))
    
    components = st.session_state.components
    
    # Initialize session state for messages
    if 'messages' not in st.session_state:
        st.session_state.messages = []
    
    # Display chat history
    for message in st.session_state.messages:
        with st.chat_message(message["role"]):
            st.markdown(message["content"])
            
            # Render visualization if present
            if message.get("visualization"):
                components['visualizer'].render(
                    message["visualization"], 
                    message.get("query", "")
                )
    
    # Chat input
    if prompt := st.chat_input("Ask about Singapore data... (e.g., 'What's the temperature today?')"):
        # Add user message to chat history
        st.session_state.messages.append({
            "role": "user", 
            "content": prompt
        })
        
        # Display user message
        with st.chat_message("user"):
            st.markdown(prompt)
        
        # Process query and display response
        with st.chat_message("assistant"):
            success, message, processed_data = process_user_query(prompt, components)
            
            # Display message
            st.markdown(message)
            
            # Render visualization if data was retrieved
            if success and processed_data:
                components['visualizer'].render(processed_data, prompt)
                
                # Add assistant message with visualization to history
                st.session_state.messages.append({
                    "role": "assistant",
                    "content": message,
                    "query": prompt,
                    "visualization": processed_data
                })
            else:
                # Add error message to history
                st.session_state.messages.append({
                    "role": "assistant",
                    "content": message
                })
    
    # Sidebar with examples and info
    with st.sidebar:
        st.header("ℹ️ About")
        st.markdown(
            """
            This app uses natural language processing to understand your queries
            and fetch relevant data from Singapore government APIs.
            """
        )
        
        st.header("💡 Example Queries")
        example_queries = [
            "What's the temperature today?",
            "Show me air temperature readings",
            "Get temperature data for yesterday",
            "Where are the buses right now?"
        ]
        
        for query in example_queries:
            if st.button(query, key=f"example_{query}"):
                st.session_state.next_query = query
                st.rerun()
        
        # Handle example query clicks
        if hasattr(st.session_state, 'next_query'):
            # This will be picked up on the next rerun
            pass
        
        st.header("🔧 Settings")
        if st.button("Clear Chat History"):
            st.session_state.messages = []
            st.rerun()


if __name__ == "__main__":
    main()
