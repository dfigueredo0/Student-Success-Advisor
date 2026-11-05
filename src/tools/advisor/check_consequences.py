"""check_consequences: what dropping one of this term's courses would do.

Result contract (the College Advisor renders against it; keep it stable):

    course, taking        the course; taking=False -> not in `current`, nothing else computed
    current               this term's courses, as checked
    credits_before/after  this term's load with and without it; None when a credit is unknown
    credits_cite          citation for the credit hours, None when the load is unknown
    unknown_credits       current courses the catalog has no fixed credits for
    crossed               [{id, message, min_credits, verified, cite}] thresholds the drop
                          takes the student below
    already_below         same shape: thresholds they're under with or without it
    blocked               [{course, title, needs, cite}] later courses it was a prerequisite
                          for and that the evaluator now finds out of reach
    corequisite_of        [{course, title, cite}] current courses that need it the same term
    also_delayed          courses that build on the blocked ones (not re-checked; an upper
                          bound)
    reasons               stable codes (VerifierRun.failure_reasons)
    citations             [{source, url, quote}]; `cite` is a 1-based index into this list
"""

import json
from dataclasses import fields
from datetime import date
from functools import lru_cache
from pathlib import Path
from typing import Any

from sqlalchemy import text

from domain.consequences import Rule, consequences
from tools.advisor._db import engine
from tools.advisor.catalog import BANNER_URL, credits

RULES = Path(__file__).resolve().parents[3] / "data" / "policies" / "consequence_rules.json"

# Courses that build on the blocked ones, a few steps out. Not re-checked by the evaluator.
_LATER = text(
    """
    WITH RECURSIVE later(code, depth) AS (
        SELECT code, 1 FROM catalog_course WHERE prerequisite_courses && :seed
        UNION
        SELECT c.code, l.depth + 1
        FROM catalog_course c JOIN later l ON l.code = ANY(c.prerequisite_courses)
        WHERE l.depth < 6
    )
    SELECT count(DISTINCT code) FROM later WHERE code <> ALL(:exclude)
    """
)


@lru_cache
def rules() -> tuple[Rule, ...]:
    names = {f.name for f in fields(Rule)}
    return tuple(
        Rule(**{k: v for k, v in r.items() if k in names} | {"effective_from": _day(r)})
        for r in json.loads(RULES.read_text())["rules"]
    )


def _day(rule: dict[str, Any]) -> date:
    return date.fromisoformat(rule["effective_from"])


def check_consequences(
    course: str,
    in_progress_courses: list[str],
    completed_courses: list[str],
    grades: dict[str, str] | None = None,
) -> dict[str, Any]:
    current = list(dict.fromkeys(in_progress_courses))
    grades = grades or {}
    with engine().connect() as conn:
        rows = {
            r["code"]: r
            for r in conn.execute(
                text(
                    "SELECT code, title, credit_hours, credit_hours_max, catalog_term "
                    "FROM catalog_course WHERE code = ANY(:codes)"
                ),
                {"codes": current},
            ).mappings()
        }
        dependents = {
            r["code"]: r
            for r in conn.execute(
                text(
                    "SELECT code, title, prerequisites, prereq_tree, catalog_term "
                    "FROM catalog_course WHERE :code = ANY(prerequisite_courses)"
                ),
                {"code": course},
            ).mappings()
        }
        result = consequences(
            course,
            {c: credits(rows[c]) if c in rows else None for c in current},
            {c: grades.get(c) for c in completed_courses},
            {code: _tree(r) for code, r in dependents.items()},
            rules(),
            date.today(),
        )
        seed = [b.course for b in result.blocked] + list(result.corequisite_of)
        also_delayed = (
            conn.execute(_LATER, {"seed": seed, "exclude": [course, *seed]}).scalar_one()
            if seed
            else 0
        )

    citations: list[dict[str, Any]] = []

    def cite(source: str, url: str, quote: str | None) -> int:
        citations.append({"source": source, "url": url, "quote": quote})
        return len(citations)

    def catalog(code: str) -> int:
        r = dependents[code]
        source = f"IIT Banner course catalog, {code}, term {r['catalog_term']}"
        return cite(source, BANNER_URL, r["prerequisites"])

    def rule(r: Rule) -> dict[str, Any]:
        n = cite(r.source, r.url, r.quote)
        return {
            "id": r.id,
            "message": r.message,
            "min_credits": r.min_credits,
            "verified": r.verified,
            "cite": n,
        }

    # Built in the order the answer reads, so citation numbers run [1], [2], ...
    credits_cite = None
    if result.credits_before is not None:
        load = "; ".join(f"{c}: {credits(rows[c]):g} credit hours" for c in current)
        term = rows[course]["catalog_term"]
        credits_cite = cite(f"IIT Banner course catalog, term {term}", BANNER_URL, load)
    crossed = [rule(r) for r in result.crossed]
    already_below = [rule(r) for r in result.already_below]
    blocked = [
        {
            "course": b.course,
            "title": dependents[b.course]["title"],
            "needs": list(b.needs),
            "cite": catalog(b.course),
        }
        for b in result.blocked
    ]
    corequisite_of = [
        {"course": c, "title": dependents[c]["title"], "cite": catalog(c)}
        for c in result.corequisite_of
    ]
    return {
        "course": course,
        "taking": result.taking,
        "current": current,
        "credits_before": result.credits_before,
        "credits_after": result.credits_after,
        "credits_cite": credits_cite,
        "unknown_credits": [c for c in current if c not in rows or credits(rows[c]) is None],
        "crossed": crossed,
        "already_below": already_below,
        "blocked": blocked,
        "corequisite_of": corequisite_of,
        "also_delayed": also_delayed,
        "reasons": result.reasons,
        "citations": citations,
    }


def _tree(row: Any) -> dict[str, Any] | None:
    # Loaded before migration 0003: never treat unparsed text as met (as check_prerequisites).
    if row["prereq_tree"] is None and row["prerequisites"]:
        return {"type": "unparsed", "text": row["prerequisites"]}
    return row["prereq_tree"]
