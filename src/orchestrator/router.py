"""Intent router: near-certain regex -> small model with the recent conversation -> clarify
below the confidence threshold."""

import json
import re
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import httpx

from agents.prompts import load_prompt
from memory import context
from settings import get_settings

ROUTER_PROMPT = load_prompt("router_intent")

# intent -> agent that owns it
INTENTS: dict[str, str] = {
    "plan_next_term": "college_advisor",
    "check_eligibility": "college_advisor",
    "course_info": "college_advisor",
    "find_courses": "college_advisor",
    "degree_progress": "college_advisor",
    "record_courses": "college_advisor",
    "help": "college_advisor",
    "career_advice": "career_advisor",
}

# What the small model sees; keep each line short and contrastive.
INTENT_DESCRIPTIONS: dict[str, str] = {
    "plan_next_term": "wants recommendations for which courses to take in a coming semester",
    "check_eligibility": "asks whether they can take one specific course (prerequisites)",
    "course_info": "asks about one specific course: what it covers, credits, when, who teaches",
    "find_courses": "looks for courses on a topic or interest, no specific course code",
    "degree_progress": "asks about graduation, degree requirements, or credits remaining",
    "record_courses": "tells you which courses they have already completed",
    "help": "greets you or asks what you can do",
    "career_advice": "asks about careers, jobs or internships, or which skills to build for one",
}

_FEW_SHOT: list[tuple[str, str]] = [
    ("What should I sign up for next fall?", "plan_next_term"),
    ("Is CS 450 open to me if I took CS 351?", "check_eligibility"),
    ("Who teaches CS 331 this term?", "course_info"),
    ("Are there any classes on machine learning?", "find_courses"),
    ("Am I on track to graduate?", "degree_progress"),
    ("I already passed MATH 151 and CS 115", "record_courses"),
    ("hey, what can you do?", "help"),
    ("What skills do I need to become a data scientist?", "career_advice"),
    ("and for SQL?", "follow_up"),
    ("what about CS 485?", "follow_up"),
    ("can I take the first one?", "check_eligibility"),
    ("Where is the gym?", "none"),
]

# Not an agent's intent: the message continues the previous request ("and SQL?"), so it gets
# that request's intent. A small model spots a follow-up far more reliably than it works out
# which earlier intent one continues (eval 2026-10-22).
FOLLOW_UP = "follow_up"
# The one follow-up wording sure enough to skip the model: "and" plus at most three words
# ("and SQL?", "and for CS 350?") right after a request is that request again.
_AND_MORE = re.compile(r"^\s*and\s+(\S+\s+){0,2}\S+?[\s?.!]*$", re.I)

_CODE = r"[A-Za-z]{2,4}\s?\d{3}\b"

# Near-certain wordings only: a hit skips the model and the conversation, so a wrong one is a
# wrong answer. Everything else, follow-ups included ("what about CS 485?", a bare "CS 485?"
# after a prerequisite check), goes to the model with the recent messages. Checked in order;
# first hit wins. `strong` hits may pull the student out of a half-answered question (they
# changed topic); a weak one ("I've taken ...") is likely the answer.
_PATTERNS: list[tuple[re.Pattern[str], str, float, bool]] = [
    (re.compile(r"\bpre-?req(uisite)?s?\b", re.I), "check_eligibility", 0.95, True),
    (
        re.compile(
            rf"\b(can|could|may|am)\b.*\b(take|enroll|register|eligible)\b.*\b{_CODE}", re.I
        ),
        "check_eligibility",
        0.95,
        True,
    ),
    (
        re.compile(
            r"\bdegree\s+(audit|progress)\b|\bon track to graduate\b"
            r"|\bgraduation requirements?\b|\bcredits?\s+(left|remaining)\b",
            re.I,
        ),
        "degree_progress",
        0.9,
        True,
    ),
    (
        re.compile(r"\b(tell me about|describe|who teaches|how many credits)\b.*\b" + _CODE, re.I),
        "course_info",
        0.9,
        True,
    ),
    (
        # A statement, not a question: "I took CS 331, what should I take next?" is planning.
        re.compile(
            r"^\s*i\s*('ve|\s+have)?\s*(already\s+)?(taken|took|completed|passed|finished)\b"
            r"[^?]*$",
            re.I,
        ),
        "record_courses",
        0.9,
        False,
    ),
    (
        re.compile(
            r"^\s*(hi+|hello+|hey+|hiya|howdy|yo|help|good (morning|afternoon|evening))"
            r"(\s+there)?[\s!.?,)]*$|\bwhat can you do\b|\bwho are you\b",
            re.I,
        ),
        "help",
        0.9,
        True,
    ),
]

CLARIFY_QUESTION = (
    "I'm not sure what you need. I can:\n"
    '- recommend courses for next term ("What should I take next semester?")\n'
    '- check prerequisites ("Can I take CS 450?")\n'
    '- look up a course ("Tell me about CS 331")\n'
    '- find courses on a topic ("Any courses on machine learning?")\n'
    '- match courses to career skills ("What skills do I need to become a data scientist?")\n'
    "What would you like to do?"
)

# (message, the conversation before it) -> (intent or None, confidence)
Classifier = Callable[[str, list[dict[str, str]]], tuple[str | None, float]]
# One chat-completions request body -> the reply message's content. The gateway in production;
# a scripted FakeLLM in agent tests, so the real prompt, schema, and parsing are exercised.
Completion = Callable[[dict[str, Any]], str]


@dataclass(frozen=True)
class Route:
    intent: str | None
    agent: str | None  # None -> clarify
    confidence: float
    source: str
    # Version of the classifier prompt when the model stage ran; None for a regex hit.
    prompt_version: str | None = None


def _classifier_prompt(text: str, history: list[dict[str, str]]) -> str:
    # TODO: security - `text` and the history are untrusted student input inside the prompt. The
    # JSON schema in ollama_classify pins the output to the intent enum, so injection can at
    # worst misroute.
    return ROUTER_PROMPT.render(
        intents="\n".join(f"- {name}: {desc}" for name, desc in INTENT_DESCRIPTIONS.items()),
        examples="\n\n".join(f"Message: {m}\nIntent: {i}" for m, i in _FEW_SHOT),
        history=context(history, text),
        message=text,
    )


def gateway_complete(payload: dict[str, Any]) -> str:
    """POST one chat completion to the LiteLLM gateway with the router's own key."""
    s = get_settings()
    resp = httpx.post(
        f"{s.litellm_base_url}/v1/chat/completions",
        headers={"Authorization": f"Bearer {s.litellm_router_key.get_secret_value()}"},
        json=payload,
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json()["choices"][0]["message"]["content"]


def ollama_classify(
    text: str,
    history: list[dict[str, str]] | None = None,
    complete: Completion = gateway_complete,
) -> tuple[str | None, float]:
    """Ask the model, via the LiteLLM gateway, for an intent and a confidence in [0, 1]."""
    schema = {
        "type": "object",
        "properties": {
            "intent": {"type": "string", "enum": [*INTENTS, FOLLOW_UP, "none"]},
            "confidence": {"type": "number"},
        },
        "required": ["intent", "confidence"],
    }
    payload = {
        "model": get_settings().llm_default_model,
        "messages": [{"role": "user", "content": _classifier_prompt(text, history or [])}],
        "response_format": {
            "type": "json_schema",
            "json_schema": {"name": "route", "schema": schema},
        },
        "temperature": 0,
        # A classifier needs no reasoning: thinking models (qwen3) otherwise spend ~400 hidden
        # tokens (5-30 s on CPU) per route and sometimes never stop. The cap bounds a runaway;
        # the answer is ~16 tokens. Eval 2026-10-14 (.claude/docs/WorkLog-2026-10-14.md).
        "reasoning_effort": "none",
        "max_tokens": 64,
        "metadata": {"prompt_version": ROUTER_PROMPT.version},
    }
    try:
        out = json.loads(complete(payload))
        intent, confidence = out["intent"], float(out["confidence"])
    except (httpx.HTTPError, KeyError, IndexError, ValueError, TypeError):
        return None, 0.0  # gateway/model unavailable or unparseable -> falls through to clarify
    # switch to logprobs or a trained classifier when eval shows misroutes.
    known = intent in INTENTS or intent == FOLLOW_UP
    return (intent if known else None), max(0.0, min(confidence, 1.0))


def regex_route(text: str, *, strong_only: bool = False) -> Route | None:
    for pattern, intent, confidence, strong in _PATTERNS:
        if (strong or not strong_only) and pattern.search(text):
            return Route(intent, INTENTS[intent], confidence, "regex")
    return None


def route(
    text: str,
    classify: Classifier = ollama_classify,
    threshold: float | None = None,
    history: list[dict[str, str]] | None = None,
    previous: str | None = None,
) -> Route:
    """`previous`: the intent of the last request, which a follow-up continues."""
    if threshold is None:
        threshold = get_settings().router_confidence_threshold
    if hit := regex_route(text):
        return hit
    if previous in INTENTS and _AND_MORE.match(text):
        return Route(previous, INTENTS[previous], 0.9, "regex")
    intent, confidence = classify(text, history or [])
    if intent == FOLLOW_UP:
        intent = previous  # nothing to follow up on -> clarify
    if intent in INTENTS and confidence >= threshold:
        return Route(intent, INTENTS[intent], confidence, "model", ROUTER_PROMPT.version)
    return Route(None, None, confidence, "clarify", ROUTER_PROMPT.version)
