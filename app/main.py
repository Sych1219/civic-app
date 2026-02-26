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
import uuid
import uvicorn
from contextlib import asynccontextmanager
from datetime import datetime, timezone

from .models import QueryRequest, QueryResponse, HealthResponse, DataContext
from .endpoint_matcher import EndpointMatcher
from .api_client import APITrigger, APIError
from .data_processor import DataProcessor
from .utils import QueryBuilder, ResponseFormatter
from .chat import SessionStore, LLMSummarizer

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
        components['session_store'] = SessionStore()
        
        # Initialize LLM summarizer with available endpoint topics
        summarizer = LLMSummarizer()
        topic_descriptions = [
            schema.get('description', '')
            for schema in components['matcher'].endpoint_index.values()
        ]
        summarizer.set_available_topics(topic_descriptions)
        components['summarizer'] = summarizer
        
        logger.info("✓ All components initialized successfully (chat mode active)")
        
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
    Process a natural language query and return structured data with LLM summary.
    
    Request lifecycle (always includes chat):
      0. SessionStore  — load history; auto-create session UUID if omitted
      1. EndpointMatcher — embed query → cosine similarity → LLM param extraction
      2. QueryBuilder   — validate & type-cast params against endpoint schema
      3. APITrigger     — POST to external trigger API
      4. DataProcessor  — detect data type → GeoJSON / DataFrame / generic
      5. ResponseFormatter — attach visualization hints, chart configs, map metadata
      6. LLMSummarizer  — build prompt from QueryResponse + history → GPT-4 → content
      7. SessionStore   — persist user + assistant turns
    """
    
    logger.info(f"Received query: {request.query}")
    
    session_store: SessionStore = components['session_store']
    summarizer: LLMSummarizer = components['summarizer']
    
    # ── Step 0: Session management ──────────────────────────────
    session_id = session_store.resolve_session_id(request.session_id)
    history = session_store.get_history(session_id)
    user_message_id = session_store.add_user_turn(session_id, request.query)
    
    # Generate a message_id for the assistant response
    assistant_message_id = str(uuid.uuid4())
    
    try:
        # ── Step 1: Match endpoint and extract parameters ───────
        logger.info("Step 1: Matching endpoint...")
        endpoint_match = components['matcher'].match_endpoint(request.query)
        
        logger.info(f"Matched endpoint: {endpoint_match.get('endpoint_id')}")
        logger.info(f"Confidence: {endpoint_match.get('confidence')}")
        
        # Check confidence threshold
        if endpoint_match.get('confidence', 0) < 0.5:
            error_response = QueryResponse(
                status="error",
                data={},
                visualization_type="error",
                error="Could not understand the query. Please try rephrasing your question.",
                session_id=session_id,
                message_id=assistant_message_id,
                content="",  # placeholder, will be replaced by LLM
                data_context=None,
            )
            # LLM summarization for error
            content = await summarizer.summarize(error_response, request.query, history)
            error_response.content = content
            # Persist assistant turn
            session_store.add_assistant_turn(session_id, assistant_message_id, content)
            return error_response
        
        # ── Step 2: Build request payload ───────────────────────
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
        
        # ── Step 3: Trigger external API ────────────────────────
        logger.info("Step 3: Triggering external API...")
        response = await components['trigger'].trigger_endpoint(
            endpoint_match['endpoint_id'],
            payload
        )
        
        logger.info("API call successful")
        
        # Build DataContext
        data_context = DataContext(
            endpoint_id=endpoint_match['endpoint_id'],
            endpoint_description=endpoint_schema.get('description', ''),
            confidence=endpoint_match.get('confidence', 0.0),
            triggered_at=datetime.now(timezone.utc).isoformat(),
        )
        
        # ── Step 4: Process data ────────────────────────────────
        logger.info("Step 4: Processing response data...")
        processed = components['processor'].process_response(response)
        
        # ── Step 5: Format response for frontend ────────────────
        logger.info("Step 5: Formatting response...")
        result = components['formatter'].format_response(
            processed, request.query, endpoint_schema
        )
        
        # Inject chat & context fields
        result.session_id = session_id
        result.message_id = assistant_message_id
        result.data_context = data_context
        
        # ── Step 6: LLM summarization ──────────────────────────
        logger.info("Step 6: Generating LLM summary...")
        content = await summarizer.summarize(result, request.query, history)
        result.content = content
        
        # ── Step 7: Persist assistant turn ──────────────────────
        session_store.add_assistant_turn(session_id, assistant_message_id, content)
        
        logger.info("Query processed successfully")
        return result
        
    except APIError as e:
        logger.error(f"API error: {e}")
        error_response = QueryResponse(
            status="error",
            data={},
            visualization_type="error",
            error=f"External API error: {str(e)}",
            session_id=session_id,
            message_id=assistant_message_id,
            content="",
            data_context=None,
        )
        content = await summarizer.summarize(error_response, request.query, history)
        error_response.content = content
        session_store.add_assistant_turn(session_id, assistant_message_id, content)
        return error_response
    
    except ValueError as e:
        logger.error(f"Validation error: {e}")
        error_response = QueryResponse(
            status="error",
            data={},
            visualization_type="error",
            error=f"Validation error: {str(e)}",
            session_id=session_id,
            message_id=assistant_message_id,
            content="",
            data_context=None,
        )
        content = await summarizer.summarize(error_response, request.query, history)
        error_response.content = content
        session_store.add_assistant_turn(session_id, assistant_message_id, content)
        return error_response
    
    except Exception as e:
        logger.error(f"Unexpected error: {e}", exc_info=True)
        error_response = QueryResponse(
            status="error",
            data={},
            visualization_type="error",
            error=f"Internal server error: {str(e)}",
            session_id=session_id,
            message_id=assistant_message_id,
            content="",
            data_context=None,
        )
        content = await summarizer.summarize(error_response, request.query, history)
        error_response.content = content
        session_store.add_assistant_turn(session_id, assistant_message_id, content)
        return error_response


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
    


if __name__ == "__main__":
    uvicorn.run("app.main:app", host="0.0.0.0", port=8000, reload=True)
