"""Uploading a transcript seeds the profile, so the advisor stops asking for completed courses."""

from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from langgraph.checkpoint.memory import InMemorySaver

from agents.college_advisor import CollegeAdvisor
from api.main import app
from orchestrator.graph import build_graph
from tests.agent.fakes import FakeLLM, FakeTool, eligibility_result
from tools.advisor import parse_transcript as tool

TEXT = (Path(__file__).parents[1] / "fixtures" / "transcript" / "synthetic.txt").read_text()


@pytest.fixture
def pdf(monkeypatch: pytest.MonkeyPatch) -> None:
    """Any upload reads as the synthetic transcript."""
    monkeypatch.setattr(tool, "pdf_text", lambda content: TEXT)


@pytest.fixture
def api() -> Iterator[tuple[TestClient, FakeTool]]:
    check = FakeTool("check_prerequisites", eligibility_result())
    # No `with`: lifespan (Postgres checkpointer) stays off; the graph is in memory.
    app.state.graph = build_graph(
        InMemorySaver(), agents=[CollegeAdvisor(check)], classify=FakeLLM().classify
    )
    yield TestClient(app), check
    del app.state.graph


@pytest.mark.usefixtures("pdf")
def test_upload_seeds_profile_and_advisor_does_not_ask(api: tuple[TestClient, FakeTool]) -> None:
    client, check = api
    up = client.post("/transcript", content=b"%PDF-", headers={"content-type": "application/pdf"})
    assert up.status_code == 200, up.text
    thread = up.json()["thread_id"]
    assert up.json()["in_progress_courses"] == ["CS 350", "CS 351"]

    chat = client.post("/chat", json={"message": "Can I take CS 450?", "thread_id": thread}).json()

    assert check.calls == [
        {"course": "CS 450", "completed_courses": ["MATH 151", "CS 115", "CS 116", "CS 331"]}
    ]
    assert chat["state"]["profile"]["grades"]["CS 331"] == "C+"


@pytest.mark.usefixtures("pdf")
def test_upload_keeps_courses_mentioned_in_chat(api: tuple[TestClient, FakeTool]) -> None:
    client, _ = api
    thread = client.post("/chat", json={"message": "I've taken CS 100"}).json()["thread_id"]
    client.post(f"/transcript?thread_id={thread}", content=b"%PDF-")
    state = client.app.state.graph.get_state({"configurable": {"thread_id": thread}}).values
    assert state["profile"]["completed_courses"][0] == "CS 100"
    assert "CS 331" in state["profile"]["completed_courses"]


def test_rejected_upload_is_422_and_leaves_profile_alone(
    api: tuple[TestClient, FakeTool],
) -> None:
    client, _ = api
    resp = client.post("/transcript?thread_id=t1", content=b"not a pdf")
    assert resp.status_code == 422
    assert "PDF" in resp.json()["detail"]
    assert client.app.state.graph.get_state({"configurable": {"thread_id": "t1"}}).values == {}
