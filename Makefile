DEV_COMPOSE = docker compose -f dev.docker-compose.yml
DEPLOY_COMPOSE = docker compose --env-file .env.runtime

.PHONY: install up down migrate seed revision lint format typecheck test test-integration check run \
	staging-config staging-up staging-down

install:
	uv sync

up:
	$(DEV_COMPOSE) up -d postgres redis rustfs rustfs-init

down:
	$(DEV_COMPOSE) down

migrate:
	uv run alembic upgrade head

seed:
	uv run python scripts/seed_demo.py

revision:
	uv run alembic revision --autogenerate -m "$(m)"

lint:
	uv run ruff check src tests scripts alembic
	uv run ruff format --check src tests scripts alembic

format:
	uv run ruff format src tests scripts alembic

typecheck:
	uv run mypy src tests scripts alembic

test:
	uv run pytest

# Только интеграционные: TEST_DATABASE_URL или Docker для testcontainers.
test-integration:
	uv run pytest tests/integration --no-cov

check: lint typecheck test

run:
	uv run uvicorn tramplin.main:create_app --factory --reload

staging-config:
	$(DEPLOY_COMPOSE) config --quiet

staging-up:
	$(DEPLOY_COMPOSE) up -d --build --remove-orphans --wait --wait-timeout 60

staging-down:
	$(DEPLOY_COMPOSE) down
