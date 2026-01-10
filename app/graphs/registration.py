"""
Graph that orchestrates the register agent.
"""
from __future__ import annotations

from langgraph.graph import END, StateGraph

from app.agents.register_agent import RegisterAgent
from app.shared.state import GovApiState


class RegistrationGraphFactory:
    """
    Builds the registration LangGraph with the register agent.
    """

    def __init__(self, *, agent: RegisterAgent | None = None):
        self.agent = agent or RegisterAgent()

    def compile(self):
        graph = StateGraph(GovApiState)
        graph.add_node("register_agent", self.agent.run)
        graph.set_entry_point("register_agent")
        graph.add_edge("register_agent", END)
        return graph.compile()


def create_registration_graph():
    """
    Convenience helper for callers to obtain the compiled graph.
    """

    return RegistrationGraphFactory().compile()
