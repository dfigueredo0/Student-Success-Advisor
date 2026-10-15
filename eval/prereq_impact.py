"""Before/after: the old flat prerequisite check vs. the tree evaluator, per student profile.

Reads the loaded catalog (catalog_course, the rows the advisor tools read) and, for a few
synthetic College of Computing profiles, sorts every course with prerequisites into:

  wrongly_blocked     flat said "missing X" but the student meets the requirement
                      (the CS 350 / OR-alternative bug)
  overstated_missing  both say not yet, but flat lists more courses than the cheapest branch
  wrongly_allowed     flat found nothing missing, the evaluator does not say satisfied
                      (grade minimums, test scores, unreadable text, ranges)
  agree               same verdict and same missing set

    uv run python eval/prereq_impact.py            # transcript case: every grade is B
    uv run python eval/prereq_impact.py --no-grades  # self-reported courses, grades unknown

Needs `make up` and a loaded catalog (`make ingest-catalog`). Profiles are synthetic.
"""

import argparse
import json
from collections import Counter
from datetime import date
from pathlib import Path
from typing import Any

from sqlalchemy import text

from domain.prereq import Status, evaluate
from tools.advisor._db import engine

PROFILES: dict[str, list[str]] = {
    "first_year": ["CS 100", "CS 115", "MATH 151"],
    "sophomore": [
        "CS 100", "CS 115", "CS 116", "CS 330", "CS 331",
        "MATH 151", "MATH 152", "PHYS 123",
    ],
    "junior": [
        "CS 100", "CS 115", "CS 116", "CS 330", "CS 331", "CS 350", "CS 351", "CS 430",
        "MATH 151", "MATH 152", "MATH 230", "MATH 251", "MATH 332", "PHYS 123", "PHYS 221",
    ],
}  # fmt: skip

RESULTS = Path(__file__).parent / "results"


def flat_missing(prerequisite_courses: list[str], completed: list[str]) -> list[str]:
    """The check the tools used before 2026-10-14 (domain/graph.unmet_prerequisites):
    every course named anywhere in the requirement is required."""
    return [c for c in prerequisite_courses if c not in set(completed)]


def compare(row: Any, completed: list[str], grade: str | None) -> tuple[str, str]:
    """(category, reason) for one course."""
    flat = flat_missing(row.prerequisite_courses, completed)
    result = evaluate(row.prereq_tree, {c: grade for c in completed})
    tree_missing = {leaf.requirement for leaf in result.missing}
    if flat and result.status is Status.SATISFIED:
        return "wrongly_blocked", "OR alternative already met"
    if not flat and result.status is not Status.SATISFIED:
        if result.unreadable:
            reason = "unreadable requirement text"
        elif result.status is Status.NEEDS_GRADE:
            reason = "grade minimum, grade unknown"
        elif result.missing:
            reason = "course range or minimum grade not met"
        else:
            reason = result.status.value
        return "wrongly_allowed", reason
    if flat and not tree_missing:
        return "agree", "both not met; evaluator: requirement text unreadable"
    if flat and len(set(flat)) > len(tree_missing):
        return "overstated_missing", "unneeded OR alternatives listed as missing"
    if not flat and result.unchecked_tests:
        return "agree", "satisfied only through an unchecked test score"
    return "agree", ""


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--no-grades", action="store_true", help="completed courses, no grades")
    args = parser.parse_args(argv)
    grade = None if args.no_grades else "B"

    with engine().connect() as conn:
        rows = conn.execute(
            text(
                "SELECT code, number, prerequisite_courses, prereq_tree FROM catalog_course "
                "WHERE prerequisites <> '' ORDER BY code"
            )
        ).all()
    if not rows:
        raise SystemExit("catalog_course is empty: run `make ingest-catalog` first")
    if any(r.prereq_tree is None for r in rows):
        raise SystemExit("prereq_tree is not filled: run migration 0003 and load_catalog.py")

    report: dict[str, Any] = {
        "date": date.today().isoformat(),
        "grades": grade or "unknown",
        "courses_with_prerequisites": len(rows),
        "profiles": {},
    }
    print(f"{len(rows)} catalog courses with prerequisites; grades: {grade or 'unknown'}\n")
    for name, completed in PROFILES.items():
        cats: Counter[str] = Counter()
        reasons: Counter[str] = Counter()
        examples: dict[str, list[str]] = {}
        extra: list[int] = []
        for row in rows:
            if row.code in completed:
                continue
            cat, why = compare(row, completed, grade)
            cats[cat] += 1
            if cat == "overstated_missing":
                tree = evaluate(row.prereq_tree, {c: grade for c in completed})
                extra.append(
                    len(flat_missing(row.prerequisite_courses, completed)) - len(tree.missing)
                )
            if cat != "agree":
                reasons[f"{cat}: {why}"] += 1
                # Undergraduate CS/MATH examples read best on a slide.
                if row.code.split()[0] in ("CS", "MATH") and int(row.number[:3]) < 500:
                    examples.setdefault(cat, []).append(row.code)
        report["profiles"][name] = {
            "completed": completed,
            "categories": dict(cats),
            "reasons": dict(reasons),
            "overstated_extra_courses_mean": round(sum(extra) / len(extra), 1) if extra else 0,
            "examples": {k: v[:8] for k, v in examples.items()},
        }
        print(f"## {name} ({len(completed)} completed)")
        for cat in ("wrongly_blocked", "overstated_missing", "wrongly_allowed", "agree"):
            ex = ", ".join(examples.get(cat, [])[:6])
            print(f"  {cat:<19} {cats[cat]:>5}" + (f"   e.g. {ex}" if ex else ""))
        if extra:
            print(
                f"    overstated: {sum(extra) / len(extra):.1f} unneeded courses listed on average"
            )
        for why, n in reasons.most_common():
            print(f"    {n:>4}  {why}")
        print()

    RESULTS.mkdir(exist_ok=True)
    out = RESULTS / f"prereq_impact-{report['date']}-{'nogrades' if args.no_grades else 'B'}.json"
    out.write_text(json.dumps(report, indent=2) + "\n")
    print(f"wrote {out.relative_to(Path.cwd()) if out.is_relative_to(Path.cwd()) else out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
