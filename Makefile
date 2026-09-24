# Clean checkout -> green:  make install && make up && make test

COMPOSE_FILES ?= -f infra/docker-compose.yml
COMPOSE       := docker compose $(COMPOSE_FILES) --env-file .env
PYTEST        := uv run pytest

.PHONY: help install up down clean ps logs migrate test test-unit test-integration \
        test-eval test-e2e lint fmt ci

help: 
	@uv run python -c "import re; [print(f'  {m[0]:<18} {m[1]}') for m in re.findall(r'^([a-z.-]+):.*?## (.*)$$', open('Makefile').read(), re.M)]"

install: 
	uv sync --locked
	uv run pre-commit install

.env: 
	uv run python -c "import shutil; shutil.copyfile('.env.example', '.env')"

up: .env 
	$(COMPOSE) up -d --wait --wait-timeout 900
	$(MAKE) migrate

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

test: test-unit test-integration  ## Unit + integration suites (needs `make up`)

test-unit: 
	$(PYTEST) -m unit

test-integration: 
	$(PYTEST) -m integration

test-eval: 
	$(PYTEST) -m eval

test-e2e: 
	$(PYTEST) -m e2e

lint:
	uv run ruff check .
	uv run ruff format --check .
	uv run lint-imports

fmt: 
	uv run ruff check --fix .
	uv run ruff format .
