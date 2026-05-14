from typing import Any, Literal, Optional, Union

from pydantic import BaseModel, Field, field_validator


# ─── GeoJSON ──────────────────────────────────────────────────────────────────

class GeoJsonPoint(BaseModel):
    type: Literal["Point"] = "Point"
    coordinates: list[float]  # [longitude, latitude]


class GeoJsonFeature(BaseModel):
    type: Literal["Feature"] = "Feature"
    geometry: GeoJsonPoint
    properties: dict[str, Any] = Field(default_factory=dict)

    @field_validator("properties", mode="before")
    @classmethod
    def _none_to_empty(cls, v: Any) -> Any:
        return {} if v is None else v


class GeoJsonFeatureCollection(BaseModel):
    type: Literal["FeatureCollection"] = "FeatureCollection"
    features: list[GeoJsonFeature]


# ─── Zone resolve ─────────────────────────────────────────────────────────────

class ZoneResolveResult(BaseModel):
    name: str
    category: str
    suggested_endpoint: str


# ─── Query contexts ───────────────────────────────────────────────────────────

class ZoneContext(BaseModel):
    type: Literal["zone"] = "zone"
    zone_name: str
    category: str


class RadiusContext(BaseModel):
    type: Literal["radius"] = "radius"
    lat: float
    lon: float
    radius_m: int


class NearestContext(BaseModel):
    type: Literal["nearest"] = "nearest"
    lat: float
    lon: float
    limit: int


class RoadContext(BaseModel):
    type: Literal["road"] = "road"
    road_name: str
    category: str
    buffer_m: int


QueryContext = Union[ZoneContext, RadiusContext, NearestContext, RoadContext]


# ─── Spatial query (count_* / find_nearest_taxis) ────────────────────────────

class SpatialQueryData(BaseModel):
    type: Literal["spatial_query"] = "spatial_query"
    taxi_count: int
    snapshot_time: str
    context: QueryContext = Field(discriminator="type")
    locations: Optional[GeoJsonFeatureCollection] = None
    locations_ref: Optional[str] = None


# ─── Timeline (get_taxi_history / get_recent_taxi_activity) ──────────────────

class SnapshotEntry(BaseModel):
    snapshot_id: Optional[int] = None
    timestamp: str
    taxi_count: int
    locations: Optional[GeoJsonFeatureCollection] = None
    locations_ref: Optional[str] = None


class TimelineData(BaseModel):
    type: Literal["timeline"] = "timeline"
    from_time: str
    to_time: str
    window_minutes: Optional[int] = None
    context: Optional[Any] = None
    snapshots: list[SnapshotEntry]
