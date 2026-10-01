"""Course catalog + schedule contract.

`CatalogSnapshot` is the JSON the Banner scraper writes (one file per term) and
the shape the pgvector loader reads back, so both sides validate against the same
models. Storage lives in `db/migrations` (tables) and `pipelines/ingest/load_catalog.py`
(upserts + embeddings); this module stays pure per the import contract.
"""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

COURSE_CODE = re.compile(r"\b([A-Z]{2,4}) (\d{3})\b")

class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid")

class Term(_Model):
    code: str = Field(pattern=r"^\d{6}$")
    name: str

class Meeting(_Model):
    type: str = ""
    days: str = ""
    time: str = ""
    where: str = ""
    date_range: str = ""
    instructor: str = ""
    schedule_type: str = ""

class Section(_Model):
    section: str
    crn: int
    special_title: str = ""
    levels: list[str] = []
    xlist_data: list[str] = []
    registration_dates: str = ""
    meetings: list[Meeting] = []
    credit_hours: float | None = None
    capacity: int | None = None
    enrolled: int | None = None
    remaining: int | None = None
    waitlist_capacity: int | None = None
    waitlist_enrolled: int | None = None
    waitlist_remaining: int | None = None
    campus: str = ""
    schedule_type: str = ""
    instruction_method: str = ""
    prerequisites: str = ""
    restrictions: str = ""
    mutual_exclusion: list[str] = []

    @property
    def instructors(self) -> list[str]:
        seen: dict[str, None] = {}
        for m in self.meetings:
            for name in m.instructor.split(","):
                if (name := name.strip()) and name != "TBA":
                    seen.setdefault(name)
        return list(seen)

class Semester(_Model):
    name: str
    code: str
    exam_time: str = ""
    exam_date: str = ""
    sections: list[Section] = []
    is_offered: bool = False
    prerequisites: str = ""

class Course(_Model):
    name: str 
    subject: str
    number: str
    title: str
    attributes: list[str] = []
    description: str = ""
    credit_hours: float | None = None
    credit_hours_max: float | None = None  # set when Banner lists "0 OR 3" / "1 TO 6"
    lecture_hours: float | None = None
    lab_hours: float | None = None
    other_hours: float | None = None
    levels: list[str] = []
    schedule_types: list[str] = []
    department: str = ""
    restrictions: str = ""
    semester: Semester

    @property
    def prerequisite_courses(self) -> list[str]:
        """Course codes named in the prerequisite expression, in order, deduplicated."""
        codes = (" ".join(m.groups()) for m in COURSE_CODE.finditer(self.semester.prerequisites))
        return list(dict.fromkeys(c for c in codes if c != self.name))

    def embedding_text(self) -> str:
        """The text a course is embedded from: stable catalog facts, never seat counts."""
        parts = [f"{self.name}: {self.title}", self.description]
        if self.department:
            parts.append(f"Department: {self.department}")
        if self.levels:
            parts.append(f"Levels: {', '.join(self.levels)}")
        if self.attributes:
            parts.append(f"Attributes: {', '.join(self.attributes)}")
        if self.semester.prerequisites:
            parts.append(f"Prerequisites: {self.semester.prerequisites}")
        return "\n".join(p for p in parts if p)

    def content_hash(self) -> str:
        """Hash of the catalog-level fields; the loader re-embeds only when it changes."""
        payload = self.model_dump(exclude={"semester"}) | {
            "prerequisites": self.semester.prerequisites
        }
        blob = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(blob.encode()).hexdigest()

class CatalogSnapshot(_Model):
    term: Term
    scraped_at: datetime
    source: str = "https://ssb.iit.edu/bnrprd"
    courses: list[Course]