import time

import httpx
from fastapi.testclient import TestClient
from langfuse import get_client

from api.main import app


def test_one_request_creates_one_trace_with_expected_spans(langfuse: httpx.Client) -> None:
    with TestClient(app) as api:
        resp = api.post("/chat", json={"message": "Can I take CS 450? I've taken CS 351."})
        assert resp.status_code == 200, resp.text
        body = resp.json()
        get_client().flush()
    assert body["trace_id"]
    assert [c["name"] for c in body["tool_calls"]] == ["check_prerequisites"]

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

    traces = langfuse.get("/api/public/traces", params={"sessionId": body["thread_id"]})
    assert [t["id"] for t in traces.json()["data"]] == [body["trace_id"]]


def test_conversation_resumes_from_postgres_after_restart() -> None:
    with TestClient(app) as api:  # first process: agent asks for the missing field
        first = api.post("/chat", json={"message": "Can I take CS 450?"}).json()
    assert first["tool_calls"] == []
    assert first["state"]["pending_field"] == "completed_courses"

    # Lifespan exit closed the graph and its checkpointer connection; a new lifespan
    # is a fresh process as far as conversation state goes.
    with TestClient(app) as api:
        second = api.post(
            "/chat", json={"message": "CS 351", "thread_id": first["thread_id"]}
        ).json()
    assert second["tool_calls"][0]["args"] == {"course": "CS 450", "completed_courses": ["CS 351"]}
    assert [m["role"] for m in second["state"]["messages"]] == ["user", "assistant"] * 2
    assert second["state"]["pending_field"] is None
