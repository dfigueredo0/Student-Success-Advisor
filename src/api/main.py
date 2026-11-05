import asyncio
import logging
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from datetime import timedelta
from pathlib import Path

from fastapi import FastAPI
from fastapi.concurrency import run_in_threadpool
from fastapi.staticfiles import StaticFiles
from langfuse import Langfuse
from langgraph.checkpoint.postgres import PostgresSaver

from api.routes import chat, saved_chat, transcript
from api.tracing import mask_trace
from memory.retention import delete_stale_conversations
from orchestrator.graph import build_graph
from settings import get_settings

FRONTEND_DIR = Path(__file__).resolve().parents[2] / "frontend"
PURGE_EVERY = timedelta(hours=1)

log = logging.getLogger(__name__)


async def purge_old_conversations(saver: PostgresSaver, max_age: timedelta) -> None:
    """Delete stale conversations at startup, then every PURGE_EVERY."""
    while True:
        try:
            deleted = await run_in_threadpool(delete_stale_conversations, saver, max_age)
            if deleted:
                log.info("deleted %d conversations older than %s", len(deleted), max_age)
        except Exception:  # a failed purge must not take the API down; retry next round
            log.exception("deleting old conversations failed")
        await asyncio.sleep(PURGE_EVERY.total_seconds())


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    s = get_settings()
    langfuse = Langfuse(
        public_key=s.langfuse_public_key,
        secret_key=s.langfuse_secret_key.get_secret_value(),
        host=s.langfuse_host,
        mask=mask_trace,
    )
    # one checkpointer connection behind PostgresSaver's lock;
    # move to psycopg_pool.ConnectionPool when concurrent chats matter.
    with PostgresSaver.from_conn_string(s.database_url.replace("+psycopg", "")) as saver:
        saver.setup()  # idempotent; creates the checkpoint tables on first run
        app.state.graph = build_graph(saver)
        if s.debug:  # dev-only; imported lazily so production never loads it
            from api import debug

            debug.configure_logging()
            app.state.graph = debug.TracedGraph(app.state.graph)
        purge = asyncio.create_task(
            purge_old_conversations(saver, timedelta(hours=s.conversation_ttl_hours))
        )
        yield
        purge.cancel()
    langfuse.flush()


app = FastAPI(title="Student Success Advisor", lifespan=lifespan)
app.include_router(chat.router)
app.include_router(transcript.router)
app.include_router(saved_chat.router)
# Mounted last so /chat and /docs win; html=True serves index.html at /.
app.mount("/", StaticFiles(directory=FRONTEND_DIR, html=True), name="frontend")
