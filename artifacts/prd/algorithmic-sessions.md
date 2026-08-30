# PRD: подготовка к алгоритмической секции

- Статус: Draft
- Дата: 2026-08-31
- Область: Tramplin backend, frontend и on-premise Judge0
- Рабочее название функции: Algorithm Practice

## 1. Контекст

В Tramplin уже есть уроки, тесты, карточки для собеседований и прогресс по курсу.
Для подготовки к алгоритмической секции этого недостаточно: алгоритмическая задача
имеет исходный код, язык, несколько запусков, публичные и скрытые тесты, ограничения
по времени и памяти, историю попыток и отдельный разбор решения.

Algorithm Practice должен поддерживать два сценария:

1. Обычная практика без жёсткого ограничения времени.
2. Имитация алгоритмической секции с таймером и итоговой ретроспективой.

Выполнение собственного кода происходит в on-premise Judge0. Интеграции с внешними
платформами не должны быть обязательны для работы основного продукта.

## 2. Цели

- Дать преподавателю возможность создавать собственные алгоритмические задачи и
  объединять их в наборы.
- Дать студенту редактор кода, запуск на примерах и проверку на скрытых тестах.
- Поддержать тренировочный и экзаменационный режимы сессии.
- Сохранять попытки и понятный прогресс: время, число запусков, verdict и подсказки.
- Добавить набор практики как самостоятельный элемент учебного модуля.
- Изолировать Tramplin от Judge0 через внутренний интерфейс `CodeRunner`.
- Оставить расширяемую модель для Codeforces, LeetCode и других источников.

## 3. Не входит в MVP

- Совместное редактирование кода в реальном времени.
- Видеозвонок и запись интервью.
- Антиплагиат и полноценный прокторинг.
- Турниры, рейтинги и глобальная таблица лидеров.
- Автоматический импорт текста и тестов LeetCode.
- Поддержка произвольных пользовательских Docker-образов и пакетов.
- Интерактивные задачи, где программа общается с отдельным interactor-процессом.
- Специальные checker-программы и задачи с несколькими допустимыми форматами вывода.

## 4. Пользователи и сценарии

### Преподаватель

- Создаёт внутреннюю задачу: условие, ограничения, примеры и скрытые тесты.
- Выбирает разрешённые языки и при необходимости задаёт starter code.
- Создаёт practice set, определяет порядок задач и рекомендуемое время.
- Выбирает режим `practice` или `mock_interview`.
- Добавляет practice set в модуль курса.
- Просматривает попытки и прогресс студентов своей учебной области.

### Студент

- Запускает сессию из учебного модуля.
- Читает условие и примеры, выбирает язык и пишет решение.
- Запускает решение на публичных примерах или собственном stdin.
- Отправляет решение на скрытые тесты.
- Получает агрегированный verdict без содержимого скрытых тестов.
- Записывает сложность алгоритма, уверенность и короткую ретроспективу.
- Возвращается к нерешённым задачам или задачам, требующим повторения.

## 5. Продуктовые решения

### 5.1. Отдельный тип контента

Algorithm Practice не является типом quiz-вопроса. В `module_items` добавляется
третий вид:

```text
lesson | quiz | practice
```

`practice` ссылается на practice set. Для него действуют существующие правила
позиционирования и публикации контента модуля.

### 5.2. Run и Submit

- `Run` выполняет код на публичных примерах либо на введённом студентом stdin.
  Возвращаются stdout, stderr, время и ошибка компиляции.
- `Submit` выполняет код на скрытых тестах. Возвращаются только итоговый verdict,
  номер первого упавшего теста, агрегированное время и безопасное описание ошибки.
- Успешным решением считается только `Submit` со статусом `accepted`.

### 5.3. Режимы сессии

`practice`:

- таймер информационный;
- задачи можно открывать в любом разрешённом порядке;
- доступны подсказки и объяснение после решения.

`mock_interview`:

- фиксируется время старта и deadline на сервере;
- подсказки учитываются в результате;
- после deadline новые submit не принимаются, уже запущенный завершается;
- объяснение открывается после завершения задачи или всей сессии;
- пауза в MVP не поддерживается.

### 5.4. Языки MVP

Начальный allowlist:

- Python;
- JavaScript;
- TypeScript;
- C++;
- Java;
- C#;
- Go;
- Kotlin.

Backend получает фактически доступные языки через Judge0 `GET /languages/`,
сопоставляет их со стабильными внутренними ключами и кеширует результат. Frontend
не хранит Judge0 `language_id` и не обращается к Judge0 напрямую.

Версии компиляторов фиксируются версией/образом Judge0. Изменение версии является
контролируемым инфраструктурным изменением и требует повторного прогона эталонных
решений.

## 6. Внешние источники

### LeetCode

MVP хранит только provider, slug, оригинальный URL и локально заданные преподавателем
метаданные. Студент решает задачу на внешней платформе, прикладывает URL submission
и подтверждает выполнение. Tramplin не выполняет scraping, не копирует условие и не
зависит от недокументированного GraphQL LeetCode.

### Codeforces

Следующий этап может синхронизировать публичные submissions по handle через
официальный API. Вызовы выполняются фоново, кешируются и соблюдают лимит провайдера.
Автоматическая синхронизация не входит в первый релиз внутреннего judge.

### Правило интеграции

Каждый источник реализуется адаптером `ProblemProvider`. Отсутствие или сбой внешнего
провайдера не должен мешать открывать курс и решать внутренние задачи.

## 7. Модель данных

Названия предварительные и уточняются перед миграцией.

### `algorithm_problems`

| Поле                              | Назначение                                       |
| --------------------------------- | ------------------------------------------------ |
| `id`                              | UUID v7                                          |
| `provider`                        | `internal`, `leetcode`, `codeforces`, `external` |
| `external_key`                    | slug или идентификатор внешней задачи, nullable  |
| `external_url`                    | проверенный HTTPS URL, nullable                  |
| `title`                           | название                                         |
| `statement_md` / `statement_html` | условие собственной задачи                       |
| `difficulty`                      | `easy`, `medium`, `hard`                         |
| `topics`                          | массив нормализованных тегов                     |
| `time_limit_ms`                   | лимит исполнения                                 |
| `memory_limit_kb`                 | лимит памяти                                     |
| `status`                          | `draft`, `published`                             |
| `created_by`                      | автор                                            |

Для внешней задачи `statement_md` пустой: отображается ссылка на оригинал.

### `algorithm_test_cases`

| Поле              | Назначение                           |
| ----------------- | ------------------------------------ |
| `id`              | UUID v7                              |
| `problem_id`      | задача                               |
| `position`        | порядок                              |
| `input`           | stdin                                |
| `expected_output` | ожидаемый stdout                     |
| `is_sample`       | можно ли показывать студенту         |
| `weight`          | резерв для будущего частичного балла |

Скрытые `input` и `expected_output` доступны только authoring API. Студенческие API
не сериализуют эти поля ни при каком verdict.

### `algorithm_templates`

| Поле            | Назначение                                              |
| --------------- | ------------------------------------------------------- |
| `problem_id`    | задача                                                  |
| `language`      | стабильный внутренний ключ                              |
| `starter_code`  | начальный код                                           |
| `solution_code` | эталон для регрессионной проверки, только teacher/admin |

### `practice_sets` и `practice_set_problems`

Набор содержит title, description, mode, duration_minutes и status. Таблица связи
содержит problem_id, position и recommended_minutes. Одна задача может входить в
несколько наборов.

### `practice_sessions`

| Поле                                          | Назначение                       |
| --------------------------------------------- | -------------------------------- |
| `id`                                          | UUID v7                          |
| `practice_set_id` / `user_id`                 | набор и студент                  |
| `mode`                                        | снимок режима на момент старта   |
| `status`                                      | `active`, `completed`, `expired` |
| `started_at` / `deadline_at` / `completed_at` | серверные timestamps             |
| `reflection_md`                               | итоговая ретроспектива           |

### `algorithm_submissions`

| Поле                                    | Назначение                                                                                                   |
| --------------------------------------- | ------------------------------------------------------------------------------------------------------------ |
| `id`                                    | публичный идентификатор Tramplin                                                                             |
| `session_id` / `problem_id` / `user_id` | контекст попытки                                                                                             |
| `kind`                                  | `run` или `submit`                                                                                           |
| `language`                              | внутренний ключ языка                                                                                        |
| `source_code`                           | отправленный код                                                                                             |
| `status`                                | `queued`, `running`, `finished`, `failed`                                                                    |
| `verdict`                               | `accepted`, `wrong_answer`, `compile_error`, `runtime_error`, `time_limit`, `memory_limit`, `internal_error` |
| `runtime_ms` / `memory_kb`              | агрегированный результат                                                                                     |
| `judge_token`                           | внутренний token Judge0, никогда не отдаётся клиенту                                                         |
| `created_at` / `finished_at`            | аудит                                                                                                        |

Детальные результаты скрытых кейсов можно хранить ограниченное время для диагностики,
но student API возвращает только безопасный агрегат.

### `algorithm_progress`

Уникальная пара `(user_id, problem_id)`: status (`unseen`, `attempted`, `solved`,
`review`), attempts, hints_used, first_solved_at, last_attempt_at, confidence,
complexity_md и reflection_md.

## 8. API MVP

Префикс остаётся `/api/v1`.

### Student

```text
GET  /practice-sets/{id}
POST /practice-sets/{id}/sessions
GET  /practice-sessions/{id}
POST /practice-sessions/{id}/complete

GET  /algorithm-problems/{id}
GET  /algorithm-languages
POST /algorithm-problems/{id}/runs
POST /algorithm-problems/{id}/submissions
GET  /algorithm-submissions/{id}
GET  /algorithm-problems/{id}/progress
PUT  /algorithm-problems/{id}/reflection
```

Создание run/submit возвращает `202 Accepted` и Tramplin submission id. Frontend
опрашивает `GET /algorithm-submissions/{id}` с ограниченным backoff. WebSocket/SSE
не требуется для MVP.

### Authoring

```text
/authoring/algorithm-problems/*
/authoring/algorithm-problems/{id}/test-cases/*
/authoring/algorithm-problems/{id}/templates/*
/authoring/practice-sets/*
/authoring/practice-sets/{id}/problems/order
```

Публикация запрещена, если у внутренней задачи нет хотя бы одного sample, одного
скрытого теста, разрешённого языка и успешно прошедшего эталонного решения.

### Admin/operations

```text
GET /admin/code-runner/health
GET /admin/code-runner/languages
GET /admin/code-runner/queue
```

## 9. Интеграция с Judge0

В доменном слое используется порт:

```python
class CodeRunner(Protocol):
    async def languages(self) -> list[RunnerLanguage]: ...
    async def submit(self, request: RunRequest) -> RunnerJob: ...
    async def result(self, job_id: str) -> RunResult | None: ...
```

Judge0-специфичные DTO, token и `language_id` остаются в infrastructure. Для unit-тестов
используется fake runner, поэтому тесты сервисов не требуют Docker/Judge0.

Поток выполнения:

1. API валидирует пользователя, сессию, язык, размер кода и rate limit.
2. В одной транзакции создаётся `algorithm_submission` со статусом `queued` и
   надёжное задание на выполнение.
3. Worker отправляет работу в Judge0 по приватной сети.
4. Для `run` выполняются публичные кейсы или пользовательский stdin.
5. Для `submit` скрытые тесты выполняются раздельно; после первого окончательного
   провала оставшиеся тесты могут не запускаться.
6. Worker нормализует Judge0 status, атомарно завершает submission и обновляет progress.
7. Клиент получает только нормализованный результат Tramplin.

Нельзя полагаться только на in-process `BackgroundTasks`: задание не должно теряться
при рестарте API. Конкретная реализация durable queue выбирается на техническом
дизайне с учётом уже используемого Redis и PostgreSQL.

## 10. Безопасность

- Judge0 API и workers не публикуются в интернет и доступны только backend/worker.
- Исполняемая среда не имеет исходящего доступа в интернет.
- Используются непривилегированные контейнеры, read-only filesystem где возможно,
  лимиты CPU, памяти, wall time, процессов, потоков и размера файлов.
- Запрещены пользовательские compiler options, command-line arguments и additional files.
- Максимальный размер исходного кода MVP: 100 KiB, настраивается конфигом.
- Максимальный возвращаемый stdout/stderr: 64 KiB; превышение даёт контролируемый verdict.
- Предлагаемый верхний предел задачи: 5 секунд и 512 MiB; преподаватель может выбрать
  только значение внутри административных границ.
- Одновременно у пользователя выполняется не более одного submission; предлагаемый
  лимит — 60 запусков в час и 30 запусков одной задачи за сессию.
- Скрытые входы, expected output, judge token и внутренние ошибки никогда не попадают
  в student API и frontend logs.
- Доступ к исходному коду имеет автор и преподаватель в рамках разрешённой учебной
  области; каждое чтение преподавателем должно быть авторизовано.
- Образы Judge0 фиксируются digest, регулярно сканируются и обновляются контролируемо.
- Перед production необходимо проверить требования GPL-3.0 к выбранному способу
  распространения и изменения on-premise компонентов.

## 11. On-premise deployment

### Development

Judge0 добавляется в локальный compose-профиль вместе с существующими PostgreSQL,
Redis и MinIO. Интеграционные тесты запускаются отдельной командой и не входят в
быстрый unit test loop.

### Production

- Judge0 web/API и execution workers находятся в отдельном сетевом сегменте.
- Backend обращается к Judge0 по внутреннему DNS и с отдельным auth token.
- Execution workers не имеют доступа к Tramplin PostgreSQL, Redis, MinIO и секретам.
- Количество workers масштабируется независимо от FastAPI.
- Очередь имеет предел; при перегрузке Tramplin возвращает `runner_busy` и `Retry-After`.
- Health check различает `unavailable`, `degraded` и `healthy`.
- Резервируются метрики очереди, длительности, verdict, ошибок и загрузки workers.

## 12. Нефункциональные требования

- Создание submission без учёта выполнения: p95 до 300 ms.
- Простое решение после выхода из очереди: целевой p95 до 10 секунд.
- API и worker допускают повторную доставку задания без двойного обновления progress.
- Рестарт FastAPI или worker не теряет queued/running submissions; зависшие задачи
  переводятся в повторную обработку или `internal_error` по timeout.
- Недоступность Judge0 не влияет на уроки, quizzes, авторизацию и внешний контент.
- Все операции используют UTC и UUID v7, как остальной backend.
- Метрики не содержат source code, stdin, stdout и персональные данные.

## 13. Метрики продукта

- Доля начатых сессий, завершённых студентом.
- Доля задач с успешным submit.
- Медианное время до первого accepted.
- Среднее число runs/submits и использованных подсказок.
- Доля повторного решения задач со статусом `review`.
- Технические: queue latency, execution latency, error rate и worker saturation.

Метрики нужны для улучшения обучения, а не для публичного ранжирования студентов.

## 14. Критерии приёмки MVP

1. Teacher создаёт внутреннюю задачу с sample, скрытым тестом и шаблоном минимум
   для одного языка.
2. Эталонное решение проходит все тесты перед публикацией.
3. Teacher создаёт practice set и добавляет его в модуль с корректным порядком.
4. Student запускает practice или mock session и получает deadline с сервера.
5. Student запускает код на sample и видит безопасные stdout/stderr.
6. Student отправляет решение, получает queued/running/final status и корректный verdict.
7. Accepted обновляет progress; повторная доставка job не увеличивает счётчики дважды.
8. Содержимое скрытого теста отсутствует во всех student-ответах и frontend logs.
9. Код с бесконечным циклом, превышением памяти и excessive output останавливается
   установленными лимитами.
10. После рестарта API/worker незавершённое задание не теряется.
11. Недоступный Judge0 даёт доменную ошибку `runner_unavailable`, не HTTP 500 с деталями.
12. Unit, repository, API и runner contract tests проходят в CI; production image
    проходит smoke test эталонными решениями на каждом разрешённом языке.

## 15. Этапы реализации

### Этап 0 — технический spike

- Поднять фиксированную версию Judge0 локально.
- Проверить allowlist языков, сетевую изоляцию и ресурсные лимиты.
- Замерить запуск эталонных решений и поведение вредоносных примеров.
- Выбрать durable queue и политику повторов.

### Этап 1 — домен и authoring

- Модели, миграция, репозитории и сервисы задач/practice sets.
- CRUD тест-кейсов и language templates.
- Валидация публикации эталонным решением.
- Новый `module_item.kind = practice`.

### Этап 2 — runner и student flow

- `CodeRunner`, Judge0 adapter, worker и нормализация verdict.
- Practice sessions, run/submit, progress и rate limits.
- Frontend: редактор кода, таймер, polling и экран результата.

### Этап 3 — эксплуатация

- Метрики, очередь, retries, reconciliation зависших jobs.
- Нагрузочные и security smoke tests.
- Runbook обновления Judge0 и языков.

### Этап 4 — внешние платформы

- LeetCode link/self-check flow.
- Codeforces account и синхронизация accepted submissions через официальный API.
- Повторение задач и рекомендации по слабым темам.

## 16. Предлагаемые значения по умолчанию

Эти значения конфигурируемые и подтверждаются spike-нагрузкой:

```text
source code                 100 KiB
stdout/stderr               64 KiB
task time limit             1000 ms default, 5000 ms max
task memory limit           256 MiB default, 512 MiB max
concurrent jobs per user    1
runs per user per hour      60
runs per problem/session    30
poll interval               1s → 2s → 3s, max 3s
submission hard timeout     task limit + queue/runner safety margin
```

## 17. Открытые вопросы перед реализацией

- Сколько одновременно активных студентов должен выдерживать первый production?
- Какие из восьми языков обязательны в первом релизе?
- Сколько времени хранить исходный код и технические результаты запусков?
- Может ли преподаватель просматривать код всех студентов или только назначенных групп?
- Нужен ли custom stdin в mock interview или только sample tests?
- Нужно ли разрешать повторный вход в уже завершённую mock session для просмотра?
- Должно ли решение одной задачи автоматически завершать её часть сессии?

До ответов используются безопасные defaults из этого документа; вопросы не блокируют
технический spike и проектирование схемы.

## 18. Внешние ссылки

- Judge0 HTTP API: <https://docs.judge0.com/products/judge0/http_api/>
- Judge0 CE API reference: <https://ce.judge0.com/docs>
- Judge0 repository and license: <https://github.com/judge0/judge0>
- Codeforces API: <https://codeforces.com/apiHelp/>
- LeetCode Terms of Service: <https://leetcode.com/terms/>
