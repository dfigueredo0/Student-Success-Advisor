"""
Pulls from IIT's public, unauthenticated Banner pages (Banner 8 self-service).

Built as a weekly cron job: it scrapes the *entire* course catalog and class
schedule for every term currently open for registration (or the terms passed
with --terms) and writes one JSON snapshot per term to data/raw/banner/<term>.json.
Every snapshot is validated against `schemas.catalog.CatalogSnapshot` before it is
written; `load_catalog.py` then upserts it into Postgres/pgvector.

    uv run --group ingest python pipelines/ingest/illinoistech_banner_scraper.py
    uv run --group ingest python pipelines/ingest/illinoistech_banner_scraper.py --terms 202710 --subjects CS MATH

Weekly cron (Sundays 03:00), scrape + load:
    0 3 * * 0  cd /srv/student-success-advisor && make ingest-catalog >> logs/ingest.log 2>&1
"""
from __future__ import annotations

import argparse
import copy
import json
import logging
import re
import ssl
import sys
import threading
import time
from collections.abc import Callable, Iterable
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, TypeVar

import httpx
from bs4 import BeautifulSoup, Tag

from schemas.catalog import COURSE_CODE, CatalogSnapshot

ROOT = Path(__file__).resolve().parents[2]

log = logging.getLogger("banner_scraper")

COURSE_SCHEDULE_URL = "https://ssb.iit.edu/bnrprd/bwckschd.p_disp_dyn_sched"
COURSE_CATALOG_URL = "https://ssb.iit.edu/bnrprd/bwckctlg.p_disp_dyn_ctlg"

# The pages each of the two entry points above post through.
SCHEDULE_TERM_URL = "https://ssb.iit.edu/bnrprd/bwckgens.p_proc_term_date"
SCHEDULE_SEARCH_URL = "https://ssb.iit.edu/bnrprd/bwckschd.p_get_crse_unsec"
SECTION_DETAIL_URL = "https://ssb.iit.edu/bnrprd/bwckschd.p_disp_detail_sched"
CATALOG_TERM_URL = "https://ssb.iit.edu/bnrprd/bwckctlg.p_disp_cat_term_date"
CATALOG_SEARCH_URL = "https://ssb.iit.edu/bnrprd/bwckctlg.p_display_courses"
COURSE_DETAIL_URL = "https://ssb.iit.edu/bnrprd/bwckctlg.p_disp_course_detail"

DEFAULT_OUT_DIR = ROOT / "data" / "raw" / "banner"
USER_AGENT = "StudentSuccessAdvisor-CatalogBot/1.0 (+https://github.com/dfigueredo0/Student-Success-Advisor)"

"""
COURSE SCHEDULE Listing Format
COURSE TITLE - CRN - $$($$) ### - Section ((L)01,(L)02)
ASSOCIATED TERM
REGISTRATION DATES
LEVELS
ATTRIBUTES
"""

"""
EXAMPLE COURSE SCHEDULE DETAIL: https://ssb.iit.edu/bnrprd/bwckschd.p_disp_detail_sched?term_in=202710&crn_in=11651

keyed by term and CRN, to collect enrollment and waitlist counts
"""

"""
COURSE CATALOG Listing Format
$$($$) ### - COURSE TITLE
COURSE DESCRIPTION
CREDITS
LEVELS:
SCHEDULE TYPES

DEPARTMENT

COURSE ATTRIBUTES
"""

"""
EXAMPLE COURSE CATALOG DETAIL: https://ssb.iit.edu/bnrprd/bwckctlg.p_disp_course_detail?cat_term_in=202730&subj_code_in=CS&crse_numb_in=450
keyed by term, subject code, and course number, to collect all credit hours, prerequisites, and general requirements
"""

"""
JSON output: one file per term, {"term": {...}, "scraped_at": ..., "courses": [<course>, ...]}.
Each course follows the shape below (the models in src/schemas/catalog.py are the source of
truth).
{
    name: "CS 450",
    title: "Operation Systems",
    attributes: ["CSCI Technical Elective", "Standard Tuition Rate"],
    description: "Introduction to operating system concepts-including system organization for uniprocessors and multiprocessors, scheduling algorithms, process management, deadlocks, paging and segmentation, files and protection, and process coordination and communication.",
    credit_hours: 3,
    lecture_hours: 3,
    lab_hours: 0,
    semester: {
        name: "Fall 2026",
        code: "202710",
        exam_time: "",
        exam_date: "",
        sections: [
            {
                section: "01",
                special_title: "",
                crn: 12419,
                levels: ["Graduate Business", "Graduate", "Undergraduate"],
                xlist_data: [],
                registration_dates: "Apr 06, 2026 to Aug 25, 2026",
                meetings: [{
                    type: "Class",
                    days: "TR",
                    time: "8:35 AM - 9:50 AM",
                    where: "Stuart Building 111",
                    date_range: "Aug 17, 2026 - Dec 12, 2026",
                    instructor: "Gerald N. Balekaki",
                    schedule_type: "Lecture",
                }],
                capacity: 60,
                enrolled: 32,
                remaining: 28,
                waitlist_capacity: 10,
                waitlist_enrolled: 0,
                waitlist_remaining: 10,
                campus: "Mies",
                schedule_type: "Lecture",
                instruction_method: "Traditional",
            },
            ...
        ],
        is_offered: true,
        prerequisites: "CS 351 or ((CS 401 or CSSP 401) and (CS 402 or CSSP 402)) or CS 403",
    },
}
"""

class BannerScraperException(Exception):
    """A page could not be fetched or no longer looks like Banner 8."""

# --------------------------------------------------------------------------
# HTML helpers
# --------------------------------------------------------------------------

HOURS = re.compile(
    r"^([\d.]+)(?:\s+(?:TO|OR)\s+([\d.]+))?\s+(Credit|Lecture|Lab|Other) hours$", re.I
)
SECTION_CREDITS = re.compile(r"^([\d.]+)(?:\s+(?:TO|OR)\s+([\d.]+))?\s+Credits$", re.I)
FIELD_LABEL = re.compile(r'<span class="fieldlabeltext">\s*([A-Z][A-Za-z ]*?)\s*:\s*</span>', re.I)
PAGE_FOOTER = re.compile(r'<table[^>]*SUMMARY="This is for formatting of the bottom links', re.I)
PREREQ_PLACEHOLDER = "Prerequisite required"

def _clean(text: str) -> str:
    return " ".join(text.replace("\xa0", " ").split())

def _lines(node: Tag | str) -> list[str]:
    """Visible text split on <br>, one cleaned, non-empty string per line."""
    soup = BeautifulSoup(node, "html.parser") if isinstance(node, str) else copy.copy(node)
    for br in soup.find_all("br"):
        br.replace_with("\n")
    return [line for raw in soup.get_text().split("\n") if (line := _clean(raw))]

def _split_list(value: str) -> list[str]:
    return [v for v in (_clean(p) for p in value.split(",")) if v]

def _expression(text: str) -> str:
    """Collapse a Banner boolean requirement into one line: `( ( CS 401` -> `((CS 401`."""
    text = _clean(text)
    text = re.sub(r"\(\s+", "(", text)
    text = re.sub(r"\s+\)", ")", text)
    return re.sub(r"\(\)\s*", "", text).strip()

def _chunks(page: str, title_marker: str) -> Iterable[str]:
    """Split a listing page at each title cell. Banner 8 leaves <td>/<tr> unclosed in the
    catalog listing, so walking the DOM would nest every course inside the one before it."""
    page = PAGE_FOOTER.split(page, maxsplit=1)[0]
    return re.split(rf'(?=<t[hd] CLASS="{title_marker}")', page, flags=re.I)[1:]

def _labeled_blocks(cell: Tag) -> tuple[str, dict[str, str]]:
    """Split a detail cell at its field labels -> (text before the first label, {label: html})."""
    parts = FIELD_LABEL.split(str(cell))
    return parts[0], {parts[i].strip(): parts[i + 1] for i in range(1, len(parts) - 1, 2)}

def _hours(lines: Iterable[str]) -> dict[str, float | None]:
    out: dict[str, float | None] = {}
    for line in lines:
        if m := HOURS.match(line):
            low, high, kind = float(m[1]), m[2], m[3].lower()
            out[f"{kind}_hours"] = low
            if kind == "credit" and high is not None:
                out["credit_hours_max"] = float(high)
    return out

def _restrictions(block_html: str) -> str:
    """'Must be enrolled in one of the following Levels:' + items -> one clause per heading."""
    clauses: list[tuple[str, list[str]]] = []
    for line in _lines(block_html):
        if line.endswith(":") or not clauses:
            clauses.append((line, []))
        else:
            clauses[-1][1].append(line)
    return "; ".join(f"{head} {', '.join(items)}".strip() for head, items in clauses)

def _general_requirements(block_html: str) -> str:
    """Banner's 'General Requirements' tree -> `(CS 430) or (CS 331 [min grade C])`."""
    text = " ".join(_lines(block_html))
    text = re.sub(r"Course or Test:\s*", "", text)
    text = re.sub(r"Minimum Grade of\s+(\S+)", r"[min grade \1]", text)
    text = text.replace("May not be taken concurrently.", "")
    text = text.replace("May be taken concurrently.", "[may be concurrent]")
    return _expression(text)

def _requirements(blocks: dict[str, str]) -> dict[str, Any]:
    """Prerequisites / restrictions / cross-lists shared by section and course detail pages."""
    prereq = _expression(" ".join(_lines(blocks["Prerequisites"]))) if "Prerequisites" in blocks else ""
    general = _general_requirements(blocks["General Requirements"]) if "General Requirements" in blocks else ""
    if prereq in ("", PREREQ_PLACEHOLDER):
        prereq = general
    elif general:
        prereq = f"({prereq}) and ({general})"

    def codes(label: str) -> list[str]:
        text = " ".join(_lines(blocks.get(label, "")))
        return list(dict.fromkeys(" ".join(m.groups()) for m in COURSE_CODE.finditer(text)))

    return {
        "prerequisites": prereq,
        "restrictions": _restrictions(blocks["Restrictions"]) if "Restrictions" in blocks else "",
        "xlist_data": codes("Cross List Courses"),
        "mutual_exclusion": codes("Mutual Exclusion"),
    }

# --------------------------------------------------------------------------
# Page parsers (pure: HTML in, dicts out)
# --------------------------------------------------------------------------

def parse_terms(page: str) -> list[dict[str, Any]]:
    """Term dropdown -> [{code, name, view_only}], newest first as Banner lists them."""
    soup = BeautifulSoup(page, "html.parser")
    select = soup.find("select", attrs={"name": re.compile(r"^(p_term|cat_term_in)$")})
    if select is None:
        raise BannerScraperException("term dropdown not found")
    terms = []
    for opt in select.find_all("option"):
        code = (opt.get("value") or "").strip()
        if not re.fullmatch(r"\d{6}", code):
            continue
        label = _clean(opt.get_text())
        terms.append({
            "code": code,
            "name": label.replace("(View only)", "").strip(),
            "view_only": "(View only)" in label,
        })
    return terms

def parse_subjects(page: str) -> list[str]:
    soup = BeautifulSoup(page, "html.parser")
    select = soup.find("select", attrs={"name": "sel_subj"})
    if select is None:
        raise BannerScraperException("subject list not found")
    return [v for opt in select.find_all("option") if (v := (opt.get("value") or "").strip())]

def _parse_course_cell(title: str, cell: Tag) -> dict[str, Any]:
    """The body shared by a catalog listing entry and a catalog detail page."""
    code, _, course_title = _clean(title).partition(" - ")
    subject, _, number = code.partition(" ")
    lead, blocks = _labeled_blocks(cell)
    lead_lines = _lines(lead)

    description: list[str] = []
    for line in lead_lines:
        if HOURS.match(line):
            break
        description.append(line)

    schedule_lines = _lines(blocks.get("Schedule Types", ""))
    rest = schedule_lines[1:]
    department = next((line for line in rest if "Dep" in line), rest[-1] if rest else "")
    first = lambda label: (_lines(blocks.get(label, "")) or [""])[0]  # noqa: E731

    return {
        "name": f"{subject} {number}",
        "subject": subject,
        "number": number,
        "title": _clean(course_title),
        "description": " ".join(description),
        **_hours(lead_lines),
        "levels": _split_list(first("Levels")),
        "schedule_types": _split_list(schedule_lines[0] if schedule_lines else ""),
        "department": department,
        "attributes": _split_list(first("Course Attributes")),
        **_requirements(blocks),
    }

def parse_catalog_listing(page: str) -> list[dict[str, Any]]:
    courses = []
    for chunk in _chunks(page, "nttitle"):
        soup = BeautifulSoup(chunk, "html.parser")
        title, cell = soup.find(class_="nttitle"), soup.find("td", class_="ntdefault")
        if title is None or cell is None:
            continue
        courses.append(_parse_course_cell(title.get_text(), cell))
    return courses

def parse_course_detail(page: str) -> dict[str, Any]:
    chunks = list(_chunks(page, "nttitle"))
    if not chunks:
        raise BannerScraperException("course detail title not found")
    soup = BeautifulSoup(chunks[0], "html.parser")
    return _parse_course_cell(soup.find(class_="nttitle").get_text(), soup.find("td", class_="ntdefault"))

def _parse_meetings(table: Tag) -> list[dict[str, str]]:
    keys = ("type", "time", "days", "where", "date_range", "schedule_type", "instructor")
    meetings = []
    for row in table.find_all("tr"):
        cells = row.find_all("td", recursive=False)
        if len(cells) != len(keys):
            continue
        values = [_clean(c.get_text(" ")) for c in cells]
        meeting = dict(zip(keys, values, strict=True))
        meeting["instructor"] = _clean(re.sub(r"\(\s*P\s*\)", "", meeting["instructor"])).replace(" ,", ",")
        meetings.append(meeting)
    return meetings

def parse_schedule_listing(page: str) -> list[dict[str, Any]]:
    """Class search results -> one dict per section (seat counts come from the detail page)."""
    sections = []
    for chunk in _chunks(page, "ddtitle"):
        soup = BeautifulSoup(chunk, "html.parser")
        title, cell = soup.find(class_="ddtitle"), soup.find("td", class_="dddefault")
        if title is None or cell is None:
            continue
        parts = _clean(title.get_text()).rsplit(" - ", 3)
        if len(parts) != 4:
            log.warning("unrecognised section title %r", title.get_text())
            continue
        course_title, crn, code, section_no = parts

        cell = copy.copy(cell)
        table = cell.find("table")
        meetings = _parse_meetings(table.extract()) if table else []

        section: dict[str, Any] = {
            "name": code,
            "course_title": course_title,
            "section": section_no,
            "crn": int(crn),
            "meetings": meetings,
            "levels": [],
            "attributes": [],
            "registration_dates": "",
            "campus": "",
            "schedule_type": "",
            "instruction_method": "",
            "credit_hours": None,
        }
        for line in _lines(cell):
            label, sep, value = line.partition(":")
            value = value.strip()
            if sep and label == "Registration Dates":
                section["registration_dates"] = value
            elif sep and label == "Levels":
                section["levels"] = _split_list(value)
            elif sep and label == "Attributes":
                section["attributes"] = _split_list(value)
            elif line.endswith(" Campus"):
                section["campus"] = line.removesuffix(" Campus")
            elif line.endswith(" Schedule Type"):
                section["schedule_type"] = line.removesuffix(" Schedule Type")
            elif line.endswith(" Instructional Method"):
                section["instruction_method"] = line.removesuffix(" Instructional Method")
            elif m := SECTION_CREDITS.match(line):
                section["credit_hours"] = float(m[2] or m[1])
        sections.append(section)
    return sections

def parse_section_detail(page: str) -> dict[str, Any]:
    """Seat / waitlist counts plus the requirement blocks for one CRN."""
    soup = BeautifulSoup(page, "html.parser")
    out: dict[str, Any] = {}
    seats = soup.find("table", attrs={"summary": re.compile("seating numbers", re.I)})
    if seats is not None:
        prefixes = {"Seats": "", "Waitlist Seats": "waitlist_"}
        for row in seats.find_all("tr"):
            label, cells = row.find("th"), row.find_all("td", class_="dddefault")
            prefix = prefixes.get(_clean(label.get_text()) if label else "")
            if prefix is None or len(cells) != 3:
                continue
            for key, cell in zip(("capacity", "enrolled", "remaining"), cells, strict=True):
                text = _clean(cell.get_text())
                out[prefix + key] = int(text) if re.fullmatch(r"-?\d+", text) else None

    cell = soup.find("td", class_="dddefault")
    if cell is not None:
        out.update(_requirements(_labeled_blocks(cell)[1]))
    return out

# --------------------------------------------------------------------------
# Scraper
# --------------------------------------------------------------------------

class _Throttle:
    """Spaces requests at least `interval` seconds apart across all worker threads."""

    def __init__(self, interval: float) -> None:
        self.interval = interval
        self._lock = threading.Lock()
        self._next = 0.0

    def wait(self) -> None:
        with self._lock:
            now = time.monotonic()
            delay = self._next - now
            self._next = max(now, self._next) + self.interval
        if delay > 0:
            time.sleep(delay)

def _banner_ssl_context() -> ssl.SSLContext:
    """ssb.iit.edu only offers legacy cipher suites that OpenSSL 3's default security
    level refuses (the handshake is reset). Lower the level; certificates are still verified."""
    ctx = ssl.create_default_context()
    ctx.set_ciphers("DEFAULT:@SECLEVEL=1")
    return ctx

class BannerScraper:
    def __init__(
        self,
        *,
        workers: int = 4,
        min_interval: float = 0.2,
        retries: int = 3,
        timeout: float = 90.0,
        client: httpx.Client | None = None,
    ) -> None:
        self.workers = workers
        self.retries = retries
        self._throttle = _Throttle(min_interval)
        self._client = client or httpx.Client(
            timeout=timeout,
            headers={"User-Agent": USER_AGENT},
            follow_redirects=True,
            verify=_banner_ssl_context(),
        )

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> BannerScraper:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    # -- transport ---------------------------------------------------------

    def _fetch(self, method: str, url: str, **kwargs: Any) -> str:
        error = ""
        for attempt in range(self.retries + 1):
            self._throttle.wait()
            try:
                response = self._client.request(method, url, **kwargs)
                if response.status_code < 500:
                    response.raise_for_status()
                    return response.text
                error = f"HTTP {response.status_code}"
            except httpx.HTTPStatusError as exc:
                raise BannerScraperException(f"{method} {url}: {exc}") from exc
            except httpx.TransportError as exc:
                error = repr(exc)
            if attempt < self.retries:
                time.sleep(2**attempt)
        raise BannerScraperException(f"{method} {url} failed after {self.retries + 1} tries: {error}")

    def _map(self, fn: Callable[[Any], Any], items: Iterable[Any]) -> list[Any]:
        with ThreadPoolExecutor(max_workers=self.workers) as pool:
            return list(pool.map(fn, items))

    # -- pages -------------------------------------------------------------

    def terms(self) -> list[dict[str, Any]]:
        return parse_terms(self._fetch("GET", COURSE_SCHEDULE_URL))

    def open_terms(self) -> list[dict[str, Any]]:
        """Terms the schedule lists without '(View only)', i.e. open for registration."""
        return [t for t in self.terms() if not t["view_only"]]

    def schedule_subjects(self, term: str) -> list[str]:
        data = {"p_calling_proc": "bwckschd.p_disp_dyn_sched", "p_term": term}
        return parse_subjects(self._fetch("POST", SCHEDULE_TERM_URL, data=data))

    def catalog_subjects(self, term: str) -> list[str]:
        data = {"call_proc_in": "bwckctlg.p_disp_dyn_ctlg", "cat_term_in": term}
        return parse_subjects(self._fetch("POST", CATALOG_TERM_URL, data=data))

    def catalog_listing(self, term: str, subject: str) -> list[dict[str, Any]]:
        # Banner's multi-selects need a leading "dummy" value; "%" means "any".
        data = {
            "term_in": term,
            "call_proc_in": "bwckctlg.p_disp_dyn_ctlg",
            "sel_subj": ["dummy", subject],
            **{k: ["dummy", "%"] for k in ("sel_levl", "sel_schd", "sel_coll", "sel_divs", "sel_dept", "sel_attr")},
            "sel_crse_strt": "", "sel_crse_end": "", "sel_title": "",
            "sel_from_cred": "", "sel_to_cred": "",
        }
        return parse_catalog_listing(self._fetch("POST", CATALOG_SEARCH_URL, data=data))

    def schedule_listing(self, term: str, subject: str) -> list[dict[str, Any]]:
        data = {
            "term_in": term,
            "sel_subj": ["dummy", subject],
            "sel_day": "dummy",
            "sel_sess": "dummy",
            **{k: ["dummy", "%"] for k in ("sel_schd", "sel_insm", "sel_camp", "sel_levl", "sel_instr", "sel_ptrm", "sel_attr")},
            "sel_crse": "", "sel_title": "", "sel_from_cred": "", "sel_to_cred": "",
            "begin_hh": "0", "begin_mi": "0", "begin_ap": "a",
            "end_hh": "0", "end_mi": "0", "end_ap": "a",
        }
        return parse_schedule_listing(self._fetch("POST", SCHEDULE_SEARCH_URL, data=data))

    def section_detail(self, term: str, crn: int) -> dict[str, Any]:
        page = self._fetch("GET", SECTION_DETAIL_URL, params={"term_in": term, "crn_in": crn})
        return parse_section_detail(page)

    def course_detail(self, term: str, subject: str, number: str) -> dict[str, Any]:
        params = {"cat_term_in": term, "subj_code_in": subject, "crse_numb_in": number}
        return parse_course_detail(self._fetch("GET", COURSE_DETAIL_URL, params=params))

    # -- whole term --------------------------------------------------------

    def _safe(self, what: str, fn: Callable[[], dict[str, Any]]) -> dict[str, Any]:
        """Detail pages are best-effort: one bad CRN must not sink the weekly run."""
        try:
            return fn()
        except BannerScraperException as exc:
            log.warning("skipping %s: %s", what, exc)
            return {}

    def scrape_term(self, term: dict[str, Any], subjects: list[str] | None = None) -> CatalogSnapshot:
        code = term["code"]
        scraped_at = datetime.now(UTC)
        cat_subjects = self.catalog_subjects(code)
        sched_subjects = self.schedule_subjects(code)
        if subjects:
            wanted = {s.upper() for s in subjects}
            cat_subjects = [s for s in cat_subjects if s in wanted]
            sched_subjects = [s for s in sched_subjects if s in wanted]
        log.info("%s: %d catalog / %d schedule subjects", term["name"], len(cat_subjects), len(sched_subjects))

        # Listing failures raise: a missing subject would make the loader drop its sections.
        catalog = {
            c["name"]: c
            for listing in self._map(lambda s: self.catalog_listing(code, s), cat_subjects)
            for c in listing
        }
        sections = [
            s for listing in self._map(lambda s: self.schedule_listing(code, s), sched_subjects) for s in listing
        ]
        log.info("%s: %d catalog courses, %d sections", term["name"], len(catalog), len(sections))

        details = self._map(
            lambda s: self._safe(f"CRN {s['crn']}", lambda: self.section_detail(code, s["crn"])), sections
        )
        by_course: dict[str, list[dict[str, Any]]] = {}
        for section, detail in zip(sections, details, strict=True):
            by_course.setdefault(section["name"], []).append(section | detail)

        # Catalog-only courses still need prerequisites for the requirement graph.
        unoffered = [c for name, c in catalog.items() if name not in by_course]
        course_details = self._map(
            lambda c: self._safe(c["name"], lambda: self.course_detail(code, c["subject"], c["number"])), unoffered
        )
        for course, detail in zip(unoffered, course_details, strict=True):
            for key in ("prerequisites", "restrictions"):
                if detail.get(key):
                    course[key] = detail[key]

        courses = [
            self._build_course(term, catalog.get(name), by_course.get(name, []))
            for name in sorted(catalog.keys() | by_course.keys())
        ]
        return CatalogSnapshot.model_validate(
            {"term": {"code": code, "name": term["name"]}, "scraped_at": scraped_at, "courses": courses}
        )

    @staticmethod
    def _build_course(
        term: dict[str, Any], catalog: dict[str, Any] | None, sections: list[dict[str, Any]]
    ) -> dict[str, Any]:
        if catalog is None:  # scheduled but missing from this term's catalog
            first = sections[0]
            subject, _, number = first["name"].partition(" ")
            catalog = {
                "name": first["name"], "subject": subject, "number": number,
                "title": first["course_title"], "credit_hours": first["credit_hours"],
                "levels": first["levels"], "attributes": first["attributes"],
            }
        sections = sorted(sections, key=lambda s: (s["section"], s["crn"]))
        section_fields = {
            "section", "crn", "levels", "xlist_data", "registration_dates", "meetings", "credit_hours",
            "capacity", "enrolled", "remaining", "waitlist_capacity", "waitlist_enrolled",
            "waitlist_remaining", "campus", "schedule_type", "instruction_method", "prerequisites",
            "restrictions", "mutual_exclusion",
        }
        built = []
        for s in sections:
            row = {k: v for k, v in s.items() if k in section_fields}
            row["special_title"] = s["course_title"] if s["course_title"] != catalog["title"] else ""
            built.append(row)

        exam = next(
            (m for s in built for m in s["meetings"] if "exam" in m["type"].lower()), None
        )
        prereq = next((s["prerequisites"] for s in built if s.get("prerequisites")), "")
        course_fields = {
            "name", "subject", "number", "title", "attributes", "description", "credit_hours",
            "credit_hours_max", "lecture_hours", "lab_hours", "other_hours", "levels",
            "schedule_types", "department",
        }
        return {
            **{k: v for k, v in catalog.items() if k in course_fields},
            "restrictions": catalog.get("restrictions") or next(
                (s["restrictions"] for s in built if s.get("restrictions")), ""
            ),
            "semester": {
                "name": term["name"],
                "code": term["code"],
                "exam_time": exam["time"] if exam else "",
                "exam_date": exam["date_range"] if exam else "",
                "sections": built,
                "is_offered": bool(built),
                "prerequisites": prereq or catalog.get("prerequisites", ""),
            },
        }

# --------------------------------------------------------------------------
# CLI / cron entry point
# --------------------------------------------------------------------------

def write_snapshot(snapshot: CatalogSnapshot, out_dir: Path) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{snapshot.term.code}.json"
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(snapshot.model_dump(mode="json"), indent=2, ensure_ascii=False), encoding="utf-8")
    tmp.replace(path)  # atomic: the loader never reads a half-written file
    return path

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--terms", nargs="+", help="term codes, e.g. 202710 (default: all terms open for registration)")
    parser.add_argument("--subjects", nargs="+", help="limit to these subject codes (default: all)")
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT_DIR, help="output directory")
    parser.add_argument("--workers", type=int, default=4, help="concurrent requests")
    parser.add_argument("--min-interval", type=float, default=0.2, help="seconds between requests")
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    logging.getLogger("httpx").setLevel(logging.INFO if args.verbose else logging.WARNING)
    with BannerScraper(workers=args.workers, min_interval=args.min_interval) as scraper:
        known = {t["code"]: t for t in scraper.terms()}
        if args.terms:
            missing = [t for t in args.terms if t not in known]
            if missing:
                parser.error(f"unknown term(s): {', '.join(missing)}")
            terms = [known[t] for t in args.terms]
        else:
            terms = [t for t in known.values() if not t["view_only"]]
        if not terms:
            log.error("no terms to scrape")
            return 1

        for term in terms:
            started = time.monotonic()
            snapshot = scraper.scrape_term(term, args.subjects)
            path = write_snapshot(snapshot, args.out)
            offered = sum(c.semester.is_offered for c in snapshot.courses)
            log.info(
                "%s: wrote %d courses (%d offered) to %s in %.0fs",
                term["name"], len(snapshot.courses), offered, path, time.monotonic() - started,
            )
    return 0

if __name__ == "__main__":
    sys.exit(main())