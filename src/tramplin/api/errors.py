import logging
from http import HTTPStatus
from typing import Final

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy.exc import IntegrityError
from starlette.exceptions import HTTPException

from tramplin.api.schemas import ErrorOut
from tramplin.core.errors import AppError

logger = logging.getLogger(__name__)

HANDLED_EXCEPTIONS: Final = (
    AppError,
    RequestValidationError,
    HTTPException,
    IntegrityError,
    Exception,
)


async def error_handler(_: Request, exc: Exception) -> JSONResponse:
    response = exception_response(exc)
    if response.status_code >= status.HTTP_500_INTERNAL_SERVER_ERROR:
        logger.error("request failed: %s", type(exc).__name__, exc_info=exc)
    return response


def register_error_handlers(app: FastAPI) -> None:
    for exception in HANDLED_EXCEPTIONS:
        app.add_exception_handler(exception, error_handler)


def exception_response(exc: Exception) -> JSONResponse:
    """Преобразует исключение в единый публичный DTO ошибки."""
    if isinstance(exc, AppError):
        return _error_response(
            ErrorOut(code=exc.code, message=exc.message, details=exc.details),
            status_code=exc.status_code,
            headers=exc.headers,
        )
    if isinstance(exc, RequestValidationError):
        return _error_response(
            ErrorOut(
                code="validation_error",
                message="Некорректные данные запроса",
                details={"fields": _validation_fields(exc)},
            ),
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
        )
    if isinstance(exc, HTTPException):
        return _error_response(
            ErrorOut(code=_status_code_name(exc.status_code), message=str(exc.detail)),
            status_code=exc.status_code,
            headers=dict(exc.headers) if exc.headers else None,
        )
    if isinstance(exc, IntegrityError):
        return _error_response(
            ErrorOut(code="conflict", message="Объект с такими данными уже существует"),
            status_code=status.HTTP_409_CONFLICT,
        )
    return _error_response(
        ErrorOut(code=AppError.code, message=AppError.message),
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
    )


def _error_response(
    error: ErrorOut,
    *,
    status_code: int,
    headers: dict[str, str] | None = None,
) -> JSONResponse:
    return JSONResponse(
        content=error.model_dump(mode="json"),
        status_code=status_code,
        headers=headers,
    )


def _validation_fields(exc: RequestValidationError) -> list[dict[str, str]]:
    return [
        {"loc": ".".join(str(part) for part in error["loc"]), "message": error["msg"]}
        for error in exc.errors()
    ]


def _status_code_name(status_code: int) -> str:
    """404 → not_found, 405 → method_not_allowed: код ошибки выводится из статуса."""
    try:
        return HTTPStatus(status_code).phrase.lower().replace(" ", "_")
    except ValueError:
        return "http_error"
