import uuid_utils.compat as uuid
from sqlalchemy import delete

from tramplin.infrastructure.repositories.base import Repository
from tramplin.models.users import RefreshToken


class RefreshTokenRepository(Repository):
    async def consume_by_hash(self, token_hash: str) -> RefreshToken | None:
        """Атомарно забирает одноразовый refresh-токен из хранилища."""
        stmt = (
            delete(RefreshToken)
            .where(RefreshToken.token_hash == token_hash)
            .returning(RefreshToken)
        )
        return (await self._session.scalars(stmt)).one_or_none()

    def add(self, token: RefreshToken) -> RefreshToken:
        self._session.add(token)
        return token

    async def delete_for_user(self, user_id: uuid.UUID) -> int:
        """RETURNING вместо rowcount: даёт точное число удалённых строк с типом из модели."""
        stmt = (
            delete(RefreshToken).where(RefreshToken.user_id == user_id).returning(RefreshToken.id)
        )
        return len((await self._session.scalars(stmt)).all())
