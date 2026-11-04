"""The router and follow-ups tell the injection guardrail which part of their prompt is the
student's new message, so an earlier blocked message doesn't block the rest of the chat."""

from agents.career_advisor import CareerAdvisor
from tests.agent.fakes import FakeLLM

HISTORY = [
    {"role": "user", "content": "How do jailbreak attacks on AI models work?"},
    {"role": "assistant", "content": "I'm not sure what you need."},
]
NEW = "what about databases instead?"


def test_router_names_only_the_new_message() -> None:
    llm = FakeLLM({"intent": "find_courses", "confidence": 0.9})
    llm.classify(NEW, HISTORY)
    (request,) = llm.requests
    assert request["metadata"]["guard_text"] == NEW
    assert NEW in request["messages"][-1]["content"]  # the guardrail requires it in the prompt


def test_followup_names_only_the_new_message() -> None:
    fields = CareerAdvisor().scaffolds["career_advice"].fields
    llm = FakeLLM({f.name: "" for f in fields})
    llm.fill(fields, NEW, HISTORY)
    (request,) = llm.requests
    assert request["metadata"]["guard_text"] == NEW
    assert NEW in request["messages"][-1]["content"]
