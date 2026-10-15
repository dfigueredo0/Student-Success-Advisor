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


def test_pattern_stage_misroutes_do_not_grow() -> None:
    """Pattern hits are confident and skip the model, so a wrong one is a wrong answer.
    Baseline 2026-10-14: 5 misroutes (R06, R08, R27, R45, R52); 0 since the pattern fixes
    on 2026-10-15. Keep it at 0."""
    misrouted = run("regex")["metrics"]["outcomes"].get("misrouted", 0)
    assert misrouted == 0
