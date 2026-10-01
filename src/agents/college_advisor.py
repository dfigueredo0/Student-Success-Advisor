"""College Advisor: course planning, prerequisites, course lookup and topic search.

Answers are templated from tool results (never free-generated) so every fact is grounded
and cited; the model only routes. Replies are plain text: the chat panel renders innerText.
"""

import re
from collections.abc import Callable
from typing import Any

from agents.base import Agent, AgentResult, Field, Scaffold
from tools.advisor.catalog import get_course_info, search_courses
from tools.advisor.check_prerequisites import check_prerequisites
from tools.advisor.get_degree_progress import get_degree_progress
from tools.advisor.recommend_courses import recommend_courses

# looser than schemas.catalog.COURSE_CODE ("cs450" ok) so it can match an
# ordinary word before a number ("take 450"); validate against the catalog if it bites.
_CODE = re.compile(r"\b([A-Za-z]{2,4})\s?(\d{3})\b")
_COMPLETED_CUE = re.compile(r"\b(taken|took|completed|passed|finished|done with)\b", re.I)
_NONE = re.compile(r"\b(none|nothing|no courses)\b|^\s*no\s*$", re.I)
_TERM = re.compile(r"\b(fall|spring|summer)\s+(20\d{2}|year\s*\d)\b", re.I)
_TOPIC = re.compile(
    r"\b(?:about|on|covering|cover|related to|involving|in|for|teach(?:es|ing)?)\s+(.+?)[?.!]*$",
    re.I,
)
_SUBJECT_WORD = re.compile(r"\b([A-Za-z]{2,4})\s+(?:courses?|classes|electives|major)\b")
_NOT_SUBJECT = {
    "what", "which", "any", "some", "more", "the", "my", "all", "next", "good", "easy",
    "fun", "core", "grad", "can", "take", "few", "new", "free", "tech", "must", "like",
}  # fmt: skip
# Common ways students name a major -> Banner subject code.
_MAJORS = {
    "computer science": "CS",
    "comp sci": "CS",
    "mathematics": "MATH",
    "math": "MATH",
    "physics": "PHYS",
    "chemistry": "CHEM",
    "biology": "BIOL",
    "psychology": "PSYC",
    "architecture": "ARCH",
    "electrical engineering": "ECE",
    "computer engineering": "ECE",
    "mechanical engineering": "MMAE",
    "aerospace": "MMAE",
    "civil engineering": "CAE",
    "biomedical": "BME",
    "information technology": "ITM",
}

HELP = (
    "I'm the Illinois Tech College Advisor. I can:\n"
    '- recommend courses for next term ("What should I take next semester?")\n'
    '- check whether you meet a course\'s prerequisites ("Can I take CS 450?")\n'
    '- look up a course\'s description, sections and instructors ("Tell me about CS 331")\n'
    '- find courses on a topic ("Any courses on machine learning?")\n\n'
    'Tell me what you\'ve completed (e.g. "I\'ve taken CS 115 and MATH 151") and I\'ll '
    "remember it for this conversation."
)

ASK_COMPLETED_FOR_PLAN = (
    "To suggest courses I need to know what you've already completed. List course codes "
    "(e.g. CS 115, MATH 151), or say 'none' if you're just starting."
)

DEGREE_PROGRESS_UNAVAILABLE = (
    "I can't run a degree audit yet - the degree-progress service isn't connected, so I can't "
    "tell you which requirements you have left. For an official audit, use the Degree Audit "
    "page in myIIT or ask your academic advisor.\n\n"
    'Meanwhile I can suggest courses for next term ("What should I take next semester?") or '
    "check prerequisites for a specific course."
)

def _codes(text: str) -> list[str]:
    return list(dict.fromkeys(f"{s.upper()} {n}" for s, n in _CODE.findall(text)))

def _course(text: str, asked: bool) -> str | None:
    codes = _codes(text)
    return codes[0] if codes else None

def _completed(text: str, asked: bool) -> list[str] | None:
    # Only parsed as an answer to our question; unprompted mentions ("I've taken CS 331")
    # are merged into the profile by CollegeAdvisor.run before the scaffold runs.
    if not asked:
        return None
    return _codes(text) or ([] if _NONE.search(text) else None)

def _subject(text: str, asked: bool) -> str | None:
    low = text.lower()
    for name, code in _MAJORS.items():
        if re.search(rf"\b{name}\b(?!\s?\d)", low):
            return code
    m = _SUBJECT_WORD.search(text)
    if m and m.group(1).lower() not in _NOT_SUBJECT:
        return m.group(1).upper()
    if asked and (m := re.fullmatch(r"\s*([A-Za-z]{2,4})\s*\.?\s*", text)):
        return m.group(1).upper()
    return None

def _term(text: str, asked: bool) -> str | None:
    m = _TERM.search(text)
    return f"{m.group(1).title()} {m.group(2).title()}" if m else None

def _query(text: str, asked: bool) -> str | None:
    if asked:
        return text.strip(" ?.!") or None
    m = _TOPIC.search(text)
    topic = m.group(1).strip() if m else ""
    return topic if len(topic) > 2 else None

def _never(slots: dict[str, Any]) -> bool:
    return False

def _no_completed(slots: dict[str, Any]) -> bool:
    return not slots.get("completed_courses")

def _absent(text: str, asked: bool) -> None:
    return None

def _seats(n: int | None) -> str:
    if n is None:
        return "seats unknown"
    return "full" if n == 0 else f"{n} seat{'s' * (n != 1)} open"

def _credits(c: float | None) -> str:
    return f" ({c:g} cr)" if c else ""

def _render_eligibility(r: dict[str, Any]) -> str:
    course = r["course"]
    if not r["found"]:
        return (
            f"I couldn't find {course} in the course catalog, so I can't check its prerequisites."
        )
    cite = f"[1] {r['citations'][0]['source']}"
    if not r["prerequisites"]:
        return f"{course} lists no prerequisites, so you can take it [1].\n\n{cite}"
    if r["eligible"]:
        verdict = f"You meet the listed prerequisites for {course} [1]."
    else:
        verdict = (
            f"You don't appear to meet the prerequisites for {course} yet. "
            f"Not in your completed courses: {', '.join(r['missing'])} [1]."
        )
    return f'{verdict}\n\nCatalog prerequisites: "{r["prerequisites"]}"\n\n{cite}'

def _render_course_info(r: dict[str, Any]) -> str:
    course = r["course"]
    if not r["found"]:
        return f"I couldn't find {course} in the course catalog. Could you double-check the code?"
    desc = r["description"]
    if len(desc) > 350:
        desc = desc[:350].rsplit(" ", 1)[0] + "..."
    lines = [f"{course} - {r['title']}{_credits(r['credits'])} [1]", desc]
    lines.append(f"Prerequisites: {r['prerequisites'] or 'none listed'}")
    if r["restrictions"]:
        lines.append(f"Restrictions: {r['restrictions']}")
    if (e := r["eligibility"]) is not None:
        lines.append(
            "From the courses you've told me, you meet the listed prerequisites."
            if e["eligible"]
            else f"Not yet in your completed courses: {', '.join(e['missing'])}."
        )
    if sections := r["sections"]:
        lines.append(f"\nOffered {sections[0]['term']} ({len(sections)} section(s)):")
        for s in sections[:5]:
            who = ", ".join(s["instructors"]) or "TBA"
            seats = _seats(s["seats_remaining"])
            kind = f"{s['section']} {s['schedule_type']}"
            lines.append(f"- {kind}, {s['when']}, {s['campus']} - {who}, {seats}")
        if len(sections) > 5:
            lines.append(f"- ...and {len(sections) - 5} more")
    else:
        lines.append("\nNo sections are listed in the current schedule.")
    lines.append(f"\n[1] {r['citations'][0]['source']}")
    return "\n".join(lines)

def _render_search(r: dict[str, Any]) -> str:
    if not r["results"]:
        return (
            f'I didn\'t find courses matching "{r["query"]}". Try other words, '
            "or ask about a specific course code."
        )
    lines = [f'Courses related to "{r["query"]}":']
    for i, c in enumerate(r["results"], 1):
        head = f"{c['code']} - {c['title']}{_credits(c['credits'])}"
        lines.append(f"{i}. {head}: {c['summary']} [{i}]")
    first = r["results"][0]["code"]
    lines.append(f'\nAsk "Tell me about {first}" for sections and prerequisites.\n')
    lines += [f"[{i}] {c['source']}" for i, c in enumerate(r["citations"], 1)]
    return "\n".join(lines)

def _render_recommendations(r: dict[str, Any]) -> str:
    if not r["found"]:
        if r["reason"] == "no_schedule":
            return "The course schedule isn't loaded yet, so I can't recommend courses."
        return (
            "I don't recognize that subject. Tell me your major or its subject code "
            '(e.g. "I\'m a CS major") and ask again.'
        )
    term, subjects = r["term"], "/".join(r["subjects"])
    lines = []
    if not r["requested_term_available"]:
        lines.append(
            f"I only have the {term} schedule loaded, so these are {term} courses "
            f"rather than {r['requested_term']}.\n"
        )
    done = ", ".join(r["completed_courses"]) or "no courses yet"
    if not r["recommendations"]:
        lines.append(
            f"I couldn't find {term} {subjects} courses whose listed prerequisites you've met "
            f"(completed: {done}). If you've finished other courses, tell me and I'll look again."
        )
        return "\n".join(lines)

    lines.append(f"Based on what you've completed ({done}), here are {term} {subjects} options:")
    for i, c in enumerate(r["recommendations"], 1):
        why = []
        if c["builds_on"]:
            why.append(f"follows {', '.join(c['builds_on'])}")
        elif not c["prerequisites"]:
            why.append("no prerequisites")
        if c["unlocks"]:
            why.append(f"prerequisite for {c['unlocks']} later course{'s' * (c['unlocks'] > 1)}")
        seats = _seats(c["seats_remaining"])
        why.append(f"{c['sections']} section(s), {seats}")
        head = f"{c['code']} - {c['title']}{_credits(c['credits'])}"
        lines.append(f"{i}. {head}: {'; '.join(why)} [{i}]")
    lines.append(
        "\nThis uses prerequisites and the schedule only - I can't see your degree requirements "
        "yet, so confirm with your academic advisor before registering. "
        f'Ask "Tell me about {r["recommendations"][0]["code"]}" for times and instructors.\n'
    )
    lines += [f"[{i}] {c['source']}" for i, c in enumerate(r["citations"], 1)]
    return "\n".join(lines)

def _render_progress(r: dict[str, Any]) -> str:
    lines = [
        f"{r['program']}: {r['credits_earned']:g} of {r['credits_required']:g} credits earned [1]."
    ]
    for req in r["requirements"]:
        status = (
            "done"
            if req["earned_credits"] >= req["required_credits"]
            else f"{req['required_credits'] - req['earned_credits']:g} credits left"
        )
        todo = ", ".join(req["remaining_courses"])
        lines.append(f"- {req['name']}: {status}" + (f" ({todo})" if todo else ""))
    lines.append(f"\n[1] {r['citations'][0]['source']}" if r["citations"] else "")
    return "\n".join(lines).rstrip()

class CollegeAdvisor(Agent):
    name = "college_advisor"

    def __init__(
        self,
        check: Callable[..., dict[str, Any]] = check_prerequisites,
        *,
        course_info: Callable[..., dict[str, Any]] = get_course_info,
        search: Callable[..., dict[str, Any]] = search_courses,
        recommend: Callable[..., dict[str, Any]] = recommend_courses,
        progress: Callable[..., dict[str, Any]] = get_degree_progress,
    ) -> None:
        completed_optional = Field("completed_courses", "", _absent, needed=_never, remember=True)
        self.scaffolds = {
            "check_eligibility": Scaffold(
                intent="check_eligibility",
                fields=(
                    Field("course", "Which course do you want to take? (e.g. CS 450)", _course),
                    Field(
                        "completed_courses",
                        "Which courses have you already completed? "
                        "List their codes, or say 'none'.",
                        _completed,
                        remember=True,
                    ),
                ),
                tool=check,
                render=_render_eligibility,
            ),
            "plan_next_term": Scaffold(
                intent="plan_next_term",
                fields=(
                    Field(
                        "completed_courses", ASK_COMPLETED_FOR_PLAN, _completed, remember=True
                    ),
                    Field(
                        "subject",
                        "Which subject or major should I plan for? (e.g. CS, MATH)",
                        _subject,
                        needed=_no_completed,
                        remember=True,
                    ),
                    Field("term", "", _term, needed=_never),
                ),
                tool=recommend,
                render=_render_recommendations,
            ),
            "course_info": Scaffold(
                intent="course_info",
                fields=(
                    Field(
                        "course",
                        "Which course would you like to know about? (e.g. CS 331)",
                        _course,
                    ),
                    completed_optional,
                ),
                tool=course_info,
                render=_render_course_info,
            ),
            "find_courses": Scaffold(
                intent="find_courses",
                fields=(
                    Field(
                        "query",
                        "What topic are you interested in? (e.g. machine learning, databases)",
                        _query,
                    ),
                ),
                tool=search,
                render=_render_search,
            ),
            "degree_progress": Scaffold(
                intent="degree_progress",
                # TODO: needs impl - student_id comes from the authenticated session
                # (api.auth) via the profile; until then the tool gets None.
                fields=(Field("student_id", "", _absent, needed=_never, remember=True),),
                tool=progress,
                render=_render_progress,
                unavailable=DEGREE_PROGRESS_UNAVAILABLE,
            ),
        }

    def run(
        self,
        intent: str,
        text: str,
        slots: dict[str, Any],
        pending: str | None,
        profile: dict[str, Any] | None = None,
    ) -> AgentResult:
        profile = dict(profile or {})
        if intent == "help":
            return self.reply(HELP, profile)
        if intent == "record_courses":
            return self._record(text, profile)
        # "Can I take CS 450? I've taken CS 351" - remember the courses after the cue.
        if pending != "completed_courses" and (cue := _COMPLETED_CUE.search(text)):
            _remember_completed(profile, _codes(text[cue.end() :]))
        return super().run(intent, text, slots, pending, profile)

    def _record(self, text: str, profile: dict[str, Any]) -> AgentResult:
        codes = _codes(text)
        if not codes:
            return self.reply(
                "Which courses have you completed? List the codes, e.g. CS 115, MATH 151.",
                profile,
                pending="completed_courses",
            )
        _remember_completed(profile, codes)
        total = len(profile["completed_courses"])
        return self.reply(
            f"Got it - I'll remember {', '.join(codes)} as completed "
            f"({total} course{'s' * (total > 1)} so far). "
            'Want suggestions? Ask "What should I take next semester?"',
            profile,
        )

def _remember_completed(profile: dict[str, Any], codes: list[str]) -> None:
    if codes:
        known = profile.get("completed_courses") or []
        profile["completed_courses"] = list(dict.fromkeys([*known, *codes]))
