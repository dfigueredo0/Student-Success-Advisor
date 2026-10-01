"""Merge node: the only place agent output becomes the user-facing reply."""

from typing import Any

from orchestrator.router import CLARIFY_QUESTION
from orchestrator.state import State

def merge(state: State) -> dict[str, Any]:
    results = state.get("agent_results") or []
    if results:
        answer = "\n\n".join(r["answer"] for r in results)
        citations = [c for r in results for c in r["citations"]]
    else:  # router did not pick an agent
        answer, citations = CLARIFY_QUESTION, []
    return {
        "answer": answer,
        "citations": citations,
        "messages": [{"role": "assistant", "content": answer}],
    }
