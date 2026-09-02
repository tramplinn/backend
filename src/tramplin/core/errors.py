from typing import Any, ClassVar


class AppError(Exception):
    """Базовая ошибка домена: всё, что ловит API-слой, наследуется отсюда."""

    status_code: int = 500
    code: str = "internal_error"
    message: str = "Внутренняя ошибка"
    headers: ClassVar[dict[str, str] | None] = None

    def __init__(self, message: str | None = None, /, **details: Any) -> None:
        self.message = message or self.message
        self.details: dict[str, Any] = details
        super().__init__(self.message)


class NotFoundError(AppError):
    status_code = 404
    code = "not_found"
    message = "Объект не найден"


class ConflictError(AppError):
    status_code = 409
    code = "conflict"
    message = "Конфликт состояния"


class UnprocessableError(AppError):
    status_code = 422
    code = "unprocessable"
    message = "Данные не могут быть обработаны"


class TooManyRequestsError(AppError):
    status_code = 429
    code = "too_many_requests"
    message = "Слишком много запросов"


class ServiceUnavailableError(AppError):
    status_code = 503
    code = "service_unavailable"
    message = "Сервис временно недоступен"


class AuthError(AppError):
    status_code = 401
    code = "unauthorized"
    message = "Требуется аутентификация"
    headers: ClassVar[dict[str, str] | None] = {"WWW-Authenticate": "Bearer"}


class ForbiddenError(AppError):
    status_code = 403
    code = "forbidden"
    message = "Недостаточно прав"


class InvalidTokenError(AuthError):
    code = "invalid_token"
    message = "Токен недействителен или истёк"


class OAuthStateError(AuthError):
    code = "invalid_oauth_state"
    message = "OAuth state недействителен или истёк"


class OAuthProviderError(AppError):
    status_code = 502
    code = "oauth_provider_error"
    message = "Провайдер OAuth вернул ошибку"


class StorageError(AppError):
    status_code = 502
    code = "storage_error"
    message = "Хранилище файлов недоступно"


class IdentityAlreadyLinkedError(ConflictError):
    code = "identity_already_linked"
    message = "Этот аккаунт провайдера уже привязан к другому пользователю"


class UserInactiveError(ForbiddenError):
    code = "user_inactive"
    message = "Учётная запись отключена"


class InvalidQuizError(UnprocessableError):
    code = "invalid_quiz"
    message = "Некорректная структура теста"


class InvalidLessonContentError(UnprocessableError):
    code = "invalid_lesson_content"
    message = "Некорректное содержимое урока"


class InvalidUpdateError(UnprocessableError):
    code = "invalid_update"
    message = "Некорректные данные обновления"


class InvalidAlgorithmProblemError(UnprocessableError):
    code = "invalid_algorithm_problem"
    message = "Некорректная алгоритмическая задача"


class SessionExpiredError(ConflictError):
    code = "session_expired"
    message = "Время сессии истекло"


class RunnerUnavailableError(ServiceUnavailableError):
    code = "runner_unavailable"
    message = "Среда выполнения кода недоступна"


class RunnerBusyError(ServiceUnavailableError):
    code = "runner_busy"
    message = "Дождитесь завершения предыдущего запуска"
    headers: ClassVar[dict[str, str] | None] = {"Retry-After": "2"}
