"""parse_transcript: unofficial transcript upload -> student record."""

from typing import Any

def parse_transcript(content: bytes, filename: str) -> dict[str, Any]:
    """Returns the get_student_record shape (completed/in-progress courses, subject, level)."""
    # TODO: needs impl - transcript parsing (pipelines/ingest/transcript_parser.py has a start).
    # TODO: frontend - the upload screen (frontend/app.js handleTranscriptUpload) should POST
    # the file to an API route that calls this, instead of simulating locally.
    # TODO: security - validate file type/size and treat contents as untrusted input.
    raise NotImplementedError("transcript parsing is not connected")
