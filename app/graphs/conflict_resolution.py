"""
Placeholder graph for conflict resolution flows.
"""
from __future__ import annotations

from langgraph.graph import END, StateGraph

from app.agents.conflict_resolution_agent import ConflictResolutionAgent
from app.shared.state import GovApiState


class ConflictResolutionGraphFactory:
    def __init__(self, *, agent: ConflictResolutionAgent | None = None):
        self.agent = agent or ConflictResolutionAgent()

    def compile(self):
        graph = StateGraph(GovApiState)
        graph.add_node("conflict_resolution_agent", self.agent.run)
        graph.set_entry_point("conflict_resolution_agent")
        graph.add_edge("conflict_resolution_agent", END)
        return graph.compile()


def create_conflict_resolution_graph():
    return ConflictResolutionGraphFactory().compile()
