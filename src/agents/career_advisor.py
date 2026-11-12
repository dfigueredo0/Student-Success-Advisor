"""Career Services: match the skills a student wants to build to catalog courses, and the
skills they have to occupations.

career_advice asks one question per turn, as in the College Advisor: career goal, then current
skills, then desired skills; the tool runs once all three are filled. job_match needs only the
current skills, which a resume upload (POST /resume) puts in the profile. Answers are templated
from the tool result and cite the catalog or O*NET. Course suggestions are catalog matches, not
a plan; job matches compare software and tool skills only.

TODO: needs impl - re-route: suggested courses should return to the orchestrator as
an AdvisingRequest so check_prerequisites runs on each before it reaches the student. Until
then the answer says prerequisites were not checked and how to check one.
"""

import re
from collections.abc import Callable
from typing import Any

from agents.base import Agent, AgentResult, Field, Resolve, Scaffold
from domain.posting import ASK_POSTING, PASTE_INSTEAD, is_posting
from domain.web_results import HEADER as WEB_RESULTS
from tools.career.onet import match_occupations
from tools.career.posting import compare_to_posting
from tools.career.skill_courses import find_courses_for_skills
from tools.career.web_search import search_openings

MAX_SKILL = 60  # characters; a longer "skill" is a pasted sentence
ASK_SKILLS = (
    "Which skills do you already have? List them, say 'none', or use the Upload resume button."
)
HANDSHAKE = "https://iit.joinhandshake.com"
NO_JOBS = {
    "no_onet": "I can't match jobs yet: the job data isn't loaded on this server.",
    "generic_only": (
        "The skills I have for you are office tools that nearly every role asks for, so they "
        "don't point to particular jobs. Tell me other tools or languages you've used, or a "
        "career you're aiming for."
    ),
}
MIN_POSTING = 40  # characters; a shorter reply to ASK_POSTING is not a posting
NO_POSTING = {
    "no_onet": "I can't compare postings yet: the job data isn't loaded on this server.",
    "unreadable": (
        "I couldn't open that link. Many job sites block automated readers or need a login. "
        + PASTE_INSTEAD
    ),
    "not_a_posting": (
        "I opened that link but didn't find a job posting on the page; it may need a login or "
        "load its text later. " + PASTE_INSTEAD
    ),
    "no_skills_in_posting": (
        "I didn't find software or tools I recognize in that posting, and those are all I can "
        "compare. Read it for its degree, experience and other requirements."
    ),
}
ASK_ROLE = "Which role should I search openings for? (e.g. data analyst)"
MAX_ROLE = 120  # characters; tools.guard refuses a longer one
ON_HANDSHAKE = f"Handshake lists jobs posted for IIT students: {HANDSHAKE}"
NO_SEARCH = {
    "not_configured": "Web search isn't set up on this server, so I can't look up openings.",
    "search_failed": "I couldn't reach the web search just now. Try again in a moment.",
}
# "openings for a data analyst" / "for current data analyst internships"
_OPENINGS = r"(?:openings|postings|positions|internships|jobs)"
_ROLE_AFTER = re.compile(rf"\b{_OPENINGS}\s+(?:for|as)\s+(?:an?\s+|the\s+)?(.+?)[\s?.!]*$", re.I)
_ROLE_BEFORE = re.compile(
    rf"\bfor\s+(?:(?:current|recent|open|new)\s+)*(.+?)\s+(?:job\s+)?{_OPENINGS}\b", re.I
)

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
        if skill and len(skill) <= MAX_SKILL:
            seen.setdefault(skill.lower(), skill)
    return list(seen.values())


def _posting(text: str, asked: bool) -> str | None:
    # Asked for it, any real reply is the posting; unasked, the message must look like one.
    if is_posting(text) or (asked and len(text) >= MIN_POSTING):
        return text.strip()
    return None


def _role(text: str, asked: bool) -> str | None:
    m = _ROLE_AFTER.search(text) or _ROLE_BEFORE.search(text)
    role = m.group(1).strip() if m else text.strip(" ?.!") if asked else ""
    return role if 2 <= len(role) <= MAX_ROLE else None


def _absent(text: str, asked: bool) -> None:
    return None


def _never(slots: dict[str, Any]) -> bool:
    return False


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


def _render_jobs(r: dict[str, Any]) -> str:
    unplaced = ", ".join(r["unrecognized"][:5])
    if r["reason"] == "no_skills":
        return (
            "I match jobs by the software or tools you know, and I don't recognize any in what "
            f"you've told me{f' ({unplaced})' if unplaced else ''}. Tell me the tools and "
            "languages you've used, or use the Upload resume button."
        )
    if r["reason"]:
        return NO_JOBS[r["reason"]]
    lines = ["Roles your skills line up with, from O*NET (U.S. Department of Labor):"]
    for i, o in enumerate(r["occupations"], 1):
        if o["asked"]:
            count = f"{o['asked_have']} of the {o['asked']} tools employers ask for most"
        else:  # O*NET marks nothing in demand for this occupation
            count = f"{len(o['matched'])} of the {o['wanted']} tools commonly used"
        needs = f"; usually needs {o['needs']}" if o["needs"] else ""
        lines.append(f"{i}. {o['title']} - you have {count}{needs} [{i}]")
        # domain.student_text.hide_record strips this line from traces and model prompts.
        lines.append(f"   - You have: {', '.join(o['matched'][:8])}")
        if o["missing"]:
            lines.append(f"   - To add: {', '.join(o['missing'])}")
    if r["graduated"]:
        when = "Look for entry-level openings in these roles"
    elif r["graduation_year"]:
        when = (
            f"You graduate in {r['graduation_year']}, so look for internships and co-ops in "
            "these roles"
        )
    else:
        when = "Look for internships or entry-level openings in these roles"
    lines.append(f"\n{when} on Handshake, which lists jobs posted for IIT students: {HANDSHAKE}")
    top = r["occupations"][0]["title"]
    lines.append(f'Ask "Find openings for {top}" to search current postings.')
    lines.append("I compare software and tool skills only, not coursework, projects or experience.")
    if unplaced:
        lines.append(f"I couldn't place: {unplaced}.")
    if gap := next((o["missing"][0] for o in r["occupations"] if o["missing"]), None):
        lines.append(f'Ask "Any courses on {gap}?" to find a class for a gap.')
    lines.append("")
    lines += [f"[{i}] {c['source']}" for i, c in enumerate(r["citations"], 1)]
    return "\n".join(lines)


def _render_posting(r: dict[str, Any]) -> str:
    if r["reason"]:
        return NO_POSTING[r["reason"]]
    n = len(r["matched"]) + len(r["missing"])
    lines = [f"That posting names {n} software and tool skill{'s' * (n != 1)} I can check."]
    if r["matched"]:
        lines.append(f"- You have: {', '.join(r['matched'])}")  # hidden like _render_jobs' line
    if r["missing"]:
        lines.append(f"- To add: {', '.join(r['missing'])}")
    else:
        lines.append("You already list all of them.")
    lines.append(
        "I compare software and tool skills only; read the posting for its degree, experience "
        "and other requirements."
    )
    if (courses := r["courses"]) and courses["gap"]:
        lines += ["", _render(courses)]
    return "\n".join(lines)


def _render_openings(r: dict[str, Any]) -> str:
    """Web results are other people's text: shown as the tool cleaned it, one source each.
    memory.context keeps the whole reply out of later model prompts (it starts WEB_RESULTS)."""
    if r["reason"] == "no_results":
        return (
            f'I found no recent web results for "{r["query"]}". Try a broader role name. '
            + ON_HANDSHAKE
        )
    if r["reason"]:
        return f"{NO_SEARCH[r['reason']]} {ON_HANDSHAKE}"
    lines = [f'{WEB_RESULTS} "{r["query"]}", past month (searched {r["searched_on"]}):']
    for i, x in enumerate(r["results"], 1):
        lines.append(f"{i}. {x['title']} ({x['site']}) [{i}]")
        if x["snippet"]:
            lines.append(f'   "{x["snippet"]}"')
    lines.append(
        "\nThese are unverified web results, not recommendations. Check the date and the "
        "employer on each page before you apply."
    )
    lines.append(ON_HANDSHAKE + "\n")
    # The page links each source line to its citation's URL.
    lines += [f"[{i}] {c['source']}" for i, c in enumerate(r["citations"], 1)]
    return "\n".join(lines)


class CareerAdvisor(Agent):
    name = "career_advisor"
    allowed_tools = frozenset(
        {"find_courses_for_skills", "match_occupations", "compare_to_posting", "search_openings"}
    )

    def __init__(
        self,
        find: Callable[..., dict[str, Any]] = find_courses_for_skills,
        *,
        match: Callable[..., dict[str, Any]] = match_occupations,
        posting: Callable[..., dict[str, Any]] = compare_to_posting,
        search: Callable[..., dict[str, Any]] = search_openings,
    ) -> None:
        # From an uploaded resume (POST /resume); never asked for in chat.
        degree_level = Field("degree_level", "", _absent, needed=_never, remember=True)
        graduation_year = Field("graduation_year", "", _absent, needed=_never, remember=True)
        self.scaffolds = {
            "job_match": Scaffold(
                intent="job_match",
                fields=(
                    Field("current_skills", ASK_SKILLS, _skills, remember=True),
                    degree_level,
                    graduation_year,
                ),
                tool=match,
                render=_render_jobs,
            ),
            "posting_fit": Scaffold(
                intent="posting_fit",
                fields=(
                    Field("posting", ASK_POSTING, _posting),
                    Field("current_skills", ASK_SKILLS, _skills, remember=True),
                ),
                tool=posting,
                render=_render_posting,
            ),
            "find_openings": Scaffold(
                intent="find_openings",
                fields=(Field("role", ASK_ROLE, _role), graduation_year),
                tool=search,
                render=_render_openings,
            ),
            "career_advice": Scaffold(
                intent="career_advice",
                fields=(
                    Field(
                        "career_goal",
                        "What career are you aiming for? (e.g. software engineer, data scientist)",
                        _goal,
                        remember=True,
                    ),
                    Field("current_skills", ASK_SKILLS, _skills, remember=True),
                    Field(
                        "desired_skills",
                        "Which skills do you want to build for that career? (e.g. Python, SQL)",
                        _wanted,
                    ),
                ),
                tool=find,
                render=_render,
            ),
        }

    def run(
        self,
        intent: str,
        text: str,
        slots: dict[str, Any],
        pending: str | None,
        profile: dict[str, Any] | None = None,
        resolve: Resolve | None = None,
    ) -> AgentResult:
        if intent == "posting_fit" and is_posting(text):
            # A posting sent while an earlier one waits for the student's skills replaces it,
            # and is not the answer to "which skills do you have?".
            slots = {k: v for k, v in slots.items() if k != "posting"}
            pending = None if pending == "current_skills" else pending
        result = super().run(intent, text, slots, pending, profile, resolve)
        # Some answers end by asking for more; the reply to them is that field, not a new
        # request (and for a posting, text the model must not read: orchestrator.graph).
        reason = next(
            (c["result"].get("reason") for c in result["tool_calls"] if "result" in c), None
        )
        if intent == "posting_fit" and reason in ("unreadable", "not_a_posting"):
            result["pending_field"] = "posting"  # "paste the requirements section instead"
        elif reason in ("no_skills", "generic_only"):
            result["pending_field"] = "current_skills"  # "tell me other tools you've used"
        return result
