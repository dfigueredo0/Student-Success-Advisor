"""Log records that later become training data (BuildPlan Phase 12: DPO pairs, GRPO rewards)."""

from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field


class VerifierRun(BaseModel):
    """One verifier call (CLAUDE.md rule 11): table verifier_run, migration 0004."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    run_id: UUID = Field(default_factory=uuid4)
    intent: str
    input_state: dict[str, Any]  # the verifier's arguments
    candidate_plan: dict[str, Any]  # what was checked, e.g. {"drop": "CS 351"}
    verifier: str  # tool name
    passed: bool
    failure_reasons: list[str] = []  # stable codes, e.g. prereq_blocked:CS 450
    retry_index: int = 0
    model_id: str | None = None  # gateway alias of the model in the loop
    prompt_version: str | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
