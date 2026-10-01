import re
from collections.abc import Callable
from typing import Any

from agents.base import Agent, Field, Scaffold
from tools.advisor.check_prerequisites import check_prerequisites

# looser than schemas.catalog.COURSE_CODE ("cs450" ok) so it can match an
# ordinary word before a number ("take 450"); validate against the catalog if it bites.
_CODE = re.compile(r"\b([A-Za-z]{2,4})\s?(\d{3})\b")
_COMPLETED_CUE = re.compile(r"\b(taken|took|completed|passed|finished|done)\b", re.I)
_NONE = re.compile(r"\b(none|nothing|no courses)\b|^\s*no\s*$", re.I)

def _codes(text: str) -> list[str]:
    return list(dict.fromkeys(f"{s.upper()} {n}" for s, n in _CODE.findall(text)))

def _course(text: str, asked: bool) -> str | None:
    codes = _codes(text)
    return codes[0] if codes else None

def _completed(text: str, asked: bool) -> list[str] | None:
    # TODO: needs impl - read completed courses from the student record
    # (tools.advisor.parse_transcript / schemas.student) instead of asking.
    if asked:
        return _codes(text) or ([] if _NONE.search(text) else None)
    # Unprompted ("Can I take CS 450? I've taken CS 331"): first code is the target course.
    cue = _COMPLETED_CUE.search(text)
    return (_codes(text[cue.end() :]) or None) if cue else None

def _render(r: dict[str, Any]) -> str:
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

class CollegeAdvisor(Agent):
    name = "college_advisor"

    def __init__(self, check: Callable[..., dict[str, Any]] = check_prerequisites) -> None:
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
                    ),
                ),
                tool=check,
                render=_render,
            )
        }
