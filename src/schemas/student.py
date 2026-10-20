"""Student record models: what a parsed transcript yields and what the advisor profile holds.

Identifying fields (name, A-number, birth date) are deliberately absent: the parser never
extracts them, so they cannot reach the profile, the graph state, or a trace.
"""

from pydantic import BaseModel, ConfigDict


class TranscriptCourse(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    course: str  # "CS 331"
    title: str
    term: str | None  # "Fall 2025"; None for transfer credit
    grade: str  # letter grade, or "TR" for transfer credit
    credits: float
    quality_points: float = 0.0  # as printed on the transcript row; 0 for transfer credit


class InProgressCourse(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    course: str
    title: str
    term: str | None
    credits: float


class Transcript(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    major: str | None = None
    completed: list[TranscriptCourse] = []
    transfer: list[TranscriptCourse] = []
    in_progress: list[InProgressCourse] = []

    def grades(self) -> dict[str, str]:
        """Course -> grade. Transfer first, so an IIT attempt of the same course wins.

        TODO: needs decision - repeat policy (which attempt counts) belongs to
        domain.grades.grade_satisfies; until then the latest attempt in transcript order wins.
        """
        return {c.course: c.grade for c in [*self.transfer, *self.completed]}

    def gpa(self) -> float | None:
        """Institution GPA: quality points over credit hours, from the figures the transcript
        prints on each row. Only the latest attempt of a retaken course counts, as in grades();
        transfer credit is not part of it. None when no graded course was read.

        TODO: needs decision - repeat policy, same as grades().
        """
        latest = {c.course: c for c in self.completed}
        hours = sum(c.credits for c in latest.values())
        if not hours:
            return None
        return round(sum(c.quality_points for c in latest.values()) / hours, 2)
