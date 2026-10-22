"""Conversation retention: delete conversations nobody has touched for a while.

There are no accounts and no memory export in the early pilot, so a conversation only
matters while the student is using it. Old ones are deleted, including the courses,
grades and major a transcript upload put into them.
"""

from datetime import UTC, datetime, timedelta

from langgraph.checkpoint.postgres import PostgresSaver

# A conversation's last activity is its newest checkpoint.
_STALE_THREADS = """
    SELECT thread_id
    FROM checkpoints
    GROUP BY thread_id
    HAVING max((checkpoint ->> 'ts')::timestamptz) < %s
"""


def delete_stale_conversations(
    saver: PostgresSaver, max_age: timedelta, now: datetime | None = None
) -> list[str]:
    """Delete every conversation with no activity for `max_age`; return their IDs."""
    cutoff = (now or datetime.now(UTC)) - max_age
    with saver.lock, saver.conn.cursor() as cur:
        cur.execute(_STALE_THREADS, (cutoff,))
        stale = [row["thread_id"] for row in cur.fetchall()]
    for thread_id in stale:
        # Removes the conversation from all three checkpoint tables.
        saver.delete_thread(thread_id)
    return stale
