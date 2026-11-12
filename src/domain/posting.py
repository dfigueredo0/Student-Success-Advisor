"""Spotting a job posting in a chat message. Pure.

A student hands the Career agent a posting as a link or as pasted text. Both are recognized by
shape, before the router's model would see them, because posting text is third-party text:
- it is full of words the hand-off rules listen for ("visa sponsorship", "tuition
  reimbursement", "legally authorized"), none of them the student's own question;
- nobody checked it for prompt injection, so it must not reach a model, now or as history.
"""

import re

URL = re.compile(r"https?://[^\s<>\"']+", re.I)
PLACEHOLDER = "[a job posting]"  # what later model prompts show in place of the message
MIN_CHARS = 300  # shorter than any real posting; a long question stays a question
# The Career agent's two requests for a posting. The message after one of them is the posting
# whatever its shape ("Requirements: Python, SQL. No visa sponsorship." is 60 characters).
ASK_POSTING = "Paste the job posting here, or its link, and I'll compare it with your skills."
PASTE_INSTEAD = "Paste the posting's requirements section here instead."

# Phrases postings use and students' questions do not. Bare "requirements" is left out:
# "degree requirements" is everyday here.
_CUES = tuple(
    re.compile(p, re.I)
    for p in (
        r"\bresponsibilit(?:y|ies)\b",
        r"\bqualifications\b",
        r"\byears? of (?:\w+ )?experience\b",
        r"\bequal opportunity\b",
        r"\b(?:we are|we're) (?:looking|seeking|hiring)\b",
        r"\bjob (?:description|requirements)\b",
        r"\bwhat you(?:'ll| will) (?:do|bring|need)\b",
        r"\babout the (?:role|job|position|team)\b",
        r"\b(?:required|preferred|minimum) (?:skills|qualifications|requirements)\b",
        r"\bthe ideal candidate\b",
        r"\bapply (?:now|today|online)\b",
        r"\bbenefits\b",
    )
)


def looks_like_posting(text: str) -> bool:
    """Pasted posting text: long, with at least two of the phrases postings use."""
    return len(text) >= MIN_CHARS and sum(bool(c.search(text)) for c in _CUES) >= 2


def asks_for_posting(reply: str) -> bool:
    """Whether an advisor reply asked the student to paste a posting."""
    return reply == ASK_POSTING or reply.endswith(PASTE_INSTEAD)


def is_posting(text: str) -> bool:
    """A message that hands over a posting: it holds a link, or is the posting's text."""
    return bool(URL.search(text)) or looks_like_posting(text)
