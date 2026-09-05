import uuid_utils.compat as uuid
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from tramplin.infrastructure.repositories.base import Repository
from tramplin.models.base import soft_delete
from tramplin.models.enums import IdentityProvider
from tramplin.models.users import UserIdentity


class UserIdentityRepository(Repository):
    async def get_by_provider(
        self,
        provider: IdentityProvider,
        provider_id: str,
    ) -> UserIdentity | None:
        stmt = (
            select(UserIdentity)
            .where(UserIdentity.provider == provider, UserIdentity.provider_id == provider_id)
            .options(selectinload(UserIdentity.user))
        )
        return (await self._session.scalars(stmt)).one_or_none()

    async def get_for_user(
        self,
        user_id: uuid.UUID,
        provider: IdentityProvider,
    ) -> UserIdentity | None:
        stmt = select(UserIdentity).where(
            UserIdentity.user_id == user_id,
            UserIdentity.provider == provider,
        )
        return (await self._session.scalars(stmt)).one_or_none()

    async def list_for_user(self, user_id: uuid.UUID) -> list[UserIdentity]:
        stmt = select(UserIdentity).where(UserIdentity.user_id == user_id)
        return list(await self._session.scalars(stmt))

    def add(self, identity: UserIdentity) -> UserIdentity:
        self._session.add(identity)
        return identity

    async def delete(self, identity: UserIdentity) -> None:
        soft_delete(identity)
