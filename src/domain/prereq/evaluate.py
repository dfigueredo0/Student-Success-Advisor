"""Evaluate a prerequisite tree against what a student has done.

Trees come from the Banner parser (pipelines/ingest/prereq_parser.py, stored per course in
data/catalog/*.json): `and` / `or` / `course` / `course_range` / `unparsed`.

Every subtree is scored by the cheapest way to meet it: (unmet leaves, pending leaves,
leaves resting on an unknown grade). AND adds, OR takes its cheapest child, so the status
falls out of the score (AND = min, OR = max) and the cheapest branch is the explanation:
a student holding CS 201 is never told to also take CS 116.

Unknown grades are evaluated twice, assuming they pass and assuming they fail. When the two
answers differ the result is NEEDS_GRADE and lists only the grades on the deciding branch,
so the advisor asks for those and nothing else.
"""

import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from domain.grades import grade_satisfies

Node = dict[str, Any]


class Status(StrEnum):
    SATISFIED = "satisfied"
    PENDING = "pending"  # met once the student's in-progress courses finish
    UNSATISFIED = "unsatisfied"
    NEEDS_GRADE = "needs_grade"  # an unknown grade decides between two answers


@dataclass(frozen=True)
class Leaf:
    requirement: str  # "CS 116", or "ICOM 102-106" for a range
    minimum_grade: str | None = None
    earned: str | None = None  # the grade the student has toward it, when it fell short


@dataclass(frozen=True)
class Eligibility:
    status: Status
    missing: tuple[Leaf, ...] = ()  # cheapest set still to take
    pending: tuple[Leaf, ...] = ()  # in-progress courses the answer relies on
    needs_grade: tuple[Leaf, ...] = ()  # unknown grades the answer relies on
    if_grade_too_low: Status | None = None  # the answer when a needs_grade grade falls short
    unchecked_tests: tuple[str, ...] = ()  # test-score requirements passed without checking
    unreadable: tuple[str, ...] = ()  # requirement text the parser could not read


def evaluate(
    tree: Node | None,
    completed: Mapping[str, str | None],
    in_progress: Iterable[str] = (),
    planned: Iterable[str] = (),
) -> Eligibility:
    """Check one course's prerequisite tree for the term the student wants to take it in.

    completed: course -> grade for work finished before that term; None when the student
      reported the course without a grade (no transcript).
    in_progress: finishes before that term, grade not yet known; counts as PENDING.
    planned: taken in that same term; counts only where Banner allows concurrent enrollment.
    """
    if tree is None:
        return Eligibility(Status.SATISFIED)
    student = _Student(dict(completed), frozenset(in_progress), frozenset(planned))
    hopeful = _walk(tree, student, optimistic=True)
    wary = _walk(tree, student, optimistic=False)
    status = hopeful.status
    if status != wary.status:
        return Eligibility(
            Status.NEEDS_GRADE,
            missing=hopeful.unmet,
            pending=hopeful.pending,
            needs_grade=hopeful.assumed,
            if_grade_too_low=wary.status,
            unchecked_tests=hopeful.tests,
            unreadable=hopeful.unreadable,
        )
    return Eligibility(
        status,
        missing=hopeful.unmet,
        pending=hopeful.pending,
        needs_grade=hopeful.assumed,
        unchecked_tests=hopeful.tests,
        unreadable=hopeful.unreadable,
    )


@dataclass(frozen=True)
class _Student:
    completed: dict[str, str | None]
    in_progress: frozenset[str]
    planned: frozenset[str]


# An unreadable requirement is only the explanation when no readable branch is left.
_UNREADABLE_COST = 1000


def _union(a: tuple[Any, ...], b: tuple[Any, ...]) -> tuple[Any, ...]:
    return a + tuple(x for x in b if x not in a)


@dataclass(frozen=True)
class _Path:
    """The cheapest way found to meet a subtree."""

    unmet: tuple[Leaf, ...] = ()
    pending: tuple[Leaf, ...] = ()
    assumed: tuple[Leaf, ...] = ()
    tests: tuple[str, ...] = ()
    unreadable: tuple[str, ...] = ()

    def cost(self) -> tuple[int, int, int]:
        unmet = len(self.unmet) + _UNREADABLE_COST * len(self.unreadable)
        return (unmet, len(self.pending), len(self.assumed))

    @property
    def status(self) -> Status:
        unmet, pending, _ = self.cost()
        if unmet:
            return Status.UNSATISFIED
        return Status.PENDING if pending else Status.SATISFIED

    def __add__(self, other: "_Path") -> "_Path":
        return _Path(
            _union(self.unmet, other.unmet),
            _union(self.pending, other.pending),
            _union(self.assumed, other.assumed),
            _union(self.tests, other.tests),
            _union(self.unreadable, other.unreadable),
        )


def _walk(node: Node, s: _Student, optimistic: bool) -> _Path:
    kind = node["type"]
    if kind == "and":
        total = _Path()
        for child in node["children"]:
            total += _walk(child, s, optimistic)
        return total
    if kind == "or":
        return min((_walk(c, s, optimistic) for c in node["children"]), key=_Path.cost)
    if kind == "course":
        return _course(node["course"], node["course"], node, s, optimistic)
    if kind == "course_range":
        return _course_range(node, s, optimistic)
    if kind == "unparsed":
        reread = _reread(node)
        if reread is not node:
            return _walk(reread, s, optimistic)
        # TODO: needs decision - unreadable requirement text (INTR placeholders, odd
        # Banner layouts). Never reported as met; the advisor should send the student to
        # an advisor for it.
        return _Path(unreadable=(" ".join(node["text"].split()),))
    if kind == "test":
        # TODO: needs decision - test scores are not on the transcript we read; a
        # test-score requirement passes for now and is listed in `unchecked_tests`.
        return _Path(tests=(f"{node['test']} {node['low']}-{node['high']}",))
    raise ValueError(f"unknown prerequisite node type {kind!r}")


def _course(code: str, label: str, node: Node, s: _Student, optimistic: bool) -> _Path:
    minimum = node.get("minimum_grade")
    earned = None
    if code in s.completed:
        earned = s.completed[code]
        met = grade_satisfies(earned, minimum)
        if met:
            return _Path()
        if met is None and optimistic:
            return _Path(assumed=(Leaf(label, minimum),))
    if code in s.in_progress:  # first attempt, or a retake after a grade that fell short
        return _Path(pending=(Leaf(label, minimum),))
    if node.get("concurrent") and code in s.planned:
        return _Path()
    return _Path(unmet=(Leaf(label, minimum, earned),))


_CODE = re.compile(r"^([A-Z]{2,5}) (\d+)")


def _course_range(node: Node, s: _Student, optimistic: bool) -> _Path:
    subject, low, high = node["subject"], _number(node["start"]), _number(node["end"])
    label = f"{subject} {node['start']}-{node['end']}"
    taken = set(s.completed) | s.in_progress | s.planned
    candidates = [
        _course(code, label, node, s, optimistic)
        for code in sorted(taken)
        if (m := _CODE.match(code)) and m.group(1) == subject and low <= int(m.group(2)) <= high
    ]
    unmet = _Path(unmet=(Leaf(label, node.get("minimum_grade")),))
    return min([*candidates, unmet], key=_Path.cost)


def _number(course_number: str) -> int:
    return int(re.match(r"\d+", course_number).group())  # "101A" -> 101


_RANGE = re.compile(r"^([A-Z][A-Z0-9]{1,4})\s+(\d+)\s+to\s+(\d+)")


def _reread(node: Node) -> Node:
    """Recover the ranges the Banner parser leaves unparsed.

    "ICOM 102 to 106" (no "Course or Test:" prefix) is a course range; codes with digits or
    non-course numbers ("S11 600 to 800", "AWR 7 to 12") are test-score ranges.
    TODO: needs impl - move this into the parser when the scrapers merge.
    """
    m = _RANGE.match(node["text"])
    if not m:
        return node
    code, low, high = m.groups()
    concurrent = re.search(r"May be taken concurrently", node["text"]) is not None
    if code.isalpha() and len(low) == len(high) == 3:
        return {
            "type": "course_range",
            "subject": code,
            "start": low,
            "end": high,
            "minimum_grade": None,
            "concurrent": concurrent,
        }
    return {"type": "test", "test": code, "low": low, "high": high}
