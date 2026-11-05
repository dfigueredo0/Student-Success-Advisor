"""Write VerifierRun rows. A failed write is logged, never raised: the
student still gets the answer the verifier produced."""

import json
import logging
from collections.abc import Callable
from typing import Any

from sqlalchemy import text

from schemas.logs import VerifierRun
from tools.advisor._db import engine

log = logging.getLogger("ssa.verifier_log")

# Tools whose every call is logged as a VerifierRun -> the plan that call checked.
VERIFIERS: dict[str, Callable[[dict[str, Any]], dict[str, Any]]] = {
    "check_consequences": lambda args: {"drop": args["course"]},
}

_INSERT = text(
    "INSERT INTO verifier_run (run_id, intent, input_state, candidate_plan, verifier, passed, "
    "failure_reasons, retry_index, model_id, prompt_version, created_at) VALUES (:run_id, "
    ":intent, CAST(:input_state AS jsonb), CAST(:candidate_plan AS jsonb), :verifier, :passed, "
    ":failure_reasons, :retry_index, :model_id, :prompt_version, :created_at)"
)


def log_verifier_run(run: VerifierRun) -> None:
    # TODO: security - input_state holds a student's course lists and grades, and
    # memory.retention does not purge this table. Needs a retention/consent rule before the
    # pilot (keep synthetic runs only, or purge with the conversation).
    row = run.model_dump()
    row["input_state"] = json.dumps(row["input_state"])
    row["candidate_plan"] = json.dumps(row["candidate_plan"])
    try:
        with engine().begin() as conn:
            conn.execute(_INSERT, row)
    except Exception:
        log.exception("verifier_run write failed for %s", run.verifier)


def verifier_run(
    call: dict[str, Any], intent: str, model_id: str | None, prompt_version: str | None
) -> VerifierRun | None:
    """The record for one tools.guard.call_tool entry; None when it is not a finished verifier
    call (another tool, or one that raised)."""
    plan = VERIFIERS.get(call["name"])
    if plan is None or "result" not in call:
        return None
    reasons = call["result"].get("reasons", [])
    return VerifierRun(
        intent=intent,
        input_state=call["args"],
        candidate_plan=plan(call["args"]),
        verifier=call["name"],
        passed=not reasons,
        failure_reasons=reasons,
        model_id=model_id,
        prompt_version=prompt_version,
    )
