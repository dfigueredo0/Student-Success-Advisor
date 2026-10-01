"""Intent router: regex/dictionary -> small model -> clarify below the confidence threshold."""

import json
import re
from collections.abc import Callable
from dataclasses import dataclass

import httpx

from settings import get_settings

# intent -> agent that owns it
INTENTS: dict[str, str] = {
    "plan_next_term": "college_advisor",
    "check_eligibility": "college_advisor",
    "course_info": "college_advisor",
    "find_courses": "college_advisor",
    "degree_progress": "college_advisor",
    "record_courses": "college_advisor",
    "help": "college_advisor",
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
}

_FEW_SHOT: list[tuple[str, str]] = [
    ("What should I sign up for next fall?", "plan_next_term"),
    ("Is CS 450 open to me if I took CS 351?", "check_eligibility"),
    ("Who teaches CS 331 this term?", "course_info"),
    ("Are there any classes on machine learning?", "find_courses"),
    ("Am I on track to graduate?", "degree_progress"),
    ("I already passed MATH 151 and CS 115", "record_courses"),
    ("hey, what can you do?", "help"),
    ("Where is the gym?", "none"),
]

_CODE = r"[A-Za-z]{2,4}\s?\d{3}\b"

# Checked in order; first hit wins. `strong` hits may pull the student out of a half-answered
# question (they changed topic); weak ones (a bare code, "I've taken ...") are likely the answer.
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
            r"\bgraduat\w*|\bdegree\s+(audit|progress|requirements?)|\bon track\b"
            r"|\brequirements?\b.*\b(left|remaining|missing|degree|major)\b"
            r"|\bcredits?\s+(left|remaining|needed|do i need)",
            re.I,
        ),
        "degree_progress",
        0.9,
        True,
    ),
    (
        re.compile(
            r"\b(what|which)\b.*\b(courses?|classes)\b.*\b(take|register|enroll|sign up)\b"
            r"|\bwhat should i (take|register|enroll|sign up)"
            r"|\b(recommend|suggest)\w*\b.*\b(courses?|classes|schedule)"
            r"|\b(plan|build)\b.*\b(semester|term|schedule)\b"
            r"|\bnext\s+(semester|term|fall|spring|summer)\b",
            re.I,
        ),
        "plan_next_term",
        0.9,
        True,
    ),
    (
        re.compile(
            r"\b(what\s+is|what's|tell me about|describe|info|information|details?|"
            r"who teaches|when is|how many credits)\b.*\b" + _CODE,
            re.I,
        ),
        "course_info",
        0.9,
        True,
    ),
    (
        re.compile(
            r"\b(find|search|look\w* for|any|are there|show me)\b.*\b(courses?|classes)\b"
            r"|\b(courses?|classes)\b\s+(about|on|covering|related to|that (teach|cover)|in)\b",
            re.I,
        ),
        "find_courses",
        0.85,
        True,
    ),
    (
        re.compile(r"\b(can|could|may|am)\b.*\b(take|enroll|register|eligible)\b", re.I),
        "check_eligibility",
        0.9,
        True,
    ),
    (
        re.compile(
            r"^\s*i\s*('ve|\s+have)?\s*(already\s+)?(taken|took|completed|passed|finished)\b",
            re.I,
        ),
        "record_courses",
        0.9,
        False,
    ),
    (re.compile(rf"^\s*{_CODE}\s*\??\s*$", re.I), "course_info", 0.8, False),
    (
        re.compile(r"^\s*(hi|hello|hey|help)\b|\bwhat can you do\b|\bwho are you\b", re.I),
        "help",
        0.9,
        True,
    ),
]

CLARIFY_QUESTION = (
    "I'm not sure what you need. I can:\n"
    "- recommend courses for next term (\"What should I take next semester?\")\n"
    "- check prerequisites (\"Can I take CS 450?\")\n"
    "- look up a course (\"Tell me about CS 331\")\n"
    "- find courses on a topic (\"Any courses on machine learning?\")\n"
    "What would you like to do?"
)

Classifier = Callable[[str], tuple[str | None, float]]

@dataclass(frozen=True)
class Route:
    intent: str | None
    agent: str | None  # None -> clarify
    confidence: float
    source: str

def _classifier_prompt(text: str) -> str:
    intents = "\n".join(f"- {name}: {desc}" for name, desc in INTENT_DESCRIPTIONS.items())
    examples = "\n".join(f"Message: {m}\nIntent: {i}" for m, i in _FEW_SHOT)
    # TODO: security - `text` is untrusted student input inside the prompt. The JSON schema
    # below pins the output to the intent enum, so injection can at worst misroute.
    return (
        "You route messages for a university academic advisor. Pick the student's intent.\n"
        f"{intents}\n- none: anything else\n\n{examples}\n\n"
        'Reply as JSON: {"intent": "<intent>", "confidence": <0..1>}.\n\n'
        f"Message: {text}\nIntent:"
    )

def ollama_classify(text: str) -> tuple[str | None, float]:
    """ask the small local model for an intent and a confidence in [0, 1]."""
    s = get_settings()
    try:
        resp = httpx.post(
            f"{s.ollama_host}/api/chat",
            json={
                "model": s.ollama_model,
                "messages": [{"role": "user", "content": _classifier_prompt(text)}],
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

def regex_route(text: str, *, strong_only: bool = False) -> Route | None:
    for pattern, intent, confidence, strong in _PATTERNS:
        if (strong or not strong_only) and pattern.search(text):
            return Route(intent, INTENTS[intent], confidence, "regex")
    return None

def route(
    text: str, classify: Classifier = ollama_classify, threshold: float | None = None
) -> Route:
    if threshold is None:
        threshold = get_settings().router_confidence_threshold
    if hit := regex_route(text):
        return hit
    intent, confidence = classify(text)
    if intent in INTENTS and confidence >= threshold:
        return Route(intent, INTENTS[intent], confidence, "model")
    return Route(None, None, confidence, "clarify")
