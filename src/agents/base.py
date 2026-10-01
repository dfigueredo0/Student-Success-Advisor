"""Agent base + scaffolds.

A scaffold declares the fields an intent needs before its tool may run. The agent
fills what it can from the user's message, asks for the first missing field (one
question per turn), and only calls the tool once every field is present.
"""

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, TypedDict

from tools.guard import call_tool


@dataclass(frozen=True)
class Field:
    name: str
    question: str
    # (user text, asked) -> value, or None if the text does not contain it.
    # `asked` is True when this field's question was the agent's previous message.
    extract: Callable[[str, bool], Any | None]


@dataclass(frozen=True)
class Scaffold:
    intent: str
    fields: tuple[Field, ...]
    tool: Callable[..., dict[str, Any]]  # called with the fields as keyword arguments
    render: Callable[[dict[str, Any]], str]  # tool result -> answer text


class AgentResult(TypedDict):
    agent: str
    answer: str
    citations: list[dict[str, Any]]
    slots: dict[str, Any]
    pending_field: str | None
    tool_calls: list[dict[str, Any]]


class Agent:
    name: str
    scaffolds: dict[str, Scaffold]

    def run(
        self, intent: str, text: str, slots: dict[str, Any], pending: str | None
    ) -> AgentResult:
        scaffold = self.scaffolds[intent]
        slots = dict(slots)
        for f in scaffold.fields:
            if f.name not in slots:
                value = f.extract(text, pending == f.name)
                if value is not None:
                    slots[f.name] = value

        missing = next((f for f in scaffold.fields if f.name not in slots), None)
        if missing:
            return AgentResult(
                agent=self.name,
                answer=missing.question,
                citations=[],
                slots=slots,
                pending_field=missing.name,
                tool_calls=[],
            )

        call = call_tool(scaffold.tool, **slots)
        return AgentResult(
            agent=self.name,
            answer=scaffold.render(call["result"]),
            citations=call["result"].get("citations", []),
            slots={},  # scaffold complete; next request starts clean
            pending_field=None,
            tool_calls=[call],
        )
