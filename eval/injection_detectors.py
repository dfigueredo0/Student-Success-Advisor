"""Prompt-injection detectors: how many attacks each catches, and how many normal messages
it blocks by mistake, on the injection gold set plus the routing questions.

    uv run python -m eval.injection_detectors                    # pattern guardrail; hermetic
    uv run --with "transformers>=4.44,<5" --with torch --with sentencepiece --with protobuf \\
        python -m eval.injection_detectors --detector protectai   # local DeBERTa classifier
    (same command with --detector promptguard for Meta's Prompt Guard 2; its download needs
    a Hugging Face login with the Llama licence accepted)

Cases (data/gold/injection.jsonl) come from three sources, scored separately:
  * written: our advisor-specific attacks and tricky normal questions
  * deepset: the deepset/prompt-injections test split (Apache-2.0). Its labels count any
    off-task request as an attack, and public classifiers may have trained on it, so it
    flatters them; "written" is the fairer comparison.
  * routing: the routing gold set (data/gold/routing.jsonl): normal student questions,
    plus R59, which that set labels as an injection attempt.
Results go to eval/results/.
"""

import argparse
import json
import statistics
import sys
import time
import types
from collections.abc import Callable
from datetime import date
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
GOLD = ROOT / "data" / "gold" / "injection.jsonl"
ROUTING = ROOT / "data" / "gold" / "routing.jsonl"
GUARD = ROOT / "infra" / "litellm" / "injection_guard.py"
RESULTS = ROOT / "eval" / "results"

Detector = Callable[[str], bool]


def load_cases() -> list[dict[str, Any]]:
    cases = [json.loads(line) for line in GOLD.read_text().splitlines() if line.strip()]
    for line in ROUTING.read_text().splitlines():
        if line.strip():
            row = json.loads(line)
            # The routing set includes one injection attempt as an out-of-scope example.
            attack = "injection" in row["source"].lower()
            cases.append(
                {"id": row["id"], "text": row["text"], "attack": attack, "source": "routing"}
            )
    for case in cases:
        case["source"] = case["source"].split("/")[0].split()[0]  # written | deepset | routing
    return cases


def pattern_detector() -> Detector:
    """The gateway's own guardrail logic, loaded from infra/ without LiteLLM installed."""
    stub = types.ModuleType("litellm.integrations.custom_guardrail")
    stub.CustomGuardrail = object  # the guard class is not used here, only its patterns
    for name in ("litellm", "litellm.integrations"):
        sys.modules.setdefault(name, types.ModuleType(name))
    sys.modules.setdefault("litellm.integrations.custom_guardrail", stub)
    namespace: dict[str, Any] = {}
    exec(compile(GUARD.read_text(), str(GUARD), "exec"), namespace)
    patterns, normalize = namespace["INJECTION_PATTERNS"], namespace["normalize"]
    return lambda text: any(p.search(v) for p in patterns for v in (text, normalize(text)))


def protectai_detector() -> Detector:
    from transformers import pipeline  # optional: see the module docstring

    classify = pipeline(
        "text-classification",
        model="protectai/deberta-v3-base-prompt-injection-v2",
        truncation=True,
        max_length=512,
    )
    classify("warm up")
    return lambda text: classify(text)[0]["label"] == "INJECTION"


def promptguard_detector() -> Detector:
    from transformers import pipeline  # optional: see the module docstring

    classify = pipeline(
        "text-classification",
        model="meta-llama/Llama-Prompt-Guard-2-86M",
        truncation=True,
        max_length=512,
    )
    classify("warm up")
    return lambda text: classify(text)[0]["label"] == "LABEL_1"  # LABEL_0 is benign


DETECTORS = {
    "patterns": pattern_detector,
    "promptguard": promptguard_detector,
    "protectai": protectai_detector,
}


def score(rows: list[dict[str, Any]]) -> dict[str, Any]:
    attacks = [r for r in rows if r["attack"]]
    normal = [r for r in rows if not r["attack"]]
    return {
        "attacks_caught": sum(r["flagged"] for r in attacks),
        "attacks": len(attacks),
        "normal_blocked": sum(r["flagged"] for r in normal),
        "normal": len(normal),
        "missed": [r["id"] for r in attacks if not r["flagged"]],
        "false_positives": [r["id"] for r in normal if r["flagged"]],
    }


def run(detector: str) -> dict[str, Any]:
    detect = DETECTORS[detector]()
    rows = []
    for case in load_cases():
        start = time.perf_counter()
        flagged = detect(case["text"])
        ms = (time.perf_counter() - start) * 1000
        rows.append({**case, "flagged": flagged, "ms": round(ms, 2)})
    by_source = {
        s: score([r for r in rows if r["source"] == s]) for s in sorted({r["source"] for r in rows})
    }
    return {
        "date": date.today().isoformat(),
        "detector": detector,
        "overall": score(rows),
        "by_source": by_source,
        "median_ms": statistics.median(r["ms"] for r in rows),
        "rows": rows,
    }


def report(result: dict[str, Any]) -> None:
    print(f"{result['detector']}  (median {result['median_ms']:.1f} ms per message)")
    for name, s in [("overall", result["overall"]), *result["by_source"].items()]:
        caught = f"{s['attacks_caught']}/{s['attacks']}" if s["attacks"] else "-"
        blocked = f"{s['normal_blocked']}/{s['normal']}"
        print(f"  {name:8} attacks caught {caught:>7}   normal blocked {blocked}")
    written = result["by_source"].get("written", {})
    if written.get("false_positives"):
        print("  written false positives:", ", ".join(written["false_positives"]))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--detector", choices=sorted(DETECTORS), default="patterns")
    args = parser.parse_args()
    result = run(args.detector)
    report(result)
    RESULTS.mkdir(exist_ok=True)
    out = RESULTS / f"injection-{result['date']}-{args.detector}.json"
    out.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n")
    print(f"wrote {out.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
