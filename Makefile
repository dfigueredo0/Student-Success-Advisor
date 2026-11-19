# Clean checkout -> green:  make install && make up && make test

# Ollama runs on this machine's GPU by default (infra/gpu.py). Force one with GPU=cpu|amd|nvidia.
# CI sets COMPOSE_FILES itself, so it never runs the detection and stays on CPU.
COMPOSE_FILES ?= -f infra/docker-compose.yml $(shell uv run --no-project python infra/gpu.py $(GPU))
COMPOSE        = docker compose $(COMPOSE_FILES) --env-file .env
PYTEST        := uv run pytest

.PHONY: help install up down clean ps logs migrate test test-unit test-agent test-integration \
        test-eval test-e2e lint fmt ci new-secrets ingest-catalog ingest-requirements api api-debug harness keys

help: 
	@uv run python -c "import re; [print(f'  {m[0]:<18} {m[1]}') for m in re.findall(r'^([a-z.-]+):.*?## (.*)$$', open('Makefile').read(), re.M)]"

install: 
	uv sync --locked

.env:  ## Create .env with random passwords and keys (runs on the first `make up`)
	uv run --no-project python infra/make_env.py

# Postgres sets its password only when its data folder is first created, so a new password is
# applied with ALTER USER (over the container's local socket, which needs none). The Langfuse
# and LiteLLM databases and the trace stores are emptied, because their stored keys were made
# with the old secrets; the ssa database (catalog, conversations) and Ollama's models are kept.
new-secrets:  ## Replace every password and key in .env (keeps your other settings and course data)
	@test -f .env || { echo "no .env yet: just run make up"; exit 1; }
	docker compose -p ssa down
	mv .env .env.bak
	uv run --no-project python infra/make_env.py --keep .env.bak
	$(COMPOSE) up -d --wait postgres
	PW=$$(sed -n 's/^POSTGRES_PASSWORD=//p' .env); \
	docker compose -p ssa exec -T postgres psql -U postgres -d ssa -v ON_ERROR_STOP=1 \
	  -c "ALTER USER postgres PASSWORD '$$PW'" \
	  -c "DROP DATABASE IF EXISTS langfuse WITH (FORCE)" -c "CREATE DATABASE langfuse" \
	  -c "DROP DATABASE IF EXISTS litellm WITH (FORCE)" -c "CREATE DATABASE litellm"
	$(COMPOSE) down
	docker volume rm -f ssa_clickhouse_data ssa_clickhouse_logs ssa_minio_data
	$(MAKE) up
	rm .env.bak
	@echo "New secrets are in .env. Langfuse login: dev@ssa.local + LANGFUSE_INIT_USER_PASSWORD"

up: .env 
	$(COMPOSE) up -d --wait --wait-timeout 900
	$(MAKE) migrate
	$(MAKE) keys

keys:  ## Create or update the gateway's per-agent API keys
	uv run python infra/litellm/seed_keys.py

down: 
	$(COMPOSE) down

clean:
	$(COMPOSE) down -v

ps:
	$(COMPOSE) ps

logs:
	$(COMPOSE) logs -f --tail 100

migrate: 
	uv run alembic upgrade head

test: test-unit test-agent test-integration  ## Unit + agent + integration suites (needs `make up`)

test-unit: 
	$(PYTEST) -m unit

test-agent:  ## Agent suite: real graph + scripted FakeLLM, no network
	$(PYTEST) -m agent

test-integration: 
	$(PYTEST) -m integration

test-eval: 
	$(PYTEST) -m eval

test-e2e: 
	$(PYTEST) -m e2e

api:  ## Chat API on :8000 (needs `make up`)
	uv run uvicorn api.main:app --reload --port 8000

api-debug: export DEBUG=true
api-debug:  ## Chat API that prints every router/agent/merge step to the terminal
	uv run uvicorn api.main:app --reload --port 8000

harness:  ## Streamlit debug page for the chat API
	uv run --group harness streamlit run frontend/harness/app.py --server.address 127.0.0.1 --server.headless true

ingest-catalog:  ## Scrape the IIT Banner catalog + schedule and load it into pgvector (weekly cron)
	uv run --group ingest python pipelines/ingest/illinoistech_banner_scraper.py
	uv run python pipelines/ingest/load_catalog.py

lint:
	uv run ruff check .
	uv run ruff format --check .
	uv run lint-imports

fmt: 
	uv run ruff check --fix .
	uv run ruff format .

ingest-requirements:  ## Scrape degree requirements + core curriculum from catalog.iit.edu into data/raw/degree_requirements/
	uv run --group ingest python pipelines/ingest/degree_requirements.py
	uv run --group ingest python pipelines/ingest/core_curriculum.py
