"""
File-based long-term memory: MEMORY.md index + experience/ entries.

Phase 0: stub — read_index() returns "".
Phase 3: full implementation.
"""

import logging
import os
import re
import time
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

_SINGLETON: Optional["FileMemoryManager"] = None


class FileMemoryManager:
    def __init__(self, data_dir: Optional[Path] = None) -> None:
        if data_dir is None:
            data_dir = Path(os.environ.get("CIVIC_DATA_DIR", "data"))
        self.memory_dir = data_dir / "memory"
        self.experience_dir = self.memory_dir / "experience"

    # ── public read API ──────────────────────────────────────────────────────

    def read_index(self, query_emb: list[float] | None = None) -> str:
        """Return a lightweight summary for System Prompt injection.

        When query_emb is provided, only experience entries whose embedding
        cosine-similarity to the query meets SIMILARITY_THRESHOLD are included
        in the Experience Entries section.
        """
        import json as _json
        md_path = self.memory_dir / "MEMORY.md"
        if not md_path.exists():
            return ""

        try:
            text = md_path.read_text(encoding="utf-8")
            counts = self._count_sections(text)
            experiences = self.list_experiences()

            lines = ["## System Memory Index"]
            for section, count in counts.items():
                lines.append(f"- {section}（{count} 条）")
            if experiences:
                lines.append(f"- Experience（{len(experiences)} 条）")
                for exp in experiences:
                    lines.append(f"  - #{exp['id']} {exp['slug']}")

            if experiences:
                relevant = []
                if query_emb is not None:
                    from app.memory.embedder import cosine_similarity, SIMILARITY_THRESHOLD
                    for exp in experiences:
                        emb_path = self.experience_dir / f"{exp['filename']}.emb.json"
                        if not emb_path.exists():
                            continue
                        exp_emb = _json.loads(emb_path.read_text(encoding="utf-8"))
                        if cosine_similarity(query_emb, exp_emb) >= SIMILARITY_THRESHOLD:
                            relevant.append(exp)
                else:
                    relevant = experiences

                if relevant:
                    lines.append("\n## Experience Entries")
                    for exp in relevant:
                        body = self.read_experience(exp["filename"]).strip()
                        lines.append(f"\n### #{exp['id']} {exp['slug']}\n{body}")

            return "\n".join(lines)
        except Exception as exc:
            logger.warning("read_index failed: %s", exc)
            return ""

    def read_memory_md(self) -> str:
        p = self.memory_dir / "MEMORY.md"
        return p.read_text(encoding="utf-8") if p.exists() else ""

    def list_experiences(self) -> list[dict]:
        if not self.experience_dir.exists():
            return []
        results = []
        for p in sorted(self.experience_dir.glob("*.md")):
            m = re.match(r"^(\d+)-(.+)\.md$", p.name)
            if m:
                results.append({"id": m.group(1), "slug": m.group(2), "filename": p.name})
        return results

    def read_experience(self, filename: str) -> str:
        p = self.experience_dir / filename
        return p.read_text(encoding="utf-8") if p.exists() else f"Error: {filename} not found."

    def write_experience(
        self,
        slug: str,
        content: str,
        embedding: list[float] | None = None,
    ) -> str:
        """Create a new numbered experience file. Returns the filename."""
        import json as _json
        self.experience_dir.mkdir(parents=True, exist_ok=True)
        existing = self.list_experiences()
        next_id = max((int(e["id"]) for e in existing), default=0) + 1
        filename = f"{next_id:03d}-{slug}.md"
        (self.experience_dir / filename).write_text(content, encoding="utf-8")
        if embedding is not None:
            emb_path = self.experience_dir / f"{filename}.emb.json"
            emb_path.write_text(_json.dumps(embedding), encoding="utf-8")
        logger.info("wrote experience: %s", filename)
        return filename

    # ── helpers ──────────────────────────────────────────────────────────────

    def _count_sections(self, md_text: str) -> dict[str, int]:
        counts: dict[str, int] = {}
        current_section: Optional[str] = None
        for line in md_text.splitlines():
            if line.startswith("## "):
                current_section = line[3:].strip()
                counts[current_section] = 0
            elif current_section and line.strip().startswith("- "):
                counts[current_section] += 1
        return counts


def _init(data_dir: Path) -> FileMemoryManager:
    global _SINGLETON
    _SINGLETON = FileMemoryManager(data_dir)
    return _SINGLETON


file_memory_manager = FileMemoryManager()
