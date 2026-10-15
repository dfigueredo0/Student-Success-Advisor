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

`.env` is only created once. When `.env.example` gains new lines after a pull, add them to
your `.env` by hand, or delete `.env` and run `make up` again if you never edited it.

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
| LiteLLM dashboard   | http://localhost:4000/ui   | Keys, usage, failed and blocked requests. Login: `admin` / `LITELLM_MASTER_KEY`   |
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
- Code uses model aliases like `local-llm`, never real model names. To change a model,
  update `infra/litellm/config.yml` (what the gateway asks Ollama for) **and**
  `OLLAMA_MODEL` / `EMBEDDING_MODEL` in `.env.example` (what Ollama downloads). If they
  disagree, every model call fails.
- Schema changes go through Alembic: add a revision in `db/migrations/versions/`, then `make migrate`.

## AI gateway and keys

Every model call (chat and embeddings) goes through the LiteLLM gateway on port 4000.
Nothing calls Ollama directly; it has no port outside Docker.

On every request the gateway:

- checks the caller's key (`401` without a valid one)
- blocks known prompt-injection phrases (`infra/litellm/injection_guard.py`)
- removes student IDs and student emails from answers, and refuses streaming
  (`infra/litellm/output_guard.py`)
- logs the request to Langfuse

Each feature gets its own key that can only do its job, defined in
`infra/litellm/seed_keys.py` and created by `make up` (or `make keys`):

| Key     | Setting                        | Can do                |
| ------- | ------------------------------ | --------------------- |
| router  | `settings.litellm_router_key`  | chat with `local-llm` |
| catalog | `settings.litellm_catalog_key` | embeddings only       |

The master key (`LITELLM_MASTER_KEY`) is for admin work only (`make keys`, the
dashboard). Don't use it in app code. If a new feature needs the model, ask Ronal for its
own key.

To call the gateway from code, use the OpenAI-style API:

```python
resp = httpx.post(
    f"{s.litellm_base_url}/v1/chat/completions",
    headers={"Authorization": f"Bearer {s.litellm_router_key.get_secret_value()}"},
    json={"model": "local-llm", "messages": messages},
)
answer = resp.json()["choices"][0]["message"]["content"]
```

`src/orchestrator/router.py` (chat) and `src/retrieval/catalog_search.py` (embeddings) are
working examples.

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

After `make clean` the database is empty again; reload the catalog (see
[Load course data](#load-course-data-first-time)).
