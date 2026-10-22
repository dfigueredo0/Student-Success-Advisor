"""Career Services through the real graph: routing, one question per turn, cited answers,
and the per-agent tool allow-list."""

from typing import Any

import pytest
from langgraph.checkpoint.memory import InMemorySaver

from agents.base import TOOL_FAILED
from agents.career_advisor import CareerAdvisor
from agents.college_advisor import CollegeAdvisor
from orchestrator.graph import build_graph
from orchestrator.router import route
from orchestrator.state import turn_input
from tests.agent.fakes import FakeLLM, FakeTool, eligibility_result


def career_result() -> dict[str, Any]:
    return {
        "career_goal": "data scientist",
        "gap": ["machine learning"],
        "skipped": [],
        "matches": [
            {
                "skill": "machine learning",
                "courses": [
                    {"code": "CS 484", "title": "Intro to Machine Learning", "credits": 3.0}
                ],
            }
        ],
        "citations": [{"source": "IIT Banner course catalog, CS 484, term 202710"}],
    }


class Chat:
    def __init__(self, llm: FakeLLM | None = None, find: FakeTool | None = None) -> None:
        self.find = find or FakeTool("find_courses_for_skills", career_result())
        self.check = FakeTool("check_prerequisites", eligibility_result())
        agents = [CollegeAdvisor(self.check), CareerAdvisor(self.find)]
        # Default: the model routes the opening career question, and nothing after it.
        self.llm = llm or FakeLLM(FakeLLM.route("career_advice", 0.9))
        self.graph = build_graph(
            InMemorySaver(), agents=agents, classify=self.llm.classify, fill=self.llm.fill
        )
        self.config = {"configurable": {"thread_id": "t"}}

    def say(self, text: str) -> dict[str, Any]:
        return self.graph.invoke(turn_input(text), self.config)


@pytest.mark.parametrize(
    "message",
    [
        "What skills do I need to become a data scientist?",
        "I want a career in cybersecurity",
        "How do I get an internship?",
    ],
)
def test_career_messages_are_routed_by_the_model(message: str) -> None:
    llm = FakeLLM(FakeLLM.route("career_advice", 0.9))
    r = route(message, llm.classify)
    assert (r.intent, r.agent, r.source) == ("career_advice", "career_advisor", "model")


def test_scaffold_asks_one_field_per_turn_then_calls_tool_and_cites() -> None:
    chat = Chat()

    first = chat.say("What skills do I need to become a data scientist?")
    assert first["route"] == "career_advisor"
    assert first["pending_field"] == "current_skills"  # goal was taken from the message
    assert chat.find.calls == []

    second = chat.say("Python, statistics")
    assert second["pending_field"] == "desired_skills" and chat.find.calls == []

    third = chat.say("machine learning and python")
    assert chat.find.calls == [
        {
            "career_goal": "data scientist",
            "current_skills": ["Python", "statistics"],
            "desired_skills": ["machine learning", "python"],
        }
    ]
    assert [c["name"] for c in third["tool_calls"]] == ["find_courses_for_skills"]
    assert "CS 484" in third["answer"] and "[1]" in third["answer"] and third["citations"]
    assert "haven't checked prerequisites" in third["answer"]
    assert chat.check.calls == []  # no agent-to-agent hop


def test_model_routes_vague_career_question_and_goal_is_asked() -> None:
    chat = Chat(FakeLLM(FakeLLM.route("career_advice", 0.85)))
    state = chat.say("I am not sure what I want to do after college")
    assert (state["route_source"], state["route"]) == ("model", "career_advisor")
    assert state["pending_field"] == "career_goal"


def _python_then(*replies: dict[str, Any]) -> Chat:
    """A finished Python lookup for a data scientist; `replies` script the turns after it."""
    chat = Chat(FakeLLM(FakeLLM.route("career_advice", 0.9), *replies))
    chat.say("What skills do I need to become a data scientist?")
    chat.say("none")
    chat.say("Python")
    return chat


def test_follow_up_keeps_the_goal_and_looks_up_only_the_new_skill() -> None:
    chat = _python_then({"desired_skills": "SQL"})

    state = chat.say("and for SQL?")

    assert chat.find.calls[-1] == {
        "career_goal": "data scientist",
        "current_skills": [],
        "desired_skills": ["SQL"],
    }
    # "and ..." right after a request is that request again: no routing call, one fill call.
    assert state["route_source"] == "regex" and state["pending_field"] is None
    assert len(chat.llm.requests) == 2
    assert "CS 484" in state["answer"] and state["citations"]
    fill_prompt = chat.llm.requests[-1]["messages"][0]["content"]
    # The conversation, without citation lines or the advisor's "(e.g. Python, SQL)".
    assert "Student: Python\nAdvisor: Courses in the IIT catalog" in fill_prompt
    assert "[1] IIT Banner" not in fill_prompt and "e.g." not in fill_prompt
    assert "- desired_skills: Which skills do you want to build for that career?\n" in fill_prompt


def test_model_spotted_follow_up_continues_career_advice() -> None:
    chat = _python_then(FakeLLM.route("follow_up", 0.9), {"desired_skills": "machine learning"})

    state = chat.say("what about machine learning?")

    assert state["intent"] == "career_advice" and state["route_source"] == "model"
    assert chat.find.calls[-1]["desired_skills"] == ["machine learning"]
    route_prompt = chat.llm.requests[1]["messages"][0]["content"]
    assert "Student: Python\nAdvisor: Courses in the IIT catalog" in route_prompt
    assert route_prompt.endswith("Message: what about machine learning?\nIntent:")


def test_follow_up_value_not_in_the_conversation_is_ignored() -> None:
    chat = _python_then({"desired_skills": "Rust"})
    state = chat.say("and for SQL?")
    assert len(chat.find.calls) == 1  # only the Python lookup
    assert state["pending_field"] == "desired_skills"  # asks instead of guessing


def test_none_is_a_valid_current_skills_answer() -> None:
    chat = Chat()
    chat.say("I want to become a software engineer")
    chat.say("none")
    chat.say("Java")
    assert chat.find.calls[0]["current_skills"] == []
    assert chat.find.calls[0]["career_goal"] == "software engineer"


def test_career_agent_cannot_call_advisor_tools() -> None:
    sneaky = FakeTool("check_prerequisites", eligibility_result())
    chat = Chat(find=sneaky)
    chat.say("I want to become a data scientist")
    chat.say("none")
    state = chat.say("SQL")
    assert sneaky.calls == []
    assert state["answer"] == TOOL_FAILED
    assert "ToolNotAllowed" in state["tool_calls"][0]["error"]


@pytest.mark.parametrize("agent", [CollegeAdvisor(), CareerAdvisor()], ids=lambda a: a.name)
def test_every_scaffold_tool_is_on_its_agents_allow_list(agent: Any) -> None:
    assert {s.tool.__name__ for s in agent.scaffolds.values()} <= agent.allowed_tools
    assert agent.allowed_tools  # an agent with no tools allowed is a config mistake


def test_agent_allow_lists_do_not_overlap() -> None:
    assert not CollegeAdvisor.allowed_tools & CareerAdvisor.allowed_tools
