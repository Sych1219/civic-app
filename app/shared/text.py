"""
Shared text utilities (normalization, chunking).
"""
from __future__ import annotations

from typing import List


class TextNormalizer:
    """
    Cleans raw user-pasted API text before chunking.

    This is intentionally lightweight: it trims surrounding whitespace and
    collapses runs of blank lines to reduce obvious copy/paste noise.
    """

    @staticmethod
    def normalize(text: str) -> str:
        if not text:
            return ""
        normalized = text.replace("\r\n", "\n").replace("\r", "\n").strip()
        lines = [line.rstrip() for line in normalized.split("\n")]
        collapsed: List[str] = []
        blank_streak = 0
        for line in lines:
            if line.strip():
                blank_streak = 0
                collapsed.append(line)
            else:
                blank_streak += 1
                if blank_streak == 1:
                    collapsed.append("")
        return "\n".join(collapsed)


class TextChunker:
    """
    Splits normalized API text into roughly 2k token chunks with slight overlaps.
    """

    def __init__(self, chunk_size: int = 4000, overlap: int = 400):
        self._chunk_size = chunk_size
        self._overlap = overlap

    def split(self, document: str) -> List[str]:
        if not document:
            return []
        chunks: List[str] = []
        start = 0
        length = len(document)
        while start < length:
            end = min(start + self._chunk_size, length)
            chunks.append(document[start:end].strip())
            if end >= length:
                break
            start = max(end - self._overlap, 0)
        return [chunk for chunk in chunks if chunk]
