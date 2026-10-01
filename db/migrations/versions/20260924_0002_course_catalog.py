"""course catalog: terms, courses (pgvector embeddings), sections

Revision ID: 0002
Revises: 0001
Create Date: 2026-09-24

Loaded weekly from the Banner scraper by pipelines/ingest/load_catalog.py.
`catalog_course.embedding` is vector(768) to match the default embedding model
(nomic-embed-text); changing models with a different width needs a new migration.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE catalog_term (
            code        text PRIMARY KEY,
            name        text NOT NULL,
            scraped_at  timestamptz NOT NULL
        )
        """
    )
    op.execute(
        """
        CREATE TABLE catalog_course (
            code                  text PRIMARY KEY,          -- 'CS 450'
            subject               text NOT NULL,
            number                text NOT NULL,
            title                 text NOT NULL,
            description           text NOT NULL DEFAULT '',
            credit_hours          numeric(5, 2),
            credit_hours_max      numeric(5, 2),
            lecture_hours         numeric(5, 2),
            lab_hours             numeric(5, 2),
            other_hours           numeric(5, 2),
            levels                text[] NOT NULL DEFAULT '{}',
            schedule_types        text[] NOT NULL DEFAULT '{}',
            department            text NOT NULL DEFAULT '',
            attributes            text[] NOT NULL DEFAULT '{}',
            prerequisites         text NOT NULL DEFAULT '',
            prerequisite_courses  text[] NOT NULL DEFAULT '{}',
            restrictions          text NOT NULL DEFAULT '',
            catalog_term          text NOT NULL REFERENCES catalog_term (code),
            content_hash          text NOT NULL,
            embedding             vector(768),
            embedding_model       text,
            embedded_hash         text,  -- content_hash the embedding was built from
            updated_at            timestamptz NOT NULL DEFAULT now()
        )
        """
    )
    op.execute("CREATE INDEX catalog_course_subject_idx ON catalog_course (subject, number)")
    op.execute(
        "CREATE INDEX catalog_course_prereq_idx ON catalog_course USING gin (prerequisite_courses)"
    )
    op.execute(
        "CREATE INDEX catalog_course_embedding_idx ON catalog_course "
        "USING hnsw (embedding vector_cosine_ops)"
    )
    op.execute(
        """
        CREATE TABLE catalog_section (
            term_code           text NOT NULL REFERENCES catalog_term (code) ON DELETE CASCADE,
            crn                 integer NOT NULL,
            course_code         text NOT NULL REFERENCES catalog_course (code) ON DELETE CASCADE,
            section             text NOT NULL,
            special_title       text NOT NULL DEFAULT '',
            levels              text[] NOT NULL DEFAULT '{}',
            cross_list          text[] NOT NULL DEFAULT '{}',
            registration_dates  text NOT NULL DEFAULT '',
            campus              text NOT NULL DEFAULT '',
            schedule_type       text NOT NULL DEFAULT '',
            instruction_method  text NOT NULL DEFAULT '',
            credit_hours        numeric(5, 2),
            capacity            integer,
            enrolled            integer,
            remaining           integer,
            waitlist_capacity   integer,
            waitlist_enrolled   integer,
            waitlist_remaining  integer,
            instructors         text[] NOT NULL DEFAULT '{}',
            meetings            jsonb NOT NULL DEFAULT '[]',
            prerequisites       text NOT NULL DEFAULT '',
            restrictions        text NOT NULL DEFAULT '',
            mutual_exclusion    text[] NOT NULL DEFAULT '{}',
            scraped_at          timestamptz NOT NULL,
            PRIMARY KEY (term_code, crn)
        )
        """
    )
    op.execute(
        "CREATE INDEX catalog_section_course_idx ON catalog_section (course_code, term_code)"
    )

def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS catalog_section")
    op.execute("DROP TABLE IF EXISTS catalog_course")
    op.execute("DROP TABLE IF EXISTS catalog_term")
