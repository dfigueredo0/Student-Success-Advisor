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
    """Shape matches get_student_record, plus `grades` (course -> grade).

    Completed courses include transfer credit (grade "TR"). Courses with a non-letter grade
    (W, I, P/NP) are not read yet, so they are neither completed nor graded here.
    """
    transcript = parse_transcript_text(pdf_text(content))
    grades = transcript.grades()
    if not grades and not transcript.in_progress:
        raise TranscriptRejected(
            "I couldn't find any courses in that file. Is it your IIT unofficial transcript?"
        )
    return {
        "completed_courses": list(grades),
        "in_progress_courses": [c.course for c in transcript.in_progress],
        "grades": grades,
        "major": transcript.major,
    }
