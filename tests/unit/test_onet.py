"""match_occupations around its SQL: O*NET names in, display labels and sources out."""

from contextlib import nullcontext
from typing import Any

import pytest

from domain.skills import build_vocab
from tools.career import onet

VOCAB = build_vocab(
    ["Python", "Structured query language SQL", "Microsoft Excel", "Kubernetes", "Git", "Google"]
)


def row(**changes: Any) -> dict[str, Any]:
    return {
        "code": "15-1252.00",
        "title": "Software Developers",
        "job_zone": 4,
        "asked": 3,
        "asked_have": 2,
        "wanted": 5,
        "matched": ["Python", "Structured query language SQL", "Microsoft Excel"],
        # "Google" is in O*NET but cannot be read from a resume, so it is never suggested.
        "missing": ["Kubernetes", "Git", "Google"],
    } | changes


class Ranked:
    """Stands in for the database: records what the ranking was asked, returns `rows`."""

    def __init__(self, monkeypatch: pytest.MonkeyPatch, rows: list[dict[str, Any]]) -> None:
        self.calls: list[tuple[list[str], int | None, int]] = []
        monkeypatch.setattr(onet, "vocabulary", lambda: VOCAB)
        monkeypatch.setattr(onet, "engine", lambda: self)
        monkeypatch.setattr(onet, "_rank", self.rank)
        self.rows = rows

    def connect(self) -> Any:
        return nullcontext()

    def rank(self, conn: Any, skills: list[str], max_zone: int | None, limit: int) -> Any:
        self.calls.append((skills, max_zone, limit))
        return self.rows


def test_ranks_by_onet_names_and_answers_in_the_students_words(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db = Ranked(monkeypatch, [row()])
    r = onet.match_occupations(["sql", "python", "Excel", "juggling"], "bachelor", 2099)

    assert db.calls == [(["Structured query language SQL", "Python", "Microsoft Excel"], 4, 5)]
    assert r["reason"] is None and r["unrecognized"] == ["juggling"]
    assert r["occupations"] == [
        {
            "title": "Software Developers",
            "asked": 3,
            "asked_have": 2,
            "wanted": 5,
            "matched": ["Python", "SQL", "Excel"],
            "missing": ["Kubernetes", "Git"],
            "needs": None,  # within reach of a bachelor's
        }
    ]
    assert r["citations"] == [
        {
            "source": "O*NET 31.0 Database, 15-1252.00 Software Developers",
            "url": "https://www.onetonline.org/link/summary/15-1252.00",
        }
    ]
    assert r["graduation_year"] == 2099 and r["graduated"] is False


@pytest.mark.parametrize(
    ("degree", "zone", "needs"),
    [
        ("bachelor", 5, "a graduate degree"),
        ("associate", 4, "a bachelor's degree"),
        ("master", 5, None),
        (None, 5, None),  # no degree on record: nothing to compare with
        ("bachelor", None, None),  # O*NET has no zone for a few occupations
    ],
)
def test_role_above_the_students_degree_says_what_it_needs(
    monkeypatch: pytest.MonkeyPatch, degree: str | None, zone: int | None, needs: str | None
) -> None:
    Ranked(monkeypatch, [row(job_zone=zone)])
    assert onet.match_occupations(["python"], degree)["occupations"][0]["needs"] == needs


def test_graduation_in_the_past_means_graduated(monkeypatch: pytest.MonkeyPatch) -> None:
    Ranked(monkeypatch, [row()])
    assert onet.match_occupations(["python"], None, 2000)["graduated"] is True
    assert onet.match_occupations(["python"])["graduated"] is None


def test_no_recognized_skill_skips_the_ranking(monkeypatch: pytest.MonkeyPatch) -> None:
    db = Ranked(monkeypatch, [row()])
    r = onet.match_occupations(["juggling", "public speaking"])
    assert (r["reason"], r["occupations"], db.calls) == ("no_skills", [], [])
    assert r["unrecognized"] == ["juggling", "public speaking"]


def test_only_everyday_office_skills_match_no_role(monkeypatch: pytest.MonkeyPatch) -> None:
    Ranked(monkeypatch, [])
    assert onet.match_occupations(["Excel"])["reason"] == "generic_only"


def test_job_data_not_loaded(monkeypatch: pytest.MonkeyPatch) -> None:
    def not_loaded() -> None:
        raise onet.OnetNotLoaded

    monkeypatch.setattr(onet, "vocabulary", not_loaded)
    assert onet.match_occupations(["Python"])["reason"] == "no_onet"
