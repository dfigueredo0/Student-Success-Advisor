"""Uploading a resume seeds the profile's skills, so the Career agent stops asking for them."""

from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from langgraph.checkpoint.memory import InMemorySaver

from agents.career_advisor import CareerAdvisor
from agents.college_advisor import CollegeAdvisor
from api.main import app
from domain.skills import build_vocab
from orchestrator.graph import build_graph
from tests.agent.fakes import FakeLLM, FakeTool, eligibility_result
from tools.career import onet
from tools.career import resume_parser as tool

TEXT = (Path(__file__).parents[1] / "fixtures" / "resume" / "synthetic.txt").read_text()
VOCAB = build_vocab(["Python", "Oracle Java", "Structured query language SQL", "Docker"])
SKILLS = ["Python", "Java", "SQL", "Docker"]
CAREER = FakeLLM.route("career_advice", 0.9)
ANSWER = FakeLLM.route("follow_up", 0.9)


@pytest.fixture
def pdf(monkeypatch: pytest.MonkeyPatch) -> None:
    """Any upload reads as the synthetic resume."""
    monkeypatch.setattr(tool, "pdf_text", lambda content, what: TEXT)
    monkeypatch.setattr(onet, "vocabulary", lambda: VOCAB)


class Api:
    def __init__(self, *replies: dict[str, Any]) -> None:
        self.find = FakeTool("find_courses_for_skills", {"career_goal": "x", "gap": []})
        check = FakeTool("check_prerequisites", eligibility_result())
        self.llm = FakeLLM(*replies)
        # No `with`: lifespan (Postgres checkpointer) stays off; the graph is in memory.
        app.state.graph = build_graph(
            InMemorySaver(),
            agents=[CollegeAdvisor(check), CareerAdvisor(self.find)],
            classify=self.llm.classify,
            fill=self.llm.fill,
        )
        self.client = TestClient(app)

    def say(self, message: str, thread: str | None = None) -> dict[str, Any]:
        return self.client.post("/chat", json={"message": message, "thread_id": thread}).json()

    def upload(self, thread: str | None = None, content: bytes = b"%PDF-") -> Any:
        headers = {"content-type": "application/pdf"} | ({"X-Thread-Id": thread} if thread else {})
        return self.client.post("/resume", content=content, headers=headers)

    def profile(self, thread: str) -> dict[str, Any]:
        state = app.state.graph.get_state({"configurable": {"thread_id": thread}}).values
        return state.get("profile") or {}


@pytest.fixture
def api() -> Iterator[type[Api]]:
    yield Api
    del app.state.graph


@pytest.mark.usefixtures("pdf")
def test_upload_seeds_skills_and_the_career_agent_does_not_ask_for_them(api: type[Api]) -> None:
    a = api(CAREER, ANSWER)
    up = a.upload()
    assert up.status_code == 200, up.text
    assert up.json() | {"thread_id": ""} == {
        "thread_id": "",
        "skills": SKILLS,
        "degree_level": "bachelor",
        "graduation_year": 2027,
        "answers_question": False,
    }
    thread = up.json()["thread_id"]

    first = a.say("What skills do I need to become a data scientist?", thread)
    assert first["pending_field"] == "desired_skills"  # current skills came from the resume

    a.say("machine learning", thread)
    assert a.find.calls[0]["current_skills"] == SKILLS


@pytest.mark.usefixtures("pdf")
def test_upload_keeps_skills_typed_in_chat_and_the_rest_of_the_profile(api: type[Api]) -> None:
    a = api(CAREER, {}, ANSWER)  # route, a follow-up read that finds nothing, the answer
    thread = a.say("I've taken CS 100")["thread_id"]
    a.say("I want to become a data scientist", thread)
    a.say("statistics and python", thread)  # answers "Which skills do you already have?"

    assert a.upload(thread).json()["thread_id"] == thread

    profile = a.profile(thread)
    assert profile["current_skills"] == ["statistics", "python", "Java", "SQL", "Docker"]
    assert profile["completed_courses"] == ["CS 100"]
    assert (profile["degree_level"], profile["graduation_year"]) == ("bachelor", 2027)


@pytest.mark.usefixtures("pdf")
def test_upload_while_the_agent_waits_for_skills_answers_its_question(api: type[Api]) -> None:
    a = api(CAREER, ANSWER)
    asked = a.say("I want to become a data scientist")
    assert asked["pending_field"] == "current_skills"
    thread = asked["thread_id"]

    assert a.upload(thread).json()["answers_question"] is True

    # Whatever the student says next is not read as their skill list.
    after = a.say("Use my resume", thread)
    assert after["pending_field"] == "desired_skills"
    assert a.profile(thread)["current_skills"] == SKILLS


def test_rejected_upload_is_422_and_leaves_the_profile_alone(
    api: type[Api], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(onet, "vocabulary", lambda: VOCAB)
    a = api()
    resp = a.upload("t1", content=b"not a pdf")
    assert resp.status_code == 422
    assert "PDF" in resp.json()["detail"] and "transcript" not in resp.json()["detail"]
    assert app.state.graph.get_state({"configurable": {"thread_id": "t1"}}).values == {}


def test_missing_job_data_is_503(api: type[Api], monkeypatch: pytest.MonkeyPatch) -> None:
    def not_loaded() -> None:
        raise onet.OnetNotLoaded

    monkeypatch.setattr(tool, "pdf_text", lambda content, what: TEXT)
    monkeypatch.setattr(onet, "vocabulary", not_loaded)
    resp = api().upload()
    assert resp.status_code == 503 and "job data" in resp.json()["detail"]


@pytest.mark.usefixtures("pdf")
def test_saved_chat_profile_leaves_resume_data_out(api: type[Api]) -> None:
    """The saved file's profile holds courses, not what the resume added. (Its messages are the
    conversation as the student saw it, so a job-match answer in it still lists their skills.)"""
    a = api()
    thread = a.upload().json()["thread_id"]
    saved = a.client.get("/chat/export", headers={"X-Thread-Id": thread})
    assert saved.status_code == 200
    assert "Python" not in saved.text and "bachelor" not in saved.text
