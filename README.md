# Student-Success-Advisor

An intelligent advising agent capable of 24/7 interaction with students, providing
personalized academic guidance.

A LangGraph orchestrator routes each student message to an advisor agent, which answers
from deterministic tools over the IIT course catalog and cites its sources. Every model
call goes through a LiteLLM gateway with guardrails; everything runs locally in Docker
Compose.

## Prerequisites

- [Docker](https://docs.docker.com/get-docker/) with Compose v2 (Docker Desktop on Windows/macOS)
- [uv](https://docs.astral.sh/uv/getting-started/installation/) (installs Python 3.12 for you)
- `make`
- ~15 GB free disk for images and local models

## Quick start

```bash
make install   # Python deps into .venv
make up        # start the stack, run migrations, create gateway keys
make api       # chat API + web UI on http://localhost:8000
```

`make up` copies `.env.example` to `.env` if you don't have one, then waits for every
service's healthcheck. **The first run takes several minutes** while Ollama downloads the
chat and embedding models (it waits up to 15 minutes). Later runs start in under a minute.

Then open **http://localhost:8000** and ask something like "Tell me about CS 331".

### Load course data (first time)

A fresh database has no courses, so the advisor can't answer catalog questions until you
load them:

```bash
make ingest-catalog   # scrape IIT Banner (all open terms), load into Postgres, embed
```

The full scrape takes a while. For a quick dev load, scrape a few subjects for one term:

```bash
uv run --group ingest python pipelines/ingest/illinoistech_banner_scraper.py --terms 202710 --subjects CS MATH
uv run python pipelines/ingest/load_catalog.py
```

Snapshots land in `data/raw/banner/` (gitignored). The loader is safe to rerun.

## What's running

All ports are bound to `localhost` only.

| Service             | URL                        | Notes                                                                            |
| ------------------- | -------------------------- | -------------------------------------------------------------------------------- |
| Web UI              | http://localhost:8000      | `frontend/` served by the API (`make api`)                                       |
| Chat API            | http://localhost:8000/chat | `POST`; interactive docs at http://localhost:8000/docs                           |
| Debug harness       | http://localhost:8501      | `make harness` (Streamlit); shows state, tool calls, trace links                 |
| Langfuse            | http://localhost:3000      | Traces for every request. Login:`dev@ssa.local` / `ssa-dev-password`             |
| LiteLLM gateway     | http://localhost:4000      | Every model call goes through here; needs a key from`.env`                       |
| Postgres + pgvector | `localhost:5433`           | `postgres` / `postgres`, database `ssa` (5433 so a local Postgres can keep 5432) |
| Ollama              | not exposed                | Reachable only by the gateway inside the compose network                         |

## For UI/UX work

The web UI is plain HTML/CSS/JS in `frontend/` (`index.html`, `app.js`, `styles.css`).

1. `make up`, then `make api`.
2. Open http://localhost:8000 and edit the files in `frontend/`. Refresh the browser to see
   changes; no build step.

Open the UI through the API at port 8000, not by double-clicking `index.html` or using a
separate dev server. The page calls `fetch('/chat')` with a relative URL, so it only reaches
the API when the API serves it.

The chat endpoint:

```http
POST /chat
Content-Type: application/json

{"message": "Can I take CS 450?", "thread_id": null}
```

Send back the returned `thread_id` to continue the same conversation. The response includes
`answer` (plain text, so render it as text, not HTML), `citations` (`source`, `url`,
`quote`), `tool_calls`, and `trace_url`. See http://localhost:8000/docs for the full schema.

The student data in `app.js` is mock data for now. Don't send course lists or student IDs
from the browser; the advisor will get them from the logged-in student once auth exists.

## For backend and agent work

```bash
make api-debug   # same API, prints every router/agent/merge step to the terminal
make harness     # Streamlit debug page (run alongside make api)
```

- Code lives in top-level packages under `src/` (`agents`, `orchestrator`, `tools`, `domain`, ...).
- Configuration comes from `.env` (see `.env.example` and `src/settings.py`).
- Model IDs live only in `infra/litellm/config.yml`; code uses aliases like `local-llm`.
- Schema changes go through Alembic: add a revision in `db/migrations/versions/`, then `make migrate`.

## Tests and lint

```bash
make test-unit          # fast, no Docker needed
make test-integration   # needs `make up`
make test               # both
make lint               # ruff + formatting + import-layer contracts (CI runs this)
make fmt                # auto-fix lint and formatting
```

Run `make fmt` and `make lint` before pushing.

## Stopping and resetting

```bash
make down    # stop the stack, keep data
make clean   # stop and delete all volumes (database, traces, downloaded models)
make ps      # service status
make logs    # follow logs
```
