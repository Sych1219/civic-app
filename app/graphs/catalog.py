"""
Placeholder graph for API catalog discovery flows.

It compiles a single-step LangGraph that hands `metadata.catalog_query` to ApiCatalogService,
which calls the registry's GET /api/v1/gov/apis to list/search registered government APIs.
"""
from __future__ import annotations

from langgraph.graph import END, StateGraph

from app.agents.api_catalog_service import ApiCatalogService
from app.shared.state import GovApiState


class CatalogGraphFactory:
    def __init__(self, *, service: ApiCatalogService | None = None):
        self.service = service or ApiCatalogService()

    def compile(self):
        graph = StateGraph(GovApiState)
        graph.add_node("api_catalog_service", self.service.run)
        graph.set_entry_point("api_catalog_service")
        graph.add_edge("api_catalog_service", END)
        return graph.compile()


def create_catalog_graph():
    return CatalogGraphFactory().compile()
