from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional
import contextvars
import time


class EventType(str, Enum):
    TOOL_CALL    = "tool_call"
    TOOL_RESULT  = "tool_result"
    LLM_DECISION = "llm_decision"
    FINAL_ANSWER = "final_answer"


@dataclass
class TrajectoryEvent:
    event_type:  EventType
    agent:       str
    request_id:  str
    iteration:   int
    data:        dict[str, Any]
    ts:          float = field(default_factory=time.time)


class EventCollector:
    """Per-request event sink. Attached to a context var for the lifetime of one request."""

    def __init__(self, request_id: str, agent: str):
        self.request_id = request_id
        self.agent      = agent
        self.events: list[TrajectoryEvent] = []

    def emit(self, event_type: EventType, iteration: int, **data: Any) -> None:
        self.events.append(TrajectoryEvent(
            event_type=event_type,
            agent=self.agent,
            request_id=self.request_id,
            iteration=iteration,
            data=data,
        ))


collector_var: contextvars.ContextVar[Optional[EventCollector]] = \
    contextvars.ContextVar("collector_var", default=None)
