"""A job posting pasted or linked in chat: compared with the student's skills, never sent to
the model, and not handed off for the boilerplate postings carry."""

from pathlib import Path
from typing import Any

from langgraph.checkpoint.memory import InMemorySaver

from agents.career_advisor import ASK_SKILLS, CareerAdvisor
from agents.college_advisor import CollegeAdvisor
from orchestrator.graph import build_graph
from orchestrator.state import turn_input
from tests.agent.fakes import FakeLLM, FakeTool, eligibility_result

POSTING = (Path(__file__).parents[1] / "fixtures" / "posting" / "synthetic.txt").read_text().strip()
LINK = "https://jobs.lever.co/acme/123"
SKILLS = {"current_skills": ["Python", "SQL"]}
ANSWER = FakeLLM.route("follow_up", 0.9)


def fit_result() -> dict[str, Any]:
    return {
        "reason": None,
        "matched": ["Python", "SQL"],
        "missing": ["Docker"],
        "courses": None,
        "citations": [],
    }


class Chat:
    def __init__(self, *replies: dict[str, Any], profile: dict[str, Any] | None = None) -> None:
        self.compare = FakeTool("compare_to_posting", fit_result())
        agents = [
            CollegeAdvisor(FakeTool("check_prerequisites", eligibility_result())),
            CareerAdvisor(FakeTool("find_courses_for_skills", {}), posting=self.compare),
        ]
        self.llm = FakeLLM(*replies)
        self.graph = build_graph(
            InMemorySaver(), agents=agents, classify=self.llm.classify, fill=self.llm.fill
        )
        self.config = {"configurable": {"thread_id": "t"}}
        if profile:
            self.graph.update_state(self.config, {"profile": profile}, as_node="merge")

    def say(self, text: str) -> dict[str, Any]:
        return self.graph.invoke(turn_input(text), self.config)


def test_pasted_posting_is_compared_without_any_model_call() -> None:
    chat = Chat(profile=SKILLS)  # no scripted replies: any model call fails the test
    chat.say("hello")  # an earlier turn, so a follow-up read would be possible

    state = chat.say(POSTING)

    # "visa sponsorship", "legally authorized", "tuition reimbursement": not a hand-off here
    assert (state["intent"], state["route_source"]) == ("posting_fit", "regex")
    assert chat.compare.calls == [{"posting": POSTING, "current_skills": ["Python", "SQL"]}]
    assert "- To add: Docker" in state["answer"] and state["pending_field"] is None
    assert chat.llm.requests == []


def test_posting_stays_out_of_later_model_prompts() -> None:
    chat = Chat(FakeLLM.route("help", 0.9), profile=SKILLS)
    chat.say(POSTING)

    chat.say("ok, and what else can you tell me?")

    prompt = chat.llm.requests[-1]["messages"][0]["content"]
    assert "Student: [a job posting]" in prompt
    assert "Acme Robotics" not in prompt and "visa sponsorship" not in prompt


def test_link_while_another_question_is_open_starts_the_posting_flow() -> None:
    chat = Chat(profile=SKILLS)
    assert chat.say("Can I take CS 450?")["pending_field"] == "completed_courses"

    state = chat.say(LINK)

    assert state["intent"] == "posting_fit" and state["pending_field"] is None
    assert chat.compare.calls == [{"posting": LINK, "current_skills": ["Python", "SQL"]}]


def test_without_skills_on_record_it_asks_then_compares() -> None:
    chat = Chat(ANSWER)

    asked = chat.say(POSTING)
    assert (asked["pending_field"], asked["answer"]) == ("current_skills", ASK_SKILLS)

    chat.say("Python and SQL")
    assert chat.compare.calls == [{"posting": POSTING, "current_skills": ["Python", "SQL"]}]


def test_second_posting_replaces_the_first_and_is_not_read_as_skills() -> None:
    chat = Chat()
    chat.say(POSTING)

    state = chat.say(f"actually this one {LINK}")

    assert state["pending_field"] == "current_skills" and chat.compare.calls == []
    assert state["slots"] == {"posting": f"actually this one {LINK}"}
    assert "current_skills" not in state["profile"]


SHORT = "Requirements: Python, SQL, 2+ years of experience. No visa sponsorship."


def unreadable_link() -> Chat:
    """A chat whose link could not be opened, so the advisor asked for the text instead."""
    chat = Chat(profile=SKILLS)  # no scripted replies: any model call fails the test
    chat.compare.result = fit_result() | {"reason": "unreadable"}
    asked = chat.say(LINK)
    assert asked["pending_field"] == "posting" and "requirements section" in asked["answer"]
    chat.compare.result = fit_result()
    return chat


def test_requirements_pasted_after_a_link_fails_are_the_posting_not_a_question() -> None:
    """Too short to look like a posting, and "visa" would hand it off as the student's own
    question: it is the text the advisor just asked for."""
    chat = unreadable_link()

    state = chat.say(SHORT)

    assert state["handoff"] is None and state["intent"] == "posting_fit"
    assert chat.compare.calls[-1] == {"posting": SHORT, "current_skills": ["Python", "SQL"]}
    assert state["pending_field"] is None and chat.llm.requests == []


def test_requirements_pasted_when_asked_stay_out_of_later_model_prompts() -> None:
    chat = unreadable_link()
    chat.say(SHORT)
    chat.llm.replies.append(FakeLLM.route("help", 0.9))

    chat.say("ok, and what else can you tell me?")

    prompt = chat.llm.requests[-1]["messages"][0]["content"]
    assert "visa sponsorship" not in prompt and "Student: [a job posting]" in prompt


def test_a_clear_new_request_still_changes_topic_while_a_posting_is_awaited() -> None:
    chat = unreadable_link()
    chat.llm.replies.append({})  # the new request's follow-up read of the conversation

    state = chat.say("Can I take CS 450?")

    # Routed by its pattern, not by the model; the posting flow is dropped, not fed this text.
    assert (state["intent"], state["route_source"]) == ("check_eligibility", "regex")
    assert len(chat.compare.calls) == 1 and state["pending_field"] == "completed_courses"
    assert LINK not in chat.llm.requests[-1]["messages"][0]["content"]


def test_asked_to_compare_first_then_given_the_posting() -> None:
    chat = Chat(FakeLLM.route("posting_fit", 0.9), profile=SKILLS)

    asked = chat.say("Can you compare my skills with a job posting?")
    assert asked["pending_field"] == "posting" and "link" in asked["answer"]

    chat.say(POSTING)
    assert chat.compare.calls == [{"posting": POSTING, "current_skills": ["Python", "SQL"]}]
    assert len(chat.llm.requests) == 1  # the posting itself was routed by its shape
