from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field


class QueryRequest(BaseModel):
    query: str


class QueryResponse(BaseModel):
    answer: str
    data: Optional[Dict[str, Any]] = None
    metadata: Optional[Dict[str, Any]] = None


class ChatRequest(BaseModel):
    message: str


class Artifact(BaseModel):
    type: str
    data: Dict[str, Any]


class ChatResponse(BaseModel):
    answer: str
    artifacts: List[Artifact] = []


class HealthResponse(BaseModel):
    status: str
    service: str
    version: str = "1.0.0"


class CameraAnalysis(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    congestion: str
    vehicle_density: str = Field(alias="vehicleDensity")
    incidents: str
    weather: str
    road_surface: str = Field(alias="roadSurface")
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


class AnalyzeCameraRequest(BaseModel):
    image_url: str
    camera_id: Optional[str] = None
    location_name: Optional[str] = None


class AnalyzeCameraResponse(BaseModel):
    analysis: CameraAnalysis


class TrafficChatRequest(BaseModel):
    message: str


class TrafficChatResponse(BaseModel):
    answer: str
    view_type: str
    cameras: List[CameraDetail] = []
