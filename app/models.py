"""
Pydantic models for API request and response validation.
"""
from pydantic import BaseModel, Field
from typing import Dict, Any, Optional, List


class QueryRequest(BaseModel):
    """Request model for query endpoint."""
    query: str = Field(..., description="Natural language query from user")
    session_id: Optional[str] = Field(None, description="Optional session ID for conversation tracking")
    context: Optional[Dict[str, Any]] = Field(None, description="Optional context data")
    
    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "query": "What's the temperature in Singapore today?",
                    "session_id": "uuid-session-123",
                    "context": {}
                }
            ]
        }
    }


class QueryResponse(BaseModel):
    """Response model for query endpoint."""
    status: str = Field(..., description="Response status: success or error")
    data: Dict[str, Any] = Field(..., description="Processed data ready for visualization")
    visualization_type: str = Field(..., description="Type of visualization: map, time_series, generic, error")
    metadata: Dict[str, Any] = Field(..., description="Metadata about the response")
    error: Optional[str] = Field(None, description="Error message if status is error")
    
    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "status": "success",
                    "data": {
                        "records": [{"timestamp": "2026-02-08T10:00:00", "value": 28.5}],
                        "summary_stats": {"mean": 28.5, "min": 26.0, "max": 31.0}
                    },
                    "visualization_type": "time_series",
                    "metadata": {"endpoint_id": "uuid-123", "timestamp": "2026-02-08T10:00:00"},
                    "error": None
                }
            ]
        }
    }


class HealthResponse(BaseModel):
    """Response model for health check endpoint."""
    status: str
    service: str
    version: str = "1.0.0"
