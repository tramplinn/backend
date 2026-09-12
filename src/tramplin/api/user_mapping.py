from tramplin.api.schemas.users import MeOut, PublicProfileOut
from tramplin.models.users import User


def _resume_url(user: User, *, asset_base_url: str) -> str | None:
    return f"{asset_base_url}/{user.resume_asset.s3_key}" if user.resume_asset else None


def me_out(user: User, *, asset_base_url: str) -> MeOut:
    return MeOut.model_validate(user).model_copy(
        update={"resume_url": _resume_url(user, asset_base_url=asset_base_url)}
    )


def with_resume_url(
    profile: PublicProfileOut,
    user: User,
    *,
    asset_base_url: str,
) -> PublicProfileOut:
    url = _resume_url(user, asset_base_url=asset_base_url)
    return profile.model_copy(update={"resume_url": url})
