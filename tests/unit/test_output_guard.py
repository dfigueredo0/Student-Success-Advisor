"""The gateway's output guardrail hook and the merge node remove the same personal data.

The hook runs inside the LiteLLM container; here it is loaded from its file with litellm
stubbed out and domain.redaction standing in for the redaction.py mounted into it.
"""

import asyncio
import importlib.util
import sys
import types
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from domain import redaction
from orchestrator.merge import merge

GUARD = Path(__file__).parents[2] / "infra" / "litellm" / "output_guard.py"


@pytest.fixture
def guard(monkeypatch: pytest.MonkeyPatch) -> Any:
    stub = types.ModuleType("litellm.integrations.custom_guardrail")
    stub.CustomGuardrail = object
    for name in ("litellm", "litellm.integrations"):
        monkeypatch.setitem(sys.modules, name, types.ModuleType(name))
    monkeypatch.setitem(sys.modules, "litellm.integrations.custom_guardrail", stub)
    monkeypatch.setitem(sys.modules, "redaction", redaction)
    spec = importlib.util.spec_from_file_location("output_guard", GUARD)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.OutputGuard()


def response(**message: Any) -> SimpleNamespace:
    return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(**message))])


def test_answer_thinking_and_tool_arguments_are_cleaned(guard: Any) -> None:
    call = SimpleNamespace(
        function=SimpleNamespace(name="lookup", arguments='{"student": "A20123456"}')
    )
    out = asyncio.run(
        guard.async_post_call_success_hook(
            {},
            None,
            response(
                content="Call 773-555-0142",
                reasoning_content="The ID is A-20123456",
                tool_calls=[call],
            ),
        )
    )
    message = out.choices[0].message
    assert message.content == "Call [removed]"
    assert message.reasoning_content == "The ID is [removed]"
    assert message.tool_calls[0].function.arguments == '{"student": "[removed]"}'


def test_message_without_tool_calls_is_fine(guard: Any) -> None:
    out = asyncio.run(guard.async_post_call_success_hook({}, None, response(content="Hi")))
    assert out.choices[0].message.content == "Hi"


def test_every_app_reply_is_checked_templates_included() -> None:
    result = {"answer": "I couldn't find A20123456 in the catalog.", "citations": []}
    out = merge({"agent_results": [result]})
    assert out["answer"] == "I couldn't find [removed] in the catalog."
    assert out["messages"][-1]["content"] == out["answer"]  # memory holds the clean text too
