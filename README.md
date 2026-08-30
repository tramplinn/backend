# Tramplin Backend

API учебной платформы Tramplin: курсы и модули, уроки, тесты, прогресс,
преподавательский кабинет, администрирование и ассистент по материалам урока.

## Возможности

- публичный каталог треков и курсов;
- уроки с безопасным Markdown, подсветкой кода и interview-карточками;
- тесты с одиночным и множественным выбором, текстом, сопоставлением,
  группировкой и файловым ответом;
- прогресс по урокам, тестам, модулям и курсам;
- authoring API для преподавателей и администраторов;
- GitHub OAuth и собственные access/refresh-сессии;
- загрузка файлов в S3-совместимое хранилище;
- потоковый AI-ассистент урока с квотами;
- управление пользователями и учебными группами.

## Стек

- Python 3.13, FastAPI и Pydantic;
- SQLAlchemy async, PostgreSQL и Alembic;
- Redis для OAuth state, refresh-сессий и квот;
- Dishka для dependency injection;
- MinIO локально, S3 API в production;
- Ruff, mypy strict и pytest с coverage.

## Требования

- Python `>=3.13,<3.14`;
- [uv](https://docs.astral.sh/uv/);
- Docker с Compose plugin;
- GitHub OAuth App для проверки полного сценария входа.

## Быстрый старт

Создайте локальную конфигурацию:

```bash
cp .env.example .env
```

Минимально заполните `JWT_SECRET`, `GITHUB_CLIENT_ID` и
`GITHUB_CLIENT_SECRET`. Секрет JWT можно сгенерировать так:

```bash
openssl rand -hex 32
```

Для локального MinIO укажите в `.env`:

```dotenv
S3_ACCESS_KEY=tramplin
S3_SECRET_KEY=tramplin-dev-secret
S3_ENDPOINT_URL=http://localhost:9000
S3_PUBLIC_URL=http://localhost:9000/tramplin
```

Установите зависимости, поднимите инфраструктуру и подготовьте базу:

```bash
make install
make up
make migrate
make seed
```

Запустите API:

```bash
make run
```

После запуска доступны:

- API: `http://localhost:8000/api/v1`;
- Swagger UI: `http://localhost:8000/docs`;
- liveness: `http://localhost:8000/api/v1/health`;
- readiness PostgreSQL/Redis: `http://localhost:8000/api/v1/health/ready`;
- MinIO API: `http://localhost:9000`;
- MinIO Console: `http://localhost:9001`.

Swagger отключается при `ENVIRONMENT=production`.

## Команды

| Команда                  | Назначение                          |
| ------------------------ | ----------------------------------- |
| `make install`           | установить зависимости через uv     |
| `make up`                | поднять PostgreSQL, Redis и MinIO   |
| `make down`              | остановить compose-проект           |
| `make migrate`           | применить Alembic-миграции          |
| `make revision m="name"` | создать миграцию через autogenerate |
| `make seed`              | добавить идемпотентные demo-данные  |
| `make run`               | запустить Uvicorn с autoreload      |
| `make lint`              | проверить Ruff                      |
| `make format`            | отформатировать Python-код          |
| `make typecheck`         | запустить mypy strict               |
| `make test`              | запустить pytest с coverage         |
| `make check`             | выполнить lint, typecheck и test    |
| `make staging-config`    | проверить staging-конфигурацию      |
| `make staging-build`     | собрать production-образ API        |
| `make staging-infra`     | поднять staging PostgreSQL и Redis  |
| `make staging-migrate`   | применить staging-миграции          |
| `make staging-up`        | собрать и запустить staging API     |
| `make staging-down`      | остановить staging API              |

Перед передачей изменений запускайте:

```bash
make check
```

Минимальное покрытие, настроенное в `pyproject.toml`, — 90%.

## Конфигурация

Все настройки читаются из переменных окружения и `.env`.

| Группа       | Основные переменные                                                                            |
| ------------ | ---------------------------------------------------------------------------------------------- |
| Приложение   | `ENVIRONMENT`, `FRONTEND_BASE_URL`                                                             |
| PostgreSQL   | `DATABASE_URL`                                                                                 |
| Redis        | `REDIS_URL`                                                                                    |
| JWT          | `JWT_SECRET`, `JWT_ISSUER`, `ACCESS_TOKEN_TTL`, `REFRESH_TOKEN_TTL`                            |
| GitHub OAuth | `GITHUB_CLIENT_ID`, `GITHUB_CLIENT_SECRET`, `GITHUB_REDIRECT_URI`                              |
| S3           | `S3_BUCKET`, `S3_REGION`, `S3_ACCESS_KEY`, `S3_SECRET_KEY`, `S3_ENDPOINT_URL`, `S3_PUBLIC_URL` |
| Файлы        | `ASSET_MAX_BYTES`                                                                              |
| Ассистент    | `LLM_BASE_URL`, `LLM_API_KEY`, `LLM_MODEL`, `LLM_*_QUOTA`                                      |

Полный список и значения по умолчанию находятся в `.env.example` и
`src/tramplin/core/config.py`. Длительности принимаются в секундах (`900`) или
ISO 8601 (`PT15M`, `P30D`).

Если `LLM_MODEL` или `LLM_API_KEY` пусты, ассистент отключён, а его endpoint
возвращает 503. Остальная платформа продолжает работать.

## Архитектура

```text
src/tramplin/
  api/
    schemas/          Pydantic-контракты API
    v1/               FastAPI-роутеры по доменным областям
    dependencies.py   текущий пользователь и проверки ролей
    errors.py         преобразование доменных ошибок в HTTP
  services/           бизнес-сценарии без зависимости от FastAPI
  infrastructure/     PostgreSQL repositories, Redis, GitHub, S3 и LLM
  models/             SQLAlchemy-модели и enum
  core/               конфигурация, DI, безопасность и время
  main.py             фабрика FastAPI-приложения
alembic/              миграции базы данных
scripts/              служебные команды и demo seed
tests/                unit, repository и API-тесты
artifacts/            PRD, будущие ADR, designs и runbooks
```

Основное направление зависимостей:

```text
API → services → contracts
          ↑
infrastructure implements contracts
```

Сервисы не импортируют FastAPI и не знают о HTTP. Репозитории и внешние клиенты
подключаются через Dishka. Доменная ошибка наследуется от `AppError`, а единый
обработчик преобразует её в контракт:

```json
{
  "code": "machine_readable_code",
  "message": "Понятное сообщение",
  "details": {}
}
```

## Основные группы API

Все маршруты имеют префикс `/api/v1`.

| Группа                                        | Назначение                                           |
| --------------------------------------------- | ---------------------------------------------------- |
| `/auth/*`                                     | GitHub OAuth, refresh, logout и текущий пользователь |
| `/tracks`, `/courses`, `/lessons`, `/quizzes` | опубликованный учебный контент                       |
| `/progress/*`, `/quizzes/{id}/attempts`       | прогресс и попытки студента                          |
| `/authoring/*`                                | CRUD контента для teacher/admin                      |
| `/assets`                                     | загрузка и управление файлами                        |
| `/tutor/*`                                    | потоковый ассистент урока                            |
| `/admin/*`                                    | пользователи и группы                                |

Студенческий API тестов не возвращает правильные ответы. Они доступны только в
authoring API.

## Аутентификация

1. Frontend получает GitHub authorize URL через `/auth/github/login`.
2. Backend сохраняет одноразовый OAuth state в Redis.
3. Callback обменивает GitHub code на профиль; GitHub token не сохраняется.
4. Refresh-токен записывается в `httpOnly`, `SameSite=Lax` cookie с path
   `/api/v1/auth`.
5. Короткий access JWT передаётся в `Authorization: Bearer`.
6. Refresh ротируется атомарно: использованный токен нельзя применить повторно.

Связывание аккаунтов выполняется по `(provider, provider_id)`, а не по совпадению
email. Проверки ролей выполняются зависимостями `CurrentUser`, `TeacherUser` и
`AdminUser`; frontend-проверки ролей не считаются защитой API.

## Контент и обучение

### Markdown

Authoring API принимает `body_md`, а backend строит безопасный `body_html`.
Raw HTML отключён. Поддерживаются fenced code, подсветка и контейнеры `note`,
`warning`, `pitfall`, `spoiler`, `interview`.

Interview-карточка описывается так:

```markdown
:::interview
Вопрос
---

Ответ
:::
```

`POST /authoring/markdown/preview` использует тот же pipeline, что и сохранение.

### Тесты

Поддерживаются типы `single`, `multiple`, `text`, `matching`, `grouping` и `file`.
Ответы отправляются как:

```json
{
  "answers": {
    "question-uuid": "answer"
  }
}
```

Для `matching` используются `pairs`, для `grouping` — `groups`. В `file` студент
загружает изображение или PDF и подтверждает самопроверку. Backend проверяет,
что файл принадлежит отправившему ответ пользователю.

### Файлы

`POST /assets` доступен авторизованному пользователю, потому что файл может быть
ответом студента. Список и удаление доступны teacher/admin. Бинарное тело имеет
тип `application/octet-stream`; `filename` и `mime` передаются query-параметрами.
Разрешены PNG, JPEG, WebP, GIF и PDF; SVG исключён.

### Ассистент урока

Ассистент использует OpenAI-совместимый `/chat/completions` и возвращает ответ
потоком Server-Sent Events. История передаётся клиентом и не хранится backend.
Квоты разделены для авторизованных пользователей, гостевой cookie, IP и общего
дневного гостевого бюджета.

## Миграции и demo-данные

Схема меняется только Alembic-миграцией и синхронно с `db.drawio`, если изменение
затрагивает диаграмму данных.

```bash
make revision m="add something"
make migrate
uv run alembic upgrade head --sql
```

`make seed` не очищает базу и безопасен при повторном запуске. Он создаёт demo-курс,
трек, модули, уроки, тест, пользователей, группу, прогресс и assets. В конце
печатаются временные access-токены ролей `student`, `teacher` и `admin`.

## Docker

### Локальная разработка

`docker-compose.yml` предназначен только для локальной разработки. `make up`
поднимает PostgreSQL, Redis, MinIO и создаёт локальный бакет. API обычно запускается
на хосте через `make run`.

При необходимости весь локальный набор можно поднять в Docker:

```bash
docker compose --profile full up --build
```

### Staging с cloud S3

`docker-compose.staging.yml` запускает API, PostgreSQL 17 и Redis 7. База и Redis
доступны только во внутренней Docker-сети, сохраняют данные в именованных volumes и
не публикуют порты на хост. MinIO, demo seed и тестовых сервисов в файле нет.
Dockerfile устанавливает зависимости с `--no-dev`, а `.dockerignore` исключает
`tests/` и `scripts/` из образа.

Создайте staging-конфигурацию:

```bash
cp .env.staging.example .env.staging
```

Сгенерируйте разные URL-safe значения `POSTGRES_PASSWORD` и `REDIS_PASSWORD`,
например через `openssl rand -hex 32`. Compose сам собирает внутренние `DATABASE_URL`
и `REDIS_URL`. Также заполните GitHub OAuth и cloud S3. Бакет должен быть создан
заранее. Для AWS `S3_ENDPOINT_URL` не задаётся; для совместимого провайдера
указывается его endpoint. `S3_PUBLIC_URL` может вести на публичный бакет или CDN.

Проверьте конфигурацию, соберите образ, примените миграции и запустите API:

```bash
make staging-config
make staging-build
make staging-migrate
make staging-up
```

По умолчанию порт публикуется на `127.0.0.1:8000` для reverse proxy на том же
сервере. Привязку можно изменить через `API_BIND_HOST` и `API_PORT`.

`.env.staging` находится в `.gitignore`. Секреты не должны попадать в compose-файл,
Docker image или систему контроля версий. Миграции остаются отдельным явным шагом
перед запуском новой версии приложения. `make staging-down` останавливает контейнеры,
но сохраняет volumes PostgreSQL и Redis.

### Что требуется на staging/production

Deploy-compose создаёт runtime-контейнеры и отдельные volumes PostgreSQL/Redis для
каждого compose project. Вне него должны быть подготовлены:

- cloud S3 bucket и IAM-ключ с минимальными `PutObject`/`DeleteObject` правами;
- DNS, TLS и reverse proxy до API;
- отдельные GitHub OAuth Apps или callback URLs для stage и production;
- регулярный `pg_dump` PostgreSQL во внешнее защищённое хранилище;
- lifecycle/retention и резервирование данных S3;
- мониторинг healthcheck, свободного места, подключений и ошибок приложения.

Redis обязателен: в нём хранятся OAuth state, refresh-сессии и квоты ассистента.
На стенде включён AOF с `appendfsync everysec`. Потеря Redis завершит активные сессии
и сбросит временные состояния, но основной учебный контент остаётся в PostgreSQL.

Текущий storage возвращает прямые публичные URL объектов. Поэтому cloud bucket/CDN
должен разрешать чтение загруженных файлов. Перед хранением приватных студенческих
работ в production следует перейти на закрытый bucket и короткоживущие presigned
GET URL — это отдельное изменение storage-контракта.

LLM-провайдер необязателен. On-premise Judge0 понадобится после реализации
Algorithm Practice и будет отдельным внутренним сервисом, а не частью этого compose.

### GitLab deploy

Pipeline использует `docker-compose.staging.yml` для stage и production с project
names `tramplin-stage` и `tramplin-prod`. Поэтому контейнеры и volumes сред не
пересекаются. В GitLab CI/CD Variables должны находиться `STAGE_ENV` и `PROD_ENV`
с полным runtime-окружением. Если обе среды работают на одном сервере, задайте им
разные `API_PORT`.

Deploy job:

1. копирует только deploy-compose и защищённый runtime env;
2. скачивает уже проверенный образ из GitLab Registry;
3. валидирует compose без печати секретов;
4. поднимает PostgreSQL и Redis и ждёт их healthchecks;
5. отдельным one-shot контейнером применяет Alembic-миграции;
6. запускает API без локальной сборки и ждёт успешный healthcheck.

Pipeline не создаёт S3 bucket, DNS, backup jobs или reverse proxy — эта
инфраструктура окружения подготавливается отдельно.

#### Переход со старого compose

Новый pipeline не удаляет контейнеры и volumes, созданные прежним compose: такое
автоматическое удаление могло бы уничтожить единственную базу окружения. Переход
выполняется один раз вручную:

1. сделать `pg_dump` старой PostgreSQL и backup файлов MinIO;
2. поднять новый compose project на свободном временном API-порту;
3. восстановить dump в новый PostgreSQL volume и перенести файлы в cloud S3;
4. проверить миграции, S3-доступы и выполнить smoke test;
5. переключить reverse proxy на новый API;
6. остановить старый compose-проект без флага `--volumes`.

Старый Redis переносить необязательно: пользователям потребуется войти заново, а
временные OAuth state и квоты создадутся повторно.

Перед остановкой имя старого проекта проверяется через `docker compose ls` и
`docker ps --filter label=com.docker.compose.project=tramplin`. Команду удаления
volumes (`down -v`) использовать нельзя, пока backup не проверен.

## Артефакты

Правила хранения продуктовых и архитектурных документов описаны в
[artifacts/README.md](artifacts/README.md). Текущий PRD алгоритмических сессий и
on-premise Judge0 находится в
[artifacts/prd/algorithmic-sessions.md](artifacts/prd/algorithmic-sessions.md).
