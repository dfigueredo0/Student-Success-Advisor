"""Conversation state shared by every node; this is what the Postgres checkpointer persists."""

import operator
from typing import Annotated, Any, TypedDict

class State(TypedDict, total=False):
    messages: Annotated[list[dict[str, str]], operator.add]  # {"role", "content"}
    # Routing (kept across turns so a half-filled scaffold resumes with the same agent)
    intent: str | None
    route: str | None  # agent name; None means the router asked for clarification
    confidence: float
    route_source: str  # "regex" | "model" | "clarify"
    # Scaffold progress
    slots: dict[str, Any]
    pending_field: str | None
    # Per-turn outputs, reset by `turn_input`
    agent_results: list[dict[str, Any]]
    tool_calls: list[dict[str, Any]]
    answer: str
    citations: list[dict[str, Any]]

def turn_input(message: str) -> State:
    """Graph input for one user turn: appends the message, clears last turn's outputs."""
    return {
        "messages": [{"role": "user", "content": message}],
        "agent_results": [],
        "tool_calls": [],
        "answer": "",
        "citations": [],
    }
