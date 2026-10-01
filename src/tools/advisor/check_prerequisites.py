"""check_prerequisites: completed courses vs. a course's catalog prerequisites."""

from functools import lru_cache
from typing import Any

from sqlalchemy import Engine, create_engine, text

from domain.graph import unmet_prerequisites
from settings import get_settings

@lru_cache
def _engine() -> Engine:
    return create_engine(get_settings().database_url, pool_pre_ping=True)

def check_prerequisites(course: str, completed_courses: list[str]) -> dict[str, Any]:
    with _engine().connect() as conn:
        row = conn.execute(
            text(
                "SELECT prerequisites, prerequisite_courses, catalog_term "
                "FROM catalog_course WHERE code = :code"
            ),
            {"code": course},
        ).one_or_none()
    if row is None:
        return {"course": course, "found": False, "citations": []}

    missing = unmet_prerequisites(row.prerequisite_courses, completed_courses)
    return {
        "course": course,
        "found": True,
        "prerequisites": row.prerequisites,
        "missing": missing,
        "eligible": not missing,
        "citations": [
            {
                "source": f"IIT Banner course catalog, {course}, term {row.catalog_term}",
                "url": "https://ssb.iit.edu/bnrprd",
                "quote": row.prerequisites,
            }
        ],
    }
