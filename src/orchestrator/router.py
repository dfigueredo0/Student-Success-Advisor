"""Intent router: whole-message patterns with one reading -> small model with the recent
conversation -> clarify below the confidence threshold. While an agent waits for an answer, the
message is read as that answer unless a pattern or the model sees a new request."""

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
# The interview's repeated questions (data/advisor_interview_findings.json: elective
# eligibility, whether a course counts, unavailable courses) are named where the model sent
# them to check_eligibility (eval 2026-11-05).
INTENT_DESCRIPTIONS: dict[str, str] = {
    "plan_next_term": "wants recommendations for which courses or electives to take next",
    "check_eligibility": "asks whether they meet the prerequisites for one specific course",
    "course_info": "asks about one specific course: what it covers, credits, when or how it "
    "is offered, open seats, who teaches",
    "find_courses": "looks for courses on a topic or interest, no specific course code",
    "degree_progress": "asks about graduation, what their degree or major still requires, "
    "whether a course counts toward it, or credits remaining",
    "record_courses": "tells you unprompted which courses they have completed, or asks what "
    "you have on record",
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
# (the advisor's question, the student's reply): a reply to the question continues the request.
_ANSWERS: list[tuple[str, str]] = [("Which skills do you already have?", "Java and C++")]

# Not an agent's intent: the message continues the open request, either answering the
# advisor's question ("CS 115 and MATH 151") or adding a detail ("and SQL?"), so it gets that
# request's intent. A small model spots a follow-up far more reliably than it works out which
# earlier intent one continues (eval 2026-10-22).
FOLLOW_UP = "follow_up"

_CODE = r"[A-Za-z]{2,4}\s?\d{3}"
_END = r"[\s?.!]*$"

# Whole messages with only one reading. A hit skips the model and the conversation, so a
# pattern must match the entire message: one more word can change the intent ("Can I take
# CS 450 online?" asks about sections, "What can you do with a math degree?" is career
# advice). Partial patterns caused 11 of 15 misroutes on new wordings (eval 2026-11-05);
# everything else goes to the model. `strong`: a hit while the agent waits for an answer is a
# new request; a weak one ("I've taken CS 351") is the answer.
_SURE: list[tuple[re.Pattern[str], str, bool]] = [
    (
        re.compile(rf"^\s*(can|may) i (take|enroll in|register for) {_CODE}{_END}", re.I),
        "check_eligibility",
        True,
    ),
    (
        re.compile(rf"^\s*(what are )?(the )?pre-?req(uisite)?s (for|of) {_CODE}{_END}", re.I),
        "check_eligibility",
        True,
    ),
    (
        re.compile(rf"^\s*(tell me about|describe|who teaches) {_CODE}{_END}", re.I),
        "course_info",
        True,
    ),
    (re.compile(rf"^\s*am i on track to graduate{_END}", re.I), "degree_progress", True),
    (
        re.compile(
            r"^\s*(what['\u2019]?s on my transcript|what (courses|classes) have i (taken|completed)"
            rf"( so far)?|show me my (courses|classes)){_END}",
            re.I,
        ),
        "record_courses",
        True,
    ),
    (
        re.compile(
            r"^\s*i\s*(['\u2019]ve|\s+have)?\s*(already\s+)?(taken|took|completed|passed|finished)"
            rf"\s+{_CODE}(\s*(,|,?\s*and)\s*{_CODE})*{_END}",
            re.I,
        ),
        "record_courses",
        False,
    ),
    (
        re.compile(
            r"^(?=.*\w)\s*((hi+|hello+|hey+|hiya|howdy|yo|good (morning|afternoon|evening))"
            r"(\s+there)?[\s!.,)]*)?(help|what can you do( for me)?|who are you)?[\s!.?,)]*$",
            re.I,
        ),
        "help",
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
        examples="\n\n".join(
            [
                *(f"Message: {m}\nIntent: {i}" for m, i in _FEW_SHOT),
                *(f"Advisor: {q}\nMessage: {a}\nIntent: {FOLLOW_UP}" for q, a in _ANSWERS),
            ]
        ),
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
            # Nothing to follow up on in a first message: qwen3:1.7b still said follow_up for
            # some (eval 2026-11-05), so the schema leaves it out.
            "intent": {
                "type": "string",
                "enum": [*INTENTS, *([FOLLOW_UP] if history else []), "none"],
            },
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
        # guard_text: the injection guardrail checks only the new message, not the history
        # (earlier messages were checked when they were new).
        "metadata": {"prompt_version": ROUTER_PROMPT.version, "guard_text": text},
    }
    try:
        out = json.loads(complete(payload))
        intent, confidence = out["intent"], float(out["confidence"])
    except (httpx.HTTPError, KeyError, IndexError, ValueError, TypeError):
        return None, 0.0  # gateway/model unavailable or unparseable -> falls through to clarify
    # switch to logprobs or a trained classifier when eval shows misroutes.
    known = intent in INTENTS or intent == FOLLOW_UP
    return (intent if known else None), max(0.0, min(confidence, 1.0))


def regex_route(text: str, answering: str | None = None) -> Route | None:
    """The route of the sure pattern the whole message matches, or None to ask the model.
    `answering`: the intent whose question the agent is waiting on; a weak hit answers it."""
    for pattern, intent, strong in _SURE:
        if pattern.match(text):
            intent = intent if strong or answering is None else answering
            return Route(intent, INTENTS[intent], 1.0, "regex")
    return None


def route(
    text: str,
    classify: Classifier = ollama_classify,
    threshold: float | None = None,
    history: list[dict[str, str]] | None = None,
    previous: str | None = None,
    answering: bool = False,
) -> Route:
    """`previous`: the intent of the open request, which a follow-up continues. `answering`:
    the agent asked a question, so the message is its answer unless it is clearly a new
    request; then the route keeps `previous` instead of asking to clarify."""
    if threshold is None:
        threshold = get_settings().router_confidence_threshold
    if hit := regex_route(text, previous if answering else None):
        return hit
    intent, confidence = classify(text, history or [])
    # Courses (or skills) listed while the agent waits are its answer, never a new request:
    # switching to record_courses would drop the open request (eval 2026-11-05).
    if intent == FOLLOW_UP or (answering and intent == "record_courses"):
        intent = previous  # nothing to follow up on -> clarify
    if intent in INTENTS and confidence >= threshold:
        return Route(intent, INTENTS[intent], confidence, "model", ROUTER_PROMPT.version)
    if answering and previous in INTENTS:
        return Route(previous, INTENTS[previous], confidence, "model", ROUTER_PROMPT.version)
    return Route(None, None, confidence, "clarify", ROUTER_PROMPT.version)
