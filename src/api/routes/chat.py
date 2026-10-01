import uuid
from typing import Any

from fastapi import APIRouter, Request
from langfuse import get_client, propagate_attributes
from pydantic import BaseModel, Field

from orchestrator.state import turn_input

router = APIRouter()

# TODO: frontend - the workspace already knows the student's courses (transcript view /
# sample profiles in frontend/app.js) but only sends the message, so the advisor has to ask.
# Once get_student_record exists, seed state["profile"] from it here (keyed by the
# authenticated student) rather than accepting course lists from the client.
class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=4000)
    thread_id: str | None = Field(default=None, max_length=64)

class ChatResponse(BaseModel):
    thread_id: str
    answer: str
    citations: list[dict[str, Any]]
    tool_calls: list[dict[str, Any]]
    # TODO: frontend - state["agent_results"][...] / tool_calls carry structured results
    # (e.g. recommend_courses' recommendations) the trajectory map could highlight.
    # TODO: security - returns the full graph state (profile, slots); trim for prod.
    state: dict[str, Any]
    trace_id: str | None
    trace_url: str | None

# TODO: needs impl - authenticate the caller (api.auth) and bind thread_id to the
# student; until then anyone who knows a thread_id can continue that conversation.
@router.post("/chat")
def chat(req: ChatRequest, request: Request) -> ChatResponse:
    thread_id = req.thread_id or uuid.uuid4().hex
    langfuse = get_client()
    # One request = one trace: every node and tool span nests under this root span.
    with (
        langfuse.start_as_current_observation(name="chat", input=req.message) as span,
        propagate_attributes(session_id=thread_id),
    ):
        state = request.app.state.graph.invoke(
            turn_input(req.message), {"configurable": {"thread_id": thread_id}}
        )
        span.update(output=state["answer"])
        trace_id = langfuse.get_current_trace_id()
    return ChatResponse(
        thread_id=thread_id,
        answer=state["answer"],
        citations=state["citations"],
        tool_calls=state["tool_calls"],
        state=state,
        trace_id=trace_id,
        trace_url=langfuse.get_trace_url(trace_id=trace_id) if trace_id else None,
    )
