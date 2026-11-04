from api.tracing import trace_session_id


def test_trace_session_id_groups_a_conversation_without_storing_its_id() -> None:
    thread_id = "3f9a1c0e7b2d4e8f9a6c5b4d3e2f1a0b"
    session = trace_session_id(thread_id)
    assert session == trace_session_id(thread_id)  # every trace of a conversation groups
    assert session != trace_session_id("another-conversation")
    assert thread_id not in session and thread_id[:8] not in session
