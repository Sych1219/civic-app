"""
Compatibility shim: re-export shared state definitions.
"""
from app.shared.state import GovApiState, GraphConfig

__all__ = ["GovApiState", "GraphConfig"]
