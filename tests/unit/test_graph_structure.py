from agents.base import Agent
from orchestrator.graph import build_graph


class _Stub(Agent):
    scaffolds = {}  # noqa: RUF012

    def __init__(self, name: str) -> None:
        self.name = name


def test_no_agent_to_agent_edges() -> None:
    """All cross-agent traffic goes through the orchestrator (router in, merge out)."""
    agents = {"college_advisor", "career_advisor"}
    edges = build_graph(agents=[_Stub(n) for n in agents]).get_graph().edges
    assert {e.target for e in edges if e.source == "router"} == agents | {"merge"}
    for agent in agents:
        assert {e.source for e in edges if e.target == agent} == {"router"}
        assert {e.target for e in edges if e.source == agent} == {"merge"}
