"""Single entry point for tool execution: every tool call is checked, traced, and recorded."""

import re
from collections.abc import Callable, Collection
from typing import Any

from langfuse import get_client

_COURSE = re.compile(r"^[A-Z]{2,4} \d{3}[A-Z]?$")
MAX_COURSES = 150  # a full degree's worth, retakes included
MAX_TEXT = 500


class ToolNotAllowed(PermissionError):
    """An agent asked for a tool outside its allow-list."""


class ToolArgsInvalid(ValueError):
    """An argument is outside what any tool should be given."""


def _is_course(value: Any) -> bool:
    return isinstance(value, str) and bool(_COURSE.match(value))


def _check_args(args: dict[str, Any]) -> None:
    """Limits every tool shares. Field values come from students and from the model."""
    for name, value in args.items():
        if value is None:
            continue
        if name == "course":
            valid = _is_course(value)
        elif name in ("completed_courses", "in_progress_courses", "grades"):
            valid = len(value) <= MAX_COURSES and all(_is_course(c) for c in value)
        else:
            valid = not isinstance(value, str) or len(value) <= MAX_TEXT
        if not valid:
            raise ToolArgsInvalid(f"argument {name!r} is outside the limits")


def call_tool(
    tool: Callable[..., dict[str, Any]], allowed: Collection[str], /, **args: Any
) -> dict[str, Any]:
    if tool.__name__ not in allowed:
        raise ToolNotAllowed(f"tool {tool.__name__!r} is not on this agent's allow-list")
    _check_args(args)
    # TODO: needs impl - per-student authorization (RLS) belongs here once api.auth exists.
    # There are no accounts by design, and no tool can read another student's data yet.
    with get_client().start_as_current_observation(
        name=tool.__name__, as_type="tool", input=args
    ) as span:
        result = tool(**args)
        span.update(output=result)
    return {"name": tool.__name__, "args": args, "result": result}
