from typing import Any, cast
from unittest.mock import AsyncMock, Mock

from tramplin.core.time import utc_now
from tramplin.infrastructure.repositories import (
    AssetRepository,
    CourseRepository,
    GroupRepository,
    LessonProgressRepository,
    LessonRepository,
    ModuleRepository,
    QuizAttemptRepository,
    QuizRepository,
    RefreshTokenRepository,
    TrackRepository,
    UserIdentityRepository,
    UserRepository,
)
from tramplin.models.assets import Asset
from tramplin.models.base import new_id
from tramplin.models.content import (
    Course,
    InterviewCard,
    Lesson,
    Module,
    ModuleDep,
    Track,
    TrackCourse,
)
from tramplin.models.enums import AssetMime, ContentStatus, IdentityProvider, QuestionType, UserRole
from tramplin.models.progress import LessonProgress, QuizAttempt
from tramplin.models.quizzes import Quiz, QuizQuestion
from tramplin.models.users import RefreshToken, StudentGroup, User, UserIdentity


class ScalarResultFake:
    def __init__(self, values: list[Any]) -> None:
        self.values = values

    def __iter__(self) -> Any:
        return iter(self.values)

    def one_or_none(self) -> Any:
        return self.values[0] if self.values else None

    def first(self) -> Any:
        return self.values[0] if self.values else None

    def all(self) -> list[Any]:
        return self.values


def session_with(*values: Any, total: int = 1) -> Any:
    return cast(
        Any,
        type(
            "SessionFake",
            (),
            {
                "scalars": AsyncMock(return_value=ScalarResultFake(list(values))),
                "scalar": AsyncMock(return_value=total),
                "get": AsyncMock(return_value=values[0] if values else None),
                "execute": AsyncMock(),
                "add": Mock(),
                "delete": AsyncMock(),
            },
        )(),
    )


async def test_asset_course_and_group_repositories() -> None:
    asset = Asset(filename="a.png", s3_key="a", mime=AssetMime.PNG, size=1)
    asset_session = session_with(asset)
    assets = AssetRepository(asset_session)
    assert await assets.list(query="a", mime=AssetMime.PNG, limit=10, offset=0) == ([asset], 1)
    assert await assets.get(asset.id) is asset
    assert assets.add(asset) is asset
    await assets.delete(asset)

    course = Course(title="Course", slug="course", status=ContentStatus.PUBLISHED)
    course_session = session_with(course)
    courses = CourseRepository(course_session)
    assert await courses.list(published_only=True) == [course]
    assert await courses.list(published_only=False) == [course]
    assert await courses.get(course.id) is course
    assert await courses.get_by_slug("course", published_only=True) is course
    assert await courses.get_by_slug("course", published_only=False) is course
    assert courses.add(course) is course
    await courses.delete(course)

    group = StudentGroup(name="G", year=2026)
    group_session = session_with(group)
    groups = GroupRepository(group_session)
    assert await groups.list() == [group]
    assert await groups.get(group.id) is group
    assert groups.add(group) is group
    await groups.delete(group)


async def test_identity_learning_and_token_repositories() -> None:
    user = User(login="user")
    identity = UserIdentity(
        user_id=user.id,
        provider=IdentityProvider.GITHUB,
        provider_id="1",
    )
    identity_session = session_with(identity)
    identities = UserIdentityRepository(identity_session)
    assert await identities.get_by_provider(IdentityProvider.GITHUB, "1") is identity
    assert await identities.get_for_user(user.id, IdentityProvider.GITHUB) is identity
    assert await identities.list_for_user(user.id) == [identity]
    assert identities.add(identity) is identity
    await identities.delete(identity)

    lesson_id = new_id()
    progress = LessonProgress(user_id=user.id, lesson_id=lesson_id)
    attempt = QuizAttempt(
        user_id=user.id,
        quiz_id=new_id(),
        score=1,
        max_score=1,
        answers_json={},
    )
    progress_session = session_with(progress)
    progress_repository = LessonProgressRepository(progress_session)
    assert await progress_repository.get(user.id, lesson_id) is progress
    assert await progress_repository.list(user.id) == [progress]
    assert await progress_repository.list(user.id, course_id=new_id()) == [progress]
    assert progress_repository.add(progress) is progress
    await progress_repository.delete(user.id, lesson_id)

    attempt_session = session_with(attempt)
    attempt_repository = QuizAttemptRepository(attempt_session)
    assert attempt_repository.add(attempt) is attempt
    assert await attempt_repository.list(user.id, attempt.quiz_id) == [attempt]

    token = RefreshToken(user_id=user.id, token_hash="hash", expired_at=utc_now())  # noqa: S106
    token_session = session_with(token)
    tokens = RefreshTokenRepository(token_session)
    assert await tokens.consume_by_hash("hash") is token
    consume_statement = token_session.scalars.await_args.args[0]
    assert consume_statement.is_delete
    assert consume_statement._returning
    assert tokens.add(token) is token
    assert await tokens.delete_for_user(user.id) == 1


async def test_content_repositories() -> None:
    course = Course(title="Course", slug="course")
    module = Module(course_id=course.id, title="Module", slug="module", position=0)
    lesson = Lesson(module_id=module.id, title="Lesson", slug="lesson")
    card = InterviewCard(lesson_id=lesson.id, position=0, question_md="Q", answer_md="A")
    lesson_session = session_with(lesson)
    lessons = LessonRepository(lesson_session)
    assert await lessons.get(lesson.id, published_only=True) is lesson
    assert await lessons.get(lesson.id, published_only=False) is lesson
    assert await lessons.get_with_interview_cards(lesson.id) is lesson
    assert lessons.add(lesson) is lesson
    await lessons.delete(lesson)
    lesson_session.scalars.return_value = ScalarResultFake([card])
    assert await lessons.list_interview_cards(lesson.id) == [card]

    dependency = ModuleDep(module_id=module.id, depends_on_id=new_id())
    module_session = session_with(module)
    modules = ModuleRepository(module_session)
    assert await modules.get(module.id) is module
    assert modules.add(module) is module
    await modules.delete(module)
    module_session.scalars.return_value = ScalarResultFake([dependency])
    assert await modules.list_dependencies(course.id, published_only=True) == [dependency]
    assert await modules.list_dependencies(course.id, published_only=False) == [dependency]
    module_session.get.return_value = dependency
    assert await modules.get_dependency(module.id, dependency.depends_on_id) is dependency
    assert modules.add_dependency(dependency) is dependency
    await modules.delete_dependency(dependency)

    quiz = Quiz(module_id=module.id, title="Quiz", slug="quiz")
    question = QuizQuestion(
        quiz_id=quiz.id,
        position=0,
        prompt_md="Q",
        type=QuestionType.SINGLE,
        options_json=[],
        answer_json={"value": 1},
    )
    quiz_session = session_with(quiz)
    quizzes = QuizRepository(quiz_session)
    assert await quizzes.get(quiz.id, published_only=True) is quiz
    assert await quizzes.get(quiz.id, published_only=False) is quiz
    assert quizzes.add(quiz) is quiz
    await quizzes.delete(quiz)
    quiz_session.scalars.return_value = ScalarResultFake([question])
    assert await quizzes.get_question(question.id) is question
    assert quizzes.add_question(question) is question
    await quizzes.delete_question(question)


async def test_track_and_user_repositories() -> None:
    track = Track(title="Track", slug="track")
    course = Course(title="Course", slug="course")
    link = TrackCourse(track_id=track.id, course_id=course.id, position=0)
    track_session = session_with(track)
    tracks = TrackRepository(track_session)
    assert await tracks.list(published_only=True) == [track]
    assert await tracks.list(published_only=False) == [track]
    assert await tracks.get(track.id) is track
    assert await tracks.get_for_update(track.id) is track
    lock_statement = track_session.scalars.await_args.args[0]
    assert lock_statement._for_update_arg is not None
    assert await tracks.get_by_slug("track", published_only=True) is track
    assert await tracks.get_by_slug("track", published_only=False) is track
    assert tracks.add(track) is track
    await tracks.delete(track)
    track_session.get.return_value = link
    assert await tracks.get_course_link(track.id, course.id) is link
    track_session.scalars.return_value = ScalarResultFake([link])
    assert await tracks.list_course_links(track.id) == [link]
    assert tracks.add_course_link(link) is link
    await tracks.delete_course_link(link)

    user = User(login="user", role=UserRole.STUDENT, is_active=True)
    user_session = session_with(user)
    users = UserRepository(user_session)
    assert await users.list(
        query="u",
        role=UserRole.STUDENT,
        group_id=new_id(),
        is_active=True,
        limit=10,
        offset=0,
    ) == ([user], 1)
    assert await users.get(user.id) is user
    assert await users.get_with_identities(user.id) is user
    assert await users.login_exists("user")
    assert users.add(user) is user
