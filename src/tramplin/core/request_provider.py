from collections.abc import AsyncIterator

from dishka import Provider, Scope, provide
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from tramplin.core.config import Settings
from tramplin.core.security import AccessTokenCodec
from tramplin.infrastructure.github import GitHubOAuthClient
from tramplin.infrastructure.oauth_state import OAuthStateStore
from tramplin.infrastructure.repositories import (
    AlgorithmRepository,
    AssetRepository,
    CourseRepository,
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
from tramplin.infrastructure.s3_storage import S3Storage
from tramplin.infrastructure.tutor_quota import TutorQuota
from tramplin.infrastructure.yandex import YandexOAuthClient
from tramplin.models.enums import IdentityProvider
from tramplin.services.algorithms import (
    AlgorithmAuthoringService,
    AlgorithmOperationsService,
    AlgorithmPracticeService,
    AlgorithmWorkerService,
)
from tramplin.services.assets import AssetService
from tramplin.services.contracts import CodeRunner
from tramplin.services.courses import CourseService
from tramplin.services.lessons import LessonService
from tramplin.services.modules import ModuleService
from tramplin.services.oauth_auth import OAuthAuthService, OAuthClientPort, OAuthRegistry
from tramplin.services.progress import ProgressService
from tramplin.services.quiz_attempts import QuizAttemptService
from tramplin.services.quizzes import QuizService
from tramplin.services.session import SessionService
from tramplin.services.tracks import TrackService
from tramplin.services.tutor import TutorService
from tramplin.services.users import UserService


class RequestProvider(Provider):
    scope = Scope.REQUEST

    @provide
    async def session(
        self,
        factory: async_sessionmaker[AsyncSession],
    ) -> AsyncIterator[AsyncSession]:
        """Сессия живёт один HTTP-запрос; коммит делает сервис, закрытие откатывает остаток."""
        async with factory() as session:
            yield session

    users = provide(UserRepository)
    identities = provide(UserIdentityRepository)
    refresh_tokens = provide(RefreshTokenRepository)
    tracks = provide(TrackRepository)
    courses = provide(CourseRepository)
    modules = provide(ModuleRepository)
    lessons = provide(LessonRepository)
    quizzes = provide(QuizRepository)
    lesson_progress = provide(LessonProgressRepository)
    quiz_attempts = provide(QuizAttemptRepository)
    assets = provide(AssetRepository)
    algorithms = provide(AlgorithmRepository)

    @provide
    def session_service(
        self,
        session: AsyncSession,
        users: UserRepository,
        refresh_tokens: RefreshTokenRepository,
        codec: AccessTokenCodec,
        settings: Settings,
    ) -> SessionService:
        return SessionService(session, users, refresh_tokens, codec, settings)

    @provide
    def user_service(
        self,
        session: AsyncSession,
        users: UserRepository,
        identities: UserIdentityRepository,
    ) -> UserService:
        return UserService(session, users, identities)

    @provide
    def oauth_registry(
        self,
        session: AsyncSession,
        users: UserRepository,
        identities: UserIdentityRepository,
        github: GitHubOAuthClient,
        yandex: YandexOAuthClient,
        state_store: OAuthStateStore,
        sessions: SessionService,
        settings: Settings,
    ) -> OAuthRegistry:
        def build(provider: IdentityProvider, client: OAuthClientPort) -> OAuthAuthService:
            return OAuthAuthService(
                session,
                users,
                identities,
                provider,
                client,
                state_store,
                sessions,
            )

        services = [build(IdentityProvider.GITHUB, github)]
        if settings.yandex_enabled:
            services.append(build(IdentityProvider.YANDEX, yandex))
        return OAuthRegistry(services)

    @provide
    def track_service(
        self,
        session: AsyncSession,
        tracks: TrackRepository,
        courses: CourseRepository,
    ) -> TrackService:
        return TrackService(session, tracks, courses)

    @provide
    def course_service(
        self,
        session: AsyncSession,
        courses: CourseRepository,
        assets: AssetRepository,
    ) -> CourseService:
        return CourseService(session, courses, assets)

    @provide
    def module_service(
        self,
        session: AsyncSession,
        modules: ModuleRepository,
        courses: CourseRepository,
    ) -> ModuleService:
        return ModuleService(session, modules, courses)

    @provide
    def lesson_service(
        self,
        session: AsyncSession,
        lessons: LessonRepository,
        modules: ModuleRepository,
    ) -> LessonService:
        return LessonService(session, lessons, modules)

    @provide
    def quiz_service(
        self,
        session: AsyncSession,
        quizzes: QuizRepository,
        modules: ModuleRepository,
        lessons: LessonRepository,
        assets: AssetRepository,
    ) -> QuizService:
        return QuizService(session, quizzes, modules, lessons, assets)

    @provide
    def progress_service(
        self,
        session: AsyncSession,
        progress: LessonProgressRepository,
        attempts: QuizAttemptRepository,
        lessons: LessonService,
        courses: CourseService,
    ) -> ProgressService:
        return ProgressService(session, progress, attempts, lessons, courses)

    @provide
    def quiz_attempt_service(
        self,
        session: AsyncSession,
        attempts: QuizAttemptRepository,
        quizzes: QuizService,
        assets: AssetRepository,
    ) -> QuizAttemptService:
        return QuizAttemptService(session, attempts, quizzes, assets)

    @provide
    def tutor_service(
        self,
        lessons: LessonService,
        quota: TutorQuota,
        settings: Settings,
    ) -> TutorService:
        return TutorService(lessons, quota, settings)

    @provide
    def asset_service(
        self,
        session: AsyncSession,
        assets: AssetRepository,
        storage: S3Storage,
        settings: Settings,
    ) -> AssetService:
        return AssetService(session, assets, storage, settings)

    @provide
    def algorithm_authoring_service(
        self,
        session: AsyncSession,
        algorithms: AlgorithmRepository,
        modules: ModuleRepository,
        runner: CodeRunner,
        settings: Settings,
    ) -> AlgorithmAuthoringService:
        return AlgorithmAuthoringService(session, algorithms, modules, runner, settings)

    @provide
    def algorithm_practice_service(
        self,
        session: AsyncSession,
        algorithms: AlgorithmRepository,
        settings: Settings,
    ) -> AlgorithmPracticeService:
        return AlgorithmPracticeService(session, algorithms, settings)

    @provide
    def algorithm_worker_service(
        self,
        session: AsyncSession,
        algorithms: AlgorithmRepository,
        runner: CodeRunner,
        settings: Settings,
    ) -> AlgorithmWorkerService:
        return AlgorithmWorkerService(session, algorithms, runner, settings)

    @provide
    def algorithm_operations_service(
        self,
        algorithms: AlgorithmRepository,
        runner: CodeRunner,
    ) -> AlgorithmOperationsService:
        return AlgorithmOperationsService(algorithms, runner)
