"""
prereq_parser.py: turn Banner "General Requirements" text into a boolean tree.

Input:
    ( Course or Test: CS 331 Minimum Grade of D May not be taken concurrently.
      and Course or Test: CS 350 Minimum Grade of D May not be taken concurrently. )
    or ( ... )

Output tree:
    {"type": "course", "course": "CS 331", "minimum_grade": "D", "concurrent": False}
    {"type": "course_range", "subject": "ICOM", "start": "102", "end": "106",
     "minimum_grade": None, "concurrent": False}
    {"type": "and" | "or", "children": [...]}
    {"type": "unparsed", "text": "..."}
"""

from __future__ import annotations

import re
from typing import Iterable


# --------------------------------------------------------------------------
# 1. Isolate the requirements text
# --------------------------------------------------------------------------

_MD_LINK = re.compile(r"\[([^\]]+)\]\([^)]*\)")
_GEN_REQ = re.compile(r"General Requirements:\s*(.*)", re.S)
_PREREQ_HDR = re.compile(r"Prerequisites?:", re.I)


def extract_requirements_text(raw: str) -> str:
    raw = _MD_LINK.sub(r"\1", raw)

    # Banner can vary whitespace/capitalization around the labels.
    # Keep everything after "General Requirements:".
    matches = list(
        re.finditer(
            r"General\s+Requirements\s*:",
            raw,
            re.IGNORECASE,
        )
    )

    if matches:
        text = raw[matches[-1].end():].strip()

        # Banner sometimes includes the course's credit value
        # immediately before the prerequisite expression.
        text = re.sub(
            r"^\s*\d+(?:\.\d+)?\s+credits?\s*",
            "",
            text,
            flags=re.IGNORECASE,
        )

        return text

    return ""


# --------------------------------------------------------------------------
# 2. Tokenizer
# --------------------------------------------------------------------------

_COURSE_ATOM = (
    r"(?P<course>Course\s+or\s+Test:\s*"
    r"(?P<subj>[A-Z]{2,5})\s+"
    r"(?P<num>\d{3}[A-Z]?)"
    r"(?:\s+to\s+(?P<num_end>\d{3}[A-Z]?))?"
    r"(?:\s*Minimum\s+Grade\s+of\s*"
    r"(?P<grade>[A-F][+-]?|P|S|TR))?"
    r"(?:\s*(?P<conc>"
    r"May\s+(?:not\s+)?be\s+taken\s+concurrently\.?"
    r"))?)"
)

_TOKEN = re.compile(
    _COURSE_ATOM
    + r"|(?P<lp>\()"
    + r"|(?P<rp>\))"
    + r"|(?P<and>\band\b)"
    + r"|(?P<or>\bor\b)"
)


def tokenize(text: str) -> list[tuple[str, object]]:
    # Banner sometimes emits empty prerequisite branches containing
    # only "May not be taken concurrently." and boolean operators.
    # These do not represent actual prerequisite conditions.
    empty_branch = (
        r"\(\s*"
        r"May\s+not\s+be\s+taken\s+concurrently\.?"
        r"(?:\s+(?:and|or)\s+"
        r"May\s+not\s+be\s+taken\s+concurrently\.?)*"
        r"\s*\)"
    )

    # Remove an empty branch together with a boolean operator immediately
    # before it. For example:
    #
    #     ... ) or ( May not be taken concurrently. )
    #
    # becomes:
    #
    #     ... )
    #
    # The same works for "and".
    text = re.sub(
        r"\s+(?:and|or)\s+" + empty_branch,
        "",
        text,
        flags=re.IGNORECASE,
    )

    # Remove an empty branch at the beginning of an expression.
    text = re.sub(
        empty_branch,
        "",
        text,
        flags=re.IGNORECASE,
    )

    # Banner can also leave a boolean operator followed by a bare
    # "May not be taken concurrently." fragment.
    text = re.sub(
        r"\s*\b(?:and|or)\s+"
        r"May\s+not\s+be\s+taken\s+concurrently\.?",
        "",
        text,
        flags=re.IGNORECASE,
    )

    tokens: list[tuple[str, object]] = []
    pos = 0

    for m in _TOKEN.finditer(text):
        gap = text[pos:m.start()].strip()

        if gap:
            if gap.lower() != "may not be taken concurrently.":
                tokens.append(("unparsed", gap))

        pos = m.end()

        if m.group("course"):
            conc = m.group("conc") or ""

            if m.group("num_end"):
                tokens.append(("course_range", {
                    "type": "course_range",
                    "subject": m.group("subj"),
                    "start": m.group("num"),
                    "end": m.group("num_end"),
                    "minimum_grade": m.group("grade"),
                    "concurrent": conc.startswith("May be"),
                }))
            else:
                tokens.append(("course", {
                    "type": "course",
                    "course": f'{m.group("subj")} {m.group("num")}',
                    "minimum_grade": m.group("grade"),
                    "concurrent": conc.startswith("May be"),
                }))

        elif m.group("lp"):
            tokens.append(("lp", None))

        elif m.group("rp"):
            tokens.append(("rp", None))

        elif m.group("and"):
            tokens.append(("and", None))

        else:
            tokens.append(("or", None))

    tail = text[pos:].strip()

    if tail and tail.lower() != "may not be taken concurrently.":
        tokens.append(("unparsed", tail))

    return tokens


# --------------------------------------------------------------------------
# 3. Recursive-descent parser
#
# expr := term ('or' term)*
# term := factor ('and' factor)*
# --------------------------------------------------------------------------

class _Parser:
    def __init__(self, tokens):
        self.t = tokens
        self.i = 0

    def peek(self):
        return self.t[self.i][0] if self.i < len(self.t) else None

    def next(self):
        tok = self.t[self.i]
        self.i += 1
        return tok

    def expr(self):
        kids = [self.term()]

        while self.peek() == "or":
            self.next()
            kids.append(self.term())

        return _make("or", kids)

    def term(self):
        kids = [self.factor()]

        while self.peek() == "and":
            self.next()
            kids.append(self.factor())

        return _make("and", kids)

    def factor(self):
        kind = self.peek()

        if kind == "lp":
            self.next()

            node = self.expr()

            if self.peek() == "rp":
                self.next()

            return node

        if kind in ("course", "course_range", "unparsed"):
            _, val = self.next()

            if kind == "unparsed":
                return {
                    "type": "unparsed",
                    "text": val,
                }

            return val

        raise ValueError(
            f"unexpected token {kind!r} at {self.i}"
        )


def _make(op: str, kids: list[dict]) -> dict:
    flat: list[dict] = []

    for k in kids:
        if k["type"] == op:
            flat.extend(k["children"])
        else:
            flat.append(k)

    return (
        flat[0]
        if len(flat) == 1
        else {"type": op, "children": flat}
    )


def parse_expression(text: str) -> dict | None:
    if not text.strip():
        return None

    tokens = tokenize(text)

    if not tokens:
        return None

    p = _Parser(tokens)

    tree = p.expr()

    if p.i != len(tokens):
        raise ValueError(
            f"trailing tokens: {tokens[p.i:]}"
        )

    return tree


# --------------------------------------------------------------------------
# 4. Human-readable expression
# --------------------------------------------------------------------------

def to_expression(node: dict | None) -> str:
    if node is None:
        return ""

    t = node["type"]

    if t == "course":
        s = node["course"]

        extras = []

        if node.get("minimum_grade"):
            extras.append(
                f'min {node["minimum_grade"]}'
            )

        if node.get("concurrent"):
            extras.append("concurrent OK")

        return (
            f'{s} ({", ".join(extras)})'
            if extras
            else s
        )

    if t == "course_range":
        s = (
            f'{node["subject"]} '
            f'{node["start"]} to '
            f'{node["end"]}'
        )

        extras = []

        if node.get("minimum_grade"):
            extras.append(
                f'min {node["minimum_grade"]}'
            )

        if node.get("concurrent"):
            extras.append("concurrent OK")

        return (
            f'{s} ({", ".join(extras)})'
            if extras
            else s
        )

    if t == "unparsed":
        return f'[{node["text"]}]'

    joined = f" {t.upper()} ".join(
        (
            f"({to_expression(c)})"
            if c["type"] in ("and", "or")
            else to_expression(c)
        )
        for c in node["children"]
    )

    return joined


# --------------------------------------------------------------------------
# 5. Course helpers
# --------------------------------------------------------------------------

def mentioned_courses(node: dict | None) -> list[str]:
    if node is None:
        return []

    if node["type"] == "course":
        return [node["course"]]

    if node["type"] == "course_range":
        return [
            f'{node["subject"]} '
            f'{node["start"]} to '
            f'{node["end"]}'
        ]

    if node["type"] == "unparsed":
        return []

    return [
        course
        for child in node["children"]
        for course in mentioned_courses(child)
    ]


# --------------------------------------------------------------------------
# 6. Requirement satisfaction
# --------------------------------------------------------------------------

GRADE_ORDER = [
    "F",
    "D",
    "D+",
    "C-",
    "C",
    "C+",
    "B-",
    "B",
    "B+",
    "A-",
    "A",
]


def _grade_ok(
    have: str | None,
    need: str | None,
) -> bool:
    if not need:
        return True

    if (
        have not in GRADE_ORDER
        or need not in GRADE_ORDER
    ):
        return have == need

    return (
        GRADE_ORDER.index(have)
        >= GRADE_ORDER.index(need)
    )


def is_satisfied(
    node: dict | None,
    completed: dict[str, str],
    in_progress: Iterable[str] = (),
) -> bool:
    if node is None:
        return True

    t = node["type"]

    if t == "course":
        course = node["course"]

        if (
            course in completed
            and _grade_ok(
                completed[course],
                node.get("minimum_grade"),
            )
        ):
            return True

        return (
            bool(node.get("concurrent"))
            and course in set(in_progress)
        )

    if t == "course_range":
        # A range represents a family of acceptable courses.
        # Check whether any completed course falls inside it.
        subject = node["subject"]

        try:
            start = int(
                re.match(r"\d+", node["start"]).group()
            )
            end = int(
                re.match(r"\d+", node["end"]).group()
            )
        except (AttributeError, ValueError):
            return False

        for course, grade in completed.items():
            match = re.match(
                r"^([A-Z]{2,5})\s+(\d+)",
                course,
            )

            if not match:
                continue

            course_subject = match.group(1)
            course_number = int(match.group(2))

            if (
                course_subject == subject
                and start <= course_number <= end
                and _grade_ok(
                    grade,
                    node.get("minimum_grade"),
                )
            ):
                return True

        if node.get("concurrent"):
            for course in in_progress:
                match = re.match(
                    r"^([A-Z]{2,5})\s+(\d+)",
                    course,
                )

                if not match:
                    continue

                course_subject = match.group(1)
                course_number = int(match.group(2))

                if (
                    course_subject == subject
                    and start <= course_number <= end
                ):
                    return True

        return False

    if t == "unparsed":
        return False

    results = (
        is_satisfied(
            child,
            completed,
            in_progress,
        )
        for child in node["children"]
    )

    return (
        all(results)
        if t == "and"
        else any(results)
    )


# --------------------------------------------------------------------------
# 7. Diagnostics
# --------------------------------------------------------------------------

def count_unparsed(node: dict | None) -> int:
    if node is None:
        return 0

    if node["type"] in (
        "course",
        "course_range",
    ):
        return 0

    if node["type"] == "unparsed":
        return 1

    return sum(
        count_unparsed(child)
        for child in node["children"]
    )


# --------------------------------------------------------------------------
# 8. NetworkX representation
# --------------------------------------------------------------------------

def to_networkx(
    course_id: str,
    tree: dict | None,
):
    import networkx as nx

    g = nx.DiGraph()

    g.add_node(
        course_id,
        kind="target",
    )

    counter = iter(range(10**9))

    def walk(node, parent):
        nid = (
            f"{course_id}#"
            f"{next(counter)}"
        )

        if node["type"] in (
            "and",
            "or",
        ):
            g.add_node(
                nid,
                kind=node["type"],
            )

            g.add_edge(
                parent,
                nid,
            )

            for child in node["children"]:
                walk(child, nid)

        elif node["type"] == "course":
            g.add_node(
                nid,
                kind="course",
                course=node["course"],
                minimum_grade=node.get(
                    "minimum_grade"
                ),
                concurrent=node.get(
                    "concurrent"
                ),
            )

            g.add_edge(
                parent,
                nid,
            )

        elif node["type"] == "course_range":
            g.add_node(
                nid,
                kind="course_range",
                subject=node["subject"],
                start=node["start"],
                end=node["end"],
                minimum_grade=node.get(
                    "minimum_grade"
                ),
                concurrent=node.get(
                    "concurrent"
                ),
            )

            g.add_edge(
                parent,
                nid,
            )

        else:
            g.add_node(
                nid,
                kind="unparsed",
                text=node["text"],
            )

            g.add_edge(
                parent,
                nid,
            )

    if tree:
        walk(tree, course_id)

    return g


# --------------------------------------------------------------------------
# 9. SQL representation
# --------------------------------------------------------------------------

PREREQ_DDL = """
CREATE TABLE IF NOT EXISTS prereq_node (
    id             INTEGER PRIMARY KEY,
    course_id      TEXT    NOT NULL,
    parent_id      INTEGER REFERENCES prereq_node(id) ON DELETE CASCADE,
    position       INTEGER NOT NULL DEFAULT 0,

    node_type      TEXT    NOT NULL CHECK (
        node_type IN (
            'and',
            'or',
            'course',
            'course_range',
            'unparsed'
        )
    ),

    req_course_id  TEXT,
    req_subject    TEXT,
    req_start      TEXT,
    req_end        TEXT,

    minimum_grade  TEXT,
    concurrent     BOOLEAN,
    raw_text       TEXT
);

CREATE INDEX IF NOT EXISTS ix_prereq_course
ON prereq_node(course_id);

CREATE INDEX IF NOT EXISTS ix_prereq_parent
ON prereq_node(parent_id);
"""


def to_rows(
    course_id: str,
    tree: dict | None,
) -> list[dict]:
    rows: list[dict] = []

    def walk(
        node,
        parent,
        pos,
    ):
        rid = len(rows) + 1

        rows.append({
            "id": rid,
            "course_id": course_id,
            "parent_id": parent,
            "position": pos,
            "node_type": node["type"],

            "req_course_id": node.get(
                "course"
            ),

            "req_subject": node.get(
                "subject"
            ),

            "req_start": node.get(
                "start"
            ),

            "req_end": node.get(
                "end"
            ),

            "minimum_grade": node.get(
                "minimum_grade"
            ),

            "concurrent": node.get(
                "concurrent"
            ),

            "raw_text": node.get(
                "text"
            ),
        })

        for i, child in enumerate(
            node.get("children", [])
        ):
            walk(
                child,
                rid,
                i,
            )

    if tree:
        walk(
            tree,
            None,
            0,
        )

    return rows


def from_rows(
    rows: list[dict],
) -> dict | None:
    by_parent: dict = {}

    for row in sorted(
        rows,
        key=lambda r: r["position"],
    ):
        by_parent.setdefault(
            row["parent_id"],
            [],
        ).append(row)

    def build(row):
        node_type = row["node_type"]

        if node_type in (
            "and",
            "or",
        ):
            return {
                "type": node_type,
                "children": [
                    build(child)
                    for child in by_parent.get(
                        row["id"],
                        [],
                    )
                ],
            }

        if node_type == "course":
            return {
                "type": "course",
                "course": row["req_course_id"],
                "minimum_grade": row[
                    "minimum_grade"
                ],
                "concurrent": bool(
                    row["concurrent"]
                ),
            }

        if node_type == "course_range":
            return {
                "type": "course_range",
                "subject": row[
                    "req_subject"
                ],
                "start": row[
                    "req_start"
                ],
                "end": row[
                    "req_end"
                ],
                "minimum_grade": row[
                    "minimum_grade"
                ],
                "concurrent": bool(
                    row["concurrent"]
                ),
            }

        return {
            "type": "unparsed",
            "text": row["raw_text"],
        }

    roots = by_parent.get(
        None,
        [],
    )

    return (
        build(roots[0])
        if roots
        else None
    )


# --------------------------------------------------------------------------
# 10. Function scraper.py calls
# --------------------------------------------------------------------------


def parse_prerequisites(
    raw_blob: str,
    keep_raw: bool = False,
) -> dict:
    text = extract_requirements_text(raw_blob)

    # raw_blob may already be the extracted
    # "General Requirements" text.
    if not text and raw_blob.strip():
        text = raw_blob.strip()

    tree = parse_expression(text)

    out = {
        "expression": to_expression(tree),
        "tree": tree,
        "unparsed_count": count_unparsed(tree),
    }

    if keep_raw:
        out["raw"] = raw_blob

    return out

