"""a drop question asks only for what it lacks, calls
check_consequences with the student's courses, answers with citations and the advice to see
an advisor, and logs one VerifierRun per call."""

from typing import Any

from langgraph.checkpoint.memory import InMemorySaver

from agents.base import TOOL_FAILED
from agents.college_advisor import ASK_BEFORE_DROPPING, ASK_CURRENT, CollegeAdvisor
from orchestrator.graph import build_graph
from orchestrator.router import ROUTER_PROMPT
from orchestrator.state import turn_input
from schemas.logs import VerifierRun
from tests.agent.fakes import FakeLLM, FakeTool

ANSWER = FakeLLM.route("follow_up", 0.9)  # the router reads a reply as the answer


def consequences_result() -> dict[str, Any]:
    return {
        "course": "CS 351",
        "taking": True,
        "current": ["CS 350", "CS 351"],
        "credits_before": 6.0,
        "credits_after": 3.0,
        "credits_cite": 1,
        "unknown_credits": [],
        "crossed": [
            {
                "id": "aid_half_time-ug",
                "message": "Below half-time you can't receive Federal Direct Loans.",
                "min_credits": 6,
                "verified": False,
                "cite": 2,
            }
        ],
        "already_below": [],
        "blocked": [
            {"course": "CS 450", "title": "Operating Systems", "needs": ["CS 351"], "cite": 3}
        ],
        "corequisite_of": [],
        "also_delayed": 4,
        "reasons": ["prereq_blocked:CS 450", "below:aid_half_time-ug"],
        "citations": [
            {"source": "IIT Banner course catalog, term 202710", "url": "u", "quote": "q"},
            {"source": "Illinois Tech Office of Financial Aid", "url": "u", "quote": "q"},
            {"source": "IIT Banner course catalog, CS 450, term 202710", "url": "u", "quote": "q"},
        ],
    }


class Chat:
    def __init__(self, *replies: dict[str, Any]) -> None:
        self.tool = FakeTool("check_consequences", consequences_result())
        self.llm = FakeLLM(*replies)
        self.runs: list[VerifierRun] = []
        self.graph = build_graph(
            InMemorySaver(),
            agents=[CollegeAdvisor(consequences=self.tool)],
            classify=self.llm.classify,
            fill=self.llm.fill,
            log_run=self.runs.append,
        )
        self.config = {"configurable": {"thread_id": "t"}}

    def say(self, text: str) -> dict[str, Any]:
        return self.graph.invoke(turn_input(text), self.config)


def test_without_a_profile_it_asks_what_it_needs_then_checks_and_logs() -> None:
    chat = Chat(ANSWER, ANSWER)

    first = chat.say("What happens if I drop CS 351?")  # whole-message pattern: no model call
    assert first["intent"] == "drop_course" and first["answer"] == ASK_CURRENT
    assert chat.tool.calls == [] and chat.runs == []

    assert chat.say("CS 350, CS 351")["pending_field"] == "completed_courses"
    state = chat.say("CS 115, CS 116 and CS 331")

    assert chat.tool.calls == [
        {
            "course": "CS 351",
            "in_progress_courses": ["CS 350", "CS 351"],
            "completed_courses": ["CS 115", "CS 116", "CS 331"],
            "grades": None,
        }
    ]
    assert state["citations"] and "[3]" in state["answer"]
    assert "CS 450 - Operating Systems (would need CS 351) [3]" in state["answer"]
    assert ASK_BEFORE_DROPPING in state["answer"]
    [run] = chat.runs
    assert run.verifier == "check_consequences" and run.intent == "drop_course"
    assert run.candidate_plan == {"drop": "CS 351"} and run.passed is False
    assert run.failure_reasons == ["prereq_blocked:CS 450", "below:aid_half_time-ug"]
    assert run.prompt_version == ROUTER_PROMPT.version  # the router's model read the reply


def test_a_transcript_profile_answers_in_one_turn() -> None:
    chat = Chat()
    profile = {
        "completed_courses": ["CS 115", "CS 116"],
        "grades": {"CS 115": "A", "CS 116": "B"},
        "in_progress_courses": ["CS 350", "CS 351"],
    }
    chat.graph.update_state(chat.config, {"profile": profile}, as_node="merge")

    state = chat.say("What happens if I drop CS 351?")

    assert chat.tool.calls[0]["grades"] == {"CS 115": "A", "CS 116": "B"}
    assert state["pending_field"] is None and "6 to 3 credit hours [1]" in state["answer"]
    assert len(chat.runs) == 1 and chat.runs[0].prompt_version is None  # pattern-routed


def test_a_failed_check_is_not_logged() -> None:
    def check_consequences(**kwargs: Any) -> dict[str, Any]:
        raise RuntimeError("catalog down")

    runs: list[VerifierRun] = []
    graph = build_graph(
        InMemorySaver(),
        agents=[CollegeAdvisor(consequences=check_consequences)],
        classify=FakeLLM().classify,
        log_run=runs.append,
    )
    config = {"configurable": {"thread_id": "t"}}
    profile = {"in_progress_courses": ["CS 351"], "completed_courses": []}
    graph.update_state(config, {"profile": profile}, as_node="merge")

    state = graph.invoke(turn_input("What happens if I drop CS 351?"), config)

    assert state["answer"] == TOOL_FAILED and runs == []
