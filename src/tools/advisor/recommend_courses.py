"""recommend_courses: next-term course suggestions from the schedule + completed courses.

Candidates are courses with sections in the target term, in the student's subjects, not yet
completed, whose prerequisites are met; research/independent-study courses are skipped.
Ranking (advisor heuristic, not policy):
  1. builds on a course the student completed (the next step in a sequence),
  2. unlocks more later courses (foundational first),
  3. lower course number.
Subjects are interleaved so a CS + MATH student sees both sequences.
"""

import re
from collections import Counter
from typing import Any

from sqlalchemy import text

from domain.graph import unmet_prerequisites
from tools.advisor._db import engine
from tools.advisor.catalog import BANNER_URL, credits

# Research, independent study, co-op etc. list no prerequisites but need a faculty sponsor;
# they are not "next courses" in a sequence.
_NOT_A_NEXT_COURSE = re.compile(
    r"research|special (projects?|problems|topics)|reading|independent|internship|co-?op"
    r"|thesis|practicum|seminar",
    re.I,
)

_TERMS = text("SELECT code, name FROM catalog_term ORDER BY code DESC")
_SUBJECTS = text("SELECT DISTINCT subject FROM catalog_course WHERE subject = ANY(:subjects)")

_CANDIDATES = text(
    """
    SELECT c.code, c.subject, c.number, c.title, c.credit_hours, c.credit_hours_max,
           c.prerequisites, c.prerequisite_courses,
           count(s.crn) AS sections,
           coalesce(sum(greatest(s.remaining, 0)), 0) AS seats,
           (SELECT count(*) FROM catalog_course d WHERE c.code = ANY(d.prerequisite_courses))
               AS unlocks
    FROM catalog_course c
    JOIN catalog_section s ON s.course_code = c.code AND s.term_code = :term
    WHERE c.subject = ANY(:subjects) AND :level = ANY(c.levels) AND NOT c.code = ANY(:completed)
    GROUP BY c.code
    """
)

def _number(code_number: str) -> int:
    digits = "".join(ch for ch in code_number if ch.isdigit())
    return int(digits) if digits else 0

def _interleave(ranked: list[dict[str, Any]], limit: int) -> list[dict[str, Any]]:
    by_subject: dict[str, list[dict[str, Any]]] = {}
    for c in ranked:
        by_subject.setdefault(c["subject"], []).append(c)
    out: list[dict[str, Any]] = []
    while len(out) < limit and any(by_subject.values()):
        for queue in by_subject.values():
            if queue and len(out) < limit:
                out.append(queue.pop(0))
    return out

# TODO: needs impl - put required courses first once tools.advisor.get_degree_progress returns
# the student's remaining requirements, and take level/major from get_student_record.
def recommend_courses(
    completed_courses: list[str],
    subject: str | None = None,
    term: str | None = None,
    level: str = "Undergraduate",
    limit: int = 6,
) -> dict[str, Any]:
    completed = list(dict.fromkeys(completed_courses))
    with engine().connect() as conn:
        terms = conn.execute(_TERMS).mappings().all()
        if not terms:
            return {"found": False, "reason": "no_schedule", "citations": []}
        chosen = next((t for t in terms if term and t["name"].lower() == term.lower()), terms[0])

        wanted = [subject.upper()] if subject else []
        wanted += [s for s, _ in Counter(c.split()[0] for c in completed).most_common()]
        subjects = [
            r[0]
            for r in conn.execute(_SUBJECTS, {"subjects": list(dict.fromkeys(wanted))})
        ]
        subjects.sort(key=wanted.index)
        if not subjects:
            return {"found": False, "reason": "no_subject", "citations": []}

        rows = conn.execute(
            _CANDIDATES,
            {"term": chosen["code"], "subjects": subjects, "level": level, "completed": completed},
        ).mappings().all()

    # Highest completed course number per subject: skip intro courses below it.
    done_level: dict[str, int] = {}
    for code in completed:
        subj, _, num = code.partition(" ")
        done_level[subj] = max(done_level.get(subj, 0), _number(num))

    candidates = []
    for r in rows:
        number = _number(r["number"])
        if number >= 500 or number < done_level.get(r["subject"], 0):
            continue
        if _NOT_A_NEXT_COURSE.search(r["title"]):
            continue
        if unmet_prerequisites(r["prerequisite_courses"], completed):
            continue
        builds_on = [c for c in r["prerequisite_courses"] if c in completed]
        candidates.append(
            {
                "code": r["code"],
                "subject": r["subject"],
                "title": r["title"],
                "credits": credits(r),
                "prerequisites": r["prerequisites"],
                "builds_on": builds_on,
                "unlocks": r["unlocks"],
                "sections": r["sections"],
                "seats_remaining": int(r["seats"]),
                "_rank": (not builds_on, -r["unlocks"], number),
            }
        )
    candidates.sort(key=lambda c: c["_rank"])
    for c in candidates:
        del c["_rank"]
    picks = _interleave(candidates, limit)

    return {
        "found": True,
        "term": chosen["name"],
        "requested_term": term,
        "requested_term_available": term is None or chosen["name"].lower() == term.lower(),
        "subjects": subjects,
        "completed_courses": completed,
        "considered": len(candidates),
        "recommendations": picks,
        "citations": [
            {
                "source": f"IIT Banner schedule, {chosen['name']}, {c['code']}",
                "url": BANNER_URL,
                "quote": c["prerequisites"] or "No prerequisites listed.",
            }
            for c in picks
        ],
    }
