# Tramplin Backend

API учебной платформы: курсы, уроки, тесты, прогресс, authoring, OAuth,
S3-файлы, AI-ассистент и запуск алгоритмических задач.

Стек: Python 3.14, FastAPI, Pydantic, SQLAlchemy, PostgreSQL, Redis, RabbitMQ,
Alembic и uv.

## Быстрый старт

Нужны Python `>=3.14,<3.15`, [uv](https://docs.astral.sh/uv/) и Docker Compose.

```bash
cp .env.dev.example .env
make install
make up
make migrate
make seed
make run
```

В `.env` обязательно заполните `JWT_SECRET`, `GITHUB_CLIENT_ID` и
`GITHUB_CLIENT_SECRET`. Для локального RustFS используйте:

```dotenv
S3_ACCESS_KEY=tramplin
S3_SECRET_KEY=tramplin-dev-secret
S3_ENDPOINT_URL=http://localhost:9000
S3_PUBLIC_URL=http://localhost:9000/tramplin
```

После запуска:

- API — `http://localhost:8000/api/v1`
- Swagger — `http://localhost:8000/docs`
- liveness — `http://localhost:8000/api/v1/health`
- readiness — `http://localhost:8000/api/v1/health/ready`
- RustFS Console — `http://localhost:9001/rustfs/console/` (логин `tramplin` / `tramplin-dev-secret`)

## Команды

```bash
make run                 # API с autoreload
make check               # Ruff, mypy и pytest
make revision m="name"   # создать Alembic-миграцию
make migrate             # применить миграции
make seed                # загрузить demo-данные
make down                # остановить локальные сервисы
```

Тестовое покрытие должно быть не ниже 90%.

## Конфигурация

Настройки читаются из переменных окружения. Шаблоны находятся в
[`.env.dev.example`](.env.dev.example) для разработки и
[`.env.example`](.env.example) для деплоя; полный список определён в
[`src/tramplin/core/config.py`](src/tramplin/core/config.py).

Основные группы:

- `DATABASE_URL`, `REDIS_URL`, `RABBITMQ_URL`
- `JWT_*`, `GITHUB_*`, `YANDEX_*`
- `S3_*`, `ASSET_MAX_BYTES`
- `LLM_*`
- `PISTON_URL`, `ALGORITHM_*`

Если `LLM_MODEL` или `LLM_API_KEY` пусты, AI-ассистент отключён. Длительности
принимаются в секундах или ISO 8601 (`900`, `PT15M`, `P30D`).

## Структура

```text
src/tramplin/
  api/             HTTP-роутеры и схемы
  services/        бизнес-логика и порты
  infrastructure/  PostgreSQL, Redis, S3, OAuth, LLM и Piston
  models/          SQLAlchemy-модели
  core/            конфигурация, DI и безопасность
  main.py          FastAPI application factory
  worker.py        RabbitMQ algorithm worker
alembic/            миграции
scripts/            demo seed
tests/              unit, repository и API-тесты
```

Направление зависимостей: `API → services ← infrastructure`. Сервисы не зависят
от FastAPI, а внешние реализации подключаются через Dishka.

Основные маршруты находятся под `/api/v1`:

- `/auth`, `/tracks`, `/courses`, `/lessons`, `/quizzes`
- `/progress`, `/assets`, `/tutor`
- `/authoring` и `/admin`

## Docker

Локальный [`dev.docker-compose.yml`](dev.docker-compose.yml) поднимает PostgreSQL,
Redis и RustFS. Полный набор вместе с API и worker:

```bash
docker compose -f dev.docker-compose.yml --profile full up --build
```

RabbitMQ и Piston предоставляет соседний репозиторий `infra` через общую сеть
`tramplin-edge`.

Staging/production используют [`docker-compose.yml`](docker-compose.yml):

```bash
cp .env.example .env.runtime
make staging-config
make staging-up
```

Compose поднимает PostgreSQL и Redis, запускает одноразовую миграцию, затем API и
worker и ждёт их healthchecks. `make staging-down` останавливает контейнеры, но
сохраняет volumes.

Cloud S3 bucket, DNS, TLS, backups, RabbitMQ, Piston и сеть `tramplin-edge`
подготавливаются отдельно.

## CI/CD

Pipeline выполняет quality/security checks, собирает и сканирует один immutable
образ, затем разворачивает его на stage или production. API, worker и migration
service используют один `API_IMAGE`.

Нужные protected CI/CD variables:

- `SERVER_IP`, `SSH_PORT`, `SSH_USER`, `SSH_PRIVATE_KEY`
- `STAGE_ENV`, `PROD_ENV` типа File
- `STAGE_URL`, `PROD_URL`

Ветки `stage` и `main` разворачиваются как отдельные Compose-проекты
`tramplin-stage` и `tramplin-prod`. При ошибке job печатает состояние и последние
логи проекта.

## Документация

- [Продуктовые спецификации](https://gitlab.com/tramplin1/specs) — бизнес-ценность,
  продукты и пользовательские кейсы.
- [PRD авторинга алгоритмических задач через MCP](https://gitlab.com/tramplin1/mcp-server/-/blob/main/docs/algorithm-authoring-prd.md)
