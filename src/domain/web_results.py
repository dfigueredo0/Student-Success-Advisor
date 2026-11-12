"""Web search results in a reply: third-party text, so cleaned before it is shown and kept
out of anything a model reads later. Pure.
"""

import re
import unicodedata
from urllib.parse import urlsplit

# The search request the job-match answer suggests, word for word; what follows is a role
# name. Routed without the model, and not the student's own question to the hand-off rules:
# O*NET has "Loan Officers", "Paralegals and Legal Assistants", "Substitute Teachers".
FIND_OPENINGS = re.compile(r"^\s*find openings for \S.{1,119}$", re.I)
HEADER = "Web results for"  # how the reply that lists results starts (agents.career_advisor)
PLACEHOLDER = "[web search results]"  # what later model prompts show in place of that reply


def clean(text: str, limit: int) -> str:
    """One line of plain text, at most `limit` characters: no control or format characters
    (escape sequences, direction overrides), whitespace collapsed."""
    kept = "".join(
        " " if c.isspace() else c for c in text if c.isspace() or unicodedata.category(c)[0] != "C"
    )
    text = " ".join(kept.split())
    return text if len(text) <= limit else text[:limit].rstrip() + "..."


def is_http_url(url: str) -> bool:
    """A link a page may open: http(s) with a host. Rules out javascript:, data:, file:."""
    try:
        parts = urlsplit(url)
    except ValueError:
        return False
    return parts.scheme in ("http", "https") and bool(parts.hostname)
