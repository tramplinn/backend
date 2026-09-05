from tramplin.infrastructure.repositories.algorithms import AlgorithmRepository
from tramplin.infrastructure.repositories.assets import AssetRepository
from tramplin.infrastructure.repositories.base import Repository
from tramplin.infrastructure.repositories.courses import CourseRepository
from tramplin.infrastructure.repositories.feedback import FeedbackRepository
from tramplin.infrastructure.repositories.identities import UserIdentityRepository
from tramplin.infrastructure.repositories.lesson_progress import LessonProgressRepository
from tramplin.infrastructure.repositories.lessons import LessonRepository
from tramplin.infrastructure.repositories.mcp_oauth import McpOAuthRepository
from tramplin.infrastructure.repositories.modules import ModuleRepository
from tramplin.infrastructure.repositories.news import NewsRepository
from tramplin.infrastructure.repositories.quiz_attempts import QuizAttemptRepository
from tramplin.infrastructure.repositories.quizzes import QuizRepository
from tramplin.infrastructure.repositories.recommendations import RecommendationRepository
from tramplin.infrastructure.repositories.refresh_tokens import RefreshTokenRepository
from tramplin.infrastructure.repositories.tags import TagRepository
from tramplin.infrastructure.repositories.tracks import TrackRepository
from tramplin.infrastructure.repositories.users import UserRepository

__all__ = [
    "AlgorithmRepository",
    "AssetRepository",
    "CourseRepository",
    "FeedbackRepository",
    "LessonProgressRepository",
    "LessonRepository",
    "McpOAuthRepository",
    "ModuleRepository",
    "NewsRepository",
    "QuizAttemptRepository",
    "QuizRepository",
    "RecommendationRepository",
    "RefreshTokenRepository",
    "Repository",
    "TagRepository",
    "TrackRepository",
    "UserIdentityRepository",
    "UserRepository",
]
