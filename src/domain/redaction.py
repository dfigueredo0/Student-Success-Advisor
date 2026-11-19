"""Personal data that must never appear in an answer, and how it is removed.

Used in two places, so they cannot disagree:
- the gateway's output guardrail (infra/litellm/output_guard.py), on everything a model writes;
  docker-compose.yml mounts this file into the LiteLLM container;
- the orchestrator's merge node, on every answer the app sends, templates included.

Standard library only, since the gateway container has none of the app's packages.
"""

import re

REDACTED = "[removed]"

_AT = r"\s*(?:@|\[at\]|\(at\)|\bat\b)\s*"
_DOT = r"\s*(?:\.|\[dot\]|\(dot\)|\bdot\b)\s*"

# Birth dates: the label stays, so "Birth Date [removed]" still reads.
_BIRTH_DATE = re.compile(
    r"\b(birth\s*date|date of birth|dob|born on)(\W{0,3})\d{1,2}[/.-]\d{1,2}[/.-]\d{2,4}\b",
    re.IGNORECASE,
)

SENSITIVE_PATTERNS = [
    # IIT student ID: "A" + 8 digits (confirmed Oct 12), also written A-20123456 or A 2012 3456.
    re.compile(r"\bA[\s-]?(?:\d[\s-]?){7}\d\b", re.IGNORECASE),
    # Student email, also disguised: "jdoe [at] hawk.iit.edu", "jdoe at hawk dot iit dot edu".
    # {1,64} is the real limit on the name part; an open-ended + takes seconds on crafted text.
    re.compile(rf"\b[\w.+-]{{1,64}}{_AT}hawk{_DOT}(?:iit|illinoistech){_DOT}edu\b", re.IGNORECASE),
    # US Social Security number.
    re.compile(r"\b\d{3}-\d{2}-\d{4}\b"),
    # US phone numbers, except campus numbers (312-567-xxxx), so office contacts stay.
    # OFFICIAL_NUMBERS below are kept too.
    re.compile(
        r"(?<!\d)(?:\+?1[\s.-]?)?\(?(?!312\)?[\s.-]?567)\d{3}\)?[\s.-]?\d{3}[\s.-]?\d{4}(?!\d)"
    ),
]

# Official Illinois Tech numbers outside 312-567 that hand-off replies give students, checked on
# iit.edu on Nov 19, 2026. Without this the crisis reply would show "[removed]" for them.
OFFICIAL_NUMBERS = {
    "3128086363",  # Public Safety, 24/7 emergency line (iit.edu/public-safety)
    "8663495575",  # Student Assistance Program / Care Hub, 24/7 (iit.edu/shwc)
}


def _phone_or_official(match: re.Match[str]) -> str:
    digits = re.sub(r"\D", "", match.group())[-10:]
    return match.group() if digits in OFFICIAL_NUMBERS else REDACTED


def redact(text: str) -> str:
    text = _BIRTH_DATE.sub(lambda m: f"{m.group(1)}{m.group(2)}{REDACTED}", text)
    *others, phone = SENSITIVE_PATTERNS
    for pattern in others:
        text = pattern.sub(REDACTED, text)
    return phone.sub(_phone_or_official, text)
