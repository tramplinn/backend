# Tramplin Backend

The platform's API: courses, lessons, quizzes, progress, authoring, OAuth, file
uploads, the AI assistant, and running algorithm problems.

Stack: Python 3.14, FastAPI, Pydantic, SQLAlchemy, PostgreSQL, Redis, RabbitMQ,
Alembic, uv.

## Quick start

You need Python 3.14, [uv](https://docs.astral.sh/uv/), and Docker Compose.

```bash
cp .env.dev.example .env
make install
make up
make migrate
make seed
make run
```

Set `JWT_SECRET`, `GITHUB_CLIENT_ID`, and `GITHUB_CLIENT_SECRET` in `.env`. For
the local RustFS storage:

```dotenv
S3_ACCESS_KEY=tramplin
S3_SECRET_KEY=tramplin-dev-secret
S3_ENDPOINT_URL=http://localhost:9000
S3_PUBLIC_URL=http://localhost:9000/tramplin
```

Then open:

- API — `http://localhost:8000/api/v1`
- Swagger — `http://localhost:8000/docs`
- health — `/api/v1/health` and `/api/v1/health/ready`
- RustFS Console — `http://localhost:9001/rustfs/console/` (`tramplin` / `tramplin-dev-secret`)

### With Docker

To run the API and worker in containers too:

```bash
docker compose -f dev.docker-compose.yml --profile full up --build
```

RabbitMQ and Piston come from the `infra` repository over the shared
`tramplin-edge` network.

## Commands

```bash
make run                 # API with autoreload
make check               # Ruff, mypy, pytest
make revision m="name"   # new Alembic migration
make migrate             # apply migrations
make seed                # load demo data
make down                # stop local services
```

Test coverage must stay at 90% or higher.

## Structure

```text
src/tramplin/
  api/             HTTP routers and schemas
  services/        business logic and ports
  infrastructure/  PostgreSQL, Redis, S3, OAuth, LLM, Piston
  models/          SQLAlchemy models
  core/            config, DI, security
  main.py          app factory
  worker.py        algorithm worker
alembic/            migrations
scripts/            demo seed
tests/              unit, repository, and API tests
```

Dependencies point inward: `API → services ← infrastructure`. Services know
nothing about FastAPI; implementations are wired in with Dishka.

Routes live under `/api/v1`: `/auth`, `/tracks`, `/courses`, `/lessons`,
`/quizzes`, `/progress`, `/assets`, `/tutor`, `/authoring`, `/admin`.

## Docs

- [Product specs](https://gitlab.com/tramplin1/specs)
- [PRD: authoring algorithm problems via MCP](https://gitlab.com/tramplin1/mcp-server/-/blob/main/docs/algorithm-authoring-prd.md)
