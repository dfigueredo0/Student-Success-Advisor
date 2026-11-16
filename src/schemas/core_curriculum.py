"""Core Curriculum contract: the university-wide requirements that program pages point to.

Program requirements say "See Illinois Tech Core Curriculum, sections B and C"
(`RuleHints.core_sections`); this file is where sections A-E are spelled out. Section text is
prose in the catalog, so the rules are written out as data by the scraper and checked against
the live page on every run (`evidence`); a rule whose wording is no longer found is listed in
the section's `needs_review`.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid")


class CoreRequirement(_Model):
    id: str  # "C.humanities"
    text: str  # what the rule says, in plain words
    evidence: str  # wording that must appear in the section's page text
    parent: str = ""  # id of the rule this one is part of
    hours_min: int | None = None
    hours_max: int | None = None
    courses_min: int | None = None
    level_min: int | None = None  # 200 = "200-level or above"
    level_max: int | None = None  # 100 with level_min 100 = exactly 100-level
    attribute: str = ""  # catalog attribute a course must carry: H, S, C or N
    # when attribute_any and subjects are both given, a course may qualify by either
    attribute_any: list[str] = []
    subjects: list[str] = []
    excluding: list[str] = []
    accepts: list[str] = []  # extra courses that also count
    fields_min: int | None = None  # "courses from at least two different fields"
    scope: str = ""  # "major" / "non_major"
    notes: str = ""


class CoreCourse(_Model):
    code: str
    title: str = ""
    hours: int | None = None


class CoreSection(_Model):
    id: str  # "A".."E"
    title: str
    text: str  # the section as written on the page
    hours_min: int | None = None
    hours_max: int | None = None
    requirements: list[CoreRequirement] = []
    courses: list[CoreCourse] = []  # course lists inside the section
    open_options: list[str] = []  # "or any other HUM 100-level elective"
    footnotes: list[str] = []
    needs_review: list[str] = []


class CoreCurriculum(_Model):
    url: str
    scraped_at: str
    sections: list[CoreSection]
    notes: list[str] = []  # page-wide statements, e.g. coursework counting toward minors
