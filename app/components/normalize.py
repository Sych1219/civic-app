"""
Component to normalize raw API text.
"""
from __future__ import annotations

from app.shared.state import GovApiState
from app.shared.text import TextNormalizer


class NormalizeComponent:
    def __init__(self, normalizer: TextNormalizer | None = None):
        self.normalizer = normalizer or TextNormalizer()

    def run(self, state: GovApiState) -> GovApiState:
        source_text = state.get("source_text")
        if not source_text:
            errors = list(state.get("validation_errors", []))
            errors.append("source_text is required to start the workflow.")
            return {"validation_errors": errors}

        document = self.normalizer.normalize(source_text)
        metadata = dict(state.get("metadata", {}))
        metadata["source_chars"] = len(source_text)
        metadata["normalized_chars"] = len(document)
        return {"cleaned_document": document, "metadata": metadata}
