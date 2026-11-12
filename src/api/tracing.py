"""What traces may say about a conversation.

With no accounts, a conversation ID works like a password: whoever has it can continue
that conversation. Langfuse groups traces by session, so traces carry a one-way hash of
the ID instead of the ID itself.

Traces must not hold a student's record either. Every span records its inputs and outputs,
and the graph's state carries grades, major and the skills read from a resume, so mask_trace
runs on everything the Langfuse client sends. The message text stays, so the wording of an
attack can still be read.
"""

import hashlib
from typing import Any

from domain.student_text import hide_record

_RECORD_KEYS = frozenset(
    {
        "profile", "grades", "major", "gpa", "courses", "completed_courses", "in_progress_courses",
        # from a resume upload (POST /resume)
        "current_skills", "degree_level", "graduation_year",
        # the student's skills as a career tool's result lists them (per role, per posting)
        "matched",
    }
)  # fmt: skip


def trace_session_id(thread_id: str) -> str:
    """Stable per conversation, but the conversation ID can't be read back from it."""
    return hashlib.sha256(thread_id.encode()).hexdigest()[:32]


def _hidden(value: Any) -> str:
    if isinstance(value, list | tuple) and value:
        return f"[{len(value)} hidden]"
    return "[hidden]" if value else str(value)


def mask_trace(*, data: Any, **kwargs: Any) -> Any:
    """Langfuse's mask hook: the same data with student records removed, at any depth."""
    if isinstance(data, str):
        return hide_record(data)
    if isinstance(data, dict):
        return {k: _hidden(v) if k in _RECORD_KEYS else mask_trace(data=v) for k, v in data.items()}
    if isinstance(data, list | tuple):
        return [mask_trace(data=v) for v in data]
    return data
