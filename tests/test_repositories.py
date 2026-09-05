from typing import Any, cast
from unittest.mock import AsyncMock, Mock

from tramplin.core.time import utc_now
from tramplin.infrastructure.repositories import (
    AlgorithmRepository,
    AssetRepository,
    CourseRepository,
    LessonProgressRepository,
    LessonRepository,
    ModuleRepository,
    NewsRepository,
    QuizAttemptRepository,
    QuizRepository,
    RecommendationRepository,
    RefreshTokenRepository,
    TrackRepository,
    UserIdentityRepository,
    UserRepository,
)
from tramplin.models.algorithms import (
    AlgorithmJobOutbox,
    AlgorithmProblem,
    AlgorithmProgress,
    AlgorithmSubmission,
    AlgorithmTemplate,
    AlgorithmTestCase,
    PracticeSession,
    PracticeSet,
    PracticeSetProblem,
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
from tramplin.models.enums import (
    AlgorithmDifficulty,
    AlgorithmProgressStatus,
    AlgorithmProvider,
    AlgorithmVerdict,
    AssetMime,
    ContentStatus,
    IdentityProvider,
    PracticeMode,
    PracticeSessionStatus,
    QuestionType,
    RecommendationEntityType,
    SubmissionKind,
    SubmissionStatus,
    UserRole,
)
from tramplin.models.news import News
from tramplin.models.progress import LessonProgress, QuizAttempt
from tramplin.models.quizzes import Quiz, QuizQuestion
from tramplin.models.recommendations import EmbeddingJobOutbox
from tramplin.models.users import RefreshToken, User, UserIdentity


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


async def test_news_repository_reads_the_feed_and_single_items() -> None:
    news = News(title="Новость", slug="novost", body_md="", status=ContentStatus.PUBLISHED)
    session = session_with(news, total=3)
    repository = NewsRepository(session)

    assert await repository.list(published_only=True, limit=10, offset=0) == ([news], 3)
    assert await repository.list(published_only=False, limit=10, offset=0) == ([news], 3)
    assert await repository.get(news.id) is news
    assert await repository.get_by_slug("novost", published_only=True) is news
    assert await repository.get_by_slug("novost", published_only=False) is news
    assert repository.add(news) is news
    await repository.delete(news)


async def test_asset_course_and_group_repositories() -> None:
    asset = Asset(filename="a.png", s3_key="a", mime=AssetMime.PNG, size=1)
    asset_session = session_with(asset)
    assets = AssetRepository(asset_session)
    assert await assets.get(asset.id) is asset
    assert assets.add(asset) is asset

    course = Course(title="Course", slug="course", status=ContentStatus.PUBLISHED)
    course_session = session_with(course)
    courses = CourseRepository(course_session)
    assert await courses.list(published_only=True) == [course]
    assert await courses.list(published_only=False) == [course]
    assert await courses.get(course.id) is course
    assert await courses.get_by_slug("course", published_only=True) is course
    assert await courses.get_by_slug("course", published_only=False) is course
    assert courses.add(course) is course
    await courses.delete_cascade(course)


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
    await progress_repository.delete_for_lesson(user.id, lesson_id)

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
    await modules.delete_cascade(module)
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


async def test_algorithm_repository_queries_and_mutations() -> None:
    user_id = new_id()
    problem = AlgorithmProblem(
        provider=AlgorithmProvider.INTERNAL,
        external_key=None,
        external_url=None,
        title="Problem",
        statement_md="S",
        statement_html="<p>S</p>",
        difficulty=AlgorithmDifficulty.EASY,
        topics=[],
        time_limit_ms=1000,
        memory_limit_kb=262144,
        status=ContentStatus.PUBLISHED,
    )
    case = AlgorithmTestCase(
        problem_id=problem.id,
        position=0,
        input="",
        expected_output="ok",
        is_sample=True,
        weight=1,
    )
    template = AlgorithmTemplate(
        problem_id=problem.id,
        language="python",
        starter_code="",
        solution_code="print('ok')",
        validated_at=utc_now(),
    )
    practice_set = PracticeSet(
        title="Set",
        description="",
        mode=PracticeMode.PRACTICE,
        duration_minutes=None,
        status=ContentStatus.PUBLISHED,
    )
    link = PracticeSetProblem(
        practice_set_id=practice_set.id,
        problem_id=problem.id,
        position=0,
        recommended_minutes=None,
    )
    practice_session = PracticeSession(
        practice_set_id=practice_set.id,
        user_id=user_id,
        mode=PracticeMode.PRACTICE,
        status=PracticeSessionStatus.ACTIVE,
        started_at=utc_now(),
        deadline_at=None,
        completed_at=None,
        reflection_md=None,
    )
    submission = AlgorithmSubmission(
        session_id=practice_session.id,
        problem_id=problem.id,
        user_id=user_id,
        kind=SubmissionKind.SUBMIT,
        language="python",
        source_code="x",
        custom_input=None,
        status=SubmissionStatus.QUEUED,
        verdict=AlgorithmVerdict.ACCEPTED,
        runtime_ms=None,
        memory_kb=None,
        failed_test=None,
        stdout=None,
        stderr=None,
        safe_error=None,
        judge_token=None,
        result_json=None,
        claimed_at=None,
        finished_at=None,
        progress_counted=False,
    )
    progress = AlgorithmProgress(
        user_id=user_id,
        problem_id=problem.id,
        status=AlgorithmProgressStatus.UNSEEN,
        attempts=0,
        hints_used=0,
        first_solved_at=None,
        last_attempt_at=None,
        confidence=None,
        complexity_md=None,
        reflection_md=None,
        last_counted_submission_id=None,
    )
    event = AlgorithmJobOutbox(
        submission_id=submission.id,
        dispatched_at=None,
        attempts=0,
        last_error=None,
    )
    session = session_with(problem, total=1)
    repository = AlgorithmRepository(session)

    assert await repository.get_problem(problem.id, published_only=True) is problem
    assert await repository.get_problem(problem.id, published_only=False) is problem
    assert repository.add_problem(problem) is problem
    await repository.delete_problem(problem)
    session.get.side_effect = [case, template, link]
    assert await repository.get_test_case(case.id) is case
    assert repository.add_test_case(case) is case
    await repository.delete_test_case(case)
    assert await repository.get_template(problem.id, "python") is template
    assert repository.add_template(template) is template
    await repository.delete_template(template)

    session.scalars.return_value = ScalarResultFake([practice_set])
    assert await repository.get_set(practice_set.id, published_only=True) is practice_set
    assert await repository.get_set(practice_set.id, published_only=False) is practice_set
    assert repository.add_set(practice_set) is practice_set
    await repository.delete_set(practice_set)
    assert repository.add_set_problem(link) is link
    await repository.delete_set_problem(link)
    assert await repository.get_set_problem(practice_set.id, problem.id) is link

    assert repository.add_session(practice_session) is practice_session
    session.scalars.return_value = ScalarResultFake([practice_session])
    assert await repository.get_session(practice_session.id) is practice_session
    assert await repository.get_session(practice_session.id, for_update=True) is practice_session
    await repository.lock_user(user_id)
    assert repository.add_submission(submission) is submission
    assert repository.add_outbox(event) is event
    session.scalars.return_value = ScalarResultFake([event])
    assert await repository.claim_outbox() is event
    session.scalars.return_value = ScalarResultFake([submission])
    assert await repository.get_submission(submission.id) is submission
    assert await repository.get_submission(submission.id, for_update=True) is submission
    assert await repository.active_submissions(user_id) == 1
    assert (
        await repository.submission_count(
            user_id=user_id,
            since=utc_now(),
            session_id=practice_session.id,
            problem_id=problem.id,
        )
        == 1
    )
    assert await repository.claim_submission(stale_before=utc_now()) is submission
    session.scalars.return_value = ScalarResultFake([progress])
    assert await repository.get_progress(user_id, problem.id) is progress
    assert await repository.get_progress(user_id, problem.id, for_update=True) is progress
    assert repository.add_progress(progress) is progress

    session.scalars.return_value = ScalarResultFake([problem])
    assert await repository.list_published_problems(
        difficulty=AlgorithmDifficulty.EASY,
        topic="arrays",
        query="two",
        limit=10,
        offset=0,
    ) == ([problem], 1)
    assert await repository.list_published_problems(
        difficulty=None, topic=None, query=None, limit=10, offset=0
    ) == ([problem], 1)
    session.scalars.return_value = ScalarResultFake(["arrays"])
    assert await repository.published_topics() == ["arrays"]
    session.scalars.return_value = ScalarResultFake([progress])
    assert await repository.progress_map(user_id, [problem.id]) == {problem.id: progress}
    assert await repository.progress_map(user_id, []) == {}


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
        is_active=True,
        limit=10,
        offset=0,
    ) == ([user], 1)
    assert await users.get(user.id) is user
    assert await users.get_with_identities(user.id) is user
    assert await users.login_exists("user")
    assert users.add(user) is user


async def test_recommendation_repository_queries_and_mutations() -> None:
    user_id = new_id()
    problem = AlgorithmProblem(
        provider=AlgorithmProvider.INTERNAL,
        external_key=None,
        external_url=None,
        title="Problem",
        statement_md="S",
        statement_html="<p>S</p>",
        difficulty=AlgorithmDifficulty.EASY,
        topics=["графы"],
        time_limit_ms=1000,
        memory_limit_kb=262144,
        status=ContentStatus.PUBLISHED,
    )
    course = Course(
        title="Course",
        summary="S",
        slug="course",
        color=None,
        est_hours=10,
        status=ContentStatus.PUBLISHED,
        topics=["графы"],
    )
    job = EmbeddingJobOutbox(
        entity_type=RecommendationEntityType.ALGORITHM_PROBLEM,
        entity_id=problem.id,
        dispatched_at=None,
        attempts=0,
        last_error=None,
    )
    session = session_with(problem, total=1)
    repository = RecommendationRepository(session)

    session.scalars.return_value = ScalarResultFake([problem])
    assert await repository.candidate_algorithm_problems(user_id) == [problem]
    assert await repository.engaged_algorithm_signal(user_id) == [problem]

    session.scalars.return_value = ScalarResultFake([course])
    assert await repository.candidate_courses(user_id) == [course]
    assert await repository.engaged_course_signal(user_id) == [course]

    session.scalars.return_value = ScalarResultFake([job])
    assert await repository.claim_embedding_job() is job

    session.get.return_value = problem
    assert await repository.get_algorithm_problem(problem.id) is problem
    session.get.return_value = course
    assert await repository.get_course(course.id) is course

    await repository.enqueue_embedding_jobs([])
    session.execute.assert_not_called()
    await repository.enqueue_embedding_jobs(
        [(RecommendationEntityType.ALGORITHM_PROBLEM, problem.id)]
    )
    await repository.set_embedding(
        RecommendationEntityType.ALGORITHM_PROBLEM, problem.id, [0.1, 0.2]
    )
    assert session.execute.await_count == 2
