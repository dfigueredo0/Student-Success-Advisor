"""
Pulls IIT's undergraduate degree requirements from the public catalog (catalog.iit.edu).

Companion to illinoistech_banner_scraper.py: that one scrapes the course catalog, this one
scrapes what each program requires. It reads the degree-programs index, follows every program
link, parses the requirements table on each page and writes one JSON file per program to
data/raw/degree_requirements/<slug>.json (plus index.json). Every file is validated against
`schemas.degree_requirements.ProgramRequirements` before it is written.

Requirement rows are either one specific course (with its "or" alternatives) or a rule such as
"Select 12 hours of HUM/SSCI at the 300-level or above". Rules keep their original text; the
parsed `hints` (min_level, subjects, ...) are best-effort. Anything the parser did not
understand is listed in the program's `needs_review`, and `--save-html` keeps the raw pages so a
bad parse can be inspected or re-run offline.

    uv run --group ingest python pipelines/ingest/degree_requirements.py
    uv run --group ingest python pipelines/ingest/degree_requirements.py --programs computer-science --save-html

Run it every term (catalog years change), e.g. 1st of each month:
    0 3 1 * *  cd /srv/student-success-advisor && make ingest-requirements >> logs/ingest.log 2>&1
"""

from __future__ import annotations

import argparse
import json
import logging
import re
import sys
import threading
import time
from collections.abc import Callable, Iterable
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urldefrag, urljoin

import httpx
from bs4 import BeautifulSoup, Tag

from schemas.degree_requirements import ProgramRequirements

ROOT = Path(__file__).resolve().parents[2]

log = logging.getLogger("degree_requirements")

BASE = "https://catalog.iit.edu"
INDEX_URL = f"{BASE}/undergraduate/undergraduate-education/undergraduate-degree-programs/"
USER_AGENT = (
    "StudentSuccessAdvisor-CatalogBot/1.0 (+https://github.com/dfigueredo0/Student-Success-Advisor)"
)
DEFAULT_OUT_DIR = ROOT / "data" / "raw" / "degree_requirements"

CODE = re.compile(r"\b([A-Z]{2,4})\s?(\d{3})\b")
HOURS = re.compile(r"^\d+(?:\s*[-–]\s*\d+)?$")
LEVEL = re.compile(r"\b([1-4])00(?:\s*[-–]?\s*level)?\s*(?:\+|or\s+(?:above|higher|more))", re.I)
FOOTNOTE = re.compile(r"footnotes?\s*(\d+(?:\s*(?:,|and|&)\s*\d+)*)", re.I)
NUMBER_WORDS = {
    w: str(i)
    for i, w in enumerate(
        "zero one two three four five six seven eight nine ten eleven twelve".split()
    )
} | {"twenty": "20"}
SELECT = re.compile(
    r"\b(?:select|choose)\s+((?:up to|a minimum of|minimum of|at least|a maximum of|no more than)\s+)?(\d+|[a-z]+)(?:\s*(?:-|–|to)\s*(\d+|[a-z]+))?\s+"
    r"(credit hours?|credits?|related courses|courses?|of\b)",
    re.I,
)
SELECT_HOURS = re.compile(r"\b(\d+)\s+(?:credit\s+)?hours?\b", re.I)


class RequirementsScraperException(Exception):
    """A page could not be fetched or no longer looks like a catalog program page."""


class NotAProgramPage(RequirementsScraperException):
    """The page has no requirements table (a college or department landing page, say)."""


# --------------------------------------------------------------------------
# HTML parsing
# --------------------------------------------------------------------------


def _clean(text: str) -> str:
    return re.sub(r"\s+", " ", text.replace("\xa0", " ")).strip()


def program_links(index_html: str) -> list[str]:
    """Program pages linked from the degree-programs index (deduplicated, in page order)."""
    soup = BeautifulSoup(index_html, "html.parser")
    root = soup.select_one("#textcontainer, #content, main") or soup
    seen: dict[str, None] = {}
    for a in root.find_all("a", href=True):
        href = urldefrag(urljoin(INDEX_URL, a["href"]))[0]
        if not href.startswith(f"{BASE}/undergraduate/") or href.rstrip("/") == INDEX_URL.rstrip(
            "/"
        ):
            continue
        if re.search(r"\.(pdf|docx?|xlsx?)$", href, re.I):
            continue
        seen[href if href.endswith("/") else href + "/"] = None
    return list(seen)


def hours_of(text: str) -> float | int | None:
    text = _clean(text).strip("()").strip()  # section headers show "(36)"
    if not text or not HOURS.match(text):
        return None
    return int(text) if text.isdigit() else None  # ranges ("3-4") stay None -> reviewed


HOURS_RANGE = re.compile(r"(\d+)\s*(?:-|–|or|to)\s*(\d+)", re.I)
INDENT_PX = re.compile(r"margin-left:\s*(\d+)px", re.I)


def hours_pair(text: str) -> tuple[int | None, int | None]:
    """ "12" -> (12, None); "13 OR 14" or "3-4" -> (13, 14); anything else -> (None, None)."""
    text = _clean(text).strip("()").strip()
    if m := HOURS_RANGE.fullmatch(text):
        return int(m.group(1)), int(m.group(2))
    return hours_of(text), None


def row_indent(tr: Tag) -> int:
    """Nesting level of a row: the catalog indents rows with <div class="blockindent"> 20px."""
    for el in tr.select(".blockindent, .commentindent"):
        if m := INDENT_PX.search(el.get("style") or ""):
            return int(m.group(1)) // 20
    return 0


def rule_hints(text: str) -> dict:
    hints: dict = {}
    if m := LEVEL.search(text):
        hints["min_level"] = int(m.group(1)) * 100
    subjects = sorted({s for s, _ in CODE.findall(text)})
    bare = re.findall(
        r"\b([A-Z]{2,4})(?=\s*(?:/|,|or|and)\s*[A-Z]{2,4}\b|\s+(?:courses?|electives?|credit))",
        text,
    )
    subjects = sorted(set(subjects) | set(bare))
    if subjects:
        hints["subjects"] = subjects
    if re.search(r"core curriculum", text, re.I):
        hints["core_curriculum"] = True
        if m := re.search(
            r"(?i:core curriculum),?\s*(?i:sections?)\s+([A-Z](?:\s*(?:,|and|&)\s*[A-Z])*)\b", text
        ):
            hints["core_sections"] = re.findall(r"[A-Z]", m.group(1))
    if m := SELECT.search(text):
        low = NUMBER_WORDS.get(m.group(2).lower(), m.group(2))
        high = NUMBER_WORDS.get((m.group(3) or "").lower(), m.group(3))
        if str(low).isdigit():
            unit = "hours" if m.group(4).lower().startswith("credit") else "courses"
            qualifier = (m.group(1) or "").strip().lower()
            if qualifier.startswith(("up to", "a maximum", "no more")):
                hints["choose"] = {"min": None, "max": int(low), "unit": unit}
            else:
                hints["choose"] = {
                    "min": int(low),
                    "max": int(high) if str(high).isdigit() else None,
                    "unit": unit,
                }
    if re.search(
        r"\b(?:of\s+)?the\s+(?:following|two options)\b|\bfollowing\b|\b(?:from|of)\s+the\s+below\b",
        text,
        re.I,
    ):
        hints["options_follow"] = True
    if m := re.search(r"(?:excluding|except|not including)\s+([^.;]+)", text, re.I):
        codes = [f"{s} {n}" for s, n in CODE.findall(m.group(1))]
        if codes:
            hints["excluding"] = codes
    return hints


def footnotes_in(text: str) -> list[int]:
    nums: list[int] = []
    for m in FOOTNOTE.finditer(text):
        nums += [int(n) for n in re.findall(r"\d+", m.group(1))]
    return nums


def _link_children(items: list[dict]) -> None:
    """Say which following rows belong to a rule ("Select one of the following:", a label).

    children = how many of the next items are its options: those indented under it, or, when the
    page does not indent, the courses right after a rule that says "of the following".
    """
    for i, item in enumerate(items):
        if item["kind"] != "rule":
            continue
        rest = items[i + 1 :]
        n = 0
        while n < len(rest) and rest[n]["indent"] > item["indent"]:
            n += 1
        if n:
            item["children"], item["children_basis"] = n, "indent"
        elif item["hints"].get("options_follow"):
            while n < len(rest) and rest[n]["kind"] == "course":
                n += 1
            if n:
                item["children"], item["children_basis"] = n, "following_courses"


def parse_table(table: Tag, review: list[str]) -> tuple[list[dict], int | None]:
    """Rows -> sections. A section starts at each header row (tr.areaheader or a bold full-width row)."""
    sections: list[dict] = []
    table_total: int | None = None

    def current() -> dict:
        if not sections:
            sections.append({"title": "", "hours": None, "items": [], "footnotes": []})
        return sections[-1]

    for tr in table.find_all("tr"):
        classes = set(tr.get("class") or [])
        cells = tr.find_all("td")
        if not cells:
            continue
        # footnote markers sit in <sup> (or a marker-like link); lift them out of the text
        marks: list[int] = []
        for marker in tr.select("sup, a.sup, span.sup, [class*=footnote]"):
            marks += [int(n) for n in re.findall(r"\d+", marker.get_text(" "))]
            marker.decompose()
        text = _clean(tr.get_text(" "))
        if not text:
            continue
        if "listsum" in classes or re.match(r"^total\s+(credit\s+)?hours", text, re.I):
            if (t := re.search(r"(\d+)\s*$", text)) and table_total is None:
                table_total = int(t.group(1))
            continue
        if "areaheader" in classes or (len(cells) == 1 and cells[0].get("colspan")):
            hours, hours_max = hours_pair(cells[-1].get_text()) if len(cells) > 1 else (None, None)
            title = _clean(cells[0].get_text(" "))
            if hours is None and (m := re.search(r"\((\d+)\)\s*$", title)):
                hours, title = int(m.group(1)), title[: m.start()].strip()
            sections.append(
                {
                    "title": title,
                    "hours": hours,
                    "hours_max": hours_max,
                    "items": [],
                    "footnotes": list(dict.fromkeys([*marks, *footnotes_in(title)])),
                }
            )
            continue

        codecol = tr.select_one("td.codecol")
        code_text = _clean(codecol.get_text(" ")) if codecol else _clean(cells[0].get_text(" "))
        hours_cell = tr.select_one("td.hourscol") or (cells[-1] if len(cells) > 1 else None)
        hours, hours_max = hours_pair(hours_cell.get_text()) if hours_cell else (None, None)
        indent = row_indent(tr)
        title_cell = cells[1] if len(cells) > 2 else None
        title = _clean(title_cell.get_text(" ")) if title_cell else ""
        is_or = "orclass" in classes or bool(re.match(r"^or\b", code_text, re.I))
        # a course row starts with its code ("MATH 332", "or MATH 333"); prose that merely
        # mentions codes ("Students wishing to take BME 200 ...") is a rule
        match = (
            CODE.search(code_text)
            if re.match(r"^(?:or\s+)?[A-Z]{2,4}\s?\d{3}\b", code_text)
            else None
        )

        section = current()
        if match and (len(cells) > 1) and not re.search(r"\bselect\b", text, re.I):
            code = f"{match.group(1)} {match.group(2)}"
            if is_or and section["items"] and section["items"][-1]["kind"] == "course":
                section["items"][-1]["alternatives"].append({"code": code, "title": title})
            else:
                if is_or:
                    review.append(f"'or' row without a course above it: {text}")
                codes = [f"{a} {b}" for a, b in CODE.findall(code_text)]
                together = []
                joined = len(codes) > 1 and re.fullmatch(
                    r"[A-Z]{2,4}\s?\d{3}(?:\s*(?:&|and)\s*[A-Z]{2,4}\s?\d{3})+", code_text
                )
                if joined:
                    # "CS 115 & CS 116" with "Title one and Title two": taken together
                    parts = title.split(" and ")
                    titles = (
                        parts if len(parts) == len(codes) else [title] + [""] * (len(codes) - 1)
                    )
                    title = titles[0]
                    together = [{"code": c, "title": t} for c, t in zip(codes[1:], titles[1:])]
                elif len(codes) > 1:
                    review.append(f"several codes in one row, check: {text}")
                section["items"].append(
                    {
                        "kind": "course",
                        "code": code,
                        "title": title,
                        "hours": hours,
                        "hours_max": hours_max,
                        "indent": indent,
                        "alternatives": [],
                        "together_with": together,
                        "footnotes": list(dict.fromkeys(marks)),
                    }
                )
            continue

        rule_text = _clean(" ".join(_clean(c.get_text(" ")) for c in cells if c is not hours_cell))
        item = {
            "kind": "rule",
            "text": rule_text,
            "hours": hours,
            "hours_max": hours_max,
            "indent": indent,
            "hints": rule_hints(rule_text),
            "footnotes": list(dict.fromkeys([*marks, *footnotes_in(rule_text)])),
            "children": 0,
        }
        section["items"].append(item)
        if item["hours"] is None and (m := SELECT_HOURS.search(rule_text)):
            item["hours"] = int(m.group(1))
        if rule_text.endswith(":") and not item["hints"]:
            item["hints"] = {"options_follow": True}  # a lead-in to the rows below

    for section in sections:
        _link_children(section["items"])
        for item in section["items"]:
            if item["kind"] != "rule" or item["children"] or item["hints"]:
                continue
            if item["hours"]:
                review.append(f"rule with hours but nothing understood: {item['text']}")
            else:
                review.append(f"unrecognised row kept as text: {item['text']}")
    return sections, table_total


def total_hours(root: Tag) -> int | None:
    text = _clean(root.get_text(" "))
    m = re.search(r"total\s+(?:credit\s+)?hours?\s*[:\-]?\s*(\d+)", text, re.I)
    return int(m.group(1)) if m else None


def _is_block(tag: Tag) -> bool:
    classes = tag.get("class") or []
    return (tag.name == "table" and ("sc_courselist" in classes or "sc_plangrid" in classes)) or (
        tag.name == "dl" and "sc_footnotes" in classes
    )


def _read_notes(block: Tag) -> dict[int, str]:
    notes: dict[int, str] = {}
    for dt in block.find_all("dt"):
        number = re.search(r"\d+", dt.get_text())
        dd = dt.find_next_sibling("dd")
        if number and dd:
            notes[int(number.group())] = _clean(dd.get_text(" "))
    return notes


def notes_after(table: Tag, *, past_plan_grid: bool = False) -> dict[int, str]:
    """The footnote block that directly follows a table: {number: text}.

    Every table has its own block, numbered from 1. Some pages put no block after the table and
    one after the semester grid instead; `past_plan_grid` reaches that one (never crossing
    another requirements table).
    """
    for block in table.find_all_next(_is_block):
        if block.name == "dl":
            return _read_notes(block)
        if "sc_plangrid" in (block.get("class") or []) and past_plan_grid:
            continue
        break
    return {}


def notes_before(table: Tag) -> dict[int, str]:
    """The nearest footnote block above a table, looking back past plan grids only."""
    for block in table.find_all_previous(_is_block):
        if block.name == "dl":
            return _read_notes(block)
        if "sc_plangrid" not in (block.get("class") or []):
            break
    return {}


def parse_program(html: str, url: str = "") -> dict:
    soup = BeautifulSoup(html, "html.parser")
    root = (
        soup.select_one("#requirementstextcontainer, #requirementstext")
        or soup.select_one("#textcontainer, #content")
        or soup
    )
    review: list[str] = []
    h1 = soup.select_one("h1")
    if h1:
        title = _clean(h1.get_text(" "))
    else:
        tag = soup.select_one("title")
        title = _clean(tag.get_text(" ")).split(" < ")[0] if tag else ""
    sections: list[dict] = []
    table_totals: list[int | None] = []
    notes: list[dict] = []
    tables = root.select("table.sc_courselist") or root.find_all("table")
    for n, table in enumerate(tables):
        rows, total_of_table = parse_table(table, review)
        heading = table.find_previous(re.compile(r"^h[2-6]$"))
        group = _clean(heading.get_text(" ")) if heading else ""
        table_notes = notes_after(table)
        borrowed = False
        used = {k for sec in rows for i in sec["items"] for k in i.get("footnotes", [])}
        used |= {k for sec in rows for k in sec.get("footnotes", [])}
        if used - set(table_notes):
            found = notes_after(table, past_plan_grid=True)
            where = "after"
            if not found:
                found, where = notes_before(table), "before"
            if found and not table_notes:
                table_notes, borrowed = found, True
                review.append(
                    f"table {n} footnotes taken from the block {where} it (not beside it)"
                )
        for number, text in table_notes.items():
            notes.append({"table": n, "number": number, "text": text, "borrowed": borrowed})
        for sec in rows:
            sec["table"] = n
            sec["group"] = group
            sec["group_total_hours"] = total_of_table
            for item in sec["items"]:
                if item["kind"] == "rule":
                    found = [
                        rule_hints(table_notes[k]) for k in item["footnotes"] if k in table_notes
                    ]
                    item["footnote_hints"] = {k: v for h in found for k, v in h.items()}
        cited = {k for sec in rows for i in sec["items"] for k in i.get("footnotes", [])}
        cited |= {k for sec in rows for k in sec.get("footnotes", [])}
        if cited - set(table_notes):
            review.append(
                f"table {n} cites footnotes {sorted(cited - set(table_notes))} with no note text"
            )
        sections += rows
        table_totals.append(total_of_table)
    sections = [s for s in sections if s["items"] or s["title"]]

    if not sections:
        review.append("no requirement tables found: page layout may differ, send the saved HTML")
    total = next((t for t in table_totals if t), None) or total_hours(root)
    if total is None:
        review.append("total credit hours not found")
    slug = url.rstrip("/").rsplit("/", 1)[-1] if url else ""
    program_slug = "-".join(url.rstrip("/").split("/")[-2:]) if "/" in url.rstrip("/")[8:] else slug
    return {
        "slug": program_slug,
        "url": url,
        "title": title,
        "total_hours": total,
        "scraped_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "sections": sections,
        "notes": notes,
        "needs_review": review,
    }


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


def slug_of(url: str) -> str:
    return "-".join(url.rstrip("/").split("/")[-2:])


class RequirementsScraper:
    def __init__(
        self,
        *,
        workers: int = 4,
        min_interval: float = 0.2,
        retries: int = 3,
        timeout: float = 60.0,
        client: httpx.Client | None = None,
    ) -> None:
        self.workers = workers
        self.retries = retries
        self._throttle = _Throttle(min_interval)
        self._client = client or httpx.Client(
            timeout=timeout, headers={"User-Agent": USER_AGENT}, follow_redirects=True
        )

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> RequirementsScraper:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def _fetch(self, url: str) -> str:
        error = ""
        for attempt in range(self.retries + 1):
            self._throttle.wait()
            try:
                response = self._client.get(url)
                if response.status_code < 500:
                    response.raise_for_status()
                    return response.text
                error = f"HTTP {response.status_code}"
            except httpx.HTTPStatusError as exc:
                raise RequirementsScraperException(f"GET {url}: {exc}") from exc
            except httpx.TransportError as exc:
                error = repr(exc)
            if attempt < self.retries:
                time.sleep(2**attempt)
        raise RequirementsScraperException(
            f"GET {url} failed after {self.retries + 1} tries: {error}"
        )

    def _map(self, fn: Callable[[Any], Any], items: Iterable[Any]) -> list[Any]:
        with ThreadPoolExecutor(max_workers=self.workers) as pool:
            return list(pool.map(fn, items))

    def program_urls(self) -> list[str]:
        urls = program_links(self._fetch(INDEX_URL))
        if not urls:
            raise RequirementsScraperException(f"no program links found on {INDEX_URL}")
        return urls

    def scrape_program(self, url: str, html_dir: Path | None = None) -> ProgramRequirements:
        page = self._fetch(url)
        if html_dir is not None:
            html_dir.mkdir(parents=True, exist_ok=True)
            (html_dir / f"{slug_of(url)}.html").write_text(page, encoding="utf-8")
        parsed = parse_program(page, url)
        if not parsed["sections"]:
            raise NotAProgramPage(f"no requirements table on {url}")
        return ProgramRequirements.model_validate(parsed)

    def scrape(
        self, urls: list[str], html_dir: Path | None = None
    ) -> tuple[list[ProgramRequirements], list[dict[str, str]], list[dict[str, str]]]:
        """(programs, failed, skipped). Skipped pages simply have no requirements table."""

        def one(url: str) -> ProgramRequirements | dict[str, str]:
            try:
                return self.scrape_program(url, html_dir)
            except NotAProgramPage as exc:
                log.info("skipped (no requirements table): %s", url)
                return {"slug": slug_of(url), "url": url, "skipped": str(exc)}
            except Exception as exc:  # one bad page must not lose the rest of the run
                log.exception("failed: %s", url)
                return {"slug": slug_of(url), "url": url, "error": repr(exc)}

        results = self._map(one, urls)
        return (
            [r for r in results if isinstance(r, ProgramRequirements)],
            [r for r in results if isinstance(r, dict) and "error" in r],
            [r for r in results if isinstance(r, dict) and "skipped" in r],
        )


# --------------------------------------------------------------------------
# CLI / cron entry point
# --------------------------------------------------------------------------


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    tmp.replace(path)  # atomic: readers never see a half-written file


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--programs", nargs="+", help="only URLs containing one of these, e.g. computer-science"
    )
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT_DIR, help="output directory")
    parser.add_argument(
        "--save-html", action="store_true", help="also keep each raw page in <out>/html/"
    )
    parser.add_argument(
        "--html", type=Path, help="parse one saved page, print its JSON, no network"
    )
    parser.add_argument("--workers", type=int, default=4, help="concurrent requests")
    parser.add_argument("--min-interval", type=float, default=0.2, help="seconds between requests")
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    logging.getLogger("httpx").setLevel(logging.INFO if args.verbose else logging.WARNING)

    if args.html:
        program = ProgramRequirements.model_validate(
            parse_program(args.html.read_text(encoding="utf-8"), str(args.html))
        )
        print(program.model_dump_json(indent=2))
        return 0

    started = time.monotonic()
    with RequirementsScraper(workers=args.workers, min_interval=args.min_interval) as scraper:
        urls = scraper.program_urls()
        if args.programs:
            urls = [u for u in urls if any(p in u for p in args.programs)]
        if not urls:
            log.error("no programs to scrape")
            return 1
        programs, failed, skipped = scraper.scrape(
            urls, args.out / "html" if args.save_html else None
        )

    for program in programs:
        # fields equal to their schema default are left out; schemas.degree_requirements has them
        write_json(
            args.out / f"{program.slug}.json",
            program.model_dump(mode="json", exclude_defaults=True),
        )
    write_json(
        args.out / "index.json",
        {
            "scraped_at": datetime.now(UTC).isoformat(timespec="seconds"),
            "programs": [
                {
                    "slug": p.slug,
                    "url": p.url,
                    "title": p.title,
                    "total_hours": p.total_hours,
                    "requirements": sum(len(s.items) for s in p.sections),
                    "needs_review": len(p.needs_review),
                }
                for p in programs
            ],
            "failed": failed,
            "skipped": skipped,
        },
    )
    review = sum(bool(p.needs_review) for p in programs)
    log.info(
        "wrote %d programs to %s (%d need review, %d failed, %d skipped) in %.0fs",
        len(programs),
        args.out,
        review,
        len(failed),
        len(skipped),
        time.monotonic() - started,
    )
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
