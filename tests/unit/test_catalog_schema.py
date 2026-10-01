import pytest
from pydantic import ValidationError

from schemas.catalog import CatalogSnapshot, Course

COURSE = {
    "name": "CS 450",
    "subject": "CS",
    "number": "450",
    "title": "Operating Systems",
    "attributes": ["CSCI Technical Elective", "Standard Tuition Rate"],
    "description": "Introduction to operating system concepts.",
    "credit_hours": 3,
    "lecture_hours": 3,
    "lab_hours": 0,
    "levels": ["Graduate", "Undergraduate"],
    "department": "Computer Science Department",
    "semester": {
        "name": "Fall 2026",
        "code": "202710",
        "is_offered": True,
        "prerequisites": "CS 351 or ((CS 401 or CSSP 401) and (CS 402 or CSSP 402)) or CS 403",
        "sections": [
            {
                "section": "01",
                "crn": 12419,
                "capacity": 60,
                "enrolled": 32,
                "remaining": 28,
                "meetings": [
                    {"type": "Class", "instructor": "Gerald N. Balekaki"},
                    {"type": "Lab", "instructor": "Gerald N. Balekaki, TBA"},
                ],
            }
        ],
    },
}

def course(**overrides: object) -> Course:
    return Course.model_validate(COURSE | overrides)

def test_prerequisite_courses_in_order() -> None:
    assert course().prerequisite_courses == [
        "CS 351",
        "CS 401",
        "CSSP 401",
        "CS 402",
        "CSSP 402",
        "CS 403",
    ]

def test_section_instructors_deduplicated() -> None:
    assert course().semester.sections[0].instructors == ["Gerald N. Balekaki"]

def test_embedding_text_has_catalog_facts_only() -> None:
    text = course().embedding_text()
    assert text.startswith("CS 450: Operating Systems")
    assert "Prerequisites: CS 351" in text
    assert "32" not in text  # seat counts change weekly and must not force re-embedding

def test_content_hash_ignores_seats_but_tracks_catalog() -> None:
    base = course()
    busier = course(semester=COURSE["semester"] | {"sections": []})
    assert base.content_hash() == busier.content_hash()
    assert base.content_hash() != course(description="Rewritten.").content_hash()

def test_unknown_fields_rejected() -> None:
    with pytest.raises(ValidationError):
        course(unexpected=True)

def test_snapshot_term_code_validated() -> None:
    with pytest.raises(ValidationError):
        CatalogSnapshot.model_validate(
            {
                "term": {"code": "fall26", "name": "Fall 2026"},
                "scraped_at": "2026-09-24T00:00:00Z",
                "courses": [],
            }
        )