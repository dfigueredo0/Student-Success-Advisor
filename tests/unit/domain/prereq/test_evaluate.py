"""Prerequisite evaluator: golden UC-01 cases from the fall 2026 catalog, then properties."""

import itertools
import json
from pathlib import Path
from typing import Any

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from domain.prereq import Leaf, Status, evaluate

TREES = {
    code: entry["tree"]
    for code, entry in json.loads(
        (Path(__file__).parents[3] / "fixtures" / "prereq" / "fall2026_trees.json").read_text()
    ).items()
}


def course(code: str, minimum: str | None = "D", concurrent: bool = False) -> dict[str, Any]:
    return {"type": "course", "course": code, "minimum_grade": minimum, "concurrent": concurrent}


def any_of(*children: dict[str, Any]) -> dict[str, Any]:
    return {"type": "or", "children": list(children)}


def all_of(*children: dict[str, Any]) -> dict[str, Any]:
    return {"type": "and", "children": list(children)}


# --- golden: UC-01 on real catalog trees (status and missing set) ---


def test_cs350_or_alternative_is_enough() -> None:
    """The bug the flat check had: CS 116 holders were told they also need CS 201."""
    r = evaluate(TREES["CS 350"], {"CS 115": "A", "CS 116": "B", "CS 330": "A", "CS 331": "B"})
    assert r.status is Status.SATISFIED
    assert r.missing == ()


def test_cs350_missing_names_one_branch() -> None:
    r = evaluate(TREES["CS 350"], {"CS 115": "A"})
    assert r.status is Status.UNSATISFIED
    assert r.missing == (Leaf("CS 116", "D"),)


def test_cs350_allows_concurrent_cs116() -> None:
    r = evaluate(TREES["CS 350"], {"CS 115": "A"}, planned={"CS 116"})
    assert r.status is Status.SATISFIED


def test_cs331_does_not_allow_concurrent_cs116() -> None:
    r = evaluate(TREES["CS 331"], {"CS 115": "A"}, planned={"CS 116"})
    assert r.status is Status.UNSATISFIED


def test_in_progress_prerequisite_is_pending() -> None:
    r = evaluate(TREES["CS 331"], {"CS 115": "A"}, in_progress={"CS 116"})
    assert r.status is Status.PENDING
    assert r.pending == (Leaf("CS 116", "D"),)


def test_grade_below_minimum_reports_what_was_earned() -> None:
    r = evaluate(TREES["MATH 152"], {"MATH 151": "D"})
    assert r.status is Status.UNSATISFIED
    # Equal-cost branches: the first one listed in the catalog is the explanation.
    assert r.missing == (Leaf("MATH 149", "C"),)
    r = evaluate(all_of(course("MATH 151", "C")), {"MATH 151": "D"})
    assert r.missing == (Leaf("MATH 151", "C", "D"),)


def test_retake_in_progress_after_low_grade_is_pending() -> None:
    r = evaluate(TREES["MATH 152"], {"MATH 151": "D"}, in_progress={"MATH 151"})
    assert r.status is Status.PENDING


def test_itmd411_nested_branch() -> None:
    r = evaluate(TREES["ITMD 411"], {"CS 201": "A", "ITM 312": "B"})
    assert r.status is Status.SATISFIED
    r = evaluate(TREES["ITMD 411"], {"CS 201": "A"})
    assert r.status is Status.UNSATISFIED
    assert r.missing == (Leaf("ITM 311", "D"),)  # one course beats the CS 201 + ITM 312 pair


def test_pass_fail_minimum() -> None:
    assert evaluate(TREES["CS 425"], {"CSSP 401": "S"}).status is Status.SATISFIED


def test_test_score_ranges_pass_and_are_listed() -> None:
    # AAH 119: (8 test-score ranges and ICOM 102-106 and HUM 100) or HUM 102 or ... COM 111
    r = evaluate(TREES["AAH 119"], {"ICOM 104": "B", "HUM 100": "C"})
    assert r.status is Status.SATISFIED
    assert "S11 600-800" in r.unchecked_tests
    assert evaluate(TREES["AAH 119"], {"COM 101": "B"}).unchecked_tests == ()


def test_unparsed_course_range_is_recovered() -> None:
    tree = {"type": "unparsed", "text": "ICOM\n  102\n to \n  106 May not be taken concurrently."}
    assert evaluate(tree, {"ICOM 104": "B"}).status is Status.SATISFIED
    assert evaluate(tree, {"ICOM 107": "B"}).missing == (Leaf("ICOM 102-106"),)


def test_unreadable_text_is_never_met() -> None:
    r = evaluate(TREES["INTR 011"], {"CS 116": "A"})
    assert r.status is Status.UNSATISFIED
    assert r.unreadable


def test_readable_branch_wins_over_unreadable() -> None:
    tree = any_of({"type": "unparsed", "text": "Course"}, course("CS 116"))
    r = evaluate(tree, {})
    assert r.missing == (Leaf("CS 116", "D"),)
    assert r.unreadable == ()


def test_no_tree_is_satisfied() -> None:
    assert evaluate(None, {}).status is Status.SATISFIED


# --- unknown grades: ask only for the grades that decide the answer ---


def test_reported_course_without_grade_meets_d_minimum() -> None:
    assert evaluate(TREES["CS 331"], {"CS 116": None}).status is Status.SATISFIED


def test_unknown_grade_against_c_minimum_needs_grade() -> None:
    r = evaluate(TREES["MATH 152"], {"MATH 151": None})
    assert r.status is Status.NEEDS_GRADE
    assert r.needs_grade == (Leaf("MATH 151", "C"),)
    assert r.if_grade_too_low is Status.UNSATISFIED


def test_unknown_grade_is_not_asked_when_another_branch_decides() -> None:
    r = evaluate(TREES["MATH 152"], {"MATH 151": None, "MATH 149": "A"})
    assert r.status is Status.SATISFIED
    assert r.needs_grade == ()


def test_unknown_grade_is_not_asked_when_answer_is_no_anyway() -> None:
    tree = all_of(course("MATH 151", "C"), course("CS 116"))
    r = evaluate(tree, {"MATH 151": None})
    assert r.status is Status.UNSATISFIED
    assert r.missing == (Leaf("CS 116", "D"),)
    assert r.if_grade_too_low is None


def test_needs_grade_falls_back_to_pending() -> None:
    tree = any_of(course("MATH 151", "C"), course("MATH 149", "C"))
    r = evaluate(tree, {"MATH 151": None}, in_progress={"MATH 149"})
    assert r.status is Status.NEEDS_GRADE
    assert r.if_grade_too_low is Status.PENDING


# --- properties against a brute-force reference ---

CODES = ["CS 100", "CS 116", "CS 201", "CS 331", "CS 350"]
GRADES = ["A", "B", "C", "D", "E", "TR", None]

leaves = st.builds(
    course,
    st.sampled_from(CODES),
    st.sampled_from([None, "D", "C"]),
    st.booleans(),
)
trees = st.recursive(
    leaves,
    lambda kids: st.builds(
        lambda kind, children: {"type": kind, "children": children},
        st.sampled_from(["and", "or"]),
        st.lists(kids, min_size=2, max_size=3),
    ),
    max_leaves=6,
)
students = st.tuples(
    st.dictionaries(st.sampled_from(CODES), st.sampled_from(GRADES), max_size=4),
    st.sets(st.sampled_from(CODES), max_size=2),
    st.sets(st.sampled_from(CODES), max_size=2),
)


def clauses(node: dict[str, Any]) -> list[list[dict[str, Any]]]:
    """Disjunctive normal form: every set of leaves that together meets the tree."""
    if node["type"] == "course":
        return [[node]]
    parts = [clauses(c) for c in node["children"]]
    if node["type"] == "or":
        return [clause for part in parts for clause in part]
    return [list(itertools.chain.from_iterable(combo)) for combo in itertools.product(*parts)]


RANK = {Status.UNSATISFIED: 0, Status.PENDING: 1, Status.SATISFIED: 2}


def reference(node: dict[str, Any], completed: dict, in_progress: set, planned: set) -> Status:
    """Brute force, grades known: best clause, where a clause is as good as its worst leaf."""
    from domain.grades import grade_satisfies

    def leaf(n: dict[str, Any]) -> Status:
        if n["course"] in completed and grade_satisfies(completed[n["course"]], n["minimum_grade"]):
            return Status.SATISFIED
        if n["course"] in in_progress:
            return Status.PENDING
        if n["concurrent"] and n["course"] in planned:
            return Status.SATISFIED
        return Status.UNSATISFIED

    best = max(min(RANK[leaf(n)] for n in clause) for clause in clauses(node))
    return next(s for s, r in RANK.items() if r == best)


@settings(max_examples=300)
@given(trees, students)
def test_status_matches_brute_force_when_grades_known(tree: dict, student: tuple) -> None:
    completed, in_progress, planned = student
    completed = {c: g for c, g in completed.items() if g is not None}
    expected = reference(tree, completed, in_progress, planned)
    assert evaluate(tree, completed, in_progress, planned).status is expected


@settings(max_examples=300)
@given(trees, students)
def test_taking_the_missing_courses_is_enough(tree: dict, student: tuple) -> None:
    completed, in_progress, planned = student
    r = evaluate(tree, completed, in_progress, planned)
    after = {**completed, **{leaf.requirement: "A" for leaf in r.missing}}
    assert evaluate(tree, after, in_progress, planned).status is not Status.UNSATISFIED


@settings(max_examples=300)
@given(trees, students, st.sampled_from(CODES))
def test_monotone_in_completed_courses(tree: dict, student: tuple, extra: str) -> None:
    completed, in_progress, planned = student
    completed = {c: g for c, g in completed.items() if g is not None}
    before = evaluate(tree, completed, in_progress, planned).status
    after = evaluate(tree, {**completed, extra: "A"}, in_progress, planned).status
    assert RANK[after] >= RANK[before]


@settings(max_examples=300)
@given(trees, students)
def test_unknown_grade_answer_brackets_both_outcomes(tree: dict, student: tuple) -> None:
    completed, in_progress, planned = student
    r = evaluate(tree, completed, in_progress, planned)
    # "D" behaves like an unknown grade except against a minimum above D.
    best = evaluate(tree, {c: g or "A" for c, g in completed.items()}, in_progress, planned)
    worst = evaluate(tree, {c: g or "D" for c, g in completed.items()}, in_progress, planned)
    if r.status is Status.NEEDS_GRADE:
        assert best.status is not worst.status
        assert r.if_grade_too_low is worst.status
        assert r.needs_grade
    else:
        assert r.status is best.status is worst.status


@pytest.mark.parametrize("bad", [{"type": "nof"}, {"type": "course"}])
def test_malformed_tree_raises(bad: dict) -> None:
    with pytest.raises((ValueError, KeyError)):
        evaluate(bad, {})
