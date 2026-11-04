"""GET /chat/export and POST /chat/import: a student saves a conversation to a file and loads
it later, instead of logging in (there are no accounts).

The saved file holds the profile (completed and in-progress courses, grades, major) and the
messages. An imported file is untrusted - the student can edit it - so:
- every field is checked against a strict format, and the body size is capped;
- only the profile goes back into the advisor's memory, marked as imported, so the advisor
  says it came from a saved chat, not from a transcript;
- the messages are echoed back for the page to show, but never become the conversation's
  history: the router and follow-up filler read the history, and the injection guardrail
  only checks new messages.
"""

import uuid
from datetime import UTC, datetime
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Header, HTTPException, Request
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel, ConfigDict, Field, StringConstraints, ValidationError

router = APIRouter()

MAX_BYTES = 1_000_000  # 200 messages of 4,000 characters is about 800 kB

CourseCode = Annotated[str, StringConstraints(pattern=r"^[A-Z]{2,4} \d{3}[A-Z]?$")]
# The grades the transcript parser returns.
Grade = Literal["A", "A-", "B+", "B", "B-", "C+", "C", "C-", "D+", "D", "D-", "E", "F", "TR"]


class SavedProfile(BaseModel):
    model_config = ConfigDict(extra="forbid")

    completed_courses: list[CourseCode] = Field(default=[], max_length=150)
    in_progress_courses: list[CourseCode] = Field(default=[], max_length=20)
    grades: dict[CourseCode, Grade] = Field(default={}, max_length=150)
    major: (
        Annotated[str, StringConstraints(max_length=120, pattern=r"^[A-Za-z0-9 ,&()/.'-]*$")] | None
    ) = None


class SavedMessage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    role: Literal["user", "assistant"]
    content: str = Field(min_length=1, max_length=4000)


class SavedChat(BaseModel):
    model_config = ConfigDict(extra="forbid")

    format: Literal["ssa-saved-chat"] = "ssa-saved-chat"
    version: Literal[1] = 1
    exported_at: datetime | None = None
    profile: SavedProfile = SavedProfile()
    messages: list[SavedMessage] = Field(default=[], max_length=200)


class ImportResponse(BaseModel):
    thread_id: str
    messages: list[SavedMessage]  # to show on the page; not the advisor's memory


def _profile_out(profile: dict[str, Any]) -> SavedProfile:
    return SavedProfile(
        completed_courses=profile.get("completed_courses") or [],
        in_progress_courses=profile.get("in_progress_courses") or [],
        grades=profile.get("grades") or {},
        major=profile.get("major"),
    )


# TODO: needs impl - bind thread_id to the authenticated student (api.auth), as for /chat.
# Until then the conversation ID is the only key, and this returns the student's grades to
# whoever sends it.
@router.get("/chat/export")
async def export_chat(
    request: Request,
    # A header, not a query parameter: URLs end up in access logs.
    thread_id: str = Header(alias="X-Thread-Id", max_length=64),
) -> SavedChat:
    graph = request.app.state.graph
    config = {"configurable": {"thread_id": thread_id}}
    state = (await run_in_threadpool(graph.get_state, config)).values or {}
    if not state:
        raise HTTPException(404, "There's no conversation to save yet.")
    return SavedChat(
        exported_at=datetime.now(UTC),
        profile=_profile_out(state.get("profile") or {}),
        messages=[SavedMessage(**m) for m in state.get("messages") or [] if m.get("content")],
    )


@router.post("/chat/import")
async def import_chat(request: Request) -> ImportResponse:
    body = bytearray()
    async for chunk in request.stream():
        body += chunk
        if len(body) > MAX_BYTES:
            raise HTTPException(413, "That file is too large for a saved chat (1 MB max).")
    try:
        saved = SavedChat.model_validate_json(bytes(body))
    except ValidationError as exc:
        raise HTTPException(422, "That doesn't look like a saved advisor chat.") from exc

    profile: dict[str, Any] = saved.profile.model_dump(exclude_none=True)
    profile["imported"] = True  # the advisor names a saved chat as the source, not a transcript
    thread_id = uuid.uuid4().hex  # always a new conversation
    graph = request.app.state.graph
    config = {"configurable": {"thread_id": thread_id}}
    await run_in_threadpool(graph.update_state, config, {"profile": profile}, as_node="merge")
    return ImportResponse(thread_id=thread_id, messages=saved.messages)
