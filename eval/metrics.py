"""Routing metrics. A misroute (confidently sent to the wrong agent) is worse than a clarify
(the router asks), so they are counted apart; out-of-scope items (gold intent None) are
handled only when the router clarifies."""

from collections import Counter
from typing import Any


def outcome(gold: str | None, predicted: str | None) -> str:
    if predicted == gold:
        return "correct"
    return "clarified" if predicted is None else "misrouted"


def score(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """rows: {"id", "gold", "predicted", "stage"}; predicted None means the router clarified."""
    n = len(rows)
    outcomes = Counter(outcome(r["gold"], r["predicted"]) for r in rows)
    in_scope = [r for r in rows if r["gold"] is not None]
    out_scope = [r for r in rows if r["gold"] is None]

    per_intent = {}
    for intent in sorted({r["gold"] for r in in_scope}):
        tp = sum(r["gold"] == intent and r["predicted"] == intent for r in rows)
        predicted = sum(r["predicted"] == intent for r in rows)
        gold = sum(r["gold"] == intent for r in rows)
        per_intent[intent] = {
            "n": gold,
            "precision": round(tp / predicted, 3) if predicted else None,
            "recall": round(tp / gold, 3),
        }

    stages = {}
    for stage in sorted({r["stage"] for r in rows}):
        hits = [r for r in rows if r["stage"] == stage]
        stages[stage] = {
            "n": len(hits),
            "correct": sum(r["gold"] == r["predicted"] for r in hits),
        }

    return {
        "n": n,
        "accuracy": round(outcomes["correct"] / n, 3),
        "misroute_rate": round(outcomes["misrouted"] / n, 3),
        "clarify_rate_in_scope": round(
            sum(r["predicted"] is None for r in in_scope) / len(in_scope), 3
        ),
        "out_of_scope_handled": round(
            sum(r["predicted"] is None for r in out_scope) / len(out_scope), 3
        )
        if out_scope
        else None,
        "outcomes": dict(outcomes),
        "per_intent": per_intent,
        "stages": stages,
        "confusions": dict(
            Counter(
                f"{r['gold']} -> {r['predicted']}" for r in rows if r["gold"] != r["predicted"]
            ).most_common()
        ),
    }
