import asyncio
import base64
from datetime import timedelta
from pathlib import Path

import aioboto3
import uuid_utils.compat as uuid
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import selectinload

from tramplin.core.config import Settings, load_settings
from tramplin.core.security import AccessTokenCodec
from tramplin.infrastructure.s3_storage import S3Storage
from tramplin.models.assets import Asset
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
from tramplin.models.enums import AssetMime, ContentStatus, QuestionType, UserRole
from tramplin.models.progress import LessonProgress, QuizAttempt
from tramplin.models.quizzes import Quiz, QuizQuestion
from tramplin.models.users import User
from tramplin.services.lesson_markdown import render_lesson_content

DEMO_COURSE_SLUG = "demo-fullstack"
DEMO_TRACK_SLUG = "demo-learning-path"
DEMO_ASSET_DIR = Path(__file__).with_name("assets")
DEMO_FULLSTACK_COVER_KEY = "assets/course-covers/demo-fullstack.webp"
DEMO_WEB_BASICS_COVER_KEY = "assets/course-covers/web-basics.webp"
DEMO_EXTRA_MODULES = (
    (
        "Git и командная работа",
        "git",
        "Ветки, pull request и разрешение конфликтов",
        (
            (
                "Ветки и история",
                "branches-history",
                "# Ветки и история\n\n"
                "Работайте небольшими коммитами и сохраняйте линейную историю.",
            ),
            (
                "Pull request",
                "pull-requests",
                "# Pull request\n\nПроверяемые изменения проще обсуждать и безопаснее выпускать.",
            ),
        ),
    ),
    (
        "Docker",
        "docker",
        "Контейнеры и локальное окружение",
        (
            (
                "Dockerfile",
                "dockerfile",
                "# Dockerfile\n\nСобирайте воспроизводимые образы с минимальным runtime-слоем.",
            ),
            (
                "Docker Compose",
                "docker-compose",
                "# Docker Compose\n\nCompose связывает приложение с локальной инфраструктурой.",
            ),
        ),
    ),
    (
        "Асинхронность и интеграции",
        "async-integrations",
        "AsyncIO, фоновые задачи и внешние API",
        (
            (
                "AsyncIO",
                "asyncio",
                "# AsyncIO\n\nНе блокируйте event loop синхронными сетевыми операциями.",
            ),
            (
                "Внешние API",
                "external-apis",
                "# Внешние API\n\nИспользуйте таймауты, ограниченные повторы и идемпотентность.",
            ),
        ),
    ),
    (
        "Тестирование",
        "testing",
        "Unit-, integration- и API-тесты",
        (
            (
                "Pytest",
                "pytest",
                "# Pytest\n\nТест проверяет наблюдаемое поведение, а не детали реализации.",
            ),
            (
                "Интеграционные тесты",
                "integration-tests",
                "# Интеграционные тесты\n\nПроверяйте контракты на реальных границах приложения.",
            ),
        ),
    ),
    (
        "CI/CD",
        "ci-cd",
        "Автоматические проверки и сборка",
        (
            (
                "Pipeline",
                "pipeline",
                "# Pipeline\n\nКаждый merge должен пройти линтеры, тесты и сборку образа.",
            ),
            (
                "Стратегии выпуска",
                "release-strategies",
                "# Стратегии выпуска\n\nНебольшие релизы проще откатывать и диагностировать.",
            ),
        ),
    ),
    (
        "Развёртывание",
        "deployment",
        "Конфигурация production и миграции",
        (
            (
                "Production-конфигурация",
                "production-config",
                "# Production-конфигурация\n\n"
                "Секреты и параметры окружения не должны попадать в образ.",
            ),
            (
                "Миграции без простоя",
                "zero-downtime-migrations",
                "# Миграции без простоя\n\nИзменяйте схему поэтапно с обратной совместимостью.",
            ),
        ),
    ),
    (
        "Наблюдаемость",
        "observability",
        "Логи, метрики, трассировка и алерты",
        (
            (
                "Структурированные логи",
                "structured-logs",
                "# Структурированные логи\n\nДобавляйте request ID и бизнес-контекст к событиям.",
            ),
            (
                "Метрики и алерты",
                "metrics-alerts",
                "# Метрики и алерты\n\nАлерт должен сообщать о влиянии на пользователя.",
            ),
        ),
    ),
)
DEMO_MODULE_DEPENDENCIES = (
    ("fastapi", "python"),
    ("postgresql", "python"),
    ("git", "python"),
    ("docker", "git"),
    ("async-integrations", "fastapi"),
    ("testing", "fastapi"),
    ("ci-cd", "testing"),
    ("deployment", "ci-cd"),
    ("observability", "deployment"),
)
DEMO_ASSETS = (
    (
        "demo-cover.png",
        "assets/demo-cover.png",
        AssetMime.PNG,
        base64.b64decode(
            "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUB"
            "AScY42YAAAAASUVORK5CYII="
        ),
    ),
    (
        "demo-handbook.pdf",
        "assets/demo-handbook.pdf",
        AssetMime.PDF,
        b"%PDF-1.4\n1 0 obj<</Type/Catalog>>endobj\ntrailer<</Root 1 0 R>>\n%%EOF\n",
    ),
    (
        "demo-fullstack.webp",
        DEMO_FULLSTACK_COVER_KEY,
        AssetMime.WEBP,
        (DEMO_ASSET_DIR / "course-covers" / "demo-fullstack.webp").read_bytes(),
    ),
    (
        "web-basics.webp",
        DEMO_WEB_BASICS_COVER_KEY,
        AssetMime.WEBP,
        (DEMO_ASSET_DIR / "course-covers" / "web-basics.webp").read_bytes(),
    ),
)


async def get_or_create_user(
    session: AsyncSession,
    *,
    login: str,
    role: UserRole,
    name: str,
    actor_id: uuid.UUID | None = None,
) -> User:
    user = await session.scalar(select(User).where(User.login == login))
    if user is None:
        user = User(
            login=login,
            name=name,
            role=role,
            is_active=True,
        )
        session.add(user)
        await session.flush()
    user.name = name
    user.role = role
    user.is_active = True
    audit_id = actor_id or user.id
    user.created_by = user.created_by or audit_id
    user.updated_by = audit_id
    return user


def lesson(
    module: Module,
    *,
    title: str,
    slug: str,
    body_md: str,
    actor_id: uuid.UUID,
) -> Lesson:
    rendered = render_lesson_content(body_md)
    item = Lesson(
        module_id=module.id,
        title=title,
        slug=slug,
        est_minutes=20,
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


async def get_or_create_course(session: AsyncSession, actor_id: uuid.UUID) -> Course:
    course = await session.scalar(
        select(Course)
        .where(Course.slug == DEMO_COURSE_SLUG)
        .options(
            selectinload(Course.modules).selectinload(Module.items).selectinload(ModuleItem.lesson),
            selectinload(Course.modules)
            .selectinload(Module.items)
            .selectinload(ModuleItem.quiz)
            .selectinload(Quiz.questions),
        )
    )
    if course is not None:
        return course

    course = Course(
        title="Fullstack-разработка",
        slug=DEMO_COURSE_SLUG,
        summary="Демонстрационный курс для разработки интерфейса Tramplin",
        color="#6366f1",
        est_hours=18,
        status=ContentStatus.PUBLISHED,
        created_by=actor_id,
        updated_by=actor_id,
    )
    modules = [
        Module(
            course_id=course.id,
            title=title,
            slug=slug,
            summary=summary,
            position=position,
            status=ContentStatus.PUBLISHED,
            created_by=actor_id,
            updated_by=actor_id,
        )
        for position, (title, slug, summary) in enumerate(
            [
                ("Основы Python", "python", "Синтаксис и типы данных"),
                ("FastAPI", "fastapi", "HTTP API и валидация"),
                ("PostgreSQL", "postgresql", "Модели данных и запросы"),
            ]
        )
    ]
    course.modules = modules
    python_lessons = [
        lesson(
            modules[0],
            title="Переменные и функции",
            slug="variables-functions",
            body_md="""# Переменные и функции

```python
def greet(name: str) -> str:
    return f"Привет, {name}!"
```""",
            actor_id=actor_id,
        ),
        lesson(
            modules[0],
            title="Коллекции",
            slug="collections",
            body_md="""# Коллекции

:::note
Для отображения списка используйте list comprehension.
:::

:::interview
Чем tuple отличается от list?
---
Tuple неизменяем, list можно изменять.
:::""",
            actor_id=actor_id,
        ),
    ]
    fastapi_lessons = [
        lesson(
            modules[1],
            title="Первый endpoint",
            slug="first-endpoint",
            body_md="""# Первый endpoint

```python
@app.get("/health")
def health():
    return {"status": "ok"}
```""",
            actor_id=actor_id,
        ),
        lesson(
            modules[1],
            title="Схемы Pydantic",
            slug="pydantic-schemas",
            body_md="# Схемы Pydantic\n\nКонтракты API должны быть явными и проверяемыми.",
            actor_id=actor_id,
        ),
    ]
    postgres_lessons = [
        lesson(
            modules[2],
            title="SELECT и JOIN",
            slug="select-join",
            body_md="# SELECT и JOIN\n\n```sql\nSELECT * FROM courses ORDER BY title;\n```",
            actor_id=actor_id,
        ),
        lesson(
            modules[2],
            title="Транзакции",
            slug="transactions",
            body_md="""# Транзакции

:::warning
Не выполняйте внешние сетевые операции внутри долгой транзакции.
:::

:::interview
Что гарантирует атомарность?
---
Транзакция применяется целиком либо не применяется вовсе.
:::""",
            actor_id=actor_id,
        ),
    ]
    quiz = Quiz(
        module_id=modules[0].id,
        lesson_id=python_lessons[1].id,
        title="Проверка основ Python",
        slug="python-basics",
        status=ContentStatus.PUBLISHED,
        created_by=actor_id,
        updated_by=actor_id,
    )
    quiz.questions = [
        QuizQuestion(
            quiz_id=quiz.id,
            position=0,
            prompt_md="Какой тип является неизменяемым?",
            type=QuestionType.SINGLE,
            options_json=["list", "tuple", "dict"],
            answer_json={"value": "tuple"},
            explain_md="Tuple нельзя изменить после создания.",
            created_by=actor_id,
            updated_by=actor_id,
        ),
        QuizQuestion(
            quiz_id=quiz.id,
            position=1,
            prompt_md="Выберите коллекции Python",
            type=QuestionType.MULTIPLE,
            options_json=["list", "set", "SELECT"],
            answer_json={"values": ["list", "set"]},
            explain_md=None,
            created_by=actor_id,
            updated_by=actor_id,
        ),
    ]
    module_lessons = [python_lessons, fastapi_lessons, postgres_lessons]
    for module, lessons in zip(modules, module_lessons, strict=True):
        module.lessons = lessons
        module.items = [
            ModuleItem(
                module_id=module.id,
                position=position,
                lesson_id=lesson_item.id,
                lesson=lesson_item,
                created_by=actor_id,
                updated_by=actor_id,
            )
            for position, lesson_item in enumerate(lessons)
        ]
    modules[0].quizzes = [quiz]
    modules[0].items.append(
        ModuleItem(
            module_id=modules[0].id,
            position=len(modules[0].items),
            quiz_id=quiz.id,
            quiz=quiz,
            created_by=actor_id,
            updated_by=actor_id,
        )
    )
    session.add(course)
    await session.flush()
    session.add_all(
        [
            ModuleDep(
                module_id=modules[1].id,
                depends_on_id=modules[0].id,
                created_by=actor_id,
                updated_by=actor_id,
            ),
            ModuleDep(
                module_id=modules[2].id,
                depends_on_id=modules[1].id,
                created_by=actor_id,
                updated_by=actor_id,
            ),
        ]
    )
    return course


async def expand_demo_course(
    session: AsyncSession,
    course: Course,
    actor_id: uuid.UUID,
) -> None:
    """Дополняет существующий demo-курс, не меняя UUID уже созданного контента."""
    course.est_hours = 42
    course.updated_by = actor_id
    modules_by_slug = {module.slug: module for module in course.modules}
    next_position = max((module.position for module in course.modules), default=-1) + 1

    for title, slug, summary, lesson_specs in DEMO_EXTRA_MODULES:
        if slug in modules_by_slug:
            continue
        module = Module(
            course_id=course.id,
            title=title,
            slug=slug,
            summary=summary,
            position=next_position,
            status=ContentStatus.PUBLISHED,
            created_by=actor_id,
            updated_by=actor_id,
        )
        lessons = [
            lesson(
                module,
                title=lesson_title,
                slug=lesson_slug,
                body_md=body_md,
                actor_id=actor_id,
            )
            for lesson_title, lesson_slug, body_md in lesson_specs
        ]
        module.lessons = lessons
        module.items = [
            ModuleItem(
                module_id=module.id,
                position=position,
                lesson_id=lesson_item.id,
                lesson=lesson_item,
                created_by=actor_id,
                updated_by=actor_id,
            )
            for position, lesson_item in enumerate(lessons)
        ]
        course.modules.append(module)
        modules_by_slug[slug] = module
        next_position += 1

    await session.flush()
    module_ids = [module.id for module in modules_by_slug.values()]
    await session.execute(delete(ModuleDep).where(ModuleDep.module_id.in_(module_ids)))
    for module_slug, dependency_slug in DEMO_MODULE_DEPENDENCIES:
        module = modules_by_slug[module_slug]
        dependency = modules_by_slug[dependency_slug]
        session.add(
            ModuleDep(
                module_id=module.id,
                depends_on_id=dependency.id,
                created_by=actor_id,
                updated_by=actor_id,
            )
        )


async def get_or_create_track(
    session: AsyncSession,
    course: Course,
    actor_id: uuid.UUID,
) -> None:
    track = await session.scalar(select(Track).where(Track.slug == DEMO_TRACK_SLUG))
    if track is None:
        track = Track(
            title="Путь fullstack-разработчика",
            slug=DEMO_TRACK_SLUG,
            description="Демонстрационный учебный трек",
            color="#22c55e",
            status=ContentStatus.PUBLISHED,
            created_by=actor_id,
            updated_by=actor_id,
        )
        session.add(track)
        await session.flush()
    link = await session.get(TrackCourse, (track.id, course.id))
    if link is None:
        max_position = await session.scalar(
            select(TrackCourse.position)
            .where(TrackCourse.track_id == track.id)
            .order_by(TrackCourse.position.desc())
            .limit(1)
        )
        session.add(
            TrackCourse(
                track_id=track.id,
                course_id=course.id,
                position=(max_position if max_position is not None else -1) + 1,
                created_by=actor_id,
                updated_by=actor_id,
            )
        )


async def add_student_activity(
    session: AsyncSession,
    course: Course,
    student: User,
    actor_id: uuid.UUID,
) -> None:
    lessons = [
        item.lesson for module in course.modules for item in module.items if item.lesson is not None
    ]
    for lesson_item in lessons[:3]:
        if await session.get(LessonProgress, (student.id, lesson_item.id)) is None:
            session.add(
                LessonProgress(
                    user_id=student.id,
                    lesson_id=lesson_item.id,
                    created_by=actor_id,
                    updated_by=actor_id,
                )
            )
    quiz = next(
        (item.quiz for module in course.modules for item in module.items if item.quiz is not None),
        None,
    )
    if quiz is None:
        return
    existing_attempt = await session.scalar(
        select(QuizAttempt.id).where(
            QuizAttempt.user_id == student.id,
            QuizAttempt.quiz_id == quiz.id,
        )
    )
    if existing_attempt is None:
        session.add(
            QuizAttempt(
                user_id=student.id,
                quiz_id=quiz.id,
                score=1,
                max_score=2,
                answers_json={str(quiz.questions[0].id): "tuple"},
                created_by=actor_id,
                updated_by=actor_id,
            )
        )


async def add_demo_assets(
    session: AsyncSession,
    settings: Settings,
    actor_id: uuid.UUID,
) -> dict[str, Asset]:
    assets: dict[str, Asset] = {}
    s3_session = aioboto3.Session(
        aws_access_key_id=settings.s3_access_key.get_secret_value(),
        aws_secret_access_key=settings.s3_secret_key.get_secret_value(),
        region_name=settings.s3_region,
    )
    async with s3_session.client("s3", endpoint_url=settings.s3_endpoint_url) as client:
        storage = S3Storage(client, settings.s3_bucket, settings.s3_public_base_url)
        for filename, key, mime, body in DEMO_ASSETS:
            asset = await session.scalar(select(Asset).where(Asset.s3_key == key))
            if asset is None:
                await storage.upload(key, body, mime)
                asset = Asset(
                    filename=filename,
                    s3_key=key,
                    mime=mime,
                    size=len(body),
                    created_by=actor_id,
                    updated_by=actor_id,
                )
                session.add(asset)
            assets[key] = asset
    return assets


async def assign_demo_covers(
    session: AsyncSession,
    course: Course,
    assets: dict[str, Asset],
) -> None:
    course.cover_asset = assets[DEMO_FULLSTACK_COVER_KEY]
    web_basics = await session.scalar(select(Course).where(Course.slug == "web-basics"))
    if web_basics is not None:
        web_basics.cover_asset = assets[DEMO_WEB_BASICS_COVER_KEY]


async def seed(settings: Settings) -> dict[str, User]:
    engine = create_async_engine(settings.database_url, pool_pre_ping=True)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with factory() as session:
            admin = await get_or_create_user(
                session,
                login="demo-admin",
                role=UserRole.ADMIN,
                name="Demo Admin",
            )
            teacher = await get_or_create_user(
                session,
                login="demo-teacher",
                role=UserRole.TEACHER,
                name="Demo Teacher",
                actor_id=admin.id,
            )
            student = await get_or_create_user(
                session,
                login="demo-student",
                role=UserRole.STUDENT,
                name="Demo Student",
                actor_id=admin.id,
            )
            for number in range(2, 6):
                await get_or_create_user(
                    session,
                    login=f"demo-student-{number}",
                    role=UserRole.STUDENT,
                    name=f"Demo Student {number}",
                    actor_id=admin.id,
                )
            course = await get_or_create_course(session, teacher.id)
            await expand_demo_course(session, course, teacher.id)
            assets = await add_demo_assets(session, settings, teacher.id)
            await assign_demo_covers(session, course, assets)
            await get_or_create_track(session, course, teacher.id)
            await add_student_activity(session, course, student, admin.id)
            await session.commit()
            return {"admin": admin, "teacher": teacher, "student": student}
    finally:
        await engine.dispose()


async def main() -> None:
    settings = load_settings()
    users = await seed(settings)
    settings.access_token_ttl = timedelta(days=7)
    codec = AccessTokenCodec(settings)
    print("Demo data is ready. Development access tokens (valid for 7 days):")  # noqa: T201
    for role, user in users.items():
        token, _ = codec.encode(user.id)
        print(f"{role}: {token}")  # noqa: T201


if __name__ == "__main__":
    asyncio.run(main())
