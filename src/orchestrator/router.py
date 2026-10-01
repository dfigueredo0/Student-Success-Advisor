"""Intent router: regex/dictionary -> small model -> clarify below the confidence threshold."""

import json
import re
from collections.abc import Callable
from dataclasses import dataclass

import httpx

from settings import get_settings

# intent -> agent that owns it
INTENTS: dict[str, str] = {"check_eligibility": "college_advisor"}

_PATTERNS: list[tuple[re.Pattern[str], str, float]] = [
    (re.compile(r"\bpre-?req(uisite)?s?\b", re.I), "check_eligibility", 0.95),
    (
        re.compile(r"\b(can|could|may|am)\b.*\b(take|enroll|register|eligible)\b", re.I),
        "check_eligibility",
        0.9,
    ),
]

CLARIFY_QUESTION = (
    "I'm not sure what you need. I can check whether you meet the prerequisites for a "
    "course - which course are you asking about?"
)

Classifier = Callable[[str], tuple[str | None, float]]

@dataclass(frozen=True)
class Route:
    intent: str | None
    agent: str | None  # None -> clarify
    confidence: float
    source: str

def ollama_classify(text: str) -> tuple[str | None, float]:
    """ask the small local model for an intent and a confidence in [0, 1]."""
    s = get_settings()
    prompt = (
        f"Classify the student's message into one intent from {[*INTENTS, 'none']}. "
        'Reply as JSON: {"intent": "<intent>", "confidence": <0..1>}.\n\n'
        f"Message: {text}"
    )
    try:
        resp = httpx.post(
            f"{s.ollama_host}/api/chat",
            json={
                "model": s.ollama_model,
                "messages": [{"role": "user", "content": prompt}],
                "format": {
                    "type": "object",
                    "properties": {
                        "intent": {"type": "string", "enum": [*INTENTS, "none"]},
                        "confidence": {"type": "number"},
                    },
                    "required": ["intent", "confidence"],
                },
                "stream": False,
                "options": {"temperature": 0},
            },
            timeout=30,
        )
        resp.raise_for_status()
        out = json.loads(resp.json()["message"]["content"])
        intent, confidence = out["intent"], float(out["confidence"])
    except (httpx.HTTPError, KeyError, ValueError, TypeError):
        return None, 0.0  # model unavailable or unparseable -> falls through to clarify
    # switch to logprobs or a trained classifier when eval shows misroutes.
    return (intent if intent in INTENTS else None), max(0.0, min(confidence, 1.0))

def route(text: str, classify: Classifier = ollama_classify, threshold: float | None = None) -> Route:
    if threshold is None:
        threshold = get_settings().router_confidence_threshold
    for pattern, intent, confidence in _PATTERNS:
        if pattern.search(text):
            return Route(intent, INTENTS[intent], confidence, "regex")
    intent, confidence = classify(text)
    if intent in INTENTS and confidence >= threshold:
        return Route(intent, INTENTS[intent], confidence, "model")
    return Route(None, None, confidence, "clarify")
