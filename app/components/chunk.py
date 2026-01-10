"""
Component to split normalized text into chunks.
"""
from __future__ import annotations

from app.shared.state import GovApiState
from app.shared.text import TextChunker


class ChunkComponent:
    def __init__(self, chunker: TextChunker | None = None):
        self.chunker = chunker or TextChunker()

    def run(self, state: GovApiState) -> GovApiState:
        document = state.get("cleaned_document", "")
        chunks = self.chunker.split(document)
        if not chunks:
            errors = list(state.get("validation_errors", []))
            errors.append("No usable content found in the documentation.")
            return {"validation_errors": errors}
        metadata = dict(state.get("metadata", {}))
        metadata["chunk_count"] = len(chunks)
        metadata["chunk_preview"] = [chunk[:200] for chunk in chunks[:2]]
        return {"context_chunks": chunks, "metadata": metadata}
