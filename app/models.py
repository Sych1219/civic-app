"""
Pydantic models for API request and response validation.
"""
from pydantic import BaseModel, Field
from typing import Dict, Any, Optional, List


class QueryRequest(BaseModel):
    """Request model for query endpoint."""
    query: str = Field(..., description="Natural language query from user")
    session_id: Optional[str] = Field(
        None,
        description="Omit only on the very first call; server creates one and returns it. "
                    "Must be echoed on every subsequent request.",
    )
    context: Optional[Dict[str, Any]] = Field(None, description="Optional context data")

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "query": "What's the temperature in Singapore today?",
                    "session_id": "session-uuid-123",
                    "context": {}
                }
            ]
        }
    }


class DataContext(BaseModel):
    """API call metadata returned inside QueryResponse.data_context."""
    endpoint_id: str = Field(..., description="UUID of the matched gov API endpoint")
    endpoint_description: str = Field(..., description="Human-readable description from the schema")
    confidence: float = Field(..., description="Matching confidence score [0, 1]")
    triggered_at: str = Field(..., description="ISO-8601 timestamp of the external API call")


class QueryResponse(BaseModel):
    """Response model for query endpoint."""
    status: str = Field(..., description="Response status: success or error")
    data: Dict[str, Any] = Field(..., description="Processed data ready for visualization")
    visualization_type: str = Field(
        ...,
        description="Type of visualization: map, map_temporal, time_series, generic, error",
    )
    layer_id: Optional[str] = Field(
        None,
        description="Stable machine identifier for the map layer (map/map_temporal only)",
    )
    layer_label: Optional[str] = Field(
        None,
        description="Human-readable layer name for the LayerToggle panel (map/map_temporal only)",
    )
    error: Optional[str] = Field(None, description="Error message if status is error")
    session_id: Optional[str] = Field(
        None,
        description="Echoed or newly created session UUID. Always present.",
    )
    message_id: Optional[str] = Field(
        None,
        description="Server-generated UUID v4 for this response turn. Always present.",
    )
    content: Optional[str] = Field(
        None,
        description="LLM-generated plain-English summary; an LLM apology when status is error. Always present.",
    )
    data_context: Optional[DataContext] = Field(
        None,
        description="API call metadata (matched endpoint, confidence). Null when status is error.",
    )

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
                    "layer_id": None,
                    "layer_label": None,
                    "error": None,
                    "session_id": "session-uuid-123",
                    "message_id": "msg-uuid-001",
                    "content": "The air temperature is currently averaging 28.5 °C.",
                    "data_context": {
                        "endpoint_id": "3a5f2831-815b-4a0a-bbc6-38e54598c8d9",
                        "endpoint_description": "Get real-time air temperature readings",
                        "confidence": 0.94,
                        "triggered_at": "2026-02-08T10:00:00+08:00"
                    }
                }
            ]
        }
    }


class ChatHistoryEntry(BaseModel):
    """A single turn in the conversation history (user or assistant)."""
    role: str = Field(..., description="'user' or 'assistant'")
    message_id: str = Field(..., description="UUID v4 for this message")
    content: str = Field(..., description="Message text")
    timestamp: str = Field(..., description="ISO-8601 timestamp")


class HealthResponse(BaseModel):
    """Response model for health check endpoint."""
    status: str
    service: str
    version: str = "1.0.0"
