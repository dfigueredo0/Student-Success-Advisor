"""Parse the scraper's one-line prerequisite text into the tree `evaluate` reads.

The Banner scraper (pipelines/ingest/illinoistech_banner_scraper.py) flattens Banner's
requirement tree into the text catalog_course.prerequisites stores:

    (CS 116 [min grade D] [may be concurrent]) or (CS 201 [min grade D])
    (Prerequisite Required) and ((MATH 151) or (MATH 147 and MATH 148))
    (ITM 100 to 299 [min grade D]) or (S11 600 to 800)      course range, test-score range

`and` binds tighter than `or`. Banner's header placeholders ("Prerequisite Required") carry no
requirement and are dropped, as are empty operands ("(A and B) or)"). Anything else becomes an
`unparsed` node, which the evaluator never reports as met; unbalanced text is unparsed whole.
"""

import re

from domain.prereq.evaluate import Node

_PLACEHOLDER = re.compile(r"\(\s*pre\w*(?:\s+or\s+test)?\s+(?:re\w*|check)\s*\)", re.I)
_OPERATOR = r"\(|\)|\band\b|\bor\b"
_TOKEN = re.compile(rf"\s*({_OPERATOR}|[^()]+?(?=\s*(?:{_OPERATOR}|$)))")
_SUFFIX = r"(?: \[min grade (\w+)\])?( \[may be concurrent\])?$"
_COURSE = re.compile(rf"^([A-Z][A-Z-]{{1,4}}) (\d{{3}}[A-Z]?){_SUFFIX}")
_RANGE = re.compile(rf"^([A-Z][A-Z-]{{1,4}}) (\d{{3}}) to (\d{{3}}){_SUFFIX}")
_TEST = re.compile(r"^([A-Z0-9]{2,6}) (\d+) to (\d+)$")


class _Unbalanced(Exception):
    pass


def parse(text: str) -> Node | None:
    """None when there is no requirement."""
    tokens = [t.strip() for t in _TOKEN.findall(_PLACEHOLDER.sub("()", text)) if t.strip()]
    try:
        tree, rest = _expr(tokens)
        if rest:
            raise _Unbalanced
    except _Unbalanced:
        return {"type": "unparsed", "text": " ".join(text.split())}
    return tree


def render(node: Node | None) -> str:
    """The scraper's text for a tree: parse(render(t)) == t."""
    if node is None:
        return ""
    kind = node["type"]
    if kind in ("and", "or"):
        return f" {kind} ".join(f"({render(c)})" for c in node["children"])
    if kind == "test":
        return f"{node['test']} {node['low']} to {node['high']}"
    if kind == "unparsed":
        return node["text"]
    head = (
        node["course"]
        if kind == "course"
        else f"{node['subject']} {node['start']} to {node['end']}"
    )
    grade = f" [min grade {node['minimum_grade']}]" if node["minimum_grade"] else ""
    return head + grade + (" [may be concurrent]" if node["concurrent"] else "")


def _expr(tokens: list[str]) -> tuple[Node | None, list[str]]:
    return _chain(tokens, "or", _term)


def _term(tokens: list[str]) -> tuple[Node | None, list[str]]:
    return _chain(tokens, "and", _factor)


def _chain(tokens: list[str], op: str, operand) -> tuple[Node | None, list[str]]:
    node, tokens = operand(tokens)
    kids = [node]
    while tokens and tokens[0] == op:
        node, tokens = operand(tokens[1:])
        kids.append(node)
    kids = [k for k in kids if k is not None]
    if len(kids) < 2:
        return (kids[0] if kids else None), tokens
    return {"type": op, "children": kids}, tokens


def _factor(tokens: list[str]) -> tuple[Node | None, list[str]]:
    if not tokens or tokens[0] in ("and", "or", ")"):
        return None, tokens  # empty operand
    if tokens[0] == "(":
        node, tokens = _expr(tokens[1:])
        if not tokens or tokens[0] != ")":
            raise _Unbalanced
        return node, tokens[1:]
    return _leaf(tokens[0]), tokens[1:]


def _leaf(text: str) -> Node:
    if m := _COURSE.match(text):
        code, grade, concurrent = f"{m[1]} {m[2]}", m[3], bool(m[4])
        return {"type": "course", "course": code, "minimum_grade": grade, "concurrent": concurrent}
    if m := _RANGE.match(text):
        return {
            "type": "course_range",
            "subject": m[1],
            "start": m[2],
            "end": m[3],
            "minimum_grade": m[4],
            "concurrent": bool(m[5]),
        }
    if m := _TEST.match(text):
        return {"type": "test", "test": m[1], "low": m[2], "high": m[3]}
    return {"type": "unparsed", "text": text}
