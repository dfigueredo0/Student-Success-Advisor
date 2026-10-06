"""get_degree_progress: degree audit (program requirements x student record)."""

from typing import Any

def get_degree_progress(student_id: str | None) -> dict[str, Any]:
    """Remaining degree requirements for one student.

    Shape the College Advisor will render once this exists:
        {
            "program": "B.S. Computer Science",
            "credits_earned": 92.0,
            "credits_required": 126.0,
            "requirements": [
                {"name": "Computer Science Core", "required_credits": 42.0,
                 "earned_credits": 30.0, "remaining_courses": ["CS 425", "CS 450"]},
            ],
            "citations": [{"source": "...", "url": "...", "quote": "..."}],
        }
    """
    # TODO: needs impl - degree-progress service. Needs program requirements data
    # (domain.requirements) and the student's record (get_student_record).
    # TODO: security - authorize student_id against the authenticated caller (api.auth).
    raise NotImplementedError("degree progress service is not connected")
