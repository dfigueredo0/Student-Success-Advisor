"""UC-09 consequence check: the Build Plan's Phase 8 unit cases, on hand-built trees."""

from datetime import date
from typing import Any

from domain.consequences import Blocked, Rule, consequences

TODAY = date(2026, 11, 5)


def course(code: str, concurrent: bool = False) -> dict[str, Any]:
    return {"type": "course", "course": code, "minimum_grade": "D", "concurrent": concurrent}


def any_of(*children: dict[str, Any]) -> dict[str, Any]:
    return {"type": "or", "children": list(children)}


def rule(min_credits: float, kind: str = "full_time", **kw: Any) -> Rule:
    fields = {
        "id": f"{kind}-ug",
        "kind": kind,
        "level": "undergraduate",
        "min_credits": min_credits,
        "message": "may affect your status",
        "source": "Policy page",
        "url": "https://example.edu/policy",
        "quote": "12 credit hours",
        "effective_from": date(2020, 1, 1),
    }
    return Rule(**(fields | kw))


CURRENT = {"CS 351": 3.0, "CS 330": 3.0, "MATH 251": 4.0, "HUM 200": 3.0}  # 13 credits


def test_course_reachable_another_way_is_not_reported() -> None:
    """Needs CS 351 or CS 350; the student has CS 350, so dropping CS 351 changes nothing."""
    r = consequences(
        "CS 351",
        CURRENT,
        {"CS 350": "B"},
        {"CS 430": any_of(course("CS 351"), course("CS 350"))},
        [],
        TODAY,
    )
    assert r.blocked == ()


def test_later_course_that_needed_it_is_blocked_with_what_it_needs() -> None:
    r = consequences("CS 351", CURRENT, {}, {"CS 430": course("CS 351")}, [], TODAY)
    assert r.blocked == (Blocked("CS 430", ("CS 351",)),)
    assert r.reasons == ["prereq_blocked:CS 430"]


def test_course_already_out_of_reach_is_not_blamed_on_the_drop() -> None:
    tree = {"type": "and", "children": [course("CS 351"), course("CS 331")]}  # no CS 331
    assert consequences("CS 351", CURRENT, {}, {"CS 430": tree}, [], TODAY).blocked == ()


def test_dropping_a_corequisite_reports_the_course_taken_with_it() -> None:
    current = CURRENT | {"CS 352": 3.0}
    deps = {"CS 352": course("CS 351", concurrent=True)}
    r = consequences("CS 351", current, {}, deps, [], TODAY)
    assert r.corequisite_of == ("CS 352",) and r.blocked == ()
    assert r.reasons == ["coreq_broken:CS 352"]


def test_completed_dependents_are_ignored() -> None:
    deps = {"CS 430": course("CS 351")}
    assert consequences("CS 351", CURRENT, {"CS 430": "A"}, deps, [], TODAY).blocked == ()


def test_crossing_a_threshold_fires_the_rule_with_its_source() -> None:
    r = consequences("CS 351", CURRENT, {}, {}, [rule(12)], TODAY)
    assert (r.credits_before, r.credits_after) == (13.0, 10.0)
    assert [x.url for x in r.crossed] == ["https://example.edu/policy"]
    assert r.reasons == ["below:full_time-ug"]


def test_threshold_still_met_after_the_drop_does_not_fire() -> None:
    r = consequences("CS 351", CURRENT | {"PE 100": 3.0}, {}, {}, [rule(12)], TODAY)
    assert r.crossed == () and r.already_below == ()


def test_already_below_is_reported_apart_from_what_the_drop_did() -> None:
    current = {"CS 351": 3.0, "CS 330": 3.0}
    r = consequences("CS 351", current, {}, {}, [rule(12)], TODAY)
    assert r.crossed == () and [x.id for x in r.already_below] == ["full_time-ug"]
    assert r.reasons == []


def test_unknown_credits_leave_the_load_unknown() -> None:
    r = consequences("CS 351", CURRENT | {"CS 597": None}, {}, {}, [rule(12)], TODAY)
    assert r.credits_before is None and r.crossed == () and r.already_below == ()


def test_course_not_being_taken_is_flagged_and_nothing_else_computed() -> None:
    r = consequences("CS 450", CURRENT, {}, {"CS 485": course("CS 450")}, [rule(12)], TODAY)
    assert r.taking is False and r.blocked == () and r.crossed == ()


def test_only_the_newest_rule_in_effect_counts() -> None:
    rules = [
        rule(12, id="old", effective_from=date(2020, 1, 1)),
        rule(9, id="new", effective_from=date(2025, 8, 1)),
        rule(15, id="future", effective_from=date(2027, 1, 1)),
        rule(12, id="grad", level="graduate"),
    ]
    r = consequences("CS 351", CURRENT, {}, {}, rules, TODAY)
    assert [x.id for x in r.crossed] == []  # 10 credits after: above the new 9
    r = consequences(
        "CS 351", {"CS 351": 3.0, "CS 330": 3.0, "MATH 251": 4.0}, {}, {}, rules, TODAY
    )
    assert [x.id for x in r.crossed] == ["new"]  # 10 -> 7
