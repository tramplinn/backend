from collections.abc import AsyncIterator

from dishka import Provider, Scope, provide
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from tramplin.core.config import Settings
from tramplin.core.security import AccessTokenCodec
from tramplin.infrastructure.email_code_store import EmailCodeStore
from tramplin.infrastructure.email_renderer import EmailRenderer
from tramplin.infrastructure.github import GitHubOAuthClient
from tramplin.infrastructure.gitlab import GitLabOAuthClient
from tramplin.infrastructure.llm import LlmClient
from tramplin.infrastructure.oauth_state import OAuthStateStore
from tramplin.infrastructure.repositories import (
    AlgorithmRepository,
    AssetRepository,
    CompanyRepository,
    CourseRepository,
    EmailJobRepository,
    FeedbackRepository,
    InterestRepository,
    LessonProgressRepository,
    LessonRepository,
    McpOAuthRepository,
    ModuleRepository,
    NewsRepository,
    QuizAttemptRepository,
    QuizRepository,
    RecommendationRepository,
    RefreshTokenRepository,
    TagRepository,
    TrackRepository,
    UniversityRepository,
    UserIdentityRepository,
    UserRepository,
)
from tramplin.infrastructure.s3_storage import S3Storage
from tramplin.infrastructure.tutor_quota import TutorQuota
from tramplin.infrastructure.yandex import YandexOAuthClient
from tramplin.models.enums import IdentityProvider
from tramplin.services.algorithm_plans import AlgorithmPlanService
from tramplin.services.algorithms import (
    AlgorithmAuthoringService,
    AlgorithmOperationsService,
    AlgorithmPracticeService,
    AlgorithmWorkerService,
)
from tramplin.services.assets import AssetService
from tramplin.services.contracts import CodeRunner
from tramplin.services.course_plans import CoursePlanService
from tramplin.services.courses import CourseService
from tramplin.services.directories import CompanyService, InterestService, UniversityService
from tramplin.services.email_auth import EmailAuthService
from tramplin.services.feedback import FeedbackService
from tramplin.services.lessons import LessonService
from tramplin.services.mcp_oauth import McpOAuthService
from tramplin.services.modules import ModuleService
from tramplin.services.news import NewsService
from tramplin.services.oauth_auth import OAuthAuthService, OAuthClientPort, OAuthRegistry
from tramplin.services.progress import ProgressService
from tramplin.services.publish_cascade import PublishCascadeService
from tramplin.services.quiz_attempts import QuizAttemptService
from tramplin.services.quizzes import QuizService
from tramplin.services.recommendations import RecommendationService
from tramplin.services.session import SessionService
from tramplin.services.tags import TagService
from tramplin.services.teacher_assistant import TeacherAssistantService
from tramplin.services.track_plans import TrackPlanService
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
    news = provide(NewsRepository)
    feedback = provide(FeedbackRepository)
    lessons = provide(LessonRepository)
    quizzes = provide(QuizRepository)
    lesson_progress = provide(LessonProgressRepository)
    quiz_attempts = provide(QuizAttemptRepository)
    assets = provide(AssetRepository)
    algorithms = provide(AlgorithmRepository)
    recommendations = provide(RecommendationRepository)
    mcp_oauth = provide(McpOAuthRepository)
    tags = provide(TagRepository)
    email_jobs = provide(EmailJobRepository)
    companies = provide(CompanyRepository)
    universities = provide(UniversityRepository)
    interests = provide(InterestRepository)

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
    def email_auth_service(
        self,
        session: AsyncSession,
        users: UserRepository,
        identities: UserIdentityRepository,
        email_jobs: EmailJobRepository,
        codes: EmailCodeStore,
        renderer: EmailRenderer,
        sessions: SessionService,
        settings: Settings,
    ) -> EmailAuthService:
        return EmailAuthService(
            session, users, identities, email_jobs, codes, renderer, sessions, settings
        )

    @provide
    def course_plan_service(
        self,
        session: AsyncSession,
        courses: CourseRepository,
        modules: ModuleRepository,
        lessons: LessonRepository,
        quizzes: QuizRepository,
        assets: AssetRepository,
        algorithms: AlgorithmRepository,
    ) -> CoursePlanService:
        return CoursePlanService(session, courses, modules, lessons, quizzes, assets, algorithms)

    @provide
    def algorithm_plan_service(
        self,
        session: AsyncSession,
        algorithms: AlgorithmRepository,
        tags: TagRepository,
    ) -> AlgorithmPlanService:
        return AlgorithmPlanService(session, algorithms, tags)

    @provide
    def track_plan_service(
        self,
        session: AsyncSession,
        tracks: TrackRepository,
        courses: CourseRepository,
    ) -> TrackPlanService:
        return TrackPlanService(session, tracks, courses)

    @provide
    def mcp_oauth_service(
        self,
        session: AsyncSession,
        store: McpOAuthRepository,
        users: UserRepository,
        settings: Settings,
    ) -> McpOAuthService:
        return McpOAuthService(session, store, users, settings)

    @provide
    def user_service(
        self,
        session: AsyncSession,
        users: UserRepository,
        identities: UserIdentityRepository,
        companies: CompanyRepository,
        universities: UniversityRepository,
        interests: InterestRepository,
        assets: AssetRepository,
    ) -> UserService:
        return UserService(session, users, identities, companies, universities, interests, assets)

    @provide
    def company_service(self, companies: CompanyRepository) -> CompanyService:
        return CompanyService(companies)

    @provide
    def university_service(self, universities: UniversityRepository) -> UniversityService:
        return UniversityService(universities)

    @provide
    def interest_service(self, interests: InterestRepository) -> InterestService:
        return InterestService(interests)

    @provide
    def oauth_registry(
        self,
        session: AsyncSession,
        users: UserRepository,
        identities: UserIdentityRepository,
        github: GitHubOAuthClient,
        yandex: YandexOAuthClient,
        gitlab: GitLabOAuthClient,
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
        if settings.gitlab_enabled:
            services.append(build(IdentityProvider.GITLAB, gitlab))
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
        tags: TagRepository,
    ) -> CourseService:
        return CourseService(session, courses, assets, tags)

    @provide
    def tag_service(self, tags: TagRepository) -> TagService:
        return TagService(tags)

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
        algorithms: AlgorithmPracticeService,
        quota: TutorQuota,
        settings: Settings,
    ) -> TutorService:
        return TutorService(lessons, algorithms, quota, settings)

    @provide
    def teacher_assistant_service(
        self,
        client: LlmClient,
        settings: Settings,
    ) -> TeacherAssistantService:
        return TeacherAssistantService(client, settings)

    @provide
    def news_service(
        self,
        session: AsyncSession,
        news: NewsRepository,
        assets: AssetRepository,
    ) -> NewsService:
        return NewsService(session, news, assets)

    @provide
    def feedback_service(
        self,
        session: AsyncSession,
        feedback: FeedbackRepository,
        assets: AssetRepository,
    ) -> FeedbackService:
        return FeedbackService(session, feedback, assets)

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
        tags: TagRepository,
    ) -> AlgorithmAuthoringService:
        return AlgorithmAuthoringService(session, algorithms, modules, runner, settings, tags)

    @provide
    def algorithm_practice_service(
        self,
        session: AsyncSession,
        algorithms: AlgorithmRepository,
        settings: Settings,
    ) -> AlgorithmPracticeService:
        return AlgorithmPracticeService(session, algorithms, settings)

    @provide
    def publish_cascade_service(
        self,
        modules: ModuleService,
        courses: CourseService,
        tracks: TrackService,
        lessons: LessonService,
        quizzes: QuizService,
        algorithm_authoring: AlgorithmAuthoringService,
    ) -> PublishCascadeService:
        return PublishCascadeService(
            modules, courses, tracks, lessons, quizzes, algorithm_authoring
        )

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

    @provide
    def recommendation_service(
        self,
        session: AsyncSession,
        recommendations: RecommendationRepository,
        settings: Settings,
    ) -> RecommendationService:
        return RecommendationService(session, recommendations, settings)
