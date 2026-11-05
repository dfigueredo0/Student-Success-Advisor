"""Merge node: the only place agent output becomes the user-facing reply."""

from typing import Any

from domain.redaction import redact
from orchestrator.router import CLARIFY_QUESTION
from orchestrator.state import State


def merge(state: State) -> dict[str, Any]:
    results = state.get("agent_results") or []
    if results:
        answer = "\n\n".join(r["answer"] for r in results)
        citations = [c for r in results for c in r["citations"]]
    elif state.get("handoff"):  # orchestrator.escalation: hand off to a person
        answer, citations = state["handoff"], []
    else:  # router did not pick an agent
        answer, citations = CLARIFY_QUESTION, []
    # Every reply passes the same check as model output at the gateway, templates included:
    # they can echo what the student typed or what an uploaded file contained.
    answer = redact(answer)
    return {
        "answer": answer,
        "citations": citations,
        "messages": [{"role": "assistant", "content": answer}],
    }
