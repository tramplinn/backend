"""Общий формат ответа планов (курсы, банк задач, треки): diff и найденные проблемы."""

from typing import Literal

import uuid_utils.compat as uuid
from pydantic import Field

from tramplin.api.schemas.base import ApiModel
from tramplin.services.plan_report import PlanReport


class PlanChangeOut(ApiModel):
    action: Literal["create", "update", "unchanged"]
    kind: str = Field(description="Тип сущности: course, module, lesson, quiz, question, …")
    path: str = Field(description="Человекочитаемый адрес, например 'python/basics/intro'.")
    entity_id: uuid.UUID | None = Field(
        description="id сущности; для create в preview — id, который будет присвоен."
    )
    fields: list[str] = Field(description="Изменённые поля; пусто для create и unchanged.")


class PlanIssueOut(ApiModel):
    severity: Literal["error", "warning"] = Field(description="'error' блокирует apply.")
    path: str
    code: str = Field(description="Машиночитаемый код проблемы, например 'unknown_problem'.")
    message: str


class PlanReportOut(ApiModel):
    valid: bool = Field(description="Нет проблем с severity='error'.")
    created: int
    updated: int
    unchanged: int
    changes: list[PlanChangeOut]
    issues: list[PlanIssueOut]
    warnings: list[str]


def plan_report_fields(report: PlanReport) -> dict[str, object]:
    return {
        "valid": report.valid,
        "created": report.created,
        "updated": report.updated,
        "unchanged": report.unchanged,
        "changes": [
            PlanChangeOut(
                action=change.action,
                kind=change.kind,
                path=change.path,
                entity_id=change.entity_id,
                fields=change.fields,
            )
            for change in report.changes
        ],
        "issues": [
            PlanIssueOut(
                severity=issue.severity, path=issue.path, code=issue.code, message=issue.message
            )
            for issue in report.issues
        ],
        "warnings": list(dict.fromkeys(report.warnings)),
    }
