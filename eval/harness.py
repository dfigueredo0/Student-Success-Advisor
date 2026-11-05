"""Routing baseline: run the gold set (data/gold/routing.jsonl) through the intent router.

    uv run python -m eval.harness --mode regex   # pattern stage only; hermetic
    uv run python -m eval.harness --mode model   # small model on every item (needs `make up`)
    uv run python -m eval.harness --mode full    # production path: hand-offs -> patterns -> model
    uv run python -m eval.harness --mode full --model bakeoff-qwen3-8b   # bake-off a candidate

Gold intents trace to the Researcher's survey areas (data/research_findings.json, F02/F06/
F07/F08/F10); the wording is ours, not collected student messages. Out-of-scope items have
intent null: the right answer is a clarify. Follow-up items carry the conversation before the
message in `history` ({"role", "content"} messages), which the model stage sees and the pattern
stage does not, and the intent of its last request in `previous_intent`. `pending` items reply
to the advisor's question (history ends with it): gold is `previous_intent` for an answer, the
new intent for a change of topic. Results go to eval/results/.
"""

import argparse
import json
import time
from datetime import date
from pathlib import Path
from typing import Any

from eval.metrics import score
from orchestrator.escalation import escalate
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
    error and duration: ollama_classify turns a gateway error or an unparseable reply into a
    clarify, which must not be scored as the model's answer.

    `overrides` replace request fields for a bake-off (model alias, max_tokens,
    reasoning_effort) without touching the router's own request."""

    def __init__(self, overrides: dict[str, Any] | None = None) -> None:
        self.overrides = overrides or {}
        self.error: str | None = None
        self.ms: int | None = None
        self._last = 0.0

    def __call__(self, payload: dict[str, Any]) -> str:
        if (wait := _MIN_INTERVAL_S - (time.monotonic() - self._last)) > 0:
            time.sleep(wait)
        self._last = start = time.monotonic()
        try:
            reply = gateway_complete(payload | self.overrides)
        except Exception as exc:
            self.error = repr(exc)[:200]
            raise
        finally:
            self.ms = round((time.monotonic() - start) * 1000)
        try:
            json.loads(reply)
        except (TypeError, ValueError):
            self.error = f"unparseable: {str(reply)[:80]!r}"
        return reply


def predict(
    text: str,
    mode: str,
    threshold: float,
    gateway: Gateway,
    history: list[dict[str, str]] | None = None,
    previous: str | None = None,
    pending: bool = False,
) -> tuple[str | None, str, float]:
    """(intent or None for clarify, stage that decided, confidence). `pending`: the advisor
    asked a question, so anything but a clear new request keeps `previous` (the answer)."""
    if mode == "regex":
        hit = regex_route(text, previous if pending else None)
        if hit:
            return hit.intent, "regex", hit.confidence
        return (previous if pending else None), "clarify", 0.0
    if mode == "model":
        intent, confidence = ollama_classify(text, history, gateway)
        if intent == FOLLOW_UP:
            intent = previous
        if intent is not None and confidence >= threshold:
            return intent, "model", confidence
        return (previous if pending else None), "clarify", confidence
    if escalate(text):  # production hands these off before the router; gold is null
        return None, "escalation", 1.0
    r = route(
        text,
        classify=lambda t, h: ollama_classify(t, h, gateway),
        threshold=threshold,
        history=history,
        previous=previous,
        answering=pending,
    )
    return r.intent, r.source, r.confidence


def run(mode: str, overrides: dict[str, Any] | None = None) -> dict[str, Any]:
    threshold = get_settings().router_confidence_threshold
    rows = []
    gateway = Gateway(overrides)
    cold_ms = None
    if mode != "regex":  # load the model first so the first item isn't timed with the load
        ollama_classify("hi", [], gateway)
        cold_ms, gateway.error = gateway.ms, None
    for item in load_gold():
        gateway.error = gateway.ms = None
        predicted, stage, confidence = predict(
            item["text"],
            mode,
            threshold,
            gateway,
            item.get("history"),
            item.get("previous_intent"),
            item.get("pending", False),
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
        "model_alias": None
        if mode == "regex"
        else (overrides or {}).get("model", get_settings().llm_default_model),
        "overrides": overrides or {},
        "threshold": threshold,
        "metrics": score(rows),
        "latency_ms": _latency(rows, cold_ms),
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
    if lat := report["latency_ms"]:
        print(
            f"  model calls {lat['calls']}: p50 {lat['p50']} ms, p95 {lat['p95']} ms, "
            f"max {lat['max']} ms, timeouts {lat['timeouts']}, cold load {lat['cold']} ms"
        )


def _latency(rows: list[dict[str, Any]], cold_ms: int | None) -> dict[str, Any] | None:
    ms = sorted(r["ms"] for r in rows if r["ms"] is not None)
    if not ms:
        return None
    return {
        "calls": len(ms),
        "p50": ms[len(ms) // 2],
        "p95": ms[min(len(ms) - 1, round(0.95 * (len(ms) - 1)))],
        "max": ms[-1],
        "timeouts": sum(m >= 30_000 for m in ms),  # gateway_complete's timeout -> clarify
        "cold": cold_ms,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--mode", choices=["regex", "model", "full"], default="full")
    parser.add_argument("--model", help="gateway alias to route with (bake-off)")
    parser.add_argument("--max-tokens", type=int, help="override the router's max_tokens")
    parser.add_argument("--reasoning", help="override reasoning_effort, e.g. low")
    args = parser.parse_args(argv)
    wanted = {
        "model": args.model,
        "max_tokens": args.max_tokens,
        "reasoning_effort": args.reasoning,
    }
    overrides = {k: v for k, v in wanted.items() if v is not None}
    report = run(args.mode, overrides)
    _print(report)
    RESULTS.mkdir(exist_ok=True)
    tag = "".join(f"-{v}" for v in overrides.values())  # e.g. -bakeoff-qwen3-8b-512-low
    out = RESULTS / f"routing-{report['date']}-{args.mode}{tag}.json"
    out.write_text(json.dumps(report, indent=2) + "\n")
    print(f"wrote {out.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
