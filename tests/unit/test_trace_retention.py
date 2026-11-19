"""api/trace_retention.py deletes Langfuse traces older than the retention period."""

import json
from datetime import UTC, datetime, timedelta

import httpx
import pytest

from api.trace_retention import PAGE, delete_old_traces

NOW = datetime(2026, 11, 19, 12, 0, tzinfo=UTC)


class FakeLangfuse:
    """Serves `old` trace IDs in pages for any toTimestamp and records deletes."""

    def __init__(self, old: list[str]) -> None:
        self.old = old
        self.cutoffs: list[str] = []
        self.deleted: list[list[str]] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        if request.method == "GET":
            self.cutoffs.append(request.url.params["toTimestamp"])
            page, limit = int(request.url.params["page"]), int(request.url.params["limit"])
            data = [{"id": i} for i in self.old[(page - 1) * limit : page * limit]]
            return httpx.Response(200, json={"data": data, "meta": {"totalItems": len(self.old)}})
        self.deleted.append(json.loads(request.content)["traceIds"])
        return httpx.Response(200, json={"message": "Traces deleted successfully"})


def _client(fake: FakeLangfuse) -> httpx.Client:
    return httpx.Client(base_url="http://langfuse", transport=httpx.MockTransport(fake))


def test_asks_only_for_traces_older_than_the_retention_period() -> None:
    fake = FakeLangfuse([])
    assert delete_old_traces(_client(fake), timedelta(days=7), now=NOW) == 0
    assert fake.cutoffs == ["2026-11-12T12:00:00Z"]
    assert fake.deleted == []  # nothing old: no delete call at all


def test_deletes_every_page_in_batches() -> None:
    old = [f"t{i}" for i in range(PAGE * 2 + 5)]
    fake = FakeLangfuse(old)
    assert delete_old_traces(_client(fake), timedelta(days=7), now=NOW) == len(old)
    assert [len(batch) for batch in fake.deleted] == [PAGE, PAGE, 5]
    assert [i for batch in fake.deleted for i in batch] == old


def test_a_langfuse_error_is_raised_for_the_caller_to_log() -> None:
    def broken(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"message": "Invalid credentials"})

    client = httpx.Client(base_url="http://langfuse", transport=httpx.MockTransport(broken))
    with pytest.raises(httpx.HTTPStatusError):
        delete_old_traces(client, timedelta(days=7), now=NOW)
