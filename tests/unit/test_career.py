from typing import Any

import pytest

from agents.career_advisor import _goal, parse_skills
from domain.skills import skill_gap
from tools.career import skill_courses


def test_skill_gap_is_case_insensitive_ordered_and_deduped() -> None:
    assert skill_gap(
        ["Python", "SQL"], ["sql", "Machine  Learning", "python", "Docker", "docker"]
    ) == [
        "Machine  Learning",
        "Docker",
    ]
    assert skill_gap([], []) == []
    assert skill_gap(["a"], ["  "]) == []


@pytest.mark.parametrize(
    ("text", "skills"),
    [
        ("Python, SQL and machine learning", ["Python", "SQL", "machine learning"]),
        ("I know java; c++", ["java", "c++"]),
        ("python, Python.", ["python"]),
    ],
)
def test_parse_skills(text: str, skills: list[str]) -> None:
    assert parse_skills(text) == skills


@pytest.mark.parametrize(
    ("text", "asked", "goal"),
    [
        ("What skills do I need to become a data scientist?", False, "data scientist"),
        ("I want to work as an embedded engineer and travel", False, "embedded engineer"),
        ("I want to be able to code", False, None),  # "be" needs an article
        ("product manager.", True, "product manager"),
        ("not sure yet", False, None),
    ],
)
def test_goal_extraction(text: str, asked: bool, goal: str | None) -> None:
    assert _goal(text, asked) == goal


def test_tool_searches_only_the_gap_with_the_career_key(monkeypatch: pytest.MonkeyPatch) -> None:
    searches: list[dict[str, Any]] = []

    def fake_search(query: str, **kwargs: Any) -> list[dict[str, Any]]:
        searches.append({"query": query, **kwargs})
        row = {
            "code": "CS 484",
            "title": "Intro to Machine Learning",
            "description": "Learning from data. More text.",
            "credit_hours": 3,
            "credit_hours_max": None,
            "catalog_term": "202710",
        }
        return [row] if query == "machine learning" else []

    monkeypatch.setattr(skill_courses, "search_catalog", fake_search)
    r = skill_courses.find_courses_for_skills(
        "data scientist", ["Python"], ["python", "machine learning", "spark"]
    )

    assert [s["query"] for s in searches] == ["machine learning", "spark"]
    key = searches[0]["api_key"].get_secret_value()
    assert key == skill_courses.get_settings().litellm_career_key.get_secret_value()
    assert r["gap"] == ["machine learning", "spark"]
    assert r["matches"][0]["courses"][0]["code"] == "CS 484"
    assert r["matches"][1]["courses"] == []
    assert [c["source"] for c in r["citations"]] == [
        "IIT Banner course catalog, CS 484, term 202710"
    ]


def test_tool_caps_searches_per_turn(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(skill_courses, "search_catalog", lambda q, **kw: [])
    wanted = [f"skill {i}" for i in range(7)]
    r = skill_courses.find_courses_for_skills("x", [], wanted)
    assert len(r["matches"]) == skill_courses.MAX_SKILLS
    assert r["skipped"] == wanted[skill_courses.MAX_SKILLS :]
