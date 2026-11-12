"""Student details in reply text that neither logs nor the model need to see.

The transcript summary (agents.college_advisor) writes a student's grades and major into a
reply, and the job-match answer (agents.career_advisor) their skills. They are kept for the
student, but this removes them from the two copies that leave the conversation: traces
(api.tracing) and the history in model prompts (memory).
"""

import re

_GRADE = r"(?:[A-D][+-]?|E|F|TR|transfer)"
_COURSE_GRADE = re.compile(rf"\b([A-Z]{{2,4}} \d{{3}}[A-Z]?) \({_GRADE}\)")
_MAJOR_LINE = re.compile(r"^- Major: .*(?:\n|$)", re.MULTILINE)
# The job-match answer (agents.career_advisor) lists the student's own skills under each role;
# they can come from an uploaded resume.
_HAVE_LINE = re.compile(r"^[ \t]*- You have: .*(?:\n|$)", re.MULTILINE)


def hide_record(text: str) -> str:
    return _HAVE_LINE.sub("", _MAJOR_LINE.sub("", _COURSE_GRADE.sub(r"\1", text)))
