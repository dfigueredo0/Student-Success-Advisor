"""Catalog lookups for the advisor: one course in detail, and courses by topic."""

from typing import Any

from sqlalchemy import text

from domain.graph import unmet_prerequisites
from retrieval.catalog_search import search_catalog
from tools.advisor._db import engine

BANNER_URL = "https://ssb.iit.edu/bnrprd"

def credits(row: Any) -> float | None:
    """Catalog credit hours; Banner stores variable-credit courses as 0 with a max."""
    value = max(float(row["credit_hours"] or 0), float(row["credit_hours_max"] or 0))
    return value or None

def meeting_summary(meetings: list[dict[str, Any]]) -> str:
    parts = [
        f"{m.get('days') or ''} {m.get('time') or 'TBA'}".strip()
        for m in meetings
        if m.get("type", "Class") == "Class"
    ]
    return ", ".join(dict.fromkeys(parts)) or "TBA"

_COURSE = text(
    """
    SELECT c.code, c.title, c.description, c.credit_hours, c.credit_hours_max, c.levels,
           c.attributes, c.prerequisites, c.prerequisite_courses, c.restrictions,
           c.catalog_term, t.name AS catalog_term_name
    FROM catalog_course c JOIN catalog_term t ON t.code = c.catalog_term
    WHERE c.code = :code
    """
)

_SECTIONS = text(
    """
    SELECT s.section, s.crn, s.campus, s.instruction_method, s.schedule_type, s.remaining,
           s.capacity, s.instructors, s.meetings, t.name AS term_name
    FROM catalog_section s JOIN catalog_term t ON t.code = s.term_code
    WHERE s.course_code = :code
    ORDER BY s.term_code DESC, s.section
    """
)

def get_course_info(course: str, completed_courses: list[str] | None = None) -> dict[str, Any]:
    with engine().connect() as conn:
        row = conn.execute(_COURSE, {"code": course}).mappings().one_or_none()
        if row is None:
            return {"course": course, "found": False, "citations": []}
        sections = conn.execute(_SECTIONS, {"code": course}).mappings().all()

    eligibility = None
    if completed_courses is not None:
        missing = unmet_prerequisites(row["prerequisite_courses"], completed_courses)
        eligibility = {"missing": missing, "eligible": not missing}
    return {
        "course": course,
        "found": True,
        "title": row["title"],
        "description": row["description"],
        "credits": credits(row),
        "levels": row["levels"],
        "attributes": row["attributes"],
        "prerequisites": row["prerequisites"],
        "restrictions": row["restrictions"],
        "eligibility": eligibility,
        "sections": [
            {
                "term": s["term_name"],
                "section": s["section"],
                "crn": s["crn"],
                "campus": s["campus"],
                "schedule_type": s["schedule_type"],
                "when": meeting_summary(s["meetings"]),
                "instructors": s["instructors"],
                "seats_remaining": s["remaining"],
            }
            for s in sections
        ],
        "citations": [
            {
                "source": f"IIT Banner course catalog, {course}, term {row['catalog_term']}",
                "url": BANNER_URL,
                "quote": row["description"][:300],
            }
        ],
    }

# TODO: needs impl - take the student's level (undergrad/grad) from the student record
# (tools.advisor.get_student_record) instead of defaulting to undergraduate.
def search_courses(query: str, level: str = "Undergraduate", limit: int = 5) -> dict[str, Any]:
    rows = search_catalog(query, limit=limit, level=level)
    results = [
        {
            "code": r["code"],
            "title": r["title"],
            "credits": credits(r),
            "summary": r["description"].split(". ")[0][:200],
            "prerequisites": r["prerequisites"],
        }
        for r in rows
    ]
    return {
        "query": query,
        "results": results,
        "citations": [
            {
                "source": f"IIT Banner course catalog, {r['code']}, term {r['catalog_term']}",
                "url": BANNER_URL,
                "quote": r["description"][:300],
            }
            for r in rows
        ],
    }
