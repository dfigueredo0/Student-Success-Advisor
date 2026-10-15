"""prerequisite trees on catalog_course

Revision ID: 0003
Revises: 0002
Create Date: 2026-10-14

`prereq_tree` is `prerequisites` parsed by domain.prereq.parse at load time (and/or/course/
course_range/test/unparsed); NULL when the course has no prerequisites. check_prerequisites
evaluates it with domain.prereq.evaluate. Rerun load_catalog.py after upgrading to fill it.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("ALTER TABLE catalog_course ADD COLUMN prereq_tree jsonb")


def downgrade() -> None:
    op.execute("ALTER TABLE catalog_course DROP COLUMN prereq_tree")
