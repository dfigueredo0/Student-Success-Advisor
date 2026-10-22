"""Short-term memory: the part of this conversation the model sees with a new message.

The checkpointer already keeps every message of a thread (State.messages); this picks what
goes into a prompt. The last few messages always do, so a follow-up ("and SQL?", "the first
one") can be read against them. Older messages come back only when they share words with the
new message ("the Python course you mentioned"), so an earlier answer stays citable without
sending the whole thread to a small model.
"""

import re

RECENT = 4  # messages: the last two exchanges
EARLIER = 2  # older messages brought back by in-chat search
MAX_CHARS = 600  # per message; a course list with its citations runs ~1-2k

_CITATION_LINE = re.compile(r"^\[\d+\] .*$\n?", re.M)  # sources; the [n] marks stay inline
# The advisor's examples ("(e.g. Python, SQL)") are not something the student said; a small
# model reads them back as the student's answer.
EXAMPLES = re.compile(r"\s*\(e\.g\.[^)]*\)")
_WORD = re.compile(r"[a-z]+|\d+")
_STOP = {
    "a", "an", "and", "are", "about", "any", "be", "can", "course", "courses", "class",
    "classes", "do", "does", "for", "from", "have", "how", "i", "in", "is", "it", "me", "my",
    "of", "on", "or", "so", "that", "the", "this", "to", "what", "when", "which", "who",
    "with", "you", "your",
}  # fmt: skip


def words(text: str) -> set[str]:
    return set(_WORD.findall(text.lower()))


def _line(message: dict[str, str]) -> str:
    text = EXAMPLES.sub("", _CITATION_LINE.sub("", message["content"])).strip()
    if len(text) > MAX_CHARS:
        text = text[:MAX_CHARS].rsplit(" ", 1)[0] + "..."
    return f"{'Student' if message['role'] == 'user' else 'Advisor'}: {text}"


def search(history: list[dict[str, str]], text: str, k: int = EARLIER) -> list[dict[str, str]]:
    """Up to k messages from `history` sharing the most words with `text`, oldest first.

    shortcut: keyword overlap, not embeddings; switch to retrieval.embed_query if references
    to older answers miss.
    """
    wanted = words(text) - _STOP
    scored = [(len(wanted & words(m["content"])), i) for i, m in enumerate(history)]
    hits = sorted((s for s in scored if s[0]), reverse=True)[:k]  # ties: the most recent
    return [history[i] for _, i in sorted(hits, key=lambda s: s[1])]


def context(history: list[dict[str, str]], text: str) -> str:
    """The prompt's view of the conversation before `text`: search hits, then recent messages."""
    recent, older = history[-RECENT:], history[:-RECENT]
    lines = [_line(m) for m in recent]
    if earlier := search(older, text):
        lines = ["(earlier)", *map(_line, earlier), "(recent)", *lines]
    return "\n".join(lines) or "(none)"
