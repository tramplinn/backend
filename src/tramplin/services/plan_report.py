"""Отчёт о плане: какие сущности он создаёт/меняет и какие проблемы в нём найдены.

Один и тот же код применения работает и для предпросмотра (без commit, сессия
откатывается при закрытии), и для настоящего apply, поэтому предпросмотр не может
разойтись с тем, что реально будет записано.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Literal

import uuid_utils.compat as uuid

from tramplin.core.errors import InvalidPlanError
from tramplin.models.base import Base
from tramplin.models.enums import ContentStatus
from tramplin.services.entity_updates import mark_created, mark_updated

type ChangeAction = Literal["create", "update", "unchanged"]
type IssueSeverity = Literal["error", "warning"]


@dataclass(slots=True)
class PlanChange:
    action: ChangeAction
    kind: str
    path: str
    entity: Any = None
    fields: list[str] = field(default_factory=list)

    @property
    def entity_id(self) -> uuid.UUID | None:
        return getattr(self.entity, "id", None)

    def touch(self, field_name: str) -> None:
        """Отмечает изменение, которое не сводится к полю самой сущности (например, порядок)."""
        if self.action == "create":
            return
        self.action = "update"
        if field_name not in self.fields:
            self.fields.append(field_name)


@dataclass(slots=True, frozen=True)
class PlanIssue:
    severity: IssueSeverity
    path: str
    code: str
    message: str


@dataclass(slots=True)
class PlanReport:
    changes: list[PlanChange] = field(default_factory=list)
    issues: list[PlanIssue] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def valid(self) -> bool:
        return not any(issue.severity == "error" for issue in self.issues)

    @property
    def created(self) -> int:
        return sum(change.action == "create" for change in self.changes)

    @property
    def updated(self) -> int:
        return sum(change.action == "update" for change in self.changes)

    @property
    def unchanged(self) -> int:
        return sum(change.action == "unchanged" for change in self.changes)

    def error(self, path: str, code: str, message: str) -> None:
        self.issues.append(PlanIssue("error", path, code, message))

    def warning(self, path: str, code: str, message: str) -> None:
        self.issues.append(PlanIssue("warning", path, code, message))

    def raise_if_invalid(self) -> None:
        if not self.valid:
            raise InvalidPlanError(issues=[asdict(issue) for issue in self.issues])

    def create(self, kind: str, path: str, entity: Base, actor_id: uuid.UUID) -> PlanChange:
        mark_created(entity, actor_id)
        change = PlanChange("create", kind, path, entity)
        self.changes.append(change)
        return change

    def update(
        self,
        kind: str,
        path: str,
        entity: Base,
        values: dict[str, object],
        actor_id: uuid.UUID,
    ) -> PlanChange:
        fields = [name for name, value in values.items() if getattr(entity, name) != value]
        if "status" in fields and getattr(entity, "status", None) == ContentStatus.PUBLISHED:
            self.warnings.append(f"{path}: опубликованная сущность станет черновиком")
        for name in fields:
            setattr(entity, name, values[name])
        if fields:
            mark_updated(entity, actor_id)
        change = PlanChange("update" if fields else "unchanged", kind, path, entity, fields)
        self.changes.append(change)
        return change
