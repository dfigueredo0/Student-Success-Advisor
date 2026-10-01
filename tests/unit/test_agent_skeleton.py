from typing import Any

from agents.college_advisor import CollegeAdvisor
from orchestrator.graph import build_graph
from orchestrator.router import CLARIFY_QUESTION, route
from orchestrator.state import turn_input


class FakeCheck:
    """Stands in for tools.advisor.check_prerequisites; records every call."""

    __name__ = "check_prerequisites"

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def __call__(self, course: str, completed_courses: list[str]) -> dict[str, Any]:
        self.calls.append({"course": course, "completed_courses": completed_courses})
        missing = [c for c in ["CS 351"] if c not in completed_courses]
        return {
            "course": course,
            "found": True,
            "prerequisites": "CS 351",
            "missing": missing,
            "eligible": not missing,
            "citations": [{"source": f"catalog, {course}", "quote": "CS 351"}],
        }


def no_model(text: str) -> tuple[str | None, float]:
    return None, 0.0


def test_missing_scaffold_field_asks_and_does_not_call_tool() -> None:
    check = FakeCheck()
    agent = CollegeAdvisor(check)

    first = agent.run("check_eligibility", "Can I take CS 450?", {}, None)
    assert check.calls == []
    assert first["tool_calls"] == []
    assert first["pending_field"] == "completed_courses"
    assert first["answer"].endswith("say 'none'.")
    assert first["slots"] == {"course": "CS 450"}

    second = agent.run("check_eligibility", "cs351 and CS 331", first["slots"], "completed_courses")
    assert check.calls == [{"course": "CS 450", "completed_courses": ["CS 351", "CS 331"]}]
    assert second["pending_field"] is None
    assert "[1]" in second["answer"] and second["citations"]


def test_fields_are_asked_one_at_a_time() -> None:
    check = FakeCheck()
    result = CollegeAdvisor(check).run("check_eligibility", "what are the prereqs?", {}, None)
    assert result["pending_field"] == "course"  # asks for the course only, not both fields
    assert "completed" not in result["answer"]
    assert check.calls == []


def test_router_stages() -> None:
    assert route("Can I take CS 450?", no_model).source == "regex"
    by_model = route("is 450 open to me", lambda t: ("check_eligibility", 0.8), threshold=0.6)
    assert (by_model.agent, by_model.source) == ("college_advisor", "model")


def test_low_router_confidence_clarifies_instead_of_routing() -> None:
    low = route("hmm", lambda t: ("check_eligibility", 0.59), threshold=0.6)
    assert (low.agent, low.source) == (None, "clarify")

    check = FakeCheck()
    graph = build_graph(
        agents=[CollegeAdvisor(check)], classify=lambda t: ("check_eligibility", 0.2)
    )
    state = graph.invoke(turn_input("tell me something"))
    assert state["route"] is None
    assert state["answer"] == CLARIFY_QUESTION
    assert state["agent_results"] == [] and check.calls == []


def test_full_path_through_graph_returns_cited_answer() -> None:
    check = FakeCheck()
    graph = build_graph(agents=[CollegeAdvisor(check)], classify=no_model)
    state = graph.invoke(turn_input("Can I take CS 450? I've taken CS 351."))
    assert [c["name"] for c in state["tool_calls"]] == ["check_prerequisites"]
    assert state["citations"] and "[1]" in state["answer"]
    assert state["messages"][-1] == {"role": "assistant", "content": state["answer"]}
