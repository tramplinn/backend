import uuid_utils.compat as uuid
from sqlalchemy import select
from sqlalchemy.orm import aliased, selectinload

from tramplin.infrastructure.repositories.base import Repository
from tramplin.models.content import Module, ModuleDep, ModuleItem
from tramplin.models.enums import ContentStatus
from tramplin.models.quizzes import Quiz, QuizQuestion


class ModuleRepository(Repository):
    async def get(self, module_id: uuid.UUID) -> Module | None:
        return await self._session.get(Module, module_id)

    async def get_for_update(self, module_id: uuid.UUID) -> Module | None:
        stmt = select(Module).where(Module.id == module_id).with_for_update()
        return (await self._session.scalars(stmt)).one_or_none()

    async def get_tree(self, module_id: uuid.UUID) -> Module | None:
        """Модуль вместе с уроками и тестами: редактору теста нужны соседи."""
        stmt = (
            select(Module)
            .where(Module.id == module_id)
            .options(
                selectinload(Module.items).selectinload(ModuleItem.lesson),
                selectinload(Module.items)
                .selectinload(ModuleItem.quiz)
                .selectinload(Quiz.questions),
                selectinload(Module.items)
                .selectinload(ModuleItem.quiz)
                .selectinload(Quiz.questions)
                .selectinload(QuizQuestion.attachments),
            )
        )
        return (await self._session.scalars(stmt)).one_or_none()

    async def list_for_course(self, course_id: uuid.UUID) -> list[Module]:
        stmt = select(Module).where(Module.course_id == course_id).order_by(Module.position)
        return list(await self._session.scalars(stmt))

    async def list_items(self, module_id: uuid.UUID) -> list[ModuleItem]:
        stmt = (
            select(ModuleItem)
            .where(ModuleItem.module_id == module_id)
            .order_by(ModuleItem.position)
        )
        return list(await self._session.scalars(stmt))

    def add_item(self, item: ModuleItem) -> ModuleItem:
        self._session.add(item)
        return item

    def add(self, module: Module) -> Module:
        self._session.add(module)
        return module

    async def delete(self, module: Module) -> None:
        await self._session.delete(module)

    async def list_dependencies(
        self,
        course_id: uuid.UUID,
        *,
        published_only: bool,
    ) -> list[ModuleDep]:
        required = aliased(Module)
        stmt = (
            select(ModuleDep)
            .join(Module, ModuleDep.module_id == Module.id)
            .join(required, ModuleDep.depends_on_id == required.id)
            .where(Module.course_id == course_id)
        )
        if published_only:
            stmt = stmt.where(
                Module.status == ContentStatus.PUBLISHED,
                required.status == ContentStatus.PUBLISHED,
            )
        return list(await self._session.scalars(stmt))

    async def get_dependency(
        self,
        module_id: uuid.UUID,
        depends_on_id: uuid.UUID,
    ) -> ModuleDep | None:
        return await self._session.get(ModuleDep, (module_id, depends_on_id))

    def add_dependency(self, dependency: ModuleDep) -> ModuleDep:
        self._session.add(dependency)
        return dependency

    async def delete_dependency(self, dependency: ModuleDep) -> None:
        await self._session.delete(dependency)
