import logging
from .client import MemoryClient
from .events import EventCollector, EventType
from .extractor import extract
from .reflector import reflect
from .registry import HintRegistry

logger = logging.getLogger(__name__)


async def post_request_pipeline(
    request_id:     str,
    agent:          str,
    question:       str,
    collector:      EventCollector,
    hints_injected: list[str],
    registry:       HintRegistry,
    client:         MemoryClient,
) -> None:
    try:
        extracted  = extract(collector.events)
        iterations = extracted["iterations"]
        success    = not any(
            not e.data["success"]
            for e in collector.events
            if e.event_type == EventType.TOOL_RESULT
        )

        await client.save_trajectory(
            request_id, agent, question, collector.events, iterations
        )

        await registry.record_observation(
            agent, request_id, hints_injected, iterations, success
        )

        hint_text = await reflect(question, extracted)
        if hint_text:
            await registry.submit(agent, hint_text)
            logger.info("[memory] new hint candidate: %.120s", hint_text)

        await registry.prune_underperforming(agent)

    except Exception as exc:
        logger.warning("[memory] post_request_pipeline failed: %s", exc)
