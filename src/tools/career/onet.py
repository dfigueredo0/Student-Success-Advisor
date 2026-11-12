"""O*NET occupation data for the Career agent: the skill vocabulary resumes are read with,
and match_occupations, which ranks occupations by the skills a student has.

Loaded by pipelines/ingest/load_onet.py (`make ingest-onet`) from data/onet/*.csv. O*NET is
published by the U.S. Department of Labor (USDOL/ETA) under CC BY 4.0.
"""

from datetime import date
from functools import lru_cache
from typing import Any

from sqlalchemy import Connection, text
from sqlalchemy.exc import ProgrammingError

from domain.skills import Vocab, build_vocab, canonical
from tools.advisor._db import engine

ONET_RELEASE = "31.0"
# O*NET job zone a degree prepares for; a role in a higher zone "usually needs" more.
MAX_ZONE = {"associate": 3, "bachelor": 4, "master": 5, "doctorate": 5}
ZONE_NEEDS = {4: "a bachelor's degree", 5: "a graduate degree"}
SHOWN_GAPS = 5  # missing skills listed per role

# An occupation's rows are the skills O*NET flags for it (in demand, or a hot technology).
# `generic`: wanted by more than half of all occupations (Microsoft Excel: 859 of 904), so
# holding it says nothing about which role fits; it neither makes a match nor is a gap.
# Order: roles above the student's degree last, then most in-demand skills held, then most
# skills held, then the shorter list (the same skills cover more of it).
_RANK = text(
    """
    WITH df AS (
        SELECT example, count(*) AS n FROM onet_software_skill GROUP BY example
    ), s AS (
        SELECT k.soc_code, k.example, k.in_demand, df.n,
               k.example = ANY(CAST(:skills AS text[])) AS has,
               df.n > (SELECT count(*) FROM onet_occupation) / 2 AS generic
        FROM onet_software_skill k JOIN df USING (example)
    )
    SELECT o.code, o.title, o.job_zone,
           count(*) FILTER (WHERE s.in_demand) AS asked,
           count(*) FILTER (WHERE s.in_demand AND s.has) AS asked_have,
           count(*) AS wanted,
           coalesce(array_agg(s.example ORDER BY s.in_demand DESC, s.n DESC, s.example)
                    FILTER (WHERE s.has), '{}') AS matched,
           coalesce(array_agg(s.example ORDER BY s.in_demand DESC, s.n DESC, s.example)
                    FILTER (WHERE NOT s.has AND NOT s.generic), '{}') AS missing
    FROM onet_occupation o JOIN s ON s.soc_code = o.code
    GROUP BY o.code, o.title, o.job_zone
    HAVING count(*) FILTER (WHERE s.has AND NOT s.generic) > 0
    ORDER BY (o.job_zone > CAST(:max_zone AS int)) IS TRUE,
             count(*) FILTER (WHERE s.in_demand AND s.has) DESC,
             count(*) FILTER (WHERE s.has) DESC,
             count(*), o.title
    LIMIT :limit
    """
)


class OnetNotLoaded(RuntimeError):
    """The O*NET tables are missing or empty: `make migrate` and `make ingest-onet` not run."""


@lru_cache
def vocabulary() -> Vocab:
    """Every skill name O*NET lists, with its aliases. Built once: the data only changes when
    the loader runs, and a failed load is not cached, so loading it later needs no restart."""
    try:
        with engine().connect() as conn:
            names = conn.execute(text("SELECT DISTINCT example FROM onet_software_skill")).scalars()
            names = list(names)
    except ProgrammingError as exc:  # the table does not exist
        raise OnetNotLoaded from exc
    if not names:
        raise OnetNotLoaded
    return build_vocab(names)


def _rank(
    conn: Connection, skills: list[str], max_zone: int | None, limit: int
) -> list[dict[str, Any]]:
    """The `limit` occupations that best fit `skills` (O*NET names); see _RANK for the order."""
    rows = conn.execute(_RANK, {"skills": skills, "max_zone": max_zone, "limit": limit})
    return [dict(r) for r in rows.mappings()]


def match_occupations(
    current_skills: list[str],
    degree_level: str | None = None,
    graduation_year: int | None = None,
    limit: int = 5,
) -> dict[str, Any]:
    """Occupations whose employers ask for the software and tools the student has.

    `reason` says why `occupations` is empty: "no_onet" (data not loaded), "no_skills" (none
    of the skills is in the vocabulary) or "generic_only" (only skills nearly every role wants).
    Skill names in the result are display labels, in the student's words ("SQL").
    """
    result: dict[str, Any] = {
        "reason": None,
        "occupations": [],
        "unrecognized": [],
        "graduation_year": graduation_year,
        "graduated": None if graduation_year is None else graduation_year < date.today().year,
        "citations": [],
    }
    try:
        vocab = vocabulary()
    except OnetNotLoaded:
        return result | {"reason": "no_onet"}
    names, result["unrecognized"] = canonical(current_skills, vocab)
    if not names:
        return result | {"reason": "no_skills"}
    max_zone = MAX_ZONE.get(degree_level or "")
    with engine().connect() as conn:
        rows = _rank(conn, names, max_zone, limit)
    if not rows:
        return result | {"reason": "generic_only"}

    def labels(examples: list[str]) -> list[str]:
        # Names the vocabulary blocks ("Google") cannot be read from a resume: not shown.
        return list(dict.fromkeys(vocab.short[e] for e in examples if e in vocab.short))

    for r in rows:
        zone = r["job_zone"]
        above = bool(max_zone and zone and zone > max_zone)
        result["occupations"].append(
            {
                "title": r["title"],
                "asked": r["asked"],
                "asked_have": r["asked_have"],
                "wanted": r["wanted"],
                "matched": labels(r["matched"]),
                "missing": labels(r["missing"])[:SHOWN_GAPS],
                "needs": ZONE_NEEDS.get(zone) if above else None,
            }
        )
        result["citations"].append(
            {
                "source": f"O*NET {ONET_RELEASE} Database, {r['code']} {r['title']}",
                "url": f"https://www.onetonline.org/link/summary/{r['code']}",
            }
        )
    return result
