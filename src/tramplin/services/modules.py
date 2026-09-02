from collections.abc import Sequence
from typing import Any, Protocol

import uuid_utils.compat as uuid

from tramplin.core.errors import ConflictError, NotFoundError
from tramplin.models.content import Module, ModuleDep, ModuleItem
from tramplin.services.contracts import Transaction
from tramplin.services.courses import CourseRepositoryPort
from tramplin.services.entity_updates import (
    apply_order,
    apply_order_by,
    mark_created,
    mark_updated,
    validate_required_updates,
)


class ModuleRepositoryPort(Protocol):
    async def get(self, module_id: uuid.UUID) -> Module | None: ...

    async def get_for_update(self, module_id: uuid.UUID) -> Module | None: ...

    async def get_tree(self, module_id: uuid.UUID) -> Module | None: ...

    async def list_items(self, module_id: uuid.UUID) -> list[ModuleItem]: ...

    def add_item(self, item: ModuleItem) -> ModuleItem: ...

    async def list_for_course(self, course_id: uuid.UUID) -> list[Module]: ...

    def add(self, module: Module) -> Module: ...

    async def delete(self, module: Module) -> None: ...

    async def list_dependencies(
        self,
        course_id: uuid.UUID,
        *,
        published_only: bool,
    ) -> list[ModuleDep]: ...

    async def get_dependency(
        self,
        module_id: uuid.UUID,
        depends_on_id: uuid.UUID,
    ) -> ModuleDep | None: ...

    def add_dependency(self, dependency: ModuleDep) -> ModuleDep: ...

    async def delete_dependency(self, dependency: ModuleDep) -> None: ...


def next_module_item(
    items: Sequence[ModuleItem],
    *,
    module_id: uuid.UUID,
    actor_id: uuid.UUID,
    lesson_id: uuid.UUID | None = None,
    quiz_id: uuid.UUID | None = None,
    practice_set_id: uuid.UUID | None = None,
) -> ModuleItem:
    """Создаёт следующий элемент общей ленты уроков и тестов модуля."""
    return ModuleItem(
        module_id=module_id,
        position=max((item.position for item in items), default=-1) + 1,
        lesson_id=lesson_id,
        quiz_id=quiz_id,
        practice_set_id=practice_set_id,
        created_by=actor_id,
        updated_by=actor_id,
    )


class ModuleService:
    def __init__(
        self,
        transaction: Transaction,
        modules: ModuleRepositoryPort,
        courses: CourseRepositoryPort,
    ) -> None:
        self._transaction = transaction
        self._modules = modules
        self._courses = courses

    async def list_dependencies(
        self,
        course_slug: str,
        *,
        published_only: bool = True,
    ) -> list[ModuleDep]:
        course = await self._courses.get_by_slug(course_slug, published_only=published_only)
        if course is None:
            raise NotFoundError("Курс не найден")
        return await self._modules.list_dependencies(
            course.id,
            published_only=published_only,
        )

    async def get_tree(self, module_id: uuid.UUID) -> Module:
        module = await self._modules.get_tree(module_id)
        if module is None:
            raise NotFoundError("Модуль не найден")
        return module

    async def create(self, course_id: uuid.UUID, module: Module, actor_id: uuid.UUID) -> Module:
        if await self._courses.get(course_id) is None:
            raise NotFoundError("Курс не найден")
        module.course_id = course_id
        mark_created(module, actor_id)
        self._modules.add(module)
        await self._transaction.commit()
        return module

    async def update(
        self, module_id: uuid.UUID, changes: dict[str, Any], actor_id: uuid.UUID
    ) -> Module:
        module = await self._modules.get(module_id)
        if module is None:
            raise NotFoundError("Модуль не найден")
        validate_required_updates(changes, {"title", "slug", "position", "status"})
        module.title = changes.get("title", module.title)
        module.slug = changes.get("slug", module.slug)
        module.summary = changes.get("summary", module.summary)
        module.position = changes.get("position", module.position)
        module.status = changes.get("status", module.status)
        mark_updated(module, actor_id)
        await self._transaction.commit()
        return module

    async def add_dependency(
        self,
        module_id: uuid.UUID,
        depends_on_id: uuid.UUID,
        actor_id: uuid.UUID,
    ) -> None:
        module = await self._modules.get(module_id)
        dependency = await self._modules.get(depends_on_id)
        if module is None or dependency is None:
            raise NotFoundError("Модуль не найден")
        if module.id == dependency.id:
            raise ConflictError("Модуль не может зависеть от самого себя")
        if module.course_id != dependency.course_id:
            raise ConflictError("Зависимые модули должны принадлежать одному курсу")
        if await self._modules.get_dependency(module_id, depends_on_id) is not None:
            raise ConflictError("Зависимость уже существует")
        edges = await self._modules.list_dependencies(module.course_id, published_only=False)
        if has_dependency_path(edges, start=depends_on_id, target=module_id):
            raise ConflictError("Зависимость создаёт цикл")
        self._modules.add_dependency(
            ModuleDep(
                module_id=module_id,
                depends_on_id=depends_on_id,
                created_by=actor_id,
                updated_by=actor_id,
            ),
        )
        await self._transaction.commit()

    async def remove_dependency(self, module_id: uuid.UUID, depends_on_id: uuid.UUID) -> None:
        dependency = await self._modules.get_dependency(module_id, depends_on_id)
        if dependency is None:
            raise NotFoundError("Зависимость модулей не найдена")
        await self._modules.delete_dependency(dependency)
        await self._transaction.commit()

    async def reorder(
        self,
        course_id: uuid.UUID,
        module_ids: Sequence[uuid.UUID],
        actor_id: uuid.UUID,
    ) -> None:
        if await self._courses.get(course_id) is None:
            raise NotFoundError("Курс не найден")
        modules = await self._modules.list_for_course(course_id)
        apply_order(modules, module_ids, actor_id, subject="модули курса")
        await self._transaction.commit()

    async def reorder_content(
        self,
        module_id: uuid.UUID,
        item_ids: Sequence[uuid.UUID],
        actor_id: uuid.UUID,
    ) -> None:
        """
        Порядок ленты модуля целиком. Уроки и тесты нумеруются вместе, поэтому
        и переставляются одной транзакцией: раздельные вызовы оставляли бы
        состояние наполовину применённым.
        """
        if await self._modules.get_for_update(module_id) is None:
            raise NotFoundError("Модуль не найден")
        stored = await self._modules.list_items(module_id)
        apply_order_by(
            stored,
            item_ids,
            actor_id,
            subject="материалы модуля",
            key=lambda item: item.id,
        )
        await self._transaction.commit()

    async def delete(self, module_id: uuid.UUID) -> None:
        module = await self._modules.get(module_id)
        if module is None:
            raise NotFoundError("Модуль не найден")
        await self._modules.delete(module)
        await self._transaction.commit()


def has_dependency_path(
    edges: list[ModuleDep],
    *,
    start: uuid.UUID,
    target: uuid.UUID,
) -> bool:
    """Возвращает True, если target достижим по зависимостям из start."""
    adjacency: dict[uuid.UUID, set[uuid.UUID]] = {}
    for edge in edges:
        adjacency.setdefault(edge.module_id, set()).add(edge.depends_on_id)

    pending = [start]
    visited: set[uuid.UUID] = set()
    while pending:
        current = pending.pop()
        if current == target:
            return True
        if current in visited:
            continue
        visited.add(current)
        pending.extend(adjacency.get(current, ()))
    return False
