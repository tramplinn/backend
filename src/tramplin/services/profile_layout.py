from collections.abc import Sequence
from dataclasses import dataclass
from typing import Final, Protocol

import uuid_utils.compat as uuid

from tramplin.core.errors import InvalidUpdateError
from tramplin.models.enums import ProfileBlock
from tramplin.models.projects import UserProfileBlock
from tramplin.services.contracts import Transaction
from tramplin.services.entity_updates import mark_created

DEFAULT_PROFILE_LAYOUT: Final[tuple[ProfileBlock, ...]] = (
    ProfileBlock.ABOUT,
    ProfileBlock.PROJECTS,
    ProfileBlock.STATS,
    ProfileBlock.COURSES,
    ProfileBlock.RESUME,
)


@dataclass(frozen=True, slots=True)
class ProfileLayoutItem:
    block: ProfileBlock
    visible: bool = True


type ProfileLayout = list[ProfileLayoutItem]


class ProfileLayoutRepositoryPort(Protocol):
    async def list_for_user(self, user_id: uuid.UUID) -> list[UserProfileBlock]: ...

    async def delete_for_user(self, user_id: uuid.UUID) -> None: ...

    def add(self, block: UserProfileBlock) -> UserProfileBlock: ...


def resolve_layout(rows: Sequence[UserProfileBlock]) -> ProfileLayout:
    """Сохранённый порядок плюс блоки, которых в нём ещё нет: новые блоки
    появляются в конце видимыми и не требуют миграции данных."""
    if not rows:
        return [ProfileLayoutItem(block) for block in DEFAULT_PROFILE_LAYOUT]
    ordered = sorted(rows, key=lambda row: row.position)
    layout = [ProfileLayoutItem(row.block, row.is_visible) for row in ordered]
    known = {row.block for row in ordered}
    layout.extend(
        ProfileLayoutItem(block) for block in DEFAULT_PROFILE_LAYOUT if block not in known
    )
    return layout


class ProfileLayoutService:
    def __init__(self, transaction: Transaction, blocks: ProfileLayoutRepositoryPort) -> None:
        self._transaction = transaction
        self._blocks = blocks

    async def get(self, user_id: uuid.UUID) -> ProfileLayout:
        return resolve_layout(await self._blocks.list_for_user(user_id))

    async def visible_blocks(self, user_id: uuid.UUID) -> list[ProfileBlock]:
        return [item.block for item in await self.get(user_id) if item.visible]

    async def save(self, user_id: uuid.UUID, items: Sequence[ProfileLayoutItem]) -> ProfileLayout:
        blocks = [item.block for item in items]
        if len(blocks) != len(set(blocks)) or set(blocks) != set(DEFAULT_PROFILE_LAYOUT):
            raise InvalidUpdateError(
                "Раскладка должна содержать каждый блок профиля ровно один раз",
                field="blocks",
            )
        # Удаление и вставка в одной транзакции; уникальность (user_id, position)
        # отложена до коммита, так что перестановка не конфликтует сама с собой.
        await self._blocks.delete_for_user(user_id)
        for position, item in enumerate(items):
            row = UserProfileBlock(
                user_id=user_id,
                block=item.block,
                position=position,
                is_visible=item.visible,
            )
            mark_created(row, user_id)
            self._blocks.add(row)
        await self._transaction.commit()
        return list(items)
