import uuid
from contextvars import ContextVar
from dataclasses import dataclass, field


@dataclass
class LocationStore:
    """Request-scoped store for GeoJSON locations stripped from the LLM context."""
    _store: dict[str, dict] = field(default_factory=dict)

    def put(self, locations: dict) -> str:
        ref_id = uuid.uuid4().hex[:8]
        self._store[ref_id] = locations
        return ref_id

    def collect(self) -> dict[str, dict]:
        return dict(self._store)


# Set once per request in run_taxi_agent; read by tools during that request.
location_store_var: ContextVar[LocationStore] = ContextVar("location_store")
