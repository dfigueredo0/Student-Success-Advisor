"""parse_resume: resume PDF -> the skills and education the Career agent uses.

Deterministic and local, like parse_transcript: the PDF is never sent to a model. Skills are
matched against the O*NET vocabulary and education against fixed patterns, so the result can
only hold vocabulary names, a degree level and a year, never a name, contact detail or employer.
"""

from typing import Any

from domain.resume import education, scrub
from domain.skills import MAX_SCAN, extract_skills
from tools.advisor.parse_transcript import MAX_BYTES, TranscriptRejected, pdf_text
from tools.career import onet

__all__ = ["MAX_BYTES", "ResumeRejected", "parse_resume"]

MIN_TEXT = 100  # characters; a scanned resume has a page image and no text


class ResumeRejected(ValueError):
    """The upload is not a readable PDF resume; the message is safe to show the student."""


def parse_resume(content: bytes) -> dict[str, Any]:
    """`skills` are display labels ("SQL", "Excel") in the order the resume names them."""
    try:
        text = pdf_text(content, "resume")[:MAX_SCAN]  # a resume is a few thousand characters
    except TranscriptRejected as exc:
        raise ResumeRejected(str(exc)) from exc
    if len(text.strip()) < MIN_TEXT:
        raise ResumeRejected(
            "I couldn't find any text in that PDF. If it's a scan, export your resume from Word "
            "or Google Docs as a PDF and try again."
        )
    skills = extract_skills(scrub(text), onet.vocabulary())
    if not skills:
        raise ResumeRejected(
            "I couldn't find any software or tool skills in that file. Is it your resume? You "
            "can also list your skills in the chat."
        )
    degree_level, graduation_year = education(text)
    return {"skills": skills, "degree_level": degree_level, "graduation_year": graduation_year}
