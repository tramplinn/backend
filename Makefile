STAGING_COMPOSE = docker compose --env-file .env.runtime -f docker-compose.staging.yml

.PHONY: install up down migrate seed revision lint format typecheck test check run \
	staging-config staging-build staging-infra staging-migrate staging-up staging-down

install:
	uv sync

up:
	docker compose up -d postgres redis minio minio-init

down:
	docker compose down

migrate:
	uv run alembic upgrade head

seed:
	uv run python scripts/seed_demo.py

revision:
	uv run alembic revision --autogenerate -m "$(m)"

lint:
	uv run ruff check src tests scripts alembic

format:
	uv run ruff format src tests scripts alembic

typecheck:
	uv run mypy src tests scripts alembic

test:
	uv run pytest

check: lint typecheck test

run:
	uv run uvicorn tramplin.main:create_app --factory --reload

staging-config:
	$(STAGING_COMPOSE) config --quiet

staging-build:
	$(STAGING_COMPOSE) build api

staging-infra:
	$(STAGING_COMPOSE) up -d --wait --wait-timeout 60 postgres redis

staging-migrate:
	$(STAGING_COMPOSE) up -d --wait --wait-timeout 60 postgres redis
	$(STAGING_COMPOSE) run --rm --no-deps api alembic upgrade head

staging-up:
	$(STAGING_COMPOSE) up -d --build --wait --wait-timeout 60 api algorithm-worker

staging-down:
	$(STAGING_COMPOSE) down
