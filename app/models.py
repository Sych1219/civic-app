from typing import Any, Dict, Optional

from pydantic import BaseModel


class QueryRequest(BaseModel):
    query: str


class QueryResponse(BaseModel):
    answer: str
    data: Optional[Dict[str, Any]] = None
    query_plan: Optional[Dict[str, Any]] = None
    metadata: Optional[Dict[str, Any]] = None


class HealthResponse(BaseModel):
    status: str
    service: str
    version: str = "1.0.0"
