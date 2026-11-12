"""call_tool: the allow-list and the limits on what reaches a tool."""

from typing import Any

import pytest

from tools.guard import ToolArgsInvalid, ToolNotAllowed, call_tool


def lookup(**kwargs: Any) -> dict[str, Any]:
    return {"ok": True}


def test_tool_outside_the_allow_list_is_refused() -> None:
    with pytest.raises(ToolNotAllowed):
        call_tool(lookup, {"something_else"})


@pytest.mark.parametrize(
    "args",
    [
        {"course": "CS 450", "completed_courses": ["CS 115", "MATH 151"], "grades": None},
        {"course": "IPRO 497", "in_progress_courses": [], "term": "Fall 2026"},
        {"query": "machine learning", "subject": "CS", "limit": 6},
        {"grades": {"CS 115": "A", "MATH 151": "TR"}},
        {"current_skills": ["Python", "SQL"], "desired_skills": [], "graduation_year": 2027},
        {"posting": "x" * 4000},
        {"role": "r" * 120},
    ],
)
def test_ordinary_arguments_pass(args: dict[str, Any]) -> None:
    assert call_tool(lookup, {"lookup"}, **args)["result"] == {"ok": True}


@pytest.mark.parametrize(
    "args",
    [
        {"course": "CS 450; DROP TABLE catalog_course"},
        {"course": "x" * 40},
        {"completed_courses": ["CS 115", "not a course"]},
        {"completed_courses": ["CS 115"] * 151},
        {"in_progress_courses": [42]},
        {"grades": {"CS 115": "A", "bad key": "A"}},
        {"grades": {f"CS {n}": "A" for n in range(100, 251)}},
        {"query": "x" * 501},
        {"current_skills": ["Python"] * 401},
        {"current_skills": ["x" * 101]},
        {"desired_skills": [42]},
        {"current_skills": "Python, SQL"},
        {"posting": "x" * 4001},
        {"posting": ["Responsibilities"]},
        {"role": "r" * 121},
        {"role": ["analyst"]},
    ],
)
def test_arguments_outside_the_limits_never_reach_the_tool(args: dict[str, Any]) -> None:
    calls: list[dict[str, Any]] = []

    def tool(**kwargs: Any) -> dict[str, Any]:
        calls.append(kwargs)
        return {}

    tool.__name__ = "lookup"
    with pytest.raises(ToolArgsInvalid):
        call_tool(tool, {"lookup"}, **args)
    assert calls == []
