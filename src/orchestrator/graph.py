"""Orchestrator graph: router -> one agent -> merge.

Agents never link to each other; every hop goes router -> agent -> merge, and
`tests/unit/test_graph_structure.py` enforces that on the compiled graph.
"""

from collections.abc import Iterable
from typing import Any

from langfuse import observe
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph

from agents.base import Agent
from agents.college_advisor import CollegeAdvisor
from orchestrator.merge import merge
from orchestrator.router import Classifier, ollama_classify, route
from orchestrator.state import State

def build_graph(
    checkpointer: BaseCheckpointSaver | None = None,
    *,
    agents: Iterable[Agent] | None = None,
    classify: Classifier = ollama_classify,
) -> CompiledStateGraph:
    by_name = {a.name: a for a in (agents or [CollegeAdvisor()])}

    def router_node(state: State) -> dict[str, Any]:
        # no way to change topic mid-scaffold; re-route on a confident
        # regex hit for a different intent once there is more than one intent.
        if state.get("pending_field") and state.get("route") in by_name:
            return {}
        r = route(state["messages"][-1]["content"], classify)
        return {
            "intent": r.intent,
            "route": r.agent,
            "confidence": r.confidence,
            "route_source": r.source,
        }

    def agent_node(agent: Agent):
        def node(state: State) -> dict[str, Any]:
            result = agent.run(
                state["intent"],
                state["messages"][-1]["content"],
                state.get("slots") or {},
                state.get("pending_field"),
            )
            return {
                "agent_results": [result],
                "slots": result["slots"],
                "pending_field": result["pending_field"],
                "tool_calls": result["tool_calls"],
            }

        return observe(name=agent.name, as_type="agent")(node)

    g = StateGraph(State)
    g.add_node("router", observe(name="router")(router_node))
    g.add_node("merge", observe(name="merge")(merge))
    g.add_edge(START, "router")
    g.add_conditional_edges("router", lambda s: s.get("route") or "merge", [*by_name, "merge"])
    for name, agent in by_name.items():
        g.add_node(name, agent_node(agent))
        g.add_edge(name, "merge")
    g.add_edge("merge", END)
    return g.compile(checkpointer=checkpointer)
