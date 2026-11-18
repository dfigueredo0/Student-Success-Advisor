"""Degree requirements contract.

`ProgramRequirements` is the JSON the catalog scraper writes (one file per program) and the
shape the advisor's requirements/degree-progress code reads back. Pure models, like
`schemas.catalog`.

A requirement row is one of:
  course  one specific course; `alternatives` are its "or" rows (take it OR one of them).
  rule    anything else ("Select 12 hours of HUM/SSCI at the 300-level or above"). `text` is the
          source of truth, verbatim; `hints` are best-effort and may be empty.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Alternative(_Model):
    code: str
    title: str = ""


class Choose(_Model):
    """ "Select N" rules: pick min..max `unit`s ("hours" or "courses") from the options."""

    min: int | None = None
    max: int | None = None
    unit: str = "courses"


class RuleHints(_Model):
    min_level: int | None = None  # 300 = "300-level or above"
    subjects: list[str] = []
    core_sections: list[str] = []  # "sections B and C" -> ["B", "C"]
    core_curriculum: bool = False  # points at the Illinois Tech Core Curriculum
    excluding: list[str] = []
    choose: Choose | None = None
    options_follow: bool = False  # "...of the following": the options are the rows after it


class Requirement(_Model):
    kind: Literal["course", "rule"]
    text: str = ""  # rule: verbatim row text
    code: str = ""  # course: "MATH 332"
    title: str = ""
    hours: int | None = None
    hours_max: int | None = None  # "13 OR 14" -> hours 13, hours_max 14
    indent: int = 0  # nesting level on the page (a row under a rule is indented)
    children: int = 0  # rule: how many of the next items are its options
    children_basis: str = ""  # "indent" or "following_courses"
    alternatives: list[Alternative] = []
    together_with: list[Alternative] = []  # "CS 115 & CS 116": all of them, not a choice
    hints: RuleHints = RuleHints()
    footnote_hints: RuleHints = RuleHints()  # same parse, run on the cited footnote text
    footnotes: list[int] = []


class Section(_Model):
    title: str
    hours: int | None = None
    hours_max: int | None = None
    table: int = 0  # which table on the page (0 = the main requirements)
    footnotes: list[int] = []  # markers on the section header
    group: str = ""  # heading above the table (a specialization, honors track, ...)
    group_total_hours: int | None = None  # the table's own "Total Credit Hours"
    items: list[Requirement] = []


class Note(_Model):
    """A footnote. Numbers restart in every table, so a footnote is (table, number)."""

    table: int
    number: int
    text: str
    borrowed: bool = False  # the page had no block beside the table; this one was nearby


class ProgramRequirements(_Model):
    slug: str
    url: str
    title: str
    total_hours: int | None = None
    scraped_at: str
    sections: list[Section] = []
    notes: list[Note] = []  # footnote text, verbatim; a Section.table + a footnote number finds it
    needs_review: list[str] = []  # rows/pages the parser did not understand
