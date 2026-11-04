"""What traces may say about a conversation.

With no accounts, a conversation ID works like a password: whoever has it can continue
that conversation. Langfuse groups traces by session, so traces carry a one-way hash of
the ID instead of the ID itself.
"""

import hashlib


def trace_session_id(thread_id: str) -> str:
    """Stable per conversation, but the conversation ID can't be read back from it."""
    return hashlib.sha256(thread_id.encode()).hexdigest()[:32]
