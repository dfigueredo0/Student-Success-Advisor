import json
import time
from datetime import UTC, datetime
from typing import Any

import httpx
from fastapi.testclient import TestClient
from langfuse import get_client
from sqlalchemy import Engine, text

from api.main import app
from api.tracing import trace_session_id


def stored(api: TestClient, thread_id: str) -> dict[str, Any]:
    """The conversation as the server keeps it; normal responses no longer carry it."""
    return api.app.state.graph.get_state({"configurable": {"thread_id": thread_id}}).values


def test_one_request_creates_one_trace_with_expected_spans(langfuse: httpx.Client) -> None:
    with TestClient(app) as api:
        resp = api.post("/chat", json={"message": "Can I take CS 450? I've taken CS 351."})
        assert resp.status_code == 200, resp.text
        body = resp.json()
        tool_calls = stored(api, body["thread_id"])["tool_calls"]
        get_client().flush()
    assert body["trace_id"]
    assert [c["name"] for c in tool_calls] == ["check_prerequisites"]

    expected = ["chat", "check_prerequisites", "college_advisor", "merge", "router"]
    names: list[str] = []
    deadline = time.monotonic() + 60  # ingestion is asynchronous
    while time.monotonic() < deadline:
        got = langfuse.get(f"/api/public/traces/{body['trace_id']}")
        if got.status_code == 200:
            names = sorted(o["name"] for o in got.json()["observations"])
            if names == expected:
                break
        time.sleep(1)
    assert names == expected

    session = trace_session_id(body["thread_id"])
    traces = langfuse.get("/api/public/traces", params={"sessionId": session})
    assert [t["id"] for t in traces.json()["data"]] == [body["trace_id"]]


def test_conversation_resumes_from_postgres_after_restart() -> None:
    with TestClient(app) as api:  # first process: agent asks for the missing field
        first = api.post("/chat", json={"message": "Can I take CS 450?"}).json()
        assert stored(api, first["thread_id"])["tool_calls"] == []
    assert first["pending_field"] == "completed_courses"

    # Lifespan exit closed the graph and its checkpointer connection; a new lifespan
    # is a fresh process as far as conversation state goes.
    with TestClient(app) as api:
        second = api.post(
            "/chat", json={"message": "CS 351", "thread_id": first["thread_id"]}
        ).json()
        kept = stored(api, first["thread_id"])
    assert kept["tool_calls"][0]["args"] == {
        "course": "CS 450",
        "completed_courses": ["CS 351"],
        "grades": None,
        "in_progress_courses": None,
    }
    assert [m["role"] for m in kept["messages"]] == ["user", "assistant"] * 2
    assert second["pending_field"] is None


def test_drop_question_checks_the_real_catalog_and_logs_one_verifier_run(engine: Engine) -> None:
    """UC-09 on the loaded catalog: CS 450 lists CS 351 as a prerequisite."""
    with TestClient(app) as api:
        thread = api.post("/chat", json={"message": "hi"}).json()["thread_id"]
        profile = {"in_progress_courses": ["CS 350", "CS 351"], "completed_courses": ["CS 331"]}
        api.app.state.graph.update_state(
            {"configurable": {"thread_id": thread}}, {"profile": profile}, as_node="merge"
        )
        start = datetime.now(UTC)
        body = api.post(
            "/chat", json={"message": "What happens if I drop CS 351?", "thread_id": thread}
        ).json()
        args = stored(api, thread)["tool_calls"][0]["args"]

    assert "CS 450 - Operating Systems" in body["answer"] and body["citations"]
    with engine.connect() as conn:
        runs = conn.execute(
            text(
                "SELECT verifier, passed, failure_reasons FROM verifier_run "
                "WHERE input_state = CAST(:args AS jsonb) AND created_at >= :start"
            ),
            {"args": json.dumps(args), "start": start},
        ).all()
    [(verifier, passed, reasons)] = runs  # exactly one row for the one check
    assert verifier == "check_consequences" and passed is False
    assert "prereq_blocked:CS 450" in reasons
