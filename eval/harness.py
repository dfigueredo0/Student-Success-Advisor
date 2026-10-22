"""Routing baseline: run the gold set (data/gold/routing.jsonl) through the intent router.

    uv run python -m eval.harness --mode regex   # pattern stage only; hermetic
    uv run python -m eval.harness --mode model   # small model on every item (needs `make up`)
    uv run python -m eval.harness --mode full    # production path: patterns -> model -> clarify

Gold intents trace to the Researcher's survey areas (data/research_findings.json, F02/F06/
F07/F08/F10); the wording is ours, not collected student messages. Out-of-scope items have
intent null: the right answer is a clarify. Follow-up items carry the conversation before the
message in `history` ({"role", "content"} messages), which the model stage sees and the pattern
stage does not, and the intent of its last request in `previous_intent`. Results go to
eval/results/.
"""

import argparse
import json
import time
from datetime import date
from pathlib import Path
from typing import Any

from eval.metrics import score
from orchestrator.router import (
    FOLLOW_UP,
    ROUTER_PROMPT,
    gateway_complete,
    ollama_classify,
    regex_route,
    route,
)
from settings import get_settings

ROOT = Path(__file__).resolve().parents[1]
GOLD = ROOT / "data" / "gold" / "routing.jsonl"
RESULTS = Path(__file__).parent / "results"


def load_gold(path: Path = GOLD) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


# The router's gateway key allows 60 requests/minute (infra/litellm/seed_keys.py).
_MIN_INTERVAL_S = 1.1


class Gateway:
    """gateway_complete, paced under the router key's rate limit. Remembers the last call's
    error and duration: ollama_classify turns a gateway error into a clarify, which must not
    be scored as the model's answer."""

    def __init__(self) -> None:
        self.error: str | None = None
        self.ms: int | None = None
        self._last = 0.0

    def __call__(self, payload: dict[str, Any]) -> str:
        if (wait := _MIN_INTERVAL_S - (time.monotonic() - self._last)) > 0:
            time.sleep(wait)
        self._last = start = time.monotonic()
        try:
            return gateway_complete(payload)
        except Exception as exc:
            self.error = repr(exc)[:200]
            raise
        finally:
            self.ms = round((time.monotonic() - start) * 1000)


def predict(
    text: str,
    mode: str,
    threshold: float,
    gateway: Gateway,
    history: list[dict[str, str]] | None = None,
    previous: str | None = None,
) -> tuple[str | None, str, float]:
    """(intent or None for clarify, stage that decided, confidence)."""
    if mode == "regex":
        hit = regex_route(text)
        return (hit.intent, "regex", hit.confidence) if hit else (None, "clarify", 0.0)
    if mode == "model":
        intent, confidence = ollama_classify(text, history, gateway)
        if intent == FOLLOW_UP:
            intent = previous
        if intent is not None and confidence >= threshold:
            return intent, "model", confidence
        return None, "clarify", confidence
    r = route(
        text,
        classify=lambda t, h: ollama_classify(t, h, gateway),
        threshold=threshold,
        history=history,
        previous=previous,
    )
    return r.intent, r.source, r.confidence


def run(mode: str) -> dict[str, Any]:
    threshold = get_settings().router_confidence_threshold
    rows = []
    gateway = Gateway()
    for item in load_gold():
        gateway.error = gateway.ms = None
        predicted, stage, confidence = predict(
            item["text"], mode, threshold, gateway, item.get("history"), item.get("previous_intent")
        )
        rows.append(
            {
                "id": item["id"],
                "text": item["text"],
                "gold": item["intent"],
                "predicted": predicted,
                "stage": stage,
                "confidence": round(confidence, 3),
                "ms": gateway.ms,  # model call time; None when no model call
                "error": gateway.error,
            }
        )
    return {
        "date": date.today().isoformat(),
        "mode": mode,
        "prompt_version": None if mode == "regex" else ROUTER_PROMPT.version,
        "model_alias": None if mode == "regex" else get_settings().llm_default_model,
        "threshold": threshold,
        "metrics": score(rows),
        "rows": rows,
    }


def _print(report: dict[str, Any]) -> None:
    m = report["metrics"]
    print(
        f"routing eval, mode={report['mode']}, n={m['n']}, prompt={report['prompt_version']}, "
        f"model={report['model_alias']}, threshold={report['threshold']}\n"
        f"  accuracy {m['accuracy']:.0%}   misrouted {m['misroute_rate']:.0%}   "
        f"clarified (in scope) {m['clarify_rate_in_scope']:.0%}   "
        f"out-of-scope handled {m['out_of_scope_handled']:.0%}"
    )
    print("  stages: " + ", ".join(f"{k} {v['correct']}/{v['n']}" for k, v in m["stages"].items()))
    print("  per intent (precision / recall):")
    for intent, s in m["per_intent"].items():
        p = "-" if s["precision"] is None else f"{s['precision']:.2f}"
        print(f"    {intent:<18} n={s['n']:<2}  {p:>4} / {s['recall']:.2f}")
    if m["confusions"]:
        print("  errors (gold -> predicted; None = clarify):")
        for pair, n in m["confusions"].items():
            print(f"    {n:>2}  {pair}")
    errors = [r for r in report["rows"] if r["error"]]
    if errors:
        print(
            f"  WARNING {len(errors)} gateway errors scored as clarify, e.g. {errors[0]['error']}"
        )
    ms = sorted(r["ms"] for r in report["rows"] if r["ms"] is not None)
    if ms:
        slow = sum(m >= 30_000 for m in ms)  # gateway_complete's timeout -> clarify
        print(
            f"  model calls {len(ms)}: p50 {ms[len(ms) // 2]} ms, max {ms[-1]} ms, timeouts {slow}"
        )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--mode", choices=["regex", "model", "full"], default="full")
    args = parser.parse_args(argv)
    report = run(args.mode)
    _print(report)
    RESULTS.mkdir(exist_ok=True)
    out = RESULTS / f"routing-{report['date']}-{args.mode}.json"
    out.write_text(json.dumps(report, indent=2) + "\n")
    print(f"wrote {out.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
