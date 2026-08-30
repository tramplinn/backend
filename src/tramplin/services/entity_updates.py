from collections.abc import Callable, Sequence
from typing import Any, Protocol

import uuid_utils.compat as uuid

from tramplin.core.errors import ConflictError, InvalidUpdateError
from tramplin.models.base import Base


def apply_changes(entity: object, changes: dict[str, Any], *, required: set[str]) -> None:
    for field, value in changes.items():
        if field in required and value is None:
            raise InvalidUpdateError(f"Поле {field} не может быть null", field=field)
        setattr(entity, field, value)


def mark_created(entity: Base, actor_id: uuid.UUID) -> None:
    entity.created_by = actor_id
    entity.updated_by = actor_id


def mark_updated(entity: Base, actor_id: uuid.UUID) -> None:
    entity.updated_by = actor_id


class Positioned(Protocol):
    position: int
    updated_by: uuid.UUID | None


class IdentifiedPositioned(Positioned, Protocol):
    id: uuid.UUID


def apply_order(
    items: Sequence[IdentifiedPositioned],
    ordered_ids: Sequence[uuid.UUID],
    actor_id: uuid.UUID,
    *,
    subject: str,
) -> None:
    apply_order_by(
        items,
        ordered_ids,
        actor_id,
        subject=subject,
        key=lambda item: item.id,
    )


def apply_order_by[T: Positioned](
    items: Sequence[T],
    ordered_ids: Sequence[uuid.UUID],
    actor_id: uuid.UUID,
    *,
    subject: str,
    key: Callable[[T], uuid.UUID],
) -> None:
    """
    Расставляет position по индексам списка. Порядок задаётся целиком: частичный
    список молча оставил бы дыры, а уникальность (parent, position) отложена до
    конца транзакции — перестановка соседей проходит только целым набором.
    """
    by_id = {key(item): item for item in items}
    requested = set(ordered_ids)
    existing = set(by_id)
    if requested != existing:
        raise ConflictError(
            f"Порядок должен содержать все {subject} ровно один раз",
            missing=[str(item) for item in existing - requested],
            unknown=[str(item) for item in requested - existing],
        )
    for position, item_id in enumerate(ordered_ids):
        entity = by_id[item_id]
        entity.position = position
        entity.updated_by = actor_id
