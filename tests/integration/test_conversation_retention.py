"""Old conversations are deleted; recent ones are kept."""

import uuid
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta

import pytest
from langgraph.checkpoint.base import empty_checkpoint
from langgraph.checkpoint.postgres import PostgresSaver

from memory.retention import delete_stale_conversations
from settings import Settings


@pytest.fixture
def saver(settings: Settings) -> Iterator[PostgresSaver]:
    with PostgresSaver.from_conn_string(settings.database_url.replace("+psycopg", "")) as s:
        s.setup()
        yield s


def save_conversation(saver: PostgresSaver, last_active: datetime) -> str:
    """A conversation whose newest checkpoint is from `last_active`."""
    thread_id = f"retention-test-{uuid.uuid4().hex}"
    checkpoint = empty_checkpoint()
    checkpoint["ts"] = last_active.isoformat()
    config = {"configurable": {"thread_id": thread_id, "checkpoint_ns": ""}}
    saver.put(config, checkpoint, {}, {})
    return thread_id


def exists(saver: PostgresSaver, thread_id: str) -> bool:
    return saver.get_tuple({"configurable": {"thread_id": thread_id}}) is not None


def test_only_conversations_past_the_limit_are_deleted(saver: PostgresSaver) -> None:
    now = datetime.now(UTC)
    old = save_conversation(saver, now - timedelta(days=3))
    recent = save_conversation(saver, now - timedelta(minutes=5))
    try:
        deleted = delete_stale_conversations(saver, timedelta(hours=24), now=now)
        assert old in deleted and recent not in deleted
        assert not exists(saver, old)
        assert exists(saver, recent)
    finally:
        saver.delete_thread(recent)
