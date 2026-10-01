"""Single entry point for tool execution: every tool call is traced and recorded."""

from collections.abc import Callable
from typing import Any

from langfuse import get_client

def call_tool(tool: Callable[..., dict[str, Any]], **args: Any) -> dict[str, Any]:
    # TODO: needs impl - argument validation and per-student authorization (RLS)
    # belong here once api.auth and schemas.student exist.
    with get_client().start_as_current_observation(
        name=tool.__name__, as_type="tool", input=args
    ) as span:
        result = tool(**args)
        span.update(output=result)
    return {"name": tool.__name__, "args": args, "result": result}
