"""Trace retention: delete Langfuse traces older than LANGFUSE_TRACE_RETENTION_DAYS.

Traces keep each message's text, so attacks can be read in the weekly review, but students
type more than attacks. Self-hosted Langfuse only deletes old data by itself in the paid
Enterprise Edition, so the API does it through Langfuse's public API, alongside the
conversation purge in api/main.py. It covers every trace in the project, the gateway's
included. Deletion in Langfuse is asynchronous: traces disappear within minutes.
"""

from datetime import UTC, datetime, timedelta

import httpx

PAGE = 100  # Langfuse's largest page; also the batch size for each delete call
MAX_PER_RUN = 10_000  # bounds one run; anything left is deleted on the next


def delete_old_traces(client: httpx.Client, max_age: timedelta, now: datetime | None = None) -> int:
    """Delete every trace older than `max_age`; return how many were sent for deletion.

    `client` is set up with Langfuse's base URL and the project's API keys.
    """
    cutoff = ((now or datetime.now(UTC)) - max_age).isoformat().replace("+00:00", "Z")
    ids: list[str] = []
    page = 1
    while len(ids) < MAX_PER_RUN:
        resp = client.get(
            "/api/public/traces",
            params={"toTimestamp": cutoff, "limit": PAGE, "page": page, "fields": "core"},
        )
        resp.raise_for_status()
        batch = [t["id"] for t in resp.json()["data"]]
        ids += batch
        if len(batch) < PAGE:
            break
        page += 1
    for start in range(0, len(ids), PAGE):
        resp = client.request(
            "DELETE", "/api/public/traces", json={"traceIds": ids[start : start + PAGE]}
        )
        resp.raise_for_status()
    return len(ids)
