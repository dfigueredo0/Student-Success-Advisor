"""
Pulls the Core Curriculum (sections A-E) from the public catalog into structured JSON.

Companion to degree_requirements.py: program pages say "See Illinois Tech Core Curriculum,
sections B and C"; this writes what those sections require to
data/raw/degree_requirements/core-curriculum.json, validated against
`schemas.core_curriculum.CoreCurriculum`.

The catalog writes these rules as prose, so the rules themselves are written out in CORE_RULES
below, and every run checks that the wording each rule rests on (`evidence`) is still on the
page. A rule whose wording changed is flagged in that section's `needs_review` instead of
silently going stale. Section text, course lists and footnotes are scraped as they are.

    uv run --group ingest python pipelines/ingest/core_curriculum.py
    uv run --group ingest python pipelines/ingest/core_curriculum.py --html saved_page.html
"""

from __future__ import annotations

import argparse
import logging
import re
import sys
from datetime import UTC, datetime
from pathlib import Path

from bs4 import BeautifulSoup

sys.path.insert(0, str(Path(__file__).resolve().parent))
from degree_requirements import (  # noqa: E402
    DEFAULT_OUT_DIR,
    RequirementsScraper,
    _clean,
    write_json,
)

from schemas.core_curriculum import CoreCurriculum  # noqa: E402

log = logging.getLogger("core_curriculum")

URL = "https://catalog.iit.edu/undergraduate/undergraduate-education/core-curriculum/"

# Hours are for the whole section where the page states them (A has none).
SECTION_HOURS = {"B": (3, 3), "C": (18, 18), "D": (16, None), "E": (8, 8)}

# id -> list of rules. `evidence` is lower-case text that must appear in the section.
CORE_RULES: dict[str, list[dict]] = {
    "A": [
        {
            "id": "A.bwp",
            "text": "Basic Writing Proficiency: shown by test scores or COM 101 credit, else "
            "the Illinois Tech exam or an approved composition course in the first year.",
            "evidence": "basic writing proficiency",
            "accepts": ["COM 101"],
        },
        {
            "id": "A.writing_intensive",
            "text": "One writing-instruction-intensive Humanities course at the 200 level.",
            "evidence": "writing instruction intensive 200-level humanities course",
            "courses_min": 1,
            "level_min": 200,
            "attribute": "H",
        },
        {
            "id": "A.communication",
            "text": "At least 36 credit hours in courses marked (C).",
            "evidence": "minimum of 36 credit hours",
            "hours_min": 36,
            "attribute": "C",
        },
        {
            "id": "A.communication_major",
            "text": "Of those, at least 12 hours in major courses.",
            "evidence": "12 credit hours in major courses",
            "parent": "A.communication",
            "hours_min": 12,
            "attribute": "C",
            "scope": "major",
        },
        {
            "id": "A.communication_non_major",
            "text": "Of those, at least 12 hours in non-major courses.",
            "evidence": "12 credit hours in non-major courses",
            "parent": "A.communication",
            "hours_min": 12,
            "attribute": "C",
            "scope": "non_major",
        },
    ],
    "B": [
        {
            "id": "B.hum_100",
            "text": "One Humanities 100-level course: HUM 100, 102, 104, 106, 108 or any other "
            "HUM 100-level elective.",
            "evidence": "humanities 100-level course",
            "hours_min": 3,
            "courses_min": 1,
            "level_min": 100,
            "level_max": 100,
            "subjects": ["HUM"],
        }
    ],
    "C": [
        {
            "id": "C.total",
            "text": "Human Sciences Module: 18 credit hours with the distribution below.",
            "evidence": "complete 18 credit hours",
            "hours_min": 18,
        },
        {
            "id": "C.humanities",
            "text": "At least two Humanities (H) courses at the 200 level or above. "
            "Intermediate and advanced foreign language courses count as 200-level.",
            "evidence": "at least two humanities courses",
            "parent": "C.total",
            "courses_min": 2,
            "level_min": 200,
            "attribute": "H",
        },
        {
            "id": "C.social",
            "text": "At least three Social or Behavioral Science (S) courses.",
            "evidence": "at least three social or behavioral sciences courses",
            "parent": "C.total",
            "courses_min": 3,
            "attribute": "S",
        },
        {
            "id": "C.social_upper",
            "text": "Of the S courses, at least two at the 200 level or above.",
            "evidence": "at least two courses at the 200-level or above",
            "parent": "C.social",
            "courses_min": 2,
            "level_min": 200,
            "attribute": "S",
        },
        {
            "id": "C.social_fields",
            "text": "The S courses must come from at least two different fields.",
            "evidence": "from at least two different fields",
            "parent": "C.social",
            "fields_min": 2,
            "attribute": "S",
        },
        {
            "id": "C.remaining",
            "text": "The remaining course: any H course, any S course, or any COM course "
            "except COM 101 or COM 111.",
            "evidence": "any com course except com 101 or com 111",
            "parent": "C.total",
            "courses_min": 1,
            "attribute_any": ["H", "S"],
            "subjects": ["COM"],
            "excluding": ["COM 101", "COM 111"],
        },
        {
            "id": "C.double_counting",
            "text": "A course can count toward both the core and the major; each is evaluated "
            "separately against the whole transcript.",
            "evidence": "any class passed can count toward both core requirements",
            "parent": "C.total",
        },
    ],
    "D": [
        {
            "id": "D.total",
            "text": "STEM Module: at least 16 credit hours between Mathematics and Natural "
            "Science or Engineering (plus the computer science course).",
            "evidence": "a minimum 16 credit hours",
            "hours_min": 16,
        },
        {
            "id": "D.math",
            "text": "Mathematics: 5-6 hours at MATH 119 or above. BUS 221, PSYC 203 and "
            "STAT 225 also satisfy this.",
            "evidence": "mathematics: five to six credit hours",
            "parent": "D.total",
            "hours_min": 5,
            "hours_max": 6,
            "subjects": ["MATH"],
            "level_min": 119,
            "accepts": ["BUS 221", "PSYC 203", "STAT 225"],
        },
        {
            "id": "D.science",
            "text": "Natural Science or Engineering: 10-11 hours (engineering, biology, "
            "chemistry, physics, or architecture, food safety and technology, psychology "
            "courses marked (N)).",
            "evidence": "natural science or engineering: 10-11 credit hours",
            "parent": "D.total",
            "hours_min": 10,
            "hours_max": 11,
            "attribute": "N",
        },
        {
            "id": "D.science_sequence",
            "text": "Two sequential natural science or engineering courses in a single field "
            "(CHEM 122 and CHEM 123 with MS 201 satisfies this; FDSN counts as the same "
            "field as BIOL).",
            "evidence": "two sequential natural science or engineering courses in a single field",
            "parent": "D.science",
            "courses_min": 2,
        },
        {
            "id": "D.science_second_field",
            "text": "At least one natural science or engineering course in a second field.",
            "evidence": "at least one natural science or engineering course in a second field",
            "parent": "D.science",
            "courses_min": 1,
        },
        {
            "id": "D.computer_science",
            "text": "Computer Science: two credit hours from the list, or a computer science "
            "course at the 300 level or above.",
            "evidence": "computer science: two credit hours",
            "parent": "D.total",
            "hours_min": 2,
            "courses_min": 1,
            "subjects": ["CS"],
            "level_min": 300,
        },
    ],
    "E": [
        {
            "id": "E.itp",
            "text": "Introduction to the Profession: 2 hours, usually in the first year. May "
            "be waived with department approval for students entering with 30+ transfer "
            "hours; the degree's total hours must still be met.",
            "evidence": "introduction to the profession (itp): two credit hours",
            "hours_min": 2,
        },
        {
            "id": "E.ipro",
            "text": "Interprofessional Projects: 6 hours, at least two IPRO experiences. "
            "An ROTC minor exempts one of the two.",
            "evidence": "interprofessional projects (ipro): six credit hours",
            "hours_min": 6,
            "courses_min": 2,
            "subjects": ["IPRO"],
        },
    ],
}


def _norm(text: str) -> str:
    return _clean(text).lower()


def parse_core(html: str, url: str = URL) -> dict:
    soup = BeautifulSoup(html, "html.parser")
    sections: list[dict] = []
    for letter in "ABCDE":
        anchor = soup.find("a", id=f"core_{letter.lower()}")
        li = anchor.find_parent("li") if anchor else None
        if li is None:
            sections.append(
                {
                    "id": letter,
                    "title": "",
                    "text": "",
                    "needs_review": [f"section {letter} not found on the page"],
                }
            )
            continue
        title_node = anchor.next_sibling
        if title_node is None or not str(title_node).strip():
            title_node = anchor.find_next(string=lambda s: s.strip())
        text = _clean(li.get_text(" "))
        review: list[str] = []
        lowered = _norm(text)
        reqs = []
        for rule in CORE_RULES[letter]:
            if rule["evidence"] not in lowered:
                review.append(f"{rule['id']}: expected wording not found, check the page")
            reqs.append(rule)
        courses, open_options = [], []
        for row in li.select("table.sc_courselist tr"):
            code = row.select_one("td.codecol")
            hours = row.select_one("td.hourscol")
            h = _clean(hours.get_text()) if hours else ""
            if code and (m := re.search(r"([A-Z]{2,4})\s?(\d{3})", code.get_text())):
                cells = row.find_all("td")
                courses.append(
                    {
                        "code": f"{m.group(1)} {m.group(2)}",
                        "title": _clean(cells[1].get_text(" ")) if len(cells) > 2 else "",
                        "hours": int(h) if h.isdigit() else None,
                    }
                )
            elif comment := row.select_one(".courselistcomment"):
                open_options.append(_clean(comment.get_text(" ")))
        low, high = SECTION_HOURS.get(letter, (None, None))
        sections.append(
            {
                "id": letter,
                "title": _clean(str(title_node)),
                "text": text,
                "hours_min": low,
                "hours_max": high,
                "requirements": reqs,
                "courses": courses,
                "open_options": open_options,
                "footnotes": [],
                "needs_review": review,
            }
        )
    footnotes = [_clean(dd.get_text(" ")) for dd in soup.select("dl.sc_footnotes dd")]
    for s in sections:
        if s["id"] == "E":
            s["footnotes"] = footnotes
    notes = [
        _clean(p.get_text(" "))
        for p in soup.select("#textcontainer > .onecol > p")
        if "minor" in p.get_text().lower()
    ]
    return {
        "url": url,
        "scraped_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "sections": sections,
        "notes": notes,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT_DIR, help="output directory")
    parser.add_argument("--html", type=Path, help="parse a saved page, print JSON, no network")
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    if args.html:
        core = CoreCurriculum.model_validate(parse_core(args.html.read_text(encoding="utf-8")))
        print(core.model_dump_json(indent=2, exclude_defaults=True))
        return 0
    with RequirementsScraper() as scraper:
        html = scraper._fetch(URL)
    core = CoreCurriculum.model_validate(parse_core(html))
    write_json(
        args.out / "core-curriculum.json", core.model_dump(mode="json", exclude_defaults=True)
    )
    review = [r for s in core.sections for r in s.needs_review]
    log.info(
        "wrote core-curriculum.json (%d sections, %d to review)", len(core.sections), len(review)
    )
    for r in review:
        log.warning("review: %s", r)
    return 0


if __name__ == "__main__":
    sys.exit(main())
