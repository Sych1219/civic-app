"""
Context Loader — assembles dynamic System Prompt context.

Phase 0: stub that returns empty strings.
Phase 4: full implementation with domain triggers, memory index, officer info.
"""

from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from app.domains.scanner import DomainDef


async def build_context_prompt(
    message: str,
    domains: Optional[dict] = None,
    session_id: str = "default",
    officer_id: Optional[str] = None,
) -> tuple[str, list[str]]:
    """
    Assemble non-base context for the System Prompt.

    Returns:
        (context_text, matched_domain_names)
    """
    if domains is None:
        return "", []

    from app.domains.scanner import match_by_triggers

    matched_names = match_by_triggers(domains, message)
    if not matched_names:
        matched_names = list(domains.keys())

    domain_notes = "\n\n".join(
        f"## {name} Domain Notes\n{domains[name].system_notes}"
        for name in matched_names
        if domains[name].system_notes
    )

    # Memory index with semantic filtering
    memory_index = ""
    try:
        from app.memory.file_memory import file_memory_manager
        from app.memory.embedder import embed
        query_emb = await embed(message)
        memory_index = file_memory_manager.read_index(query_emb=query_emb)
    except Exception:
        memory_index = ""

    # Officer index
    officer_index = ""
    if officer_id:
        try:
            from app.officers.manager import officer_manager
            officer_index = officer_manager.load_index(officer_id)
        except Exception:
            pass

    parts = [p for p in [domain_notes, officer_index, memory_index] if p]
    context_text = "\n\n".join(parts)

    return context_text, matched_names
