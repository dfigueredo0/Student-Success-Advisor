"""Agent base + scaffolds.

A scaffold declares the fields an intent needs before its tool may run. The agent
fills what it can from the user's message, asks for the first missing field (one
question per turn), and only calls the tool once every field is present.
"""

import logging
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, TypedDict

from tools.guard import call_tool

log = logging.getLogger("ssa.agents")

def _always(slots: dict[str, Any]) -> bool:
    return True


@dataclass(frozen=True)
class Field:
    name: str
    question: str
    # (user text, asked) -> value, or None if the text does not contain it.
    # `asked` is True when this field's question was the agent's previous message.
    extract: Callable[[str, bool], Any | None]
    # Whether to ask for it when missing; False -> the tool gets None and uses its default.
    needed: Callable[[dict[str, Any]], bool] = _always
    # Kept in the student profile for the rest of the conversation, so it is asked once.
    remember: bool = False


@dataclass(frozen=True)
class Scaffold:
    intent: str
    fields: tuple[Field, ...]
    tool: Callable[..., dict[str, Any]]  # called with the fields as keyword arguments
    render: Callable[[dict[str, Any]], str]  # tool result -> answer text
    # Answer when the tool raises NotImplementedError (a service not wired up yet).
    unavailable: str = "Sorry, I can't do that yet - that service isn't connected."


class AgentResult(TypedDict):
    agent: str
    answer: str
    citations: list[dict[str, Any]]
    slots: dict[str, Any]
    pending_field: str | None
    tool_calls: list[dict[str, Any]]
    profile: dict[str, Any]

TOOL_FAILED = "Sorry, I couldn't reach the course data just now. Please try again in a moment."

class Agent:
    name: str
    scaffolds: dict[str, Scaffold]

    def run(
        self,
        intent: str,
        text: str,
        slots: dict[str, Any],
        pending: str | None,
        profile: dict[str, Any] | None = None,
    ) -> AgentResult:
        scaffold = self.scaffolds[intent]
        slots, profile = dict(slots), dict(profile or {})
        for f in scaffold.fields:
            if f.name not in slots:
                value = f.extract(text, pending == f.name)
                if value is None and f.remember:
                    value = profile.get(f.name)
                if value is not None:
                    slots[f.name] = value
                    if f.remember:
                        profile[f.name] = value

        missing = next(
            (f for f in scaffold.fields if f.name not in slots and f.needed(slots)), None
        )
        if missing:
            return self.reply(missing.question, profile, slots=slots, pending=missing.name)

        args = {f.name: slots.get(f.name) for f in scaffold.fields}
        try:
            call = call_tool(scaffold.tool, **args)
        except NotImplementedError:
            failed = {"name": scaffold.tool.__name__, "args": args, "error": "not implemented"}
            return self.reply(scaffold.unavailable, profile, tool_calls=[failed])
        except Exception as exc:
            log.exception("tool %s failed", scaffold.tool.__name__)
            failed = {"name": scaffold.tool.__name__, "args": args, "error": repr(exc)}
            return self.reply(TOOL_FAILED, profile, tool_calls=[failed])
        return self.reply(
            scaffold.render(call["result"]),
            profile,
            citations=call["result"].get("citations", []),
            tool_calls=[call],
        )  # scaffold complete; slots reset so the next request starts clean

    def reply(
        self,
        answer: str,
        profile: dict[str, Any],
        *,
        slots: dict[str, Any] | None = None,
        pending: str | None = None,
        citations: list[dict[str, Any]] | None = None,
        tool_calls: list[dict[str, Any]] | None = None,
    ) -> AgentResult:
        return AgentResult(
            agent=self.name,
            answer=answer,
            citations=citations or [],
            slots=slots or {},
            pending_field=pending,
            tool_calls=tool_calls or [],
            profile=profile,
        )
