from pathlib import Path

import pytest

from domain.transcript import parse_transcript_text
from tools.advisor import parse_transcript as tool

# Synthetic: follows the unofficial-transcript layout, holds no real student data.
TEXT = (Path(__file__).parents[1] / "fixtures" / "transcript" / "synthetic.txt").read_text()


def test_sections_are_parsed() -> None:
    t = parse_transcript_text(TEXT)
    assert t.major == "Computer Science, Computer Science"
    assert [(c.course, c.grade, c.term) for c in t.transfer] == [("MATH 151", "TR", None)]
    assert [(c.course, c.grade, c.term) for c in t.completed] == [
        ("CS 115", "A", "Fall 2024"),
        ("CS 116", "D", "Fall 2024"),
        ("CS 116", "A", "Spring 2025"),
        ("CS 331", "C+", "Spring 2025"),
    ]
    assert t.completed[0].title == "Object-Oriented Programming I"  # line break inside title
    assert [(c.course, c.term, c.credits) for c in t.in_progress] == [
        ("CS 350", "Fall 2025", 3.0),
        ("CS 351", "Fall 2025", 3.0),
    ]


def test_withdrawn_course_is_not_completed() -> None:
    assert "HUM 200" not in parse_transcript_text(TEXT).grades()


def test_latest_attempt_wins_and_transfer_is_tr() -> None:
    assert parse_transcript_text(TEXT).grades() == {
        "MATH 151": "TR",
        "CS 115": "A",
        "CS 116": "A",
        "CS 331": "C+",
    }


def test_identity_is_never_extracted() -> None:
    dumped = parse_transcript_text(TEXT).model_dump_json()
    assert "Student" not in dumped and "Birth" not in dumped


def test_tool_returns_profile_fields(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(tool, "pdf_text", lambda content: TEXT)
    r = tool.parse_transcript(b"%PDF-")
    assert r["completed_courses"] == ["MATH 151", "CS 115", "CS 116", "CS 331"]
    assert r["in_progress_courses"] == ["CS 350", "CS 351"]
    assert r["grades"]["CS 331"] == "C+"


@pytest.mark.parametrize(
    "content",
    [b"plain text", b"%PDF-1.7 not really a pdf", b"%PDF-" + b"0" * tool.MAX_BYTES],
    ids=["not-pdf", "corrupt", "too-large"],
)
def test_unreadable_uploads_are_rejected(content: bytes) -> None:
    with pytest.raises(tool.TranscriptRejected):
        tool.parse_transcript(content)


def test_pdf_without_courses_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(tool, "pdf_text", lambda content: "a resume, not a transcript")
    with pytest.raises(tool.TranscriptRejected, match="couldn't find any courses"):
        tool.parse_transcript(b"%PDF-")
