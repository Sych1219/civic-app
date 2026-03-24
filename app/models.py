from typing import Any, Dict, List, Optional

from pydantic import BaseModel


class QueryRequest(BaseModel):
    query: str


class QueryResponse(BaseModel):
    answer: str
    data: Optional[Dict[str, Any]] = None
    metadata: Optional[Dict[str, Any]] = None


class HealthResponse(BaseModel):
    status: str
    service: str
    version: str = "1.0.0"


class CameraAnalysis(BaseModel):
    congestion: str
    vehicle_density: str
    incidents: str
    weather: str
    road_surface: str
    summary: str


class CameraDetail(BaseModel):
    cameraId: int
    locationName: Optional[str] = None
    latitude: float
    longitude: float
    latestImage: str
    timestamp: str
    resolution: str
    analysis: Optional[CameraAnalysis] = None


class TrafficChatRequest(BaseModel):
    message: str


class TrafficChatResponse(BaseModel):
    answer: str
    view_type: str
    cameras: List[CameraDetail] = []
