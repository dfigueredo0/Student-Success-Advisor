from typing import Any

import pytest

from agents.career_advisor import (
    _goal,
    _render_jobs,
    _render_openings,
    _render_posting,
    _role,
    parse_skills,
)
from domain.redaction import redact
from domain.skills import skill_gap
from orchestrator.router import regex_route
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
        # A pasted paragraph is not a skill: it is dropped, so the question is asked again.
        ("Python, " + "x" * 61, ["Python"]),
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


def jobs(**changes: Any) -> dict[str, Any]:
    role = {
        "title": "Software Developers",
        "asked": 3,
        "asked_have": 2,
        "wanted": 5,
        "matched": ["Python", "SQL"],
        "missing": ["Kubernetes", "Git"],
        "needs": None,
    }
    return {
        "reason": None,
        "occupations": [role | changes.pop("role", {})],
        "unrecognized": [],
        "graduation_year": 2027,
        "graduated": False,
        "citations": [{"source": "O*NET 31.0 Database, 15-1252.00 Software Developers"}],
    } | changes


def test_job_answer_lists_each_role_with_counts_gaps_and_its_source() -> None:
    answer = _render_jobs(jobs())
    assert "1. Software Developers - you have 2 of the 3 tools employers ask for most [1]" in answer
    assert "\n   - You have: Python, SQL\n   - To add: Kubernetes, Git\n" in answer
    assert "You graduate in 2027, so look for internships and co-ops" in answer
    assert "https://iit.joinhandshake.com" in answer
    assert 'Ask "Find openings for Software Developers" to search current postings.' in answer
    assert "software and tool skills only" in answer
    assert answer.endswith("[1] O*NET 31.0 Database, 15-1252.00 Software Developers")
    assert redact(answer) == answer  # an occupation code must not read as a phone number


def test_job_answer_variants() -> None:
    above = _render_jobs(jobs(role={"needs": "a graduate degree"}))
    assert "tools employers ask for most; usually needs a graduate degree [1]" in above
    # O*NET marks nothing in demand for some occupations: count over its whole list instead.
    unflagged = _render_jobs(jobs(role={"asked": 0, "asked_have": 0}))
    assert "you have 2 of the 5 tools commonly used [1]" in unflagged
    graduated = _render_jobs(jobs(graduated=True, graduation_year=2020))
    assert "entry-level" in graduated and "You graduate" not in graduated
    unplaced = _render_jobs(jobs(unrecognized=["juggling"]))
    assert "juggling" in unplaced


@pytest.mark.parametrize(
    ("reason", "says"),
    [
        ("no_onet", "job data isn't loaded"),
        ("no_skills", "software or tools"),
        ("generic_only", "nearly every role"),
    ],
)
def test_job_answer_when_there_is_nothing_to_rank(reason: str, says: str) -> None:
    answer = _render_jobs(jobs(reason=reason, occupations=[], citations=[]))
    assert says in answer and "[1]" not in answer


def fit(**changes: Any) -> dict[str, Any]:
    return {
        "reason": None,
        "matched": ["Python", "SQL"],
        "missing": ["Docker", "Kubernetes"],
        "courses": None,
        "citations": [],
    } | changes


def test_posting_answer_splits_its_skills_into_held_and_missing() -> None:
    answer = _render_posting(fit())
    assert "names 4 software and tool skills" in answer
    assert "\n- You have: Python, SQL\n- To add: Docker, Kubernetes\n" in answer
    assert "software and tool skills only" in answer
    assert "all of them" in _render_posting(fit(missing=[]))
    assert "- You have" not in _render_posting(fit(matched=[]))


def test_posting_answer_adds_courses_for_the_gaps() -> None:
    courses = {
        "career_goal": "this posting",
        "gap": ["Docker"],
        "skipped": [],
        "matches": [
            {"skill": "Docker", "courses": [{"code": "CS 553", "title": "Cloud", "credits": 3.0}]}
        ],
        "citations": [{"source": "IIT Banner course catalog, CS 553, term 202710"}],
    }
    answer = _render_posting(fit(courses=courses, citations=courses["citations"]))
    assert "- Docker: CS 553 Cloud (3 cr) [1]" in answer
    assert answer.endswith("[1] IIT Banner course catalog, CS 553, term 202710")


@pytest.mark.parametrize(
    ("reason", "says"),
    [
        ("unreadable", "couldn't open that link"),
        ("not_a_posting", "didn't find a job posting"),
        ("no_skills_in_posting", "didn't find software or tools"),
        ("no_onet", "job data isn't loaded"),
    ],
)
def test_posting_answer_when_it_cannot_compare(reason: str, says: str) -> None:
    assert says in _render_posting(fit(reason=reason, matched=[], missing=[]))


def openings(**changes: Any) -> dict[str, Any]:
    return {
        "reason": None,
        "query": "data analyst internship job openings",
        "searched_on": "2026-11-12",
        "results": [
            {"title": "Data Analyst Intern - Initech", "site": "jobs.lever.co", "snippet": "SQL."},
            {"title": "Analyst - Acme", "site": "acme.com", "snippet": ""},
        ],
        "citations": [
            {"source": "Data Analyst Intern - Initech (jobs.lever.co)", "url": "https://x/1"},
            {"source": "Analyst - Acme (acme.com)", "url": "https://x/2"},
        ],
    } | changes


def test_openings_answer_numbers_each_result_and_names_its_source() -> None:
    answer = _render_openings(openings())
    assert answer.startswith(
        'Web results for "data analyst internship job openings", past month (searched 2026-11-12):'
    )
    assert '\n1. Data Analyst Intern - Initech (jobs.lever.co) [1]\n   "SQL."\n2. Analyst' in answer
    assert "unverified web results" in answer and "https://iit.joinhandshake.com" in answer
    assert answer.endswith(
        "[1] Data Analyst Intern - Initech (jobs.lever.co)\n[2] Analyst - Acme (acme.com)"
    )


@pytest.mark.parametrize(
    ("reason", "says"),
    [
        ("not_configured", "isn't set up"),
        ("search_failed", "couldn't reach the web search"),
        ("no_results", "no recent web results"),
    ],
)
def test_openings_answer_without_results_points_to_handshake(reason: str, says: str) -> None:
    answer = _render_openings(openings(reason=reason, results=[], citations=[]))
    assert says in answer and "https://iit.joinhandshake.com" in answer and "[1]" not in answer


@pytest.mark.parametrize(
    ("text", "asked", "role"),
    [
        ("Find openings for Software Developers", False, "Software Developers"),
        ("find current internships for a data analyst?", False, "data analyst"),
        ("Search the web for current data analyst internships", False, "data analyst"),
        ("Are there any openings in mechanical engineering right now", False, None),
        ("Can you look for openings on the web?", False, None),
        ("mechanical engineer.", True, "mechanical engineer"),
        ("x" * 121, True, None),  # too long to be a role; asked again
    ],
)
def test_role_extraction(text: str, asked: bool, role: str | None) -> None:
    assert _role(text, asked) == role


def test_the_longest_onet_titles_work_in_the_suggested_search_prompt() -> None:
    title = "Sales Representatives, Wholesale and Manufacturing, Technical and Scientific Products"
    prompt = f"Find openings for {title}"
    assert len(title) > 80 and _role(prompt, False) == title
    assert regex_route(prompt).intent == "find_openings"


def test_tool_caps_searches_per_turn(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(skill_courses, "search_catalog", lambda q, **kw: [])
    wanted = [f"skill {i}" for i in range(7)]
    r = skill_courses.find_courses_for_skills("x", [], wanted)
    assert len(r["matches"]) == skill_courses.MAX_SKILLS
    assert r["skipped"] == wanted[skill_courses.MAX_SKILLS :]
