"""The orchestrator -> College Advisor path, run through the
real compiled graph with a scripted FakeLLM in place of the gateway."""

from typing import Any

import httpx
import pytest

from agents.college_advisor import CollegeAdvisor
from orchestrator import graph as graph_module
from orchestrator.graph import build_graph
from orchestrator.router import CLARIFY_QUESTION, ROUTER_PROMPT
from orchestrator.state import turn_input
from tests.agent.fakes import FakeLLM, FakeTool, eligibility_result


def advisor(check: FakeTool) -> CollegeAdvisor:
    return CollegeAdvisor(check)


def test_eligibility_calls_tool_with_valid_args_and_cites() -> None:
    check = FakeTool("check_prerequisites", eligibility_result())
    llm = FakeLLM()  # regex routes this message: any model call fails the test
    graph = build_graph(agents=[advisor(check)], classify=llm.classify)

    state = graph.invoke(turn_input("Can I take CS 450? I've taken CS 351."))

    assert check.calls == [{"course": "CS 450", "completed_courses": ["CS 351"]}]
    assert [c["name"] for c in state["tool_calls"]] == ["check_prerequisites"]
    assert len(state["citations"]) >= 1 and "[1]" in state["answer"]
    assert state["messages"][-1] == {"role": "assistant", "content": state["answer"]}
    assert llm.requests == []


def test_model_routed_eligibility_reaches_the_tool() -> None:
    check = FakeTool("check_prerequisites", eligibility_result())
    llm = FakeLLM(FakeLLM.route("check_eligibility", 0.9))
    graph = build_graph(agents=[advisor(check)], classify=llm.classify)

    state = graph.invoke(turn_input("is CS 450 open to someone who finished CS 351"))

    assert state["route_source"] == "model"
    assert len(llm.requests) == 1
    assert check.calls == [{"course": "CS 450", "completed_courses": ["CS 351"]}]
    assert state["citations"]


def test_missing_field_asks_one_question_and_does_not_call_tool() -> None:
    check = FakeTool("check_prerequisites", eligibility_result())
    graph = build_graph(agents=[advisor(check)], classify=FakeLLM().classify)

    state = graph.invoke(turn_input("Can I take CS 450?"))

    assert check.calls == [] and state["tool_calls"] == []
    assert state["pending_field"] == "completed_courses"
    assert state["answer"].count("?") == 1  # one question per turn


def test_low_confidence_clarifies_instead_of_routing() -> None:
    check = FakeTool("check_prerequisites", eligibility_result())
    llm = FakeLLM(FakeLLM.route("check_eligibility", 0.2))
    graph = build_graph(agents=[advisor(check)], classify=llm.classify)

    state = graph.invoke(turn_input("tell me something"))

    assert (state["route"], state["route_source"]) == (None, "clarify")
    assert state["answer"] == CLARIFY_QUESTION
    assert state["agent_results"] == [] and check.calls == []


@pytest.mark.parametrize(
    "reply",
    [
        '{"intent": "check_elig',
        FakeLLM.route("not_an_intent", 0.99),
        httpx.ConnectError("gateway down"),
    ],
)
def test_unusable_model_reply_clarifies(reply: Any) -> None:
    graph = build_graph(agents=[advisor(FakeTool("x", {}))], classify=FakeLLM(reply).classify)
    state = graph.invoke(turn_input("tell me something"))
    assert state["answer"] == CLARIFY_QUESTION


def test_classifier_uses_versioned_prompt_and_tags_the_span(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    spans: list[dict[str, Any]] = []

    class Client:
        def update_current_span(self, **kwargs: Any) -> None:
            spans.append(kwargs)

    monkeypatch.setattr(graph_module, "get_client", Client)
    llm = FakeLLM(FakeLLM.route("check_eligibility", 0.9))
    check = FakeTool("check_prerequisites", eligibility_result())
    graph = build_graph(agents=[advisor(check)], classify=llm.classify)

    state = graph.invoke(turn_input("is CS 450 open to me"))

    request = llm.requests[0]
    assert request["metadata"] == {"prompt_version": ROUTER_PROMPT.version}
    prompt = request["messages"][0]["content"]
    assert prompt.endswith("Message: is CS 450 open to me\nIntent:")
    assert "- check_eligibility:" in prompt and "$" not in prompt
    assert state["prompt_version"] == ROUTER_PROMPT.version
    assert spans == [
        {"version": ROUTER_PROMPT.version, "metadata": {"prompt_version": ROUTER_PROMPT.version}}
    ]


def test_regex_route_has_no_prompt_version() -> None:
    check = FakeTool("check_prerequisites", eligibility_result())
    graph = build_graph(agents=[advisor(check)], classify=FakeLLM().classify)
    assert graph.invoke(turn_input("Can I take CS 450?"))["prompt_version"] is None
