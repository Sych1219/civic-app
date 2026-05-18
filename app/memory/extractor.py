from .events import EventType, TrajectoryEvent


def extract(events: list[TrajectoryEvent]) -> dict:
    """
    Returns:
        {
          "success_path": [{"tool": str, "iteration": int}, ...],
          "failed_steps": [{"tool": str, "error": str, "iteration": int}, ...],
          "iterations":   int,
        }
    """
    failed, success = [], []
    for e in events:
        if e.event_type != EventType.TOOL_RESULT:
            continue
        entry = {"tool": e.data["tool"], "iteration": e.iteration}
        if e.data["success"]:
            success.append(entry)
        else:
            failed.append({**entry, "error": e.data.get("error", "")})

    iterations = max((e.iteration for e in events), default=0)
    return {"success_path": success, "failed_steps": failed, "iterations": iterations}
