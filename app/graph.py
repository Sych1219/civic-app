"""
Compatibility shim that exposes the registration graph via the old import path.
"""
from __future__ import annotations

from app.graphs.registration import RegistrationGraphFactory, create_registration_graph

# Backwards-compatible names
GovApiGraphFactory = RegistrationGraphFactory
create_gov_api_graph = create_registration_graph

__all__ = ["GovApiGraphFactory", "create_gov_api_graph"]
