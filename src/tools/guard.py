"""Single entry point for tool execution: every tool call is checked, traced, and recorded."""

from collections.abc import Callable, Collection
from typing import Any

from langfuse import get_client


class ToolNotAllowed(PermissionError):
    """An agent asked for a tool outside its allow-list."""


def call_tool(
    tool: Callable[..., dict[str, Any]], allowed: Collection[str], /, **args: Any
) -> dict[str, Any]:
    if tool.__name__ not in allowed:
        raise ToolNotAllowed(f"tool {tool.__name__!r} is not on this agent's allow-list")
    # TODO: needs impl - argument validation and per-student authorization (RLS)
    # belong here once api.auth and schemas.student exist.
    with get_client().start_as_current_observation(
        name=tool.__name__, as_type="tool", input=args
    ) as span:
        result = tool(**args)
        span.update(output=result)
    return {"name": tool.__name__, "args": args, "result": result}
