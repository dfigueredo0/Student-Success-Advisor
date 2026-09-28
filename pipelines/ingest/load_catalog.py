"""
Loads Banner scraper snapshots (data/raw/banner/<term>.json) into Postgres/pgvector.

Idempotent, so the weekly cron can rerun it freely:
  * terms and courses are upserted; when several snapshots are loaded, the newest term
    wins for course-level catalog fields
  * a term's sections are replaced by what the snapshot lists (dropped CRNs disappear)
  * a course is (re)embedded through Ollama only when its content hash changed, so a
    typical week embeds a handful of courses, not the whole catalog

    uv run python pipelines/ingest/load_catalog.py                       # every snapshot
    uv run python pipelines/ingest/load_catalog.py data/raw/banner/202710.json
    uv run python pipelines/ingest/load_catalog.py --no-embed            # tables only
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
from collections.abc import Iterable, Sequence
from pathlib import Path
from typing import Any

import httpx
from sqlalchemy import Connection, create_engine, text

REPO_ROOT = Path(__file__).resolve().parents[2]
try:
    from schemas.catalog import CatalogSnapshot, Course
    from settings import Settings, get_settings
except ModuleNotFoundError:  # run outside `uv run`: fall back to the source tree
    sys.path.insert(0, str(REPO_ROOT / "src"))
    from schemas.catalog import CatalogSnapshot, Course
    from settings import Settings, get_settings

log = logging.getLogger("load_catalog")

DEFAULT_SNAPSHOT_DIR = REPO_ROOT / "data" / "raw" / "banner"
EMBED_BATCH = 32

UPSERT_TERM = text(
    """
    INSERT INTO catalog_term (code, name, scraped_at) VALUES (:code, :name, :scraped_at)
    ON CONFLICT (code) DO UPDATE SET name = EXCLUDED.name, scraped_at = EXCLUDED.scraped_at
    """
)

_INSERT_COURSE = """
    INSERT INTO catalog_course (
        code, subject, number, title, description, credit_hours, credit_hours_max,
        lecture_hours, lab_hours, other_hours, levels, schedule_types, department, attributes,
        prerequisites, prerequisite_courses, restrictions, catalog_term, content_hash, updated_at
    ) VALUES (
        :code, :subject, :number, :title, :description, :credit_hours, :credit_hours_max,
        :lecture_hours, :lab_hours, :other_hours, :levels, :schedule_types, :department, :attributes,
        :prerequisites, :prerequisite_courses, :restrictions, :catalog_term, :content_hash, now()
    )
"""

# Leaves the embedding alone; it is refreshed separately when content_hash moves.
UPSERT_COURSE = text(
    _INSERT_COURSE
    + """
    ON CONFLICT (code) DO UPDATE SET
        subject = EXCLUDED.subject, number = EXCLUDED.number, title = EXCLUDED.title,
        description = EXCLUDED.description, credit_hours = EXCLUDED.credit_hours,
        credit_hours_max = EXCLUDED.credit_hours_max, lecture_hours = EXCLUDED.lecture_hours,
        lab_hours = EXCLUDED.lab_hours, other_hours = EXCLUDED.other_hours,
        levels = EXCLUDED.levels, schedule_types = EXCLUDED.schedule_types,
        department = EXCLUDED.department, attributes = EXCLUDED.attributes,
        prerequisites = EXCLUDED.prerequisites,
        prerequisite_courses = EXCLUDED.prerequisite_courses,
        restrictions = EXCLUDED.restrictions, catalog_term = EXCLUDED.catalog_term,
        content_hash = EXCLUDED.content_hash, updated_at = now()
    WHERE catalog_course.content_hash IS DISTINCT FROM EXCLUDED.content_hash
       OR catalog_course.catalog_term IS DISTINCT FROM EXCLUDED.catalog_term
    """
)

# Older terms only contribute courses the newer catalog no longer lists.
INSERT_COURSE_IF_MISSING = text(_INSERT_COURSE + "ON CONFLICT (code) DO NOTHING")

INSERT_SECTION = text(
    """
    INSERT INTO catalog_section (
        term_code, crn, course_code, section, special_title, levels, cross_list,
        registration_dates, campus, schedule_type, instruction_method, credit_hours,
        capacity, enrolled, remaining, waitlist_capacity, waitlist_enrolled, waitlist_remaining,
        instructors, meetings, prerequisites, restrictions, mutual_exclusion, scraped_at
    ) VALUES (
        :term_code, :crn, :course_code, :section, :special_title, :levels, :cross_list,
        :registration_dates, :campus, :schedule_type, :instruction_method, :credit_hours,
        :capacity, :enrolled, :remaining, :waitlist_capacity, :waitlist_enrolled,
        :waitlist_remaining, :instructors, CAST(:meetings AS jsonb), :prerequisites,
        :restrictions, :mutual_exclusion, :scraped_at
    )
    """
)

STALE_EMBEDDINGS = text(
    """
    SELECT code, content_hash FROM catalog_course
    WHERE embedded_hash IS DISTINCT FROM content_hash
       OR embedding_model IS DISTINCT FROM :model
    ORDER BY code
    """
)

SET_EMBEDDING = text(
    """
    UPDATE catalog_course
    SET embedding = CAST(:embedding AS vector), embedding_model = :model, embedded_hash = :hash
    WHERE code = :code
    """
)

def _course_row(course: Course, term_code: str) -> dict[str, Any]:
    return {
        "code": course.name,
        "subject": course.subject,
        "number": course.number,
        "title": course.title,
        "description": course.description,
        "credit_hours": course.credit_hours,
        "credit_hours_max": course.credit_hours_max,
        "lecture_hours": course.lecture_hours,
        "lab_hours": course.lab_hours,
        "other_hours": course.other_hours,
        "levels": course.levels,
        "schedule_types": course.schedule_types,
        "department": course.department,
        "attributes": course.attributes,
        "prerequisites": course.semester.prerequisites,
        "prerequisite_courses": course.prerequisite_courses,
        "restrictions": course.restrictions,
        "catalog_term": term_code,
        "content_hash": course.content_hash(),
    }

def _section_rows(snapshot: CatalogSnapshot) -> list[dict[str, Any]]:
    rows = []
    for course in snapshot.courses:
        for s in course.semester.sections:
            rows.append({
                "term_code": snapshot.term.code,
                "crn": s.crn,
                "course_code": course.name,
                "section": s.section,
                "special_title": s.special_title,
                "levels": s.levels,
                "cross_list": s.xlist_data,
                "registration_dates": s.registration_dates,
                "campus": s.campus,
                "schedule_type": s.schedule_type,
                "instruction_method": s.instruction_method,
                "credit_hours": s.credit_hours,
                "capacity": s.capacity,
                "enrolled": s.enrolled,
                "remaining": s.remaining,
                "waitlist_capacity": s.waitlist_capacity,
                "waitlist_enrolled": s.waitlist_enrolled,
                "waitlist_remaining": s.waitlist_remaining,
                "instructors": s.instructors,
                "meetings": json.dumps([m.model_dump() for m in s.meetings]),
                "prerequisites": s.prerequisites,
                "restrictions": s.restrictions,
                "mutual_exclusion": s.mutual_exclusion,
                "scraped_at": snapshot.scraped_at,
            })
    return rows

def load_snapshot(conn: Connection, snapshot: CatalogSnapshot, *, newest_term: str) -> None:
    """Upsert one term. Course rows only take this term's catalog data if no newer
    snapshot is loaded in the same run (otherwise that term is the source of truth)."""
    term = snapshot.term
    conn.execute(UPSERT_TERM, {"code": term.code, "name": term.name, "scraped_at": snapshot.scraped_at})

    rows = [_course_row(c, term.code) for c in snapshot.courses]
    if rows:
        conn.execute(UPSERT_COURSE if term.code == newest_term else INSERT_COURSE_IF_MISSING, rows)

    conn.execute(text("DELETE FROM catalog_section WHERE term_code = :t"), {"t": term.code})
    sections = _section_rows(snapshot)
    if sections:
        conn.execute(INSERT_SECTION, sections)
    log.info("%s: %d courses, %d sections", term.name, len(rows), len(sections))

# --------------------------------------------------------------------------
# Embeddings (Ollama)
# --------------------------------------------------------------------------

class OllamaEmbedder:
    def __init__(self, host: str, model: str, timeout: float = 300.0) -> None:
        self.model = model
        self._client = httpx.Client(base_url=host, timeout=timeout)

    def ensure_model(self) -> None:
        """Pull the embedding model on first use; the compose stack only pulls the chat model."""
        tags = self._client.get("/api/tags").raise_for_status().json()
        names = {m["name"] for m in tags.get("models", [])}
        if self.model not in names and f"{self.model}:latest" not in names:
            log.info("pulling embedding model %s", self.model)
            self._client.post("/api/pull", json={"model": self.model, "stream": False}).raise_for_status()

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        response = self._client.post("/api/embed", json={"model": self.model, "input": list(texts)})
        return response.raise_for_status().json()["embeddings"]

    def close(self) -> None:
        self._client.close()

def _batched(items: Sequence[Any], size: int) -> Iterable[Sequence[Any]]:
    for i in range(0, len(items), size):
        yield items[i : i + size]

def refresh_embeddings(conn: Connection, courses: dict[str, Course], embedder: OllamaEmbedder) -> int:
    # Only embed rows whose stored content came from the snapshots in hand; anything else
    # (e.g. a newer term loaded in an earlier run) is left for the run that has its text.
    stale = [
        code
        for code, content_hash in conn.execute(STALE_EMBEDDINGS, {"model": embedder.model})
        if code in courses and courses[code].content_hash() == content_hash
    ]
    if not stale:
        return 0
    embedder.ensure_model()
    for batch in _batched(stale, EMBED_BATCH):
        vectors = embedder.embed([courses[code].embedding_text() for code in batch])
        conn.execute(
            SET_EMBEDDING,
            [
                {
                    "code": code,
                    "embedding": "[" + ",".join(f"{x:.7g}" for x in vector) + "]",
                    "model": embedder.model,
                    "hash": courses[code].content_hash(),
                }
                for code, vector in zip(batch, vectors, strict=True)
            ],
        )
        conn.commit()  # keep finished batches if a later one fails
    return len(stale)

# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------

def run(paths: list[Path], *, embed: bool, settings: Settings) -> None:
    snapshots = sorted(
        (CatalogSnapshot.model_validate_json(p.read_text(encoding="utf-8")) for p in paths),
        key=lambda s: s.term.code,
    )
    if not snapshots:
        raise SystemExit("no snapshots to load")
    newest = snapshots[-1].term.code

    # The newest snapshot mentioning a course is the one its row was built from.
    courses: dict[str, Course] = {c.name: c for s in snapshots for c in s.courses}

    engine = create_engine(settings.database_url)
    try:
        with engine.begin() as conn:
            for snapshot in snapshots:
                load_snapshot(conn, snapshot, newest_term=newest)
        if embed:
            embedder = OllamaEmbedder(settings.ollama_host, settings.embedding_model)
            try:
                with engine.connect() as conn:
                    count = refresh_embeddings(conn, courses, embedder)
                log.info("embedded %d courses with %s", count, embedder.model)
            finally:
                embedder.close()
    finally:
        engine.dispose()

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("paths", nargs="*", type=Path, help=f"snapshot files (default: {DEFAULT_SNAPSHOT_DIR}/*.json)")
    parser.add_argument("--no-embed", action="store_true", help="skip the Ollama embedding step")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)
    paths = args.paths or sorted(DEFAULT_SNAPSHOT_DIR.glob("*.json"))
    run(paths, embed=not args.no_embed, settings=get_settings())
    return 0

if __name__ == "__main__":
    sys.exit(main())
