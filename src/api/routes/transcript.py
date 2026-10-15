"""POST /transcript: seed a conversation's profile from an unofficial transcript PDF.

The body is the raw PDF (Content-Type: application/pdf). Completed courses, grades, in-progress
courses and major are merged into the thread's profile, so the advisor stops asking for them.
"""

import uuid
from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.concurrency import run_in_threadpool
from langfuse import get_client, propagate_attributes
from pydantic import BaseModel

from tools.advisor.parse_transcript import MAX_BYTES, TranscriptRejected, parse_transcript

router = APIRouter()


class TranscriptResponse(BaseModel):
    thread_id: str
    completed_courses: list[str]
    in_progress_courses: list[str]


async def _read_capped(request: Request) -> bytes:
    body = bytearray()
    async for chunk in request.stream():
        body += chunk
        if len(body) > MAX_BYTES:
            raise HTTPException(413, "That file is too large for a transcript (5 MB max).")
    return bytes(body)


def merge_into_profile(profile: dict[str, Any], record: dict[str, Any]) -> dict[str, Any]:
    """The transcript wins on grades; courses the student mentioned in chat are kept."""
    out = dict(profile)
    known = out.get("completed_courses") or []
    out["completed_courses"] = list(dict.fromkeys([*known, *record["completed_courses"]]))
    out["grades"] = {**(out.get("grades") or {}), **record["grades"]}
    out["in_progress_courses"] = record["in_progress_courses"]
    if record["major"]:
        out["major"] = record["major"]
    return out


# TODO: needs impl - bind thread_id to the authenticated student (api.auth), as for /chat.
@router.post("/transcript")
async def upload_transcript(
    request: Request, thread_id: str | None = Query(default=None, max_length=64)
) -> TranscriptResponse:
    thread_id = thread_id or uuid.uuid4().hex
    content = await _read_capped(request)
    langfuse = get_client()
    # The span records sizes and counts only: transcript contents never go into a trace.
    with (
        langfuse.start_as_current_observation(
            name="parse_transcript", as_type="tool", input={"bytes": len(content)}
        ) as span,
        propagate_attributes(session_id=thread_id),
    ):
        try:
            record = await run_in_threadpool(parse_transcript, content)
        except TranscriptRejected as exc:
            span.update(output={"rejected": True})
            raise HTTPException(422, str(exc)) from exc
        span.update(
            output={
                "completed": len(record["completed_courses"]),
                "in_progress": len(record["in_progress_courses"]),
            }
        )

    graph = request.app.state.graph
    config = {"configurable": {"thread_id": thread_id}}

    def save() -> None:
        current = graph.get_state(config).values or {}
        profile = merge_into_profile(current.get("profile") or {}, record)
        graph.update_state(config, {"profile": profile}, as_node="merge")

    await run_in_threadpool(save)
    return TranscriptResponse(
        thread_id=thread_id,
        completed_courses=record["completed_courses"],
        in_progress_courses=record["in_progress_courses"],
    )
