"""Smoke tests for the compose stack. Run `make up` first."""

import time
import uuid
from datetime import UTC, datetime

import httpx
from sqlalchemy import Engine, text


def test_postgres_answers_with_pgvector(engine: Engine) -> None:
    with engine.connect() as conn:
        assert conn.execute(text("select 1")).scalar_one() == 1
        version = conn.execute(
            text("select extversion from pg_extension where extname = 'vector'")
        ).scalar_one_or_none()
        server = conn.execute(text("show server_version_num")).scalar_one()
    assert version is not None, "vector extension is not installed in the app database"
    assert int(server) // 10000 == 16


def test_litellm_health_reports_local_model_healthy(litellm: httpx.Client) -> None:
    # /health actively probes every configured deployment, so this proves the
    # `local-llm` alias really reaches Ollama, not just that the proxy is up.
    resp = litellm.get("/health")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["unhealthy_count"] == 0, body["unhealthy_endpoints"]
    assert body["healthy_count"] >= 1


def test_langfuse_trace_can_be_written_and_read_back(langfuse: httpx.Client) -> None:
    trace_id = str(uuid.uuid4())
    now = datetime.now(UTC).isoformat()
    event = {
        "id": str(uuid.uuid4()),
        "timestamp": now,
        "type": "trace-create",
        "body": {"id": trace_id, "name": "phase0-smoke", "timestamp": now},
    }
    resp = langfuse.post("/api/public/ingestion", json={"batch": [event]})
    assert resp.status_code == 207, resp.text
    assert resp.json()["errors"] == []

    # Ingestion is asynchronous (web -> S3/redis -> worker -> ClickHouse).
    deadline = time.monotonic() + 60
    while time.monotonic() < deadline:
        got = langfuse.get(f"/api/public/traces/{trace_id}")
        if got.status_code == 200:
            assert got.json()["name"] == "phase0-smoke"
            return
        time.sleep(1)
    raise AssertionError(f"trace {trace_id} was accepted but never became readable")
