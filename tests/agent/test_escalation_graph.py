"""orchestrator.escalation in the real graph: a hand-off skips the router's model and the
agents, even when the agent is waiting for an answer to its own question."""

from langgraph.checkpoint.memory import InMemorySaver

from agents.college_advisor import CollegeAdvisor
from orchestrator.graph import build_graph
from orchestrator.state import turn_input
from tests.agent.fakes import FakeLLM, FakeTool, eligibility_result


def test_hand_off_replies_without_the_model_or_a_tool() -> None:
    check = FakeTool("check_prerequisites", eligibility_result())
    llm = FakeLLM()  # any model call fails the test
    graph = build_graph(agents=[CollegeAdvisor(check)], classify=llm.classify)

    state = graph.invoke(turn_input("I'm on academic probation, what do I do?"))

    assert "academic advisor" in state["answer"]
    assert state["route_source"] == "escalation"
    assert check.calls == [] and llm.requests == []


def test_crisis_mid_question_is_handed_off_not_read_as_an_answer() -> None:
    check = FakeTool("check_prerequisites", eligibility_result())
    graph = build_graph(
        InMemorySaver(), agents=[CollegeAdvisor(check)], classify=FakeLLM().classify
    )
    config = {"configurable": {"thread_id": "t"}}
    graph.invoke(turn_input("Can I take CS 450?"), config)  # asks for completed courses

    state = graph.invoke(turn_input("I'm having suicidal thoughts"), config)

    assert "988" in state["answer"]
    assert state["pending_field"] is None
    assert check.calls == []


def test_next_turn_after_a_hand_off_routes_normally() -> None:
    check = FakeTool("check_prerequisites", eligibility_result())
    graph = build_graph(
        InMemorySaver(),
        agents=[CollegeAdvisor(check)],
        classify=FakeLLM(FakeLLM.route("check_eligibility", 0.9)).classify,
    )
    config = {"configurable": {"thread_id": "t"}}
    graph.invoke(turn_input("How do I appeal my grade?"), config)

    state = graph.invoke(turn_input("Can I take CS 450? I've taken CS 351."), config)

    assert state["handoff"] is None
    assert len(check.calls) == 1 and "[1]" in state["answer"]
