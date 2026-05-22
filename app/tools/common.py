"""
Common tools shared across all domain agents.
"""

import os
from pathlib import Path

from langchain_core.tools import tool


@tool
def read_file(path: str) -> str:
    """Read a local file from the allowed data paths (memory/, officers/)."""
    data_dir = Path(os.environ.get("CIVIC_DATA_DIR", "data"))
    allowed: list[Path] = [
        data_dir / "memory" / "MEMORY.md",
        *list((data_dir / "memory" / "experience").glob("*.md")),
        *list((data_dir / "officers").glob("*.md")),
    ]
    target = Path(path)
    if target not in allowed:
        return f"Error: path '{path}' is not in the allowed list."
    return target.read_text(encoding="utf-8")
