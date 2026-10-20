"""parse_transcript: unofficial transcript PDF -> the profile fields the advisor uses.

Deterministic and local: the PDF is never sent to a model, which is what the data-routing
rule requires for a volunteered real transcript.
"""

import io
from typing import Any

from pypdf import PdfReader
from pypdf.errors import PyPdfError

from domain.transcript import parse_transcript_text

MAX_BYTES = 5 * 1024 * 1024  # an unofficial transcript is a few pages


class TranscriptRejected(ValueError):
    """The upload is not a readable PDF transcript; the message is safe to show the student."""


def pdf_text(content: bytes) -> str:
    if len(content) > MAX_BYTES:
        raise TranscriptRejected("That file is too large for a transcript (5 MB max).")
    if not content.startswith(b"%PDF-"):
        raise TranscriptRejected("Please upload your unofficial transcript as a PDF.")
    try:
        reader = PdfReader(io.BytesIO(content))
        return "\n".join(page.extract_text() or "" for page in reader.pages)
    except PyPdfError as exc:
        raise TranscriptRejected("I couldn't read that PDF.") from exc


def parse_transcript(content: bytes) -> dict[str, Any]:
    """Shape matches get_student_record, plus `grades` (course -> grade) and `courses`.

    Completed courses include transfer credit (grade "TR"). Courses with a non-letter grade
    (W, I, P/NP) are not read yet, so they are neither completed nor graded here.

    `courses` is one row per course attempt as printed on the transcript (a retaken course
    appears twice), for display only: the advisor's profile uses `grades`, which keeps the
    latest attempt. Rows carry no identifying fields.
    """
    transcript = parse_transcript_text(pdf_text(content))
    grades = transcript.grades()
    if not grades and not transcript.in_progress:
        raise TranscriptRejected(
            "I couldn't find any courses in that file. Is it your IIT unofficial transcript?"
        )
    courses: list[dict[str, Any]] = [
        {
            "course": c.course,
            "title": c.title,
            "term": c.term,
            "grade": c.grade,
            "credits": c.credits,
            "status": "completed",
        }
        for c in [*transcript.transfer, *transcript.completed]
    ]
    courses += [
        {
            "course": c.course,
            "title": c.title,
            "term": c.term,
            "grade": None,
            "credits": c.credits,
            "status": "in_progress",
        }
        for c in transcript.in_progress
    ]
    return {
        "completed_courses": list(grades),
        "in_progress_courses": [c.course for c in transcript.in_progress],
        "grades": grades,
        "major": transcript.major,
        "gpa": transcript.gpa(),
        "courses": courses,
    }
