"""Career Services: match the skills a student wants to build to catalog courses.

One question per turn, as in the College Advisor: career goal, then current skills, then
desired skills; the tool runs once all three are filled. Answers are templated from the tool
result and cite the catalog. Course suggestions are catalog matches, not a plan.

TODO: needs impl - re-route: suggested courses should return to the orchestrator as
an AdvisingRequest so check_prerequisites runs on each before it reaches the student. Until
then the answer says prerequisites were not checked and how to check one.
"""

import re
from collections.abc import Callable
from typing import Any

from agents.base import Agent, Field, Scaffold
from tools.career.skill_courses import find_courses_for_skills

_GOAL = re.compile(
    r"\b(?:(?:become|work as|career (?:as|in)|job as|role as|get into|work in)\s+(?:an?\s+)?"
    r"|be\s+an?\s+)([a-z][a-z /&+-]{2,40}?)\s*(?:[.,!?]|$|\b(?:and|so|but|after|when)\b)",
    re.I,
)
_NONE = re.compile(r"^\s*(none|nothing|no|not really|n/?a)\s*[.!]?\s*$", re.I)
_SKILL_PREFIX = re.compile(
    r"^\s*(?:i\s+(?:know|have|can do|can|use|want to learn|want|would like to learn)"
    r"|i'?m\s+good\s+at|skills?\s*:)\s*",
    re.I,
)
_SKILL_SPLIT = re.compile(r"\s*(?:,|;|\n|\band\b)\s*", re.I)


def _goal(text: str, asked: bool) -> str | None:
    if m := _GOAL.search(text):
        return m.group(1).strip()
    if asked:
        return text.strip(" .!?") or None
    return None


def parse_skills(text: str) -> list[str]:
    text = _SKILL_PREFIX.sub("", text)
    seen: dict[str, str] = {}
    for part in _SKILL_SPLIT.split(text):
        skill = part.strip(" .!?")
        if skill:
            seen.setdefault(skill.lower(), skill)
    return list(seen.values())


def _skills(text: str, asked: bool) -> list[str] | None:
    # Only parsed as an answer to our question: a skill list is too easy to misread otherwise.
    if not asked:
        return None
    if _NONE.match(text):
        return []
    return parse_skills(text) or None


def _wanted(text: str, asked: bool) -> list[str] | None:
    # Required: "none" re-asks rather than running the tool on an empty wish list.
    if not asked or _NONE.match(text):
        return None
    return parse_skills(text) or None


def _credits(c: float | None) -> str:
    return f" ({c:g} cr)" if c else ""


def _render(r: dict[str, Any]) -> str:
    goal = r["career_goal"]
    if not r["gap"]:
        return (
            f"You already listed every skill you want to build for {goal}, so there's no gap "
            "for me to match to courses. Tell me other skills you'd like to develop and I'll look."
        )
    # Citations are one per course, in first-seen order across the matches (as the tool built).
    ref: dict[str, int] = {}
    for m in r["matches"]:
        for c in m["courses"]:
            ref.setdefault(c["code"], len(ref) + 1)
    lines = [f"Courses in the IIT catalog that cover the skills you want for {goal}:"]
    for m in r["matches"]:
        if not m["courses"]:
            lines.append(f"- {m['skill']}: no matching courses found")
            continue
        found = "; ".join(
            f"{c['code']} {c['title']}{_credits(c['credits'])} [{ref[c['code']]}]"
            for c in m["courses"]
        )
        lines.append(f"- {m['skill']}: {found}")
    if r["skipped"]:
        lines.append(f"(I looked up the first {len(r['matches'])} skills; ask again for the rest.)")
    first = next((m["courses"][0]["code"] for m in r["matches"] if m["courses"]), None)
    if first:
        lines.append(
            "\nThese are catalog matches by course description, not a plan, and I haven't "
            f'checked prerequisites. Ask "Can I take {first}?" before registering.\n'
        )
    lines += [f"[{i}] {c['source']}" for i, c in enumerate(r["citations"], 1)]
    return "\n".join(lines)


class CareerAdvisor(Agent):
    name = "career_advisor"
    allowed_tools = frozenset({"find_courses_for_skills"})

    def __init__(self, find: Callable[..., dict[str, Any]] = find_courses_for_skills) -> None:
        self.scaffolds = {
            "career_advice": Scaffold(
                intent="career_advice",
                fields=(
                    Field(
                        "career_goal",
                        "What career are you aiming for? (e.g. software engineer, data scientist)",
                        _goal,
                        remember=True,
                    ),
                    Field(
                        "current_skills",
                        "Which skills do you already have? List them, or say 'none'.",
                        _skills,
                        remember=True,
                    ),
                    Field(
                        "desired_skills",
                        "Which skills do you want to build for that career? (e.g. Python, SQL)",
                        _wanted,
                    ),
                ),
                tool=find,
                render=_render,
            )
        }
