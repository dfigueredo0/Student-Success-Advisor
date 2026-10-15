"""check_prerequisites: a student's courses vs. a course's catalog prerequisite tree.

Result contract (the College Advisor renders against it; keep it stable):

    course, found          the course asked about; found=False -> nothing else but citations
    prerequisites          Banner's requirement text, quoted in the answer
    status                 domain.prereq.Status value: satisfied | pending | unsatisfied |
                           needs_grade
    missing                cheapest set still to take: [{requirement, minimum_grade, earned}]
    pending                in-progress courses the answer relies on (same leaf shape)
    needs_grade            unknown grades that decide the answer (same leaf shape)
    if_grade_too_low       status when a needs_grade grade falls short, else None
    unchecked_tests        test-score requirements passed without checking
    unreadable             requirement text the parser could not read
    citations              [{source, url, quote}]; quote is the Banner text
"""

from typing import Any

from sqlalchemy import text

from domain.prereq import Eligibility, Leaf, evaluate
from tools.advisor._db import engine


def check_prerequisites(
    course: str,
    completed_courses: list[str],
    grades: dict[str, str] | None = None,
    in_progress_courses: list[str] | None = None,
) -> dict[str, Any]:
    """grades: course -> grade from an uploaded transcript; a completed course without one
    is checked as "reported, grade unknown" (NEEDS_GRADE where the minimum is above D)."""
    with engine().connect() as conn:
        row = conn.execute(
            text(
                "SELECT prerequisites, prereq_tree, catalog_term "
                "FROM catalog_course WHERE code = :code"
            ),
            {"code": course},
        ).one_or_none()
    if row is None:
        return {"course": course, "found": False, "citations": []}

    return {
        "course": course,
        "found": True,
        "prerequisites": row.prerequisites,
        **eligibility(
            row.prerequisites, row.prereq_tree, completed_courses, grades, in_progress_courses
        ),
        "citations": [
            {
                "source": f"IIT Banner course catalog, {course}, term {row.catalog_term}",
                "url": "https://ssb.iit.edu/bnrprd",
                "quote": row.prerequisites,
            }
        ],
    }


def eligibility(
    prerequisites: str,
    tree: dict[str, Any] | None,
    completed_courses: list[str],
    grades: dict[str, str] | None = None,
    in_progress_courses: list[str] | None = None,
) -> dict[str, Any]:
    """Evaluate a catalog_course row's tree; the status fields of the result contract."""
    if tree is None and prerequisites:  # loaded before migration 0003: never report as met
        tree = {"type": "unparsed", "text": prerequisites}
    grades = grades or {}
    # TODO: needs impl - pass `planned` (same-term courses) once plan_next_term checks a
    # whole schedule; concurrent prerequisites only count from it.
    result = evaluate(
        tree,
        {code: grades.get(code) for code in completed_courses},
        in_progress=in_progress_courses or (),
    )
    return eligibility_fields(result)


def _leaves(leaves: tuple[Leaf, ...]) -> list[dict[str, Any]]:
    return [
        {"requirement": x.requirement, "minimum_grade": x.minimum_grade, "earned": x.earned}
        for x in leaves
    ]


def eligibility_fields(e: Eligibility) -> dict[str, Any]:
    """The evaluator's answer as plain JSON (it is checkpointed and traced)."""
    return {
        "status": e.status.value,
        "missing": _leaves(e.missing),
        "pending": _leaves(e.pending),
        "needs_grade": _leaves(e.needs_grade),
        "if_grade_too_low": e.if_grade_too_low.value if e.if_grade_too_low else None,
        "unchecked_tests": list(e.unchecked_tests),
        "unreadable": list(e.unreadable),
    }
