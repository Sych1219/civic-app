"""
Graph that orchestrates the API trigger agent.
"""
from __future__ import annotations

from langgraph.graph import END, StateGraph

from app.agents.api_trigger_agent import ApiTriggerAgent
from app.shared.state import GovApiState


class TriggerGraphFactory:
    def __init__(self, *, agent: ApiTriggerAgent | None = None):
        self.agent = agent or ApiTriggerAgent()

    def compile(self):
        graph = StateGraph(GovApiState)
        graph.add_node("api_trigger_agent", self.agent.run)
        graph.set_entry_point("api_trigger_agent")
        graph.add_edge("api_trigger_agent", END)
        return graph.compile()


def create_trigger_graph():
    return TriggerGraphFactory().compile()
