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


class QuestionType(StrEnum):
    SINGLE = "single"
    MULTIPLE = "multiple"
    TEXT = "text"
    MATCHING = "matching"
    GROUPING = "grouping"
    FILE = "file"


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
