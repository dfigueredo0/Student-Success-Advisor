"""IIT unofficial transcript text -> Transcript. Pure: the PDF text comes in as a string.

Moved from pipelines/ingest/transcript_parser.py. The section and row patterns are unchanged;
the student's name is no longer extracted and debug printing of course rows is gone.

Known gaps (from the original parser):
- only Mies/Internet undergraduate (UG) rows are recognized;
- only letter grades A-F (+/-) are read, so W, I, P/NP and audit rows are skipped.
"""

import re

from schemas.student import InProgressCourse, Transcript, TranscriptCourse

_TERM = re.compile(r"Term:\s+((?:Fall|Spring|Summer)\s+\d{4})")
_COURSE_START = re.compile(r"\b([A-Z]{2,6})\s+(\d{3})\s+(Mies|Internet)\s+UG\b")
_GRADED = re.compile(r"([A-F][+-]?)\s*(\d+\.\d{3})\s+(\d+\.\d{2})")
_TRANSFER_ROW = re.compile(r"\b([A-Z]{2,6})\s+(\d{3})\s+(.+?)\s+(TR)\s+(\d+\.\d{3})\s+(\d+\.\d{2})")
_CREDITS = re.compile(r"(\d+\.\d{3})")


def _clean(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def _section(text: str, pattern: str) -> str | None:
    m = re.search(pattern, text, re.DOTALL)
    return m.group(1) if m else None


def _rows(section: str) -> list[tuple[str, str]]:
    """(course code, text up to the next course) for each course row in a section."""
    starts = list(_COURSE_START.finditer(section))
    if not starts:  # e.g. an in-progress heading with no courses under it
        return []
    ends = [s.start() for s in starts[1:]] + [len(section)]
    return [
        (f"{s.group(1)} {s.group(2)}", section[s.end() : end])
        for s, end in zip(starts, ends, strict=True)
    ]


def parse_transcript_text(text: str) -> Transcript:
    major = _section(text, r"Major and Department\s+(.+?)\s+DEGREE AWARDED")

    transfer = []
    if section := _section(
        text, r"TRANSFER CREDIT ACCEPTED BY INSTITUTION(.*?)(?=INSTITUTION CREDIT)"
    ):
        for m in _TRANSFER_ROW.finditer(section):
            subject, number, title, grade, credits, _ = m.groups()
            transfer.append(
                TranscriptCourse(
                    course=f"{subject} {number}",
                    title=_clean(title),
                    term=None,
                    grade=grade,
                    credits=float(credits),
                )
            )

    completed = []
    if section := _section(text, r"INSTITUTION CREDIT(.*?)(?=TRANSCRIPT TOTALS)"):
        for term_text in re.split(r"(?=Term:\s+(?:Fall|Spring|Summer)\s+\d{4})", section):
            if not (term := _TERM.search(term_text)):
                continue
            for course, row in _rows(term_text):
                if not (d := _GRADED.search(row)):
                    continue
                completed.append(
                    TranscriptCourse(
                        course=course,
                        title=_clean(row[: d.start()]),
                        term=term.group(1),
                        grade=d.group(1),
                        credits=float(d.group(2)),
                        quality_points=float(d.group(3)),
                    )
                )

    in_progress = []
    if section := _section(text, r"COURSE\(S\) IN PROGRESS(.*)"):
        term = _TERM.search(section)
        for course, row in _rows(section):
            if not (c := _CREDITS.search(row)):
                continue
            in_progress.append(
                InProgressCourse(
                    course=course,
                    title=_clean(row[: c.start()]),
                    term=term.group(1) if term else None,
                    credits=float(c.group(1)),
                )
            )

    return Transcript(
        major=_clean(major) if major else None,
        completed=completed,
        transfer=transfer,
        in_progress=in_progress,
    )
