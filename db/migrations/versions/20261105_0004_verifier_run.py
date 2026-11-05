"""verifier_run: one row per verifier call (logging contract, CLAUDE.md rule 11)

Revision ID: 0004
Revises: 0003
Create Date: 2026-11-05

Every check_consequences (later validate_plan) call writes one row: what was checked, whether
it passed and the stable reason codes when it did not. The future DPO/GRPO dataset. Written by
tools.verifier_log; never updated.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE verifier_run (
            run_id          uuid PRIMARY KEY,
            intent          text NOT NULL,
            input_state     jsonb NOT NULL,
            candidate_plan  jsonb NOT NULL,
            verifier        text NOT NULL,
            passed          boolean NOT NULL,
            failure_reasons text[] NOT NULL DEFAULT '{}',
            retry_index     integer NOT NULL DEFAULT 0,
            model_id        text,
            prompt_version  text,
            created_at      timestamptz NOT NULL DEFAULT now()
        )
        """
    )
    op.execute("CREATE INDEX verifier_run_verifier_idx ON verifier_run (verifier, created_at)")


def downgrade() -> None:
    op.execute("DROP TABLE verifier_run")
