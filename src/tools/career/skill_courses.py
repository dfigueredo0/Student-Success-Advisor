"""find_courses_for_skills: catalog courses whose descriptions cover the skills a student lacks.

The gap is what the student said they want minus what they said they have; no occupation
skill data (O*NET/BLS) is loaded yet, so the career goal is carried through, not used to infer
skills. Course matches come from semantic catalog search, embedded with the career agent's own
gateway key.
"""

from typing import Any

from domain.skills import skill_gap
from retrieval.catalog_search import search_catalog
from settings import get_settings
from tools.advisor.catalog import BANNER_URL, credits

MAX_SKILLS = 5  # one catalog search per skill; keeps a turn's gateway calls bounded


# TODO: needs impl - take the student's level from the student record (as search_courses).
def find_courses_for_skills(
    career_goal: str,
    current_skills: list[str],
    desired_skills: list[str],
    level: str = "Undergraduate",
    per_skill: int = 3,
) -> dict[str, Any]:
    gap = skill_gap(current_skills, desired_skills)
    key = get_settings().litellm_career_key
    matches, citations, cited = [], [], set()
    for skill in gap[:MAX_SKILLS]:
        rows = search_catalog(skill, limit=per_skill, level=level, api_key=key)
        matches.append(
            {
                "skill": skill,
                "courses": [
                    {
                        "code": r["code"],
                        "title": r["title"],
                        "credits": credits(r),
                        "summary": r["description"].split(". ")[0][:200],
                    }
                    for r in rows
                ],
            }
        )
        for r in rows:
            if r["code"] not in cited:
                cited.add(r["code"])
                citations.append(
                    {
                        "source": (
                            f"IIT Banner course catalog, {r['code']}, term {r['catalog_term']}"
                        ),
                        "url": BANNER_URL,
                        "quote": r["description"][:300],
                    }
                )
    return {
        "career_goal": career_goal,
        "gap": gap,
        "skipped": gap[MAX_SKILLS:],
        "matches": matches,
        "citations": citations,
    }
