"""POST /resume: seed a conversation's profile from a resume PDF.

The body is the raw PDF (Content-Type: application/pdf), as for POST /transcript. The skills,
degree level and graduation year read from it are merged into the thread's profile, so the
Career agent stops asking which skills the student has. Nothing else on the resume is read.
"""

import uuid
from typing import Any

from fastapi import APIRouter, Header, HTTPException, Request
from fastapi.concurrency import run_in_threadpool
from langfuse import get_client, propagate_attributes
from pydantic import BaseModel

from api.routes.transcript import read_capped
from api.tracing import trace_session_id
from domain.skills import normalize_skill
from tools.career.onet import OnetNotLoaded
from tools.career.resume_parser import ResumeRejected, parse_resume

router = APIRouter()

NOT_LOADED = (
    "I can't read resumes yet: the job data isn't loaded on this server (make ingest-onet)."
)


class ResumeResponse(BaseModel):
    thread_id: str
    skills: list[str]  # software and tools found, as the page should list them
    degree_level: str | None  # "associate" | "bachelor" | "master" | "doctorate"
    graduation_year: int | None
    # The advisor was waiting for the student's skills and the resume answered it: the page
    # sends a message so the open request continues.
    answers_question: bool


def merge_resume_into_profile(profile: dict[str, Any], record: dict[str, Any]) -> dict[str, Any]:
    """Skills the student typed in chat are kept; the resume adds the ones not yet listed."""
    out = dict(profile)
    known = out.get("current_skills") or []
    have = {normalize_skill(s) for s in known}
    out["current_skills"] = [
        *known,
        *(s for s in record["skills"] if normalize_skill(s) not in have),
    ]
    for key in ("degree_level", "graduation_year"):
        if record[key] is not None:
            out[key] = record[key]
    return out


# TODO: needs impl - bind thread_id to the authenticated student (api.auth), as for /chat.
@router.post("/resume")
async def upload_resume(
    request: Request,
    # A header, not a query parameter: URLs end up in access logs.
    thread_id: str | None = Header(default=None, alias="X-Thread-Id", max_length=64),
) -> ResumeResponse:
    thread_id = thread_id or uuid.uuid4().hex
    content = await read_capped(request, "resume")
    langfuse = get_client()
    # The span records sizes and counts only: resume contents never go into a trace.
    with (
        langfuse.start_as_current_observation(
            name="parse_resume", as_type="tool", input={"bytes": len(content)}
        ) as span,
        propagate_attributes(session_id=trace_session_id(thread_id)),
    ):
        try:
            record = await run_in_threadpool(parse_resume, content)
        except ResumeRejected as exc:
            span.update(output={"rejected": True})
            raise HTTPException(422, str(exc)) from exc
        except OnetNotLoaded as exc:
            raise HTTPException(503, NOT_LOADED) from exc
        span.update(output={"skills_found": len(record["skills"])})

    graph = request.app.state.graph
    config = {"configurable": {"thread_id": thread_id}}

    def save() -> bool:
        current = graph.get_state(config).values or {}
        profile = merge_resume_into_profile(current.get("profile") or {}, record)
        update: dict[str, Any] = {"profile": profile}
        # Mid-question the next message would be read as the skill list and replace these
        # (agents.base); filling the slot makes it continue the open request instead.
        waiting = current.get("pending_field") == "current_skills"
        if waiting:
            update["slots"] = {
                **(current.get("slots") or {}),
                "current_skills": profile["current_skills"],
            }
        graph.update_state(config, update, as_node="merge")
        return waiting

    answers_question = await run_in_threadpool(save)
    return ResumeResponse(
        thread_id=thread_id,
        skills=record["skills"],
        degree_level=record["degree_level"],
        graduation_year=record["graduation_year"],
        answers_question=answers_question,
    )
