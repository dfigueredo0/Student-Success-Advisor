from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from langfuse import Langfuse
from langgraph.checkpoint.postgres import PostgresSaver

from api.routes import chat
from orchestrator.graph import build_graph
from settings import get_settings

FRONTEND_DIR = Path(__file__).resolve().parents[2] / "frontend"

@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    s = get_settings()
    langfuse = Langfuse(
        public_key=s.langfuse_public_key,
        secret_key=s.langfuse_secret_key.get_secret_value(),
        host=s.langfuse_host,
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
        yield
    langfuse.flush()

app = FastAPI(title="Student Success Advisor", lifespan=lifespan)
app.include_router(chat.router)
# Mounted last so /chat and /docs win; html=True serves index.html at /.
app.mount("/", StaticFiles(directory=FRONTEND_DIR, html=True), name="frontend")
