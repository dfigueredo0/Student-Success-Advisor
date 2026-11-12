"""O*NET occupations and the software skills employers ask for in each

Revision ID: 0005
Revises: 0004
Create Date: 2026-11-12

Filled by pipelines/ingest/load_onet.py from data/onet/*.csv (O*NET 31.0, CC BY 4.0). Only
skills flagged Hot Technology or In Demand are loaded; `in_demand` is false for one that is
Hot Technology only. The Career agent reads resumes with the distinct `example` names
(tools.career.onet.vocabulary) and ranks occupations by them (match_occupations).
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE onet_occupation (
            code     text PRIMARY KEY,
            title    text NOT NULL,
            job_zone smallint
        )
        """
    )
    op.execute(
        """
        CREATE TABLE onet_software_skill (
            soc_code  text NOT NULL REFERENCES onet_occupation (code) ON DELETE CASCADE,
            example   text NOT NULL,
            in_demand boolean NOT NULL,
            PRIMARY KEY (soc_code, example)
        )
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE onet_software_skill")
    op.execute("DROP TABLE onet_occupation")
