from enum import StrEnum


class ContentStatus(StrEnum):
    DRAFT = "draft"
    PUBLISHED = "published"


class UserRole(StrEnum):
    STUDENT = "student"
    TEACHER = "teacher"
    ADMIN = "admin"


class IdentityProvider(StrEnum):
    """Новый провайдер — новое значение здесь, миграция ALTER TYPE и свой callback-роут."""

    GITHUB = "github"


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
