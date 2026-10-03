from enum import StrEnum


class ContentStatus(StrEnum):
    DRAFT = "draft"
    PUBLISHED = "published"


class UserRole(StrEnum):
    STUDENT = "student"
    TEACHER = "teacher"
    ADMIN = "admin"


class IdentityProvider(StrEnum):
    """Новый провайдер — новое значение здесь, миграция ALTER TYPE и свои настройки."""

    GITHUB = "github"
    YANDEX = "yandex"
    GITLAB = "gitlab"
    EMAIL = "email"


class QuestionType(StrEnum):
    SINGLE = "single"
    MULTIPLE = "multiple"
    TEXT = "text"
    MATCHING = "matching"
    GROUPING = "grouping"
    FILE = "file"


class FeedbackStatus(StrEnum):
    """Обратная связь без разбора бесполезна, поэтому у неё есть состояние."""

    NEW = "new"
    RESOLVED = "resolved"


class AssetMime(StrEnum):
    """image/svg+xml отсутствует сознательно: SVG исполняет JS, отдача со своего домена = XSS."""

    PNG = "image/png"
    JPEG = "image/jpeg"
    WEBP = "image/webp"
    GIF = "image/gif"
    PDF = "application/pdf"


class AlgorithmProvider(StrEnum):
    INTERNAL = "internal"
    LEETCODE = "leetcode"
    CODEFORCES = "codeforces"
    EXTERNAL = "external"


class AlgorithmDifficulty(StrEnum):
    EASY = "easy"
    MEDIUM = "medium"
    HARD = "hard"


class PracticeMode(StrEnum):
    PRACTICE = "practice"
    MOCK_INTERVIEW = "mock_interview"


class PracticeSessionStatus(StrEnum):
    ACTIVE = "active"
    COMPLETED = "completed"
    EXPIRED = "expired"


class SubmissionKind(StrEnum):
    RUN = "run"
    SUBMIT = "submit"


class SubmissionStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    FINISHED = "finished"
    FAILED = "failed"


class AlgorithmVerdict(StrEnum):
    ACCEPTED = "accepted"
    WRONG_ANSWER = "wrong_answer"
    COMPILE_ERROR = "compile_error"
    RUNTIME_ERROR = "runtime_error"
    TIME_LIMIT = "time_limit"
    MEMORY_LIMIT = "memory_limit"
    OUTPUT_LIMIT = "output_limit"
    INTERNAL_ERROR = "internal_error"


class AlgorithmProgressStatus(StrEnum):
    UNSEEN = "unseen"
    ATTEMPTED = "attempted"
    SOLVED = "solved"
    REVIEW = "review"


class RecommendationEntityType(StrEnum):
    COURSE = "course"
    ALGORITHM_PROBLEM = "algorithm_problem"


class EmailQueue(StrEnum):
    """Приоритет доставки: транзакционные письма не должны стоять за рассылками."""

    TRANSACTIONAL = "transactional"
    BULK = "bulk"


class ProjectStatus(StrEnum):
    """Переходы свободные; archived лишь запрещает правки до смены статуса."""

    IDEA = "idea"
    PLANNING = "planning"
    IN_PROGRESS = "in_progress"
    PAUSED = "paused"
    DONE = "done"
    ARCHIVED = "archived"


class ProjectVisibility(StrEnum):
    PUBLIC = "public"
    AUTHENTICATED = "authenticated"
    PRIVATE = "private"


class ProjectRole(StrEnum):
    OWNER = "owner"
    MAINTAINER = "maintainer"
    CONTRIBUTOR = "contributor"
    VIEWER = "viewer"


class ProjectInviteStatus(StrEnum):
    PENDING = "pending"
    ACCEPTED = "accepted"
    DECLINED = "declined"
    REVOKED = "revoked"
    EXPIRED = "expired"


class ProjectLinkKind(StrEnum):
    REPOSITORY = "repository"
    DEMO = "demo"
    DOCS = "docs"
    DESIGN = "design"
    VIDEO = "video"
    PRESENTATION = "presentation"
    OTHER = "other"


class ProfileBlock(StrEnum):
    """Новый блок — новое значение здесь и в DEFAULT_PROFILE_LAYOUT, без миграции данных."""

    ABOUT = "about"
    PROJECTS = "projects"
    STATS = "stats"
    COURSES = "courses"
    RESUME = "resume"
