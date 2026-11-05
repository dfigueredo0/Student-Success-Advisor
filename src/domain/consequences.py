"""What dropping one course this term would do (UC-09): later courses it blocks, courses the
student is taking that needed it at the same time, and credit-load thresholds it crosses.

Pure: the tool passes in the prerequisite trees, credits and policy rules. A course is only
reported when the evaluator's answer gets worse after the drop, so a course the student can
still reach another way (needs A or B, has B) never is.

ponytail: direct dependents only, not checked against the student's remaining degree
requirements (no requirements data yet); the networkx graph and a graduation-timing estimate
come with Phase 8.
"""

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import date
from typing import Any

from domain.prereq import Status, evaluate


@dataclass(frozen=True)
class Rule:
    """A credit-load threshold from a cited policy page. Rules are never edited in place: a
    change is a new rule with a later `effective_from`."""

    id: str
    kind: str  # full_time | f1_full_course | aid_enrollment
    level: str  # undergraduate | graduate
    min_credits: float
    message: str
    source: str
    url: str
    quote: str
    effective_from: date
    verified: bool = False  # a teammate checked the URL and quote


@dataclass(frozen=True)
class Blocked:
    course: str
    needs: tuple[str, ...]  # the cheapest set still missing after the drop


@dataclass(frozen=True)
class Consequences:
    course: str
    taking: bool  # False: not one of the student's current courses, nothing else computed
    credits_before: float | None = None  # None when a current course's credits are unknown
    credits_after: float | None = None
    crossed: tuple[Rule, ...] = ()  # thresholds the drop takes the student below
    already_below: tuple[Rule, ...] = ()  # thresholds they are under with or without it
    blocked: tuple[Blocked, ...] = ()  # later courses they could have taken, now can't
    corequisite_of: tuple[str, ...] = ()  # current courses that need it the same term

    @property
    def reasons(self) -> list[str]:
        """Stable codes, one per finding (VerifierRun.failure_reasons)."""
        return [
            *(f"prereq_blocked:{b.course}" for b in self.blocked),
            *(f"coreq_broken:{c}" for c in self.corequisite_of),
            *(f"below:{r.id}" for r in self.crossed),
        ]


def consequences(
    course: str,
    current: Mapping[str, float | None],
    completed: Mapping[str, str | None],
    dependents: Mapping[str, dict[str, Any] | None],
    rules: Iterable[Rule],
    today: date,
    level: str = "undergraduate",
) -> Consequences:
    """current: the courses being taken this term -> credits (None if unknown).
    completed: course -> grade, as for domain.prereq.evaluate.
    dependents: courses listing `course` as a prerequisite -> their prerequisite tree."""
    if course not in current:
        return Consequences(course, taking=False)
    after = set(current) - {course}
    blocked, corequisite_of = [], []
    for code, tree in sorted(dependents.items()):
        if code == course or code in completed:
            continue
        if code in current:  # taken now: its prerequisites count only as same-term courses
            was = evaluate(tree, completed, planned=current)
            now = evaluate(tree, completed, planned=after)
            if _worse(was.status, now.status):
                corequisite_of.append(code)
            continue
        was = evaluate(tree, completed, in_progress=current)
        now = evaluate(tree, completed, in_progress=after)
        if _worse(was.status, now.status):
            blocked.append(Blocked(code, tuple(leaf.requirement for leaf in now.missing)))

    credits = list(current.values())
    before = None if None in credits else sum(credits)
    dropped = current[course]
    load_after = None if before is None or dropped is None else before - dropped
    crossed, below = [], []
    known = before is not None and load_after is not None  # else say so instead of guessing
    for rule in _in_effect(rules, level, today) if known else []:
        if before < rule.min_credits:
            below.append(rule)
        elif load_after < rule.min_credits:
            crossed.append(rule)
    return Consequences(
        course,
        taking=True,
        credits_before=before,
        credits_after=load_after,
        crossed=tuple(crossed),
        already_below=tuple(below),
        blocked=tuple(blocked),
        corequisite_of=tuple(corequisite_of),
    )


def _worse(was: Status, now: Status) -> bool:
    return was is not Status.UNSATISFIED and now is Status.UNSATISFIED


def _in_effect(rules: Iterable[Rule], level: str, today: date) -> list[Rule]:
    """The newest rule of each kind for this level that has taken effect."""
    newest: dict[str, Rule] = {}
    for r in rules:
        if r.level != level or r.effective_from > today:
            continue
        if r.kind not in newest or r.effective_from > newest[r.kind].effective_from:
            newest[r.kind] = r
    return sorted(newest.values(), key=lambda r: -r.min_credits)
