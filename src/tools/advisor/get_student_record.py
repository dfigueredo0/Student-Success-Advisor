"""get_student_record: the student's courses and standing, for seeding the advisor's profile."""

from typing import Any

def get_student_record(student_id: str) -> dict[str, Any]:
    """Shape the orchestrator's `profile` expects:
        {
            "completed_courses": ["CS 115", "MATH 151"],
            "in_progress_courses": ["CS 350"],
            "subject": "CS",            # major's subject code
            "level": "Undergraduate",
            "start_term": "Fall 2025",  # lets "Spring Year 2" resolve to a real term
        }
    """
    # TODO: needs impl - student record service (stored output of parse_transcript).
    # TODO: security - RLS / authorize student_id against the authenticated caller.
    raise NotImplementedError("student record service is not connected")
