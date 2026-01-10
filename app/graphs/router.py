"""
Placeholder router graph that could pick which agent/graph to run based on intent.
"""
from __future__ import annotations

from langgraph.graph import END, StateGraph

from app.shared.state import GovApiState


class RouterGraphFactory:
    def compile(self):
        graph = StateGraph(GovApiState)
        # Placeholder node that simply ends; real routing would inspect state/intent.
        graph.add_node("noop_router", lambda state: state)
        graph.set_entry_point("noop_router")
        graph.add_edge("noop_router", END)
        return graph.compile()


def create_router_graph():
    return RouterGraphFactory().compile()
