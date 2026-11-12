"""Skill vocabulary built from the real O*NET names (data/onet): aliases and text extraction."""

import csv
import time
from pathlib import Path

import pytest

from domain.skills import build_vocab, canonical, extract_skills

CSV = Path(__file__).resolve().parents[2] / "data" / "onet" / "software_skills.csv"


def _names() -> set[str]:
    with CSV.open(encoding="utf-8-sig", newline="") as f:
        return {
            r["Workplace Example"]
            for r in csv.DictReader(f)
            if "Y" in (r["Hot Technology"], r["In Demand"])
        }


VOCAB = build_vocab(_names())


@pytest.mark.parametrize(
    ("alias", "name"),
    [
        ("sql", "Structured query language SQL"),
        ("structured query language", "Structured query language SQL"),
        ("aws", "Amazon Web Services AWS software"),
        ("java", "Oracle Java"),
        ("matlab", "The MathWorks MATLAB"),
        ("excel", "Microsoft Excel"),
        ("html", "Hypertext markup language HTML"),
        ("solidworks", "Dassault Systemes SolidWorks"),
        ("angular", "Google Angular"),
        ("jira", "Atlassian JIRA"),
        ("salesforce", "Salesforce software"),
        (".net", "Microsoft .NET Framework"),
        ("xml", "Extensible markup language XML"),
        ("k8s", "Kubernetes"),
        ("python", "Python"),
    ],
)
def test_alias_maps_to_the_onet_name(alias: str, name: str) -> None:
    assert VOCAB.names[alias] == name


@pytest.mark.parametrize(
    "junk",
    ["tax", "payroll", "bi", "ci", "seo", "ehr", "google", "facebook", "database", "office",
     "software", "cloud software"],
)  # fmt: skip
def test_category_leftovers_and_employers_are_not_aliases(junk: str) -> None:
    assert junk not in VOCAB.names


@pytest.mark.parametrize(
    ("text", "skills"),
    [
        ("C++, C#, Node.js, .NET and ASP.NET", ["C++", "C#", "Node.js", ".NET", "ASP.NET"]),
        ("python, sql, aws", ["Python", "SQL", "AWS"]),
        ("Languages: Python, R, Go, C", ["Python", "R", "Go", "C"]),
        ("MySQL and JavaScript", ["MySQL", "JavaScript"]),  # not SQL, not Java
        ("PostgreSQL, PL/SQL, Microsoft SQL Server", ["PostgreSQL", "PL/SQL", "SQL Server"]),
        ("SQL and Structured Query Language", ["SQL"]),  # one skill, named twice
        ("Built dashboards in Tableau and Microsoft Excel.", ["Tableau", "Excel"]),
        ("Tools: Excel, Word; Git/GitHub", ["Excel", "Word", "Git", "GitHub"]),
        # Everyday words that are also product names only count in a list, capitalized.
        ("I excel at teamwork and have access to tools. Go to market fast.", []),
        ("Capstone Project\nProject Manager for a team of 4. R&D intern, John R. Smith", []),
        ("Measured airflow and angular momentum as an illustrator", []),
        ("Worked at Google and posted on Facebook", []),
    ],
)
def test_extract_skills(text: str, skills: list[str]) -> None:
    assert extract_skills(text, VOCAB) == skills


def test_canonical_maps_typed_skills_and_returns_the_rest() -> None:
    names, unknown = canonical(["sql", "Python", "r", "underwater basket weaving", "SQL"], VOCAB)
    assert names == ["Structured query language SQL", "Python", "R"]
    assert unknown == ["underwater basket weaving"]


def test_extraction_stays_fast_on_one_very_long_line() -> None:
    """Fetched pages are text someone else wrote: 20,000 list items on a single line must not
    make each item rescan the whole line before it."""
    line = "R, " * 20_000
    start = time.perf_counter()
    assert extract_skills(line, VOCAB) == ["R"]
    assert time.perf_counter() - start < 1.0


def test_every_name_with_an_alias_has_a_display_label() -> None:
    assert VOCAB.short["Structured query language SQL"] == "SQL"
    assert VOCAB.short["Amazon Web Services AWS software"] == "AWS"
    assert VOCAB.short["Kubernetes"] == "Kubernetes"  # never the informal "k8s"
    assert set(VOCAB.names.values()) == set(VOCAB.short)
    assert "Google" not in VOCAB.short  # blocked names cannot be read, so are never shown
