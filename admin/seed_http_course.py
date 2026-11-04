"""Наполняет базу курсом «HTTP и REST API». Повторный запуск ничего не дублирует."""

import asyncio
import sys

import uuid_utils.compat as uuid
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from tramplin.core.config import Settings, load_settings
from tramplin.models.content import (
    Course,
    InterviewCard,
    Lesson,
    Module,
    ModuleDep,
    ModuleItem,
    Track,
    TrackCourse,
)
from tramplin.models.enums import ContentStatus, QuestionType, UserRole
from tramplin.models.quizzes import Quiz, QuizQuestion
from tramplin.models.users import User
from tramplin.services.lesson_markdown import render_lesson_content

TRACK_SLUG = "backend"
COURSE_SLUG = "http-rest-api"

REQUEST_MD = """\
# Запрос и ответ

HTTP — это протокол вопросов и ответов. Клиент присылает **запрос**, сервер возвращает
**ответ**. Больше в протоколе ничего нет: ни соединения «на память», ни очереди
сообщений, ни подписки на события.

## Из чего состоит запрос

```http
GET /api/v1/courses?limit=20 HTTP/1.1
Host: tramplinn.tech
Accept: application/json
Authorization: Bearer eyJhbGciOi...
```

Первая строка — метод, путь и версия протокола. Дальше идут заголовки: по одному на
строку, `Имя: значение`. После пустой строки может идти тело — у `GET` его обычно нет,
у `POST` там лежат данные.

Ответ устроен так же, только вместо метода и пути в первой строке стоит код состояния:

```http
HTTP/1.1 200 OK
Content-Type: application/json
Content-Length: 42

{"items": [], "total": 0}
```

:::note
Заголовки регистронезависимы: `Content-Type`, `content-type` и `CONTENT-TYPE` — одно и
то же. А вот значения — нет, и путь тоже чувствителен к регистру.
:::

## Почему протокол не помнит клиента

HTTP не хранит состояние между запросами. Сервер, ответив, забывает о клиенте всё.
Каждый следующий запрос должен сам нести доказательство, кто его прислал — куку или
заголовок `Authorization`.

Это ограничение выглядит неудобным, но именно оно позволяет поставить за балансировщик
десять одинаковых серверов: любой запрос может попасть на любой из них, и результат не
изменится. Как только сервер начинает помнить клиента в своей памяти, такая замена
ломается.

:::interview
Что означает «HTTP — протокол без состояния» и как тогда работает авторизация?
---
Сервер не помнит предыдущие запросы клиента: каждый обрабатывается независимо.
Авторизация решается тем, что клиент прикладывает доказательство к **каждому** запросу —
куку с идентификатором сессии или токен в заголовке `Authorization`. Состояние при этом
хранится не в памяти процесса, а в общем хранилище: базе или Redis, куда может заглянуть
любой из серверов.
:::
"""

METHODS_MD = """\
# Методы и идемпотентность

Метод сообщает серверу намерение клиента. Формально сервер может делать по любому методу
что угодно, но нарушать общепринятый смысл — верный способ сломать кэши, повторы запросов
и ожидания коллег.

## Два свойства, из которых всё следует

**Безопасный** (safe) метод ничего не меняет на сервере. **Идемпотентный** — меняет, но
повторный вызов с теми же данными не меняет ничего сверх первого.

| Метод | Безопасный | Идемпотентный | Смысл |
|---|---|---|---|
| `GET` | да | да | получить представление ресурса |
| `HEAD` | да | да | то же, но без тела ответа |
| `PUT` | нет | да | заменить ресурс целиком |
| `DELETE` | нет | да | удалить ресурс |
| `PATCH` | нет | нет | изменить часть ресурса |
| `POST` | нет | нет | создать подчинённый ресурс |

`DELETE` идемпотентен, хотя это удивляет: первый вызов удаляет и возвращает `204`, второй
уже ничего не находит и возвращает `404`. Коды разные, но **состояние сервера после
обоих одинаково** — ресурса нет. Идемпотентность про состояние, не про ответ.

:::pitfall
Браузер, прокси и мобильный клиент имеют право сами повторить запрос, который не получил
ответа. Для `GET` это безобидно, для `POST` — двойной заказ или двойное списание.
Если операция должна выполниться ровно один раз, клиент присылает ключ идемпотентности
(`Idempotency-Key`), а сервер запоминает его и на повтор отдаёт прежний результат.
:::

## PUT или PATCH

`PUT` заменяет ресурс целиком: чего нет в теле — того не будет и в ресурсе. `PATCH`
меняет только присланные поля.

```http
PUT /api/v1/courses/42
{"title": "HTTP и REST API", "summary": "Основы протокола"}
```

Если в этом `PUT` забыть `summary`, поле обнулится — и это правильное поведение, а не
ошибка сервера.

:::interview
Чем `PUT` отличается от `PATCH` и почему `DELETE` считают идемпотентным?
---
`PUT` заменяет ресурс целиком, отсутствующие в теле поля сбрасываются. `PATCH` применяет
частичное изменение и потому не идемпотентен: например, `PATCH` с операцией «увеличь
счётчик на 1» даст разный результат при повторе.

`DELETE` идемпотентен, потому что идемпотентность описывает состояние сервера, а не код
ответа. После первого и после пятого удаления ресурса одинаково нет.
:::
"""

STATUS_MD = """\
# Коды состояния

Код ответа — это первое, что читает клиент, и часто единственное, что он разбирает
автоматически. Первая цифра задаёт класс.

- `1xx` — промежуточные, встречаются редко;
- `2xx` — получилось;
- `3xx` — нужно сходить в другое место;
- `4xx` — клиент прислал что-то не то;
- `5xx` — сервер не справился.

## Те, что нужны каждый день

`200 OK` — успех с телом. `201 Created` — ресурс создан, адрес нового ресурса кладут в
заголовок `Location`. `204 No Content` — успех без тела, типичный ответ на `DELETE`.

`400 Bad Request` — тело или параметры не разобрались. `401 Unauthorized` — мы не знаем,
кто ты. `403 Forbidden` — знаем, но нельзя. `404 Not Found` — нет такого ресурса.
`409 Conflict` — состояние ресурса не позволяет операцию. `422` — синтаксис верный, но
данные не проходят проверку смысла.

:::warning
`401` и `403` путают постоянно. `401` означает «нет или не годится доказательство
личности» — клиенту имеет смысл войти заново. `403` означает «личность установлена,
прав не хватает» — повторный вход не поможет.
:::

## Про пятисотые

`500` — необработанное исключение, то есть баг. `502` и `504` приходят от прокси, когда
приложение за ним не ответило или ответило мусором. `503` — приложение живо, но
сознательно отказывается обслуживать: перегрузка или обслуживание.

:::note
Разница между `502` и `500` подсказывает, где искать. `500` пришёл от вашего кода —
смотрите логи приложения. `502` пришёл от прокси — приложение, скорее всего, вообще не
поднялось или недоступно по сети.
:::
"""

RESOURCES_MD = """\
# Ресурсы и адреса

REST строится вокруг существительных. Адрес называет **вещь**, а что с ней сделать —
говорит метод. Поэтому `/api/v1/courses/42` и `DELETE`, а не `/api/v1/deleteCourse?id=42`.

## Коллекция и элемент

```
GET    /api/v1/courses          список курсов
POST   /api/v1/courses          создать курс
GET    /api/v1/courses/42       один курс
PUT    /api/v1/courses/42       заменить
DELETE /api/v1/courses/42       удалить
```

Множественное число у коллекций — не догма, а соглашение, но соблюдать его стоит хотя бы
ради единообразия внутри одного API.

## Вложенность

Вложенный путь уместен, когда дочерний ресурс не существует без родителя:

```
GET /api/v1/courses/42/modules
```

Глубже двух уровней вложенность быстро становится неудобной. `/courses/42/modules/7/lessons/3`
проще заменить на `/lessons/3`, если у урока есть собственный идентификатор.

:::note
В Tramplin в адресах контента стоит `slug`, а не UUID: `/courses/http-rest-api` читается
человеком и не меняется при переносе базы. UUID остаётся в API-путях и админке.
:::

## Фильтры, сортировка, страницы

Всё это — параметры запроса, а не отдельные пути:

```
GET /api/v1/courses?track=backend&status=published&limit=20&offset=40
```

:::pitfall
Постраничный вывод через `offset` на больших таблицах деградирует: база вынуждена
пропустить и выбросить все предыдущие строки. Для длинных списков используют курсор —
запоминают последний увиденный ключ и просят «следующие 20 после него».
:::
"""

ERRORS_MD = """\
# Ошибки и версии

## Ошибка — это тоже ответ

Клиенту мало кода `400`: ему нужно знать, что именно не так, а иногда — показать это
пользователю. Поэтому у ошибок должен быть предсказуемый формат.

```json
{
  "error": "validation_failed",
  "message": "Проверьте заполненные поля",
  "details": [
    {"field": "title", "reason": "too_long", "max": 200}
  ]
}
```

Машиночитаемый код (`error`) остаётся стабильным, текст — меняется. Клиент ветвится по
коду, а не по строке сообщения.

:::warning
Не кладите в текст ошибки внутренности: путь к файлу, SQL-запрос, stack trace. Это
подарок тому, кто изучает ваше приложение на прочность. В лог — да, в ответ — нет.
:::

## Версии

API меняется, а клиенты обновляются не одновременно — особенно мобильные. Ломающее
изменение без версии превращается в сломанное приложение у пользователя.

Самый распространённый способ — версия в пути: `/api/v1/...`. Она видна в логах, её легко
маршрутизировать на прокси, её нельзя случайно потерять.

Что считать ломающим изменением: удаление поля, переименование, сужение типа, новое
обязательное поле в запросе, изменение кода ответа. Добавление **необязательного** поля
в ответ ломающим не считается — клиент, который его не ждёт, просто его не заметит.

:::interview
Как версионируют HTTP API и какие изменения требуют новой версии?
---
Три подхода: версия в пути (`/api/v1/`), в заголовке (`Accept: application/vnd.api+json;version=1`)
и в параметре запроса. На практике чаще всего берут путь — он виден в логах и легко
маршрутизируется.

Новая версия нужна на ломающих изменениях: удалили или переименовали поле, сузили тип,
сделали необязательное поле обязательным, поменяли код ответа. Добавление необязательного
поля обратную совместимость не нарушает.
:::
"""

SESSIONS_MD = """\
# Сессии, токены и куки

Раз протокол не помнит клиента, доказательство личности нужно приносить с каждым
запросом. Способов два, и они решают разные задачи.

## Кука с идентификатором сессии

Сервер создаёт запись о сессии у себя и отдаёт клиенту случайный идентификатор в куке.
Браузер сам прикладывает её к каждому запросу на этот домен.

```http
Set-Cookie: refresh_token=8f3a...; HttpOnly; Secure; SameSite=Lax; Path=/api/v1/auth
```

Три флага здесь важнее самого значения:

- `HttpOnly` — куку не видно из JavaScript, украсть её через XSS нельзя;
- `Secure` — кука уходит только по HTTPS;
- `SameSite=Lax` — кука не прикладывается к межсайтовым `POST`, что закрывает CSRF.

:::warning
Кука привязывается к домену, который её поставил. Если вход происходит на
`api.example.com`, а приложение живёт на `example.com`, кука до приложения не дойдёт:
браузер сочтёт это разными хостами. Один origin для входа и для запросов избавляет от
целого класса таких загадок.
:::

## Токен в заголовке

Второй способ — самодостаточный токен, чаще всего JWT:

```http
Authorization: Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...
```

Внутри — подписанные сервером данные: кто пользователь и до какого момента токен
действителен. Проверка не требует похода в базу, что удобно, но у этого есть цена:
отозвать выданный токен нельзя. Он действует до истечения срока.

Отсюда обычная схема: короткоживущий access-токен (минуты) плюс долгоживущий refresh,
хранящийся в `HttpOnly`-куке. Утёкший access протухнет сам, а refresh можно отозвать,
потому что он записан в базе.

:::pitfall
JWT подписан, а не зашифрован. Его содержимое читается любым, кто его получил, — это
обычный base64. Подпись гарантирует, что данные не подменили, но не прячет их. Секретам
внутри токена не место.
:::
"""

OAUTH_MD = """\
# OAuth 2.0 на практике

OAuth решает задачу «пустить пользователя по учётной записи другого сервиса, не спрашивая
его пароль». Пароль от GitHub вводится на github.com и вашему приложению не достаётся
никогда.

## Authorization Code Flow по шагам

1. Приложение отправляет пользователя на `github.com/login/oauth/authorize` с
   `client_id`, `redirect_uri`, списком прав и случайным `state`.
2. Пользователь входит на GitHub и подтверждает доступ.
3. GitHub возвращает его на `redirect_uri` с одноразовым `code` и тем же `state`.
4. Приложение **со своего сервера** меняет `code` на access-токен, добавляя
   `client_secret`.
5. С этим токеном приложение один раз запрашивает профиль и заводит свою сессию.

Ключевой момент — четвёртый шаг. Обмен идёт сервер-к-серверу, поэтому `client_secret`
никогда не оказывается в браузере.

:::warning
`state` — не формальность, а защита от CSRF. Без него злоумышленник может подсунуть
жертве свой `code` и привязать её сеанс к чужому аккаунту. Значение должно быть
случайным, одноразовым и с коротким сроком жизни; в Tramplin оно лежит в Redis с TTL
десять минут.
:::

## Что делать с полученным токеном

Соблазн — сохранить access-токен провайдера в базу «на будущее». Не стоит: это чужой
секрет, который вам больше не нужен. Взяли профиль, завели свою сессию, токен выбросили.
Хранить его нужно, только если приложение действительно продолжает ходить в API
провайдера от имени пользователя.

:::pitfall
Не связывайте аккаунты автоматически по совпадению email. Адрес на стороне провайдера
может быть не подтверждён, и тогда регистрация с чужой почтой отдаёт злоумышленнику
существующий аккаунт. Привязка нового способа входа — только явное действие уже
вошедшего пользователя.
:::

:::interview
Зачем в OAuth нужен параметр `state` и почему обмен кода на токен делается на сервере?
---
`state` — случайное одноразовое значение, которое приложение кладёт в запрос авторизации
и сверяет при возврате. Оно защищает от CSRF: без него атакующий может подсунуть жертве
свой авторизационный код и привязать её сессию к чужому аккаунту.

Обмен кода на токен требует `client_secret`. Если делать его в браузере, секрет станет
виден всем, кто откроет исходники страницы, — поэтому шаг выполняется только сервер-к-серверу.
:::
"""


def build_lesson(
    module_id: uuid.UUID,
    *,
    title: str,
    slug: str,
    body_md: str,
    minutes: int,
    actor_id: uuid.UUID,
) -> Lesson:
    rendered = render_lesson_content(body_md)
    item = Lesson(
        module_id=module_id,
        title=title,
        slug=slug,
        est_minutes=minutes,
        body_md=body_md,
        body_html=rendered.body_html,
        status=ContentStatus.PUBLISHED,
        created_by=actor_id,
        updated_by=actor_id,
    )
    item.interview_cards = [
        InterviewCard(
            lesson_id=item.id,
            position=card.position,
            question_md=card.question_md,
            answer_md=card.answer_md,
            created_by=actor_id,
            updated_by=actor_id,
        )
        for card in rendered.interview_cards
    ]
    return item


def question(
    quiz_id: uuid.UUID,
    position: int,
    prompt: str,
    kind: QuestionType,
    options: list[str],
    answer: dict[str, object],
    explain: str,
    actor_id: uuid.UUID,
) -> QuizQuestion:
    return QuizQuestion(
        quiz_id=quiz_id,
        position=position,
        prompt_md=prompt,
        type=kind,
        options_json=options,
        answer_json=answer,
        explain_md=explain,
        created_by=actor_id,
        updated_by=actor_id,
    )


def build_course(actor_id: uuid.UUID) -> tuple[Course, list[Module]]:
    course = Course(
        title="HTTP и REST API",
        slug=COURSE_SLUG,
        summary="Как устроен протокол, по которому разговаривают фронтенд и бэкенд, "
        "и как спроектировать API, которым не стыдно пользоваться.",
        color="#2B7FFF",
        est_hours=6,
        status=ContentStatus.PUBLISHED,
        created_by=actor_id,
        updated_by=actor_id,
    )

    basics = Module(
        course_id=course.id,
        title="Как устроен HTTP",
        slug="http-basics",
        summary="Запрос, ответ, методы и коды состояния",
        position=0,
        status=ContentStatus.PUBLISHED,
        created_by=actor_id,
        updated_by=actor_id,
    )
    design = Module(
        course_id=course.id,
        title="Проектирование REST API",
        slug="rest-design",
        summary="Ресурсы, адреса, ошибки и версии",
        position=1,
        status=ContentStatus.PUBLISHED,
        created_by=actor_id,
        updated_by=actor_id,
    )
    auth = Module(
        course_id=course.id,
        title="Аутентификация",
        slug="auth",
        summary="Куки, токены и вход через внешнего провайдера",
        position=2,
        status=ContentStatus.PUBLISHED,
        created_by=actor_id,
        updated_by=actor_id,
    )

    basics_lessons = [
        build_lesson(
            basics.id,
            title="Запрос и ответ",
            slug="request-response",
            body_md=REQUEST_MD,
            minutes=15,
            actor_id=actor_id,
        ),
        build_lesson(
            basics.id,
            title="Методы и идемпотентность",
            slug="methods",
            body_md=METHODS_MD,
            minutes=20,
            actor_id=actor_id,
        ),
        build_lesson(
            basics.id,
            title="Коды состояния",
            slug="status-codes",
            body_md=STATUS_MD,
            minutes=15,
            actor_id=actor_id,
        ),
    ]
    design_lessons = [
        build_lesson(
            design.id,
            title="Ресурсы и адреса",
            slug="resources",
            body_md=RESOURCES_MD,
            minutes=20,
            actor_id=actor_id,
        ),
        build_lesson(
            design.id,
            title="Ошибки и версии",
            slug="errors-versioning",
            body_md=ERRORS_MD,
            minutes=20,
            actor_id=actor_id,
        ),
    ]
    auth_lessons = [
        build_lesson(
            auth.id,
            title="Сессии, токены и куки",
            slug="sessions-tokens",
            body_md=SESSIONS_MD,
            minutes=25,
            actor_id=actor_id,
        ),
        build_lesson(
            auth.id,
            title="OAuth 2.0 на практике",
            slug="oauth",
            body_md=OAUTH_MD,
            minutes=25,
            actor_id=actor_id,
        ),
    ]

    basics_quiz = Quiz(
        module_id=basics.id,
        lesson_id=None,
        title="Проверка: основы HTTP",
        slug="http-basics-check",
        status=ContentStatus.PUBLISHED,
        created_by=actor_id,
        updated_by=actor_id,
    )
    basics_quiz.questions = [
        question(
            basics_quiz.id,
            0,
            "Какой код вернуть на успешный `DELETE`, если тело ответа не нужно?",
            QuestionType.SINGLE,
            ["200 OK", "204 No Content", "404 Not Found", "410 Gone"],
            {"value": "204 No Content"},
            "204 означает успех без тела — типичный ответ на удаление.",
            actor_id,
        ),
        question(
            basics_quiz.id,
            1,
            "Отметьте идемпотентные методы.",
            QuestionType.MULTIPLE,
            ["GET", "POST", "PUT", "DELETE", "PATCH"],
            {"values": ["GET", "PUT", "DELETE"]},
            "PATCH не идемпотентен: повтор частичного изменения может дать другой "
            "результат. POST создаёт новый ресурс на каждый вызов.",
            actor_id,
        ),
        question(
            basics_quiz.id,
            2,
            "Клиент прислал верный токен, но не имеет прав на операцию. Какой код?",
            QuestionType.SINGLE,
            ["400", "401", "403", "422"],
            {"value": "403"},
            "401 — личность не установлена, 403 — установлена, но прав не хватает.",
            actor_id,
        ),
    ]

    design_quiz = Quiz(
        module_id=design.id,
        lesson_id=None,
        title="Проверка: проектирование API",
        slug="rest-design-check",
        status=ContentStatus.PUBLISHED,
        created_by=actor_id,
        updated_by=actor_id,
    )
    design_quiz.questions = [
        question(
            design_quiz.id,
            0,
            "Какой адрес соответствует стилю REST?",
            QuestionType.SINGLE,
            [
                "POST /api/v1/createCourse",
                "GET /api/v1/courses/42/delete",
                "DELETE /api/v1/courses/42",
                "POST /api/v1/course?action=remove",
            ],
            {"value": "DELETE /api/v1/courses/42"},
            "Адрес называет ресурс, действие задаёт метод.",
            actor_id,
        ),
        question(
            design_quiz.id,
            1,
            "Какие изменения требуют новой версии API?",
            QuestionType.MULTIPLE,
            [
                "Удалили поле из ответа",
                "Добавили необязательное поле в ответ",
                "Сделали необязательное поле запроса обязательным",
                "Переименовали поле",
            ],
            {
                "values": [
                    "Удалили поле из ответа",
                    "Сделали необязательное поле запроса обязательным",
                    "Переименовали поле",
                ]
            },
            "Добавление необязательного поля обратную совместимость не ломает.",
            actor_id,
        ),
    ]

    auth_quiz = Quiz(
        module_id=auth.id,
        lesson_id=None,
        title="Проверка: аутентификация",
        slug="auth-check",
        status=ContentStatus.PUBLISHED,
        created_by=actor_id,
        updated_by=actor_id,
    )
    auth_quiz.questions = [
        question(
            auth_quiz.id,
            0,
            "Зачем в OAuth параметр `state`?",
            QuestionType.SINGLE,
            [
                "Чтобы передать права доступа",
                "Чтобы защититься от CSRF при возврате с провайдера",
                "Чтобы зашифровать код авторизации",
                "Чтобы указать срок жизни токена",
            ],
            {"value": "Чтобы защититься от CSRF при возврате с провайдера"},
            "Случайное одноразовое значение сверяется при возврате и не даёт "
            "подсунуть жертве чужой код.",
            actor_id,
        ),
        question(
            auth_quiz.id,
            1,
            "Что верно про JWT?",
            QuestionType.MULTIPLE,
            [
                "Содержимое зашифровано",
                "Содержимое подписано и читается любым, кто получил токен",
                "Выданный токен нельзя отозвать до истечения срока",
                "Проверка подписи требует запроса в базу",
            ],
            {
                "values": [
                    "Содержимое подписано и читается любым, кто получил токен",
                    "Выданный токен нельзя отозвать до истечения срока",
                ]
            },
            "JWT подписан, но не зашифрован, и проверяется без похода в базу — "
            "поэтому и отозвать его нельзя.",
            actor_id,
        ),
    ]

    for module, lessons, quiz in (
        (basics, basics_lessons, basics_quiz),
        (design, design_lessons, design_quiz),
        (auth, auth_lessons, auth_quiz),
    ):
        module.lessons = lessons
        module.quizzes = [quiz]

    design.depends_on = [
        ModuleDep(module_id=design.id, depends_on_id=basics.id, created_by=actor_id)
    ]
    auth.depends_on = [ModuleDep(module_id=auth.id, depends_on_id=design.id, created_by=actor_id)]

    course.modules = [basics, design, auth]
    return course, [basics, design, auth]


def build_items(modules: list[Module], actor_id: uuid.UUID) -> list[ModuleItem]:
    """
    Отдельным шагом после flush: составной ключ (quiz_id, module_id) требует, чтобы
    тест уже лежал в базе, а порядок вставки SQLAlchemy сам вывести не может —
    у колонки нет собственного ForeignKey, ограничение объявлено на уровне таблицы.
    """
    items: list[ModuleItem] = []
    for module in modules:
        for position, item in enumerate(module.lessons):
            items.append(
                ModuleItem(
                    module_id=module.id,
                    position=position,
                    lesson_id=item.id,
                    created_by=actor_id,
                    updated_by=actor_id,
                )
            )
        items.append(
            ModuleItem(
                module_id=module.id,
                position=len(module.lessons),
                quiz_id=module.quizzes[0].id,
                created_by=actor_id,
                updated_by=actor_id,
            )
        )
    return items


async def attach_track(session: AsyncSession, course: Course, actor_id: uuid.UUID) -> None:
    track = await session.scalar(select(Track).where(Track.slug == TRACK_SLUG))
    if track is None:
        track = Track(
            title="Backend",
            slug=TRACK_SLUG,
            description="Серверная разработка: протоколы, базы данных, эксплуатация.",
            color="#2B7FFF",
            status=ContentStatus.PUBLISHED,
            created_by=actor_id,
            updated_by=actor_id,
        )
        session.add(track)
    position = len(track.courses) if track.courses else 0
    session.add(
        TrackCourse(
            track_id=track.id,
            course_id=course.id,
            position=position,
            created_by=actor_id,
            updated_by=actor_id,
        )
    )


async def seed(settings: Settings, login: str) -> str:
    engine = create_async_engine(settings.database_url, pool_pre_ping=True)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with factory() as session:
            author = await session.scalar(select(User).where(User.login == login))
            if author is None:
                return f"пользователь {login} не найден"
            if author.role != UserRole.ADMIN:
                return f"у {login} роль {author.role}, нужен admin"

            existing = await session.scalar(select(Course).where(Course.slug == COURSE_SLUG))
            if existing is not None:
                return f"курс {COURSE_SLUG} уже есть, ничего не менял"

            course, modules = build_course(author.id)
            session.add(course)
            await session.flush()
            session.add_all(build_items(modules, author.id))
            await attach_track(session, course, author.id)
            await session.commit()
            lessons = sum(len(module.lessons) for module in modules)
            return f"курс {COURSE_SLUG} создан: модулей {len(modules)}, уроков {lessons}"
    finally:
        await engine.dispose()


async def main() -> None:
    login = sys.argv[1] if len(sys.argv) > 1 else "semao0"
    print(await seed(load_settings(), login))  # noqa: T201


if __name__ == "__main__":
    asyncio.run(main())
