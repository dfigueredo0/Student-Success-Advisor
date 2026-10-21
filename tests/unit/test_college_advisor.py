import json
from typing import Any

import pytest
from langgraph.checkpoint.memory import InMemorySaver

from agents.base import TOOL_FAILED
from agents.college_advisor import (
    DEGREE_PROGRESS_UNAVAILABLE,
    GREETING,
    GREETINGS_AGAIN,
    HELP,
    CollegeAdvisor,
    _render_eligibility,
)
from domain.prereq import evaluate
from orchestrator.graph import build_graph
from orchestrator.router import route
from orchestrator.state import turn_input
from tools.advisor.check_prerequisites import eligibility_fields


def no_model(text: str) -> tuple[str | None, float]:
    return None, 0.0


class Recorder:
    """Stands in for a tool; records calls and returns a canned result."""

    def __init__(self, name: str, result: dict[str, Any]) -> None:
        self.__name__ = name
        self.result = result
        self.calls: list[dict[str, Any]] = []

    def __call__(self, **kwargs: Any) -> dict[str, Any]:
        self.calls.append(kwargs)
        return self.result


def recommend_result(requested: str | None = None) -> dict[str, Any]:
    return {
        "found": True,
        "term": "Fall 2026",
        "requested_term": requested,
        "requested_term_available": requested is None,
        "subjects": ["CS"],
        "completed_courses": ["CS 115", "CS 116"],
        "considered": 1,
        "recommendations": [
            {
                "code": "CS 331",
                "subject": "CS",
                "title": "Data Structures and Algorithms",
                "credits": 3.0,
                "prerequisites": "CS 116",
                "builds_on": ["CS 116"],
                "unlocks": 14,
                "sections": 3,
                "seats_remaining": 1,
            }
        ],
        "citations": [{"source": "IIT Banner schedule, Fall 2026, CS 331"}],
    }


def not_connected(**kwargs: Any) -> dict[str, Any]:
    raise NotImplementedError


not_connected.__name__ = "get_degree_progress"  # stands in for that tool on the allow-list


class Tools:
    def __init__(self) -> None:
        self.check = Recorder(
            "check_prerequisites",
            {
                "course": "CS 450",
                "found": True,
                "prerequisites": "CS 351",
                "status": "satisfied",
                "missing": [],
                "pending": [],
                "needs_grade": [],
                "if_grade_too_low": None,
                "unchecked_tests": [],
                "unreadable": [],
                "citations": [{"source": "catalog, CS 450"}],
            },
        )
        self.recommend = Recorder("recommend_courses", recommend_result())
        self.search = Recorder(
            "search_courses",
            {
                "query": "machine learning",
                "results": [
                    {
                        "code": "CS 484",
                        "title": "Intro to Machine Learning",
                        "credits": 3.0,
                        "summary": "Introduction to machine learning",
                        "prerequisites": "",
                    }
                ],
                "citations": [{"source": "catalog, CS 484"}],
            },
        )
        self.info = Recorder("get_course_info", {"course": "CS 331", "found": False})

    def advisor(self, progress: Any = not_connected) -> CollegeAdvisor:
        return CollegeAdvisor(
            self.check,
            course_info=self.info,
            search=self.search,
            recommend=self.recommend,
            progress=progress,
        )


class Chat:
    """Multi-turn conversation through the real graph with fake tools."""

    def __init__(self, advisor: CollegeAdvisor) -> None:
        self.graph = build_graph(InMemorySaver(), agents=[advisor], classify=no_model)
        self.config = {"configurable": {"thread_id": "t"}}

    def say(self, text: str) -> dict[str, Any]:
        return self.graph.invoke(turn_input(text), self.config)


@pytest.mark.parametrize(
    ("message", "intent"),
    [
        ("What courses can I take in Spring Year 2?", "plan_next_term"),
        ("What should I take next semester?", "plan_next_term"),
        ("Can you recommend some classes for me?", "plan_next_term"),
        ("Check my graduation requirements", "degree_progress"),
        ("Am I on track to graduate?", "degree_progress"),
        ("Can I take CS 450?", "check_eligibility"),
        ("Can I take CS 450 next semester?", "check_eligibility"),
        ("what are the prereqs for cs331", "check_eligibility"),
        ("Tell me about CS 331", "course_info"),
        ("Who teaches CS 331?", "course_info"),
        ("CS 331", "course_info"),
        ("Are there any courses on machine learning?", "find_courses"),
        ("I've taken CS 115 and MATH 151", "record_courses"),
        ("hi", "help"),
        ("hey there!", "help"),
        ("good morning", "help"),
        ("What can you do?", "help"),
    ],
)
def test_routing(message: str, intent: str) -> None:
    assert route(message, no_model).intent == intent


def test_plan_asks_completed_once_and_remembers_it() -> None:
    tools = Tools()
    chat = Chat(tools.advisor())

    first = chat.say("What courses can I take in Spring Year 2?")
    assert first["pending_field"] == "completed_courses"
    assert tools.recommend.calls == []

    second = chat.say("CS 115, CS 116")
    assert tools.recommend.calls == [
        {"completed_courses": ["CS 115", "CS 116"], "subject": None, "term": "Spring Year 2"}
    ]
    assert "CS 331" in second["answer"] and "[1]" in second["answer"]

    chat.say("Can I take CS 450?")  # profile carries over: no second question
    assert tools.check.calls == [
        {
            "course": "CS 450",
            "completed_courses": ["CS 115", "CS 116"],
            "grades": None,
            "in_progress_courses": None,
        }
    ]


def test_unavailable_requested_term_is_called_out() -> None:
    tools = Tools()
    tools.recommend.result = recommend_result(requested="Spring Year 2")
    chat = Chat(tools.advisor())
    chat.say("I've taken CS 115 and CS 116")
    answer = chat.say("What courses can I take in Spring Year 2?")["answer"]
    assert "only have the Fall 2026 schedule" in answer


def test_freshman_is_asked_for_subject() -> None:
    tools = Tools()
    chat = Chat(tools.advisor())
    chat.say("What should I take next semester?")
    asked = chat.say("none")
    assert asked["pending_field"] == "subject"
    chat.say("computer science")
    assert tools.recommend.calls[-1]["subject"] == "CS"
    assert tools.recommend.calls[-1]["completed_courses"] == []


def test_degree_progress_degrades_gracefully_until_service_exists() -> None:
    state = Chat(Tools().advisor()).say("Check my graduation requirements")
    assert state["answer"] == DEGREE_PROGRESS_UNAVAILABLE
    assert state["tool_calls"][0]["error"] == "not implemented"


def test_topic_change_mid_question_reroutes() -> None:
    tools = Tools()
    chat = Chat(tools.advisor())
    assert chat.say("Can I take CS 450?")["pending_field"] == "completed_courses"
    state = chat.say("Actually, check my graduation requirements")
    assert state["intent"] == "degree_progress"
    assert state["pending_field"] is None and tools.check.calls == []


def test_answer_to_pending_question_is_not_rerouted() -> None:
    tools = Tools()
    chat = Chat(tools.advisor())
    chat.say("Can I take CS 450?")
    chat.say("I've taken CS 351")  # looks like record_courses, but it answers the question
    assert tools.check.calls == [
        {
            "course": "CS 450",
            "completed_courses": ["CS 351"],
            "grades": None,
            "in_progress_courses": None,
        }
    ]


def test_find_courses_extracts_topic() -> None:
    tools = Tools()
    state = Chat(tools.advisor()).say("Are there any courses on machine learning?")
    assert tools.search.calls == [{"query": "machine learning"}]
    assert "CS 484" in state["answer"]


def test_course_info_passes_known_completed_courses() -> None:
    tools = Tools()
    chat = Chat(tools.advisor())
    chat.say("I've taken CS 116")
    chat.say("Tell me about CS 331")
    assert tools.info.calls == [{"course": "CS 331", "completed_courses": ["CS 116"]}]


def test_tool_failure_returns_friendly_answer() -> None:
    def broken(**kwargs: Any) -> dict[str, Any]:
        raise RuntimeError("db down")

    broken.__name__ = "search_courses"  # an allowed tool that fails, not a refused one
    tools = Tools()
    tools.search = broken  # type: ignore[assignment]
    state = Chat(tools.advisor()).say("Any courses on databases?")
    assert state["answer"] == TOOL_FAILED


# --- eligibility contract: domain.prereq.evaluate -> tool fields -> rendered answer ---


def _answer(tree: dict[str, Any], completed: dict[str, str | None], **kw: Any) -> str:
    result = {
        "course": "CS 450",
        "found": True,
        "prerequisites": "CS 350 and (CS 351 or CS 331)",
        **eligibility_fields(evaluate(tree, completed, **kw)),
        "citations": [{"source": "IIT Banner course catalog, CS 450"}],
    }
    json.dumps(result)  # checkpointed and traced: must stay plain JSON
    return _render_eligibility(result)


def _course(code: str, minimum: str | None = "C") -> dict[str, Any]:
    return {"type": "course", "course": code, "minimum_grade": minimum, "concurrent": False}


TREE = {
    "type": "and",
    "children": [
        _course("CS 350"),
        {"type": "or", "children": [_course("CS 351"), _course("CS 331")]},
    ],
}


def test_eligibility_satisfied_cites_banner() -> None:
    text = _answer(TREE, {"CS 350": "B", "CS 331": "A"})
    assert text.startswith("You meet the listed prerequisites for CS 450 [1].")
    assert '"CS 350 and (CS 351 or CS 331)"' in text and "[1] IIT Banner" in text


def test_eligibility_unsatisfied_names_cheapest_branch_and_low_grade() -> None:
    text = _answer(TREE, {"CS 350": "D"})
    assert "Cheapest way to get there: CS 350 (C or better; you have D), CS 351" in text
    assert "CS 331" not in text.split("Catalog")[0]  # one OR branch, not both


def test_eligibility_pending_names_in_progress_course() -> None:
    text = _answer(TREE, {"CS 331": "A"}, in_progress=["CS 350"])
    assert "once you finish CS 350 (C or better)" in text


def test_eligibility_needs_grade_asks_for_it() -> None:
    text = _answer(TREE, {"CS 350": None, "CS 331": "A"})
    assert "depends on your grade in CS 350 (C or better)" in text
    assert "Upload your transcript" in text


def test_eligibility_flags_unreadable_and_test_score_parts() -> None:
    unread = {"type": "unparsed", "text": "INTR 999"}
    assert "confirm it with your academic advisor" in _answer(unread, {})
    test = {"type": "test", "test": "S11", "low": "600", "high": "800"}
    assert "test-score option I can't verify (S11 600-800)" in _answer(test, {})


def test_greeting_gets_a_short_reply_not_the_menu() -> None:
    assert Chat(Tools().advisor()).say("hello!")["answer"] == GREETING


def test_repeated_greetings_do_not_repeat_the_same_reply() -> None:
    chat = Chat(Tools().advisor())
    answers = [chat.say("hi")["answer"] for _ in range(1 + len(GREETINGS_AGAIN))]
    assert answers[0] == GREETING
    assert answers[1:] == list(GREETINGS_AGAIN)


def test_asking_what_it_can_do_still_gets_the_full_menu() -> None:
    chat = Chat(Tools().advisor())
    chat.say("hey")
    assert chat.say("What can you do?")["answer"] == HELP
