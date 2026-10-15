"""Scripted stand-ins for the model gateway and for tools, shared by the agent suite."""

import json
from functools import partial
from typing import Any

from orchestrator.router import Classifier, ollama_classify


class FakeLLM:
    """Scripted gateway: answers chat-completion requests from a queue and records each one.

    Plugs into the router where the gateway would be (ollama_classify's `complete`), so the
    real versioned prompt, JSON schema, and reply parsing all run. A reply may be a dict
    (sent as JSON), a raw string, or an exception to raise. An unscripted call fails the test,
    which is how a test asserts the model was never asked.
    """

    def __init__(self, *replies: dict[str, Any] | str | Exception) -> None:
        self.replies = list(replies)
        self.requests: list[dict[str, Any]] = []

    def __call__(self, payload: dict[str, Any]) -> str:
        self.requests.append(payload)
        assert self.replies, f"unscripted model call: {payload['messages'][-1]['content'][-80:]}"
        reply = self.replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return reply if isinstance(reply, str) else json.dumps(reply)

    @property
    def classify(self) -> Classifier:
        return partial(ollama_classify, complete=self)

    @staticmethod
    def route(intent: str, confidence: float) -> dict[str, Any]:
        return {"intent": intent, "confidence": confidence}


class FakeTool:
    """Stands in for a tool under its real name (so allow-lists apply); records every call."""

    def __init__(self, name: str, result: dict[str, Any]) -> None:
        self.__name__ = name
        self.result = result
        self.calls: list[dict[str, Any]] = []

    def __call__(self, **kwargs: Any) -> dict[str, Any]:
        self.calls.append(kwargs)
        return self.result


def eligibility_result(course: str = "CS 450") -> dict[str, Any]:
    return {
        "course": course,
        "found": True,
        "prerequisites": "CS 351",
        "status": "satisfied",
        "missing": [],
        "pending": [],
        "needs_grade": [],
        "if_grade_too_low": None,
        "unchecked_tests": [],
        "unreadable": [],
        "citations": [{"source": f"IIT Banner course catalog, {course}", "quote": "CS 351"}],
    }
