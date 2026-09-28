"""Banner page parsers against trimmed copies of real ssb.iit.edu pages (Fall 2026)."""

import importlib.util
import json
from datetime import UTC, datetime
from pathlib import Path
from types import ModuleType

import pytest

from schemas.catalog import CatalogSnapshot

ROOT = Path(__file__).resolve().parents[2]
FIXTURES = ROOT / "tests" / "fixtures" / "banner"


def _load_scraper() -> ModuleType:
    path = ROOT / "pipelines" / "ingest" / "illinoistech_banner_scraper.py"
    spec = importlib.util.spec_from_file_location("illinoistech_banner_scraper", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


banner = _load_scraper()


def page(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


def test_terms_flag_view_only() -> None:
    terms = banner.parse_terms(page("schedule_terms.html"))
    assert terms[0] == {"code": "202710", "name": "Fall 2026", "view_only": False}
    assert terms[1] == {"code": "202630", "name": "Summer 2026", "view_only": True}


def test_catalog_listing() -> None:
    courses = {c["name"]: c for c in banner.parse_catalog_listing(page("catalog_listing.html"))}
    assert set(courses) == {"CS 100", "CS 450"}

    os_ = courses["CS 450"]
    assert os_["title"] == "Operating Systems"
    assert os_["description"].startswith("Introduction to operating system concepts")
    assert (os_["credit_hours"], os_["lecture_hours"], os_["lab_hours"]) == (3.0, 3.0, 0.0)
    assert os_["levels"] == ["Graduate Business", "Graduate", "Undergraduate"]
    assert os_["schedule_types"] == ["Lecture"]
    assert os_["department"] == "Computer Science Department"
    assert os_["attributes"] == ["CSCI Technical Elective", "Standard Tuition Rate"]

    # "0.000 OR 2.000 Credit hours"
    assert (courses["CS 100"]["credit_hours"], courses["CS 100"]["credit_hours_max"]) == (0.0, 2.0)


def test_course_detail_prerequisites() -> None:
    course = banner.parse_course_detail(page("course_detail_cs450.html"))
    assert course["name"] == "CS 450"
    # The catalog page drops the grouping; section pages keep it (see below).
    assert (
        course["prerequisites"] == "CS 351 or CS 401 or CSSP 401 and CS 402 or CSSP 402 or CS 403"
    )


def test_schedule_listing() -> None:
    sections = {s["crn"]: s for s in banner.parse_schedule_listing(page("schedule_listing.html"))}
    assert set(sections) == {12419, 14105}

    s = sections[12419]
    assert (s["name"], s["section"], s["course_title"]) == ("CS 450", "01", "Operating Systems")
    assert s["registration_dates"] == "Apr 06, 2026 to Aug 25, 2026"
    assert (s["campus"], s["schedule_type"], s["instruction_method"]) == (
        "Mies",
        "Lecture",
        "Traditional",
    )
    assert s["credit_hours"] == 3.0
    assert s["meetings"] == [
        {
            "type": "Class",
            "time": "8:35 AM - 9:50 AM",
            "days": "TR",
            "where": "Stuart Building 111",
            "date_range": "Aug 17, 2026 - Dec 12, 2026",
            "schedule_type": "Lecture",
            "instructor": "Gerald N. Balekaki",
        }
    ]
    assert sections[14105]["campus"] == "Internet"
    assert sections[14105]["meetings"][0]["time"] == "TBA"


def test_section_detail_seats_and_grouped_prereqs() -> None:
    detail = banner.parse_section_detail(page("section_detail_12419.html"))
    assert detail["capacity"] == 60 and detail["enrolled"] == 32 and detail["remaining"] == 28
    assert detail["waitlist_capacity"] == 10 and detail["waitlist_remaining"] == 10
    assert detail["prerequisites"] == (
        "CS 351 or ((CS 401 or CSSP 401) and (CS 402 or CSSP 402)) or CS 403"
    )


def test_section_detail_general_requirements_and_cross_list() -> None:
    detail = banner.parse_section_detail(page("section_detail_10345.html"))
    assert detail["xlist_data"] == ["CS 536"]
    assert detail["restrictions"] == (
        "Must be enrolled in one of the following Levels: Graduate Business, Graduate"
    )
    # "Prerequisite required" is replaced by the General Requirements tree.
    assert detail["prerequisites"].startswith("(CS 430) or (CS 440) and (CS 331 [min grade C])")


def test_build_course_matches_contract() -> None:
    term = {"code": "202710", "name": "Fall 2026"}
    catalog = next(
        c
        for c in banner.parse_catalog_listing(page("catalog_listing.html"))
        if c["name"] == "CS 450"
    )
    listing = banner.parse_schedule_listing(page("schedule_listing.html"))
    detail = banner.parse_section_detail(page("section_detail_12419.html"))
    sections = [s | detail if s["crn"] == 12419 else s for s in listing]

    course = banner.BannerScraper._build_course(term, catalog, sections)
    snapshot = CatalogSnapshot.model_validate(
        {"term": term, "scraped_at": datetime.now(UTC), "courses": [course]}
    )
    parsed = snapshot.courses[0]
    assert parsed.semester.is_offered
    assert [s.crn for s in parsed.semester.sections] == [12419, 14105]
    assert parsed.semester.prerequisites.startswith("CS 351 or ((CS 401")
    assert parsed.prerequisite_courses == [
        "CS 351",
        "CS 401",
        "CSSP 401",
        "CS 402",
        "CSSP 402",
        "CS 403",
    ]
    json.dumps(snapshot.model_dump(mode="json"))  # round-trips to plain JSON


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (
            "CS 351 or (  ( CS 401 or CSSP 401) and ( CS 402)  ) or CS 403",
            "CS 351 or ((CS 401 or CSSP 401) and (CS 402)) or CS 403",
        ),
        ("( )", ""),
    ],
)
def test_expression_normalisation(raw: str, expected: str) -> None:
    assert banner._expression(raw) == expected
