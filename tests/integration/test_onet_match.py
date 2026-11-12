"""The occupation ranking SQL (tools.career.onet._rank) on a handful of rows in real Postgres."""

from collections.abc import Iterator
from typing import Any

import pytest
from sqlalchemy import Connection, Engine, text

from tools.career import onet

OCCUPATIONS = [
    {"code": "A", "title": "Software Developers", "job_zone": 4},
    {"code": "B", "title": "Data Scientists", "job_zone": 5},
    {"code": "C", "title": "Office Clerks", "job_zone": 2},
    {"code": "D", "title": "Web Developers", "job_zone": 3},
]
# (occupation, skill, in demand). Excel is wanted by all four, so it tells no two roles apart.
SKILLS = [
    ("A", "Python", True), ("A", "SQL", True), ("A", "Git", False), ("A", "Excel", False),
    ("B", "Python", True), ("B", "R", True), ("B", "Excel", False),
    ("C", "Excel", True),
    ("D", "JavaScript", True), ("D", "Git", True), ("D", "Excel", False),
]  # fmt: skip


@pytest.fixture
def conn(engine: Engine) -> Iterator[Connection]:
    """The four occupations above in place of the loaded data; rolled back afterwards."""
    with engine.connect() as c:
        tx = c.begin()
        c.execute(text("DELETE FROM onet_occupation"))
        c.execute(
            text("INSERT INTO onet_occupation VALUES (:code, :title, :job_zone)"), OCCUPATIONS
        )
        c.execute(
            text("INSERT INTO onet_software_skill VALUES (:c, :e, :d)"),
            [{"c": c_, "e": e, "d": d} for c_, e, d in SKILLS],
        )
        yield c
        tx.rollback()


def _titles(rows: list[Any]) -> list[str]:
    return [r["title"] for r in rows]


def test_more_in_demand_skills_held_ranks_first(conn: Connection) -> None:
    rows = onet._rank(conn, ["Python", "SQL", "Excel"], None, 5)
    assert _titles(rows) == ["Software Developers", "Data Scientists"]
    top = rows[0]
    assert (top["asked"], top["asked_have"], top["wanted"]) == (2, 2, 4)
    assert top["matched"] == ["Python", "SQL", "Excel"]  # in demand first, then the rest
    assert top["missing"] == ["Git"]


def test_a_skill_most_occupations_want_makes_no_match_on_its_own(conn: Connection) -> None:
    assert onet._rank(conn, ["Excel"], None, 5) == []
    # ...and is not suggested as a gap either
    assert onet._rank(conn, ["JavaScript"], None, 5)[0]["missing"] == ["Git"]


def test_role_above_the_degree_level_sorts_last_but_stays(conn: Connection) -> None:
    skills = ["Python", "R"]  # Data Scientists (zone 5) holds both in demand, Developers one
    assert _titles(onet._rank(conn, skills, 5, 5)) == ["Data Scientists", "Software Developers"]
    assert _titles(onet._rank(conn, skills, 4, 5)) == ["Software Developers", "Data Scientists"]


def test_limit(conn: Connection) -> None:
    assert len(onet._rank(conn, ["Python", "Git"], None, 1)) == 1
