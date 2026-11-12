"""
Loads O*NET occupations and their software skills (data/onet/*.csv) into Postgres.

Only skills O*NET flags Hot Technology or In Demand are kept: those are the ones employers name
in job postings, and they are the vocabulary the Career agent reads resumes with
(domain.skills). Idempotent: both tables are replaced in one transaction.

The CSVs come verbatim from https://www.onetcenter.org/database.html (see data/onet/README.md).
For a new release, download the two files again, bump tools.career.onet.ONET_RELEASE, and
review the alias lists in domain/skills.py against the new names.

    uv run python pipelines/ingest/load_onet.py
"""
from __future__ import annotations

import argparse
import csv
import logging
import sys
from pathlib import Path
from typing import Any

from sqlalchemy import create_engine, text

REPO_ROOT = Path(__file__).resolve().parents[2]
try:
    from settings import get_settings
except ModuleNotFoundError:  # run outside `uv run`: fall back to the source tree
    sys.path.insert(0, str(REPO_ROOT / "src"))
    from settings import get_settings

log = logging.getLogger("load_onet")

DEFAULT_DIR = REPO_ROOT / "data" / "onet"
SKILL_COLUMNS = {"O*NET-SOC Code", "Title", "Workplace Example", "Hot Technology", "In Demand"}
ZONE_COLUMNS = {"O*NET-SOC Code", "Job Zone"}


def _read(path: Path, columns: set[str]) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        # O*NET renames columns between releases ("Example" became "Workplace Example" in 30.3).
        if missing := columns - set(reader.fieldnames or []):
            raise ValueError(f"{path.name} has no column {sorted(missing)}; got {reader.fieldnames}")
        return list(reader)


def read_rows(skills_csv: Path, zones_csv: Path) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """(occupations, skills): flagged skill rows and the occupations they belong to."""
    zones = {r["O*NET-SOC Code"]: int(r["Job Zone"]) for r in _read(zones_csv, ZONE_COLUMNS)}
    occupations: dict[str, dict[str, Any]] = {}
    skills = []
    for r in _read(skills_csv, SKILL_COLUMNS):
        if "Y" not in (r["Hot Technology"], r["In Demand"]):
            continue
        code = r["O*NET-SOC Code"]
        occupations.setdefault(code, {"code": code, "title": r["Title"], "job_zone": zones.get(code)})
        skills.append({"soc_code": code, "example": r["Workplace Example"], "in_demand": r["In Demand"] == "Y"})
    return list(occupations.values()), skills


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("dir", nargs="?", type=Path, default=DEFAULT_DIR, help="folder holding the two CSVs")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

    occupations, skills = read_rows(args.dir / "software_skills.csv", args.dir / "job_zones.csv")
    engine = create_engine(get_settings().database_url)
    try:
        with engine.begin() as conn:
            conn.execute(text("DELETE FROM onet_occupation"))  # skills go with it (ON DELETE CASCADE)
            conn.execute(
                text("INSERT INTO onet_occupation (code, title, job_zone) VALUES (:code, :title, :job_zone)"),
                occupations,
            )
            conn.execute(
                text(
                    "INSERT INTO onet_software_skill (soc_code, example, in_demand) "
                    "VALUES (:soc_code, :example, :in_demand)"
                ),
                skills,
            )
    finally:
        engine.dispose()
    log.info(
        "%d occupations, %d skill rows (%d in demand)",
        len(occupations), len(skills), sum(s["in_demand"] for s in skills),
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
