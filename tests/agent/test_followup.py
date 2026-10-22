"""orchestrator.followup: which model answers become an agent's fields."""

from typing import Any

from agents.career_advisor import CareerAdvisor
from agents.college_advisor import CollegeAdvisor
from tests.agent.fakes import FakeLLM

CAREER = CareerAdvisor().scaffolds["career_advice"].fields
DESIRED = [f for f in CAREER if f.name == "desired_skills"]
ELIGIBILITY = [
    f for f in CollegeAdvisor().scaffolds["check_eligibility"].fields if f.question
]  # course, completed_courses
PYTHON = [
    {"role": "user", "content": "What skills do I need to become a data scientist?"},
    {"role": "assistant", "content": "Which skills do you already have? List them, or say 'none'."},
    {"role": "user", "content": "none"},
    {"role": "user", "content": "Python"},
    {
        "role": "assistant",
        "content": "- Python: MSF 503 Financial Modeling (3 cr) [1]; PHYS 240 (3 cr) [2]",
    },
]


def fill(fields: list[Any], text: str, reply: dict[str, Any]) -> dict[str, str]:
    return FakeLLM(reply).fill(fields, text, PYTHON)


def test_latest_message_replaces_what_it_names() -> None:
    assert fill(DESIRED, "and for SQL?", {"desired_skills": "Python, SQL"}) == {
        "desired_skills": "SQL"
    }


def test_answer_from_the_conversation_is_kept_whole() -> None:
    reply = {"course": "PHYS 240", "completed_courses": ""}
    assert fill(ELIGIBILITY, "can I take [2]?", reply) == {"course": "PHYS 240"}


def test_none_from_the_model_is_not_the_students_answer() -> None:
    # The student's "none" answered the current-skills question, not completed courses.
    reply = {"course": "MSF 503", "completed_courses": "none"}
    assert fill(ELIGIBILITY, "can I take the first one?", reply) == {"course": "MSF 503"}


def test_unusable_reply_fills_nothing() -> None:
    assert fill(DESIRED, "and for SQL?", {"desired_skills": 3}) == {}
    assert FakeLLM("not json").fill(DESIRED, "and for SQL?", PYTHON) == {}
