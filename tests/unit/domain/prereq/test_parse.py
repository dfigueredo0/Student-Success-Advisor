"""Parser for the scraper's prerequisite text: golden fall 2026 strings, then round trip."""

import json
from pathlib import Path
from typing import Any

import pytest

from domain.prereq import Status, evaluate
from domain.prereq.parse import parse, render


def course(code: str, minimum: str | None = None, concurrent: bool = False) -> dict[str, Any]:
    return {"type": "course", "course": code, "minimum_grade": minimum, "concurrent": concurrent}


def test_or_of_concurrent_courses() -> None:
    tree = parse(
        "(CS 116 [min grade D] [may be concurrent]) or (CS 201 [min grade D] [may be concurrent])"
    )
    assert tree == {
        "type": "or",
        "children": [course("CS 116", "D", True), course("CS 201", "D", True)],
    }
    # the student from the bug report: CS 116 holders are not sent to CS 201
    assert evaluate(tree, {"CS 115": None, "CS 116": None}).status is Status.SATISFIED


def test_and_binds_tighter_than_or() -> None:
    assert parse("(MATH 151) or (MATH 147 and MATH 148)") == {
        "type": "or",
        "children": [
            course("MATH 151"),
            {"type": "and", "children": [course("MATH 147"), course("MATH 148")]},
        ],
    }
    assert parse("(CS 100) or (CS 104) and (CS 105) or (CS 115)")["children"][1]["type"] == "and"


@pytest.mark.parametrize(
    "text",
    [
        "(Prerequisite Required) and ((CS 331))",
        "(Prerequisite requried) and (CS 331)",
        "(Prequisites Required) and (CS 331)",
        "(Prerequisite Check) and ((CS 331))",
        "(Prerequisite Required) and ((CS 331) or)",
    ],
)
def test_banner_placeholders_and_empty_operands_are_dropped(text: str) -> None:
    assert parse(text) == course("CS 331")


def test_ranges_tests_and_hyphenated_subjects() -> None:
    tree = parse("(ITM 100 to 299 [min grade D]) or (S11 600 to 800) or (IT-S 838 [min grade P])")
    assert tree["children"] == [
        {
            "type": "course_range",
            "subject": "ITM",
            "start": "100",
            "end": "299",
            "minimum_grade": "D",
            "concurrent": False,
        },
        {"type": "test", "test": "S11", "low": "600", "high": "800"},
        course("IT-S 838", "P"),
    ]


def test_unknown_text_is_unparsed_never_met() -> None:
    tree = parse(
        "(Must be registered) and ((AAH [may be concurrent]) or (ARCH [may be concurrent]))"
    )
    assert evaluate(tree, {"ARCH 113": "A"}).status is Status.UNSATISFIED
    unbalanced = "(Prerequisite Required) and (3.000 credits (MATH 563 [min grade B]) or (MATH 564"
    assert parse(unbalanced) == {"type": "unparsed", "text": unbalanced}


def test_empty_text_has_no_requirement() -> None:
    assert parse("") is None
    assert parse("(Prerequisite Required)") is None


TREES = json.loads(
    (Path(__file__).parents[3] / "fixtures" / "prereq" / "fall2026_trees.json").read_text()
)


@pytest.mark.parametrize("code", sorted(TREES))
def test_parse_render_parse_round_trip(code: str) -> None:
    tree = parse(render(TREES[code]["tree"]))
    assert parse(render(tree)) == tree
