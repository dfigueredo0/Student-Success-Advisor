"""Student details in reply text that neither logs nor the model need to see.

Only the transcript summary (agents.college_advisor) writes a student's grades and major into
a reply. It is kept for the student, but this removes them from the two copies that leave the
conversation: traces (api.tracing) and the history in model prompts (memory).
"""

import re

_GRADE = r"(?:[A-D][+-]?|E|F|TR|transfer)"
_COURSE_GRADE = re.compile(rf"\b([A-Z]{{2,4}} \d{{3}}[A-Z]?) \({_GRADE}\)")
_MAJOR_LINE = re.compile(r"^- Major: .*(?:\n|$)", re.MULTILINE)


def hide_record(text: str) -> str:
    return _MAJOR_LINE.sub("", _COURSE_GRADE.sub(r"\1", text))
