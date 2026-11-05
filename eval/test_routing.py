"""Hermetic routing checks on the gold set; the model stage is measured by eval/harness.py."""

from eval.harness import load_gold, run
from orchestrator.router import INTENTS


def test_gold_set_is_well_formed() -> None:
    gold = load_gold()
    assert len(gold) >= 50  # Build Plan routing baseline
    assert len({g["id"] for g in gold}) == len(gold)
    assert all(g["intent"] in INTENTS or g["intent"] is None for g in gold)
    assert all(g["source"] for g in gold)  # every item traces to a research area
    assert {g["intent"] for g in gold} >= set(INTENTS)
    # A reply to the advisor's question needs the question and the request it belongs to.
    assert all(
        g.get("history") and g["previous_intent"] in INTENTS for g in gold if g.get("pending")
    )


def test_every_pattern_hit_is_right() -> None:
    """Pattern hits are confident and skip the model, so a wrong one is a wrong answer.
    The 2026-10-15 fixes reached 0 on this set, yet new wordings still hit 11 partial-pattern
    misroutes (2026-11-05); since then patterns match whole messages only. Keep it at 0."""
    regex = run("regex")["metrics"]["stages"]["regex"]
    assert regex["correct"] == regex["n"]
