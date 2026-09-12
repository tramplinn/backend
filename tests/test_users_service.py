import pytest
import uuid_utils.compat as uuid

from tests.conftest import AuthEnv
from tests.test_oauth_auth import start_login
from tramplin.api.schemas.users import UserProfileUpdate
from tramplin.api.v1.auth import me, update_me
from tramplin.api.v1.users import get_user_profile, search_users
from tramplin.core.errors import ConflictError, ForbiddenError, InvalidUpdateError, NotFoundError
from tramplin.models.assets import Asset
from tramplin.models.enums import AssetMime, IdentityProvider, UserRole
from tramplin.models.users import User, UserIdentity
from tramplin.services.contracts import CourseActivity, ProfileStats
from tramplin.services.users import ensure_role


async def test_get_profile_returns_user_with_identities(env: AuthEnv) -> None:
    result = await env.github.complete_callback("code", await start_login(env.github))

    profile = await env.users_service.get_profile(result.user.id)

    assert profile.id == result.user.id
    assert profile.login == "student-one"


async def test_public_profile_includes_stats_and_active_courses(env: AuthEnv) -> None:
    result = await env.github.complete_callback("code", await start_login(env.github))
    env.users.stats = ProfileStats(7, 2, 3)
    course = CourseActivity("python", "Python", "#3572a5", 4, 10)
    env.users.courses = [course]

    user, stats, courses = await env.users_service.get_public_profile(result.user.login)

    assert user.id == result.user.id
    assert stats.completed_lessons == 7
    assert courses == [course]


async def test_update_profile_changes_only_public_fields(env: AuthEnv) -> None:
    result = await env.github.complete_callback("code", await start_login(env.github))

    updated = await env.users_service.update_profile(
        result.user.id,
        {
            "name": "Семён",
            "specialty": "backend",
            "grade": "junior",
            "experience_years": 2,
            "role": UserRole.ADMIN,
        },
    )

    assert updated.name == "Семён"
    assert updated.specialty == "backend"
    assert updated.grade == "junior"
    assert updated.experience_years == 2
    assert updated.role is UserRole.STUDENT


async def test_update_profile_sets_company_university_and_interests(env: AuthEnv) -> None:
    result = await env.github.complete_callback("code", await start_login(env.github))

    updated = await env.users_service.update_profile(
        result.user.id,
        {"company": "Yandex", "university": " МГУ ", "interests": ["Go", "go", " ", "Rust"]},
    )

    assert updated.company is not None and updated.company.name == "Yandex"
    assert updated.university is not None and updated.university.name == "МГУ"
    assert [interest.name for interest in updated.interests] == ["Go", "Rust"]

    cleared = await env.users_service.update_profile(
        result.user.id,
        {"company": "", "university": None, "interests": []},
    )

    assert cleared.company is None
    assert cleared.university is None
    assert cleared.interests == []


async def test_update_profile_accepts_pdf_resume_and_rejects_other_mime(env: AuthEnv) -> None:
    result = await env.github.complete_callback("code", await start_login(env.github))
    resume = env.assets.add(
        Asset(filename="cv.pdf", mime=AssetMime.PDF, size=10, s3_key="assets/cv.pdf")
    )
    cover = env.assets.add(
        Asset(filename="cover.png", mime=AssetMime.PNG, size=10, s3_key="assets/cover.png")
    )

    updated = await env.users_service.update_profile(result.user.id, {"resume_asset_id": resume.id})
    assert updated.resume_asset_id == resume.id

    with pytest.raises(InvalidUpdateError):
        await env.users_service.update_profile(result.user.id, {"resume_asset_id": cover.id})

    with pytest.raises(NotFoundError):
        await env.users_service.update_profile(result.user.id, {"resume_asset_id": uuid.uuid7()})

    cleared = await env.users_service.update_profile(result.user.id, {"resume_asset_id": None})
    assert cleared.resume_asset_id is None


async def test_me_route_exposes_resume_url(env: AuthEnv) -> None:
    result = await env.github.complete_callback("code", await start_login(env.github))
    resume = env.assets.add(
        Asset(filename="cv.pdf", mime=AssetMime.PDF, size=10, s3_key="assets/cv.pdf")
    )
    await env.users_service.update_profile(result.user.id, {"resume_asset_id": resume.id})

    profile = await me(result.user, env.users_service, env.settings)

    assert profile.resume_url == f"{env.settings.s3_public_base_url}/assets/cv.pdf"


async def test_public_user_routes_hide_private_fields(env: AuthEnv) -> None:
    result = await env.github.complete_callback("code", await start_login(env.github))
    env.users.stats = ProfileStats(1, 2, 3)

    page = await search_users(env.users_service, q="student", limit=24, offset=0)
    profile = await get_user_profile(result.user.login, env.users_service, env.settings)

    assert page.items[0].login == result.user.login
    assert not hasattr(page.items[0], "email")
    assert profile.solved_algorithms == 3


async def test_update_me_route_returns_refreshed_profile(env: AuthEnv) -> None:
    result = await env.github.complete_callback("code", await start_login(env.github))

    profile = await update_me(
        UserProfileUpdate(headline="Делаю API"),
        result.user,
        env.users_service,
        env.settings,
    )

    assert profile.headline == "Делаю API"


async def test_missing_public_and_editable_profiles_are_not_found(env: AuthEnv) -> None:
    with pytest.raises(NotFoundError):
        await env.users_service.get_profile(User(login="missing").id)
    with pytest.raises(NotFoundError):
        await env.users_service.get_public_profile("missing")
    with pytest.raises(NotFoundError):
        await env.users_service.update_profile(User(login="missing").id, {"bio": "no"})


async def test_unlink_identity_removes_one_of_several(env: AuthEnv) -> None:
    result = await env.github.complete_callback("code", await start_login(env.github))
    env.identities.add(
        UserIdentity(
            user_id=result.user.id,
            provider=IdentityProvider.EMAIL,
            provider_id=result.user.id.hex,
            email="student@example.com",
        )
    )

    await env.users_service.unlink_identity(result.user.id, IdentityProvider.GITHUB)

    remaining = await env.identities.list_for_user(result.user.id)
    assert [identity.provider for identity in remaining] == [IdentityProvider.EMAIL]


async def test_unlink_last_identity_is_rejected(env: AuthEnv) -> None:
    result = await env.github.complete_callback("code", await start_login(env.github))

    with pytest.raises(ConflictError):
        await env.users_service.unlink_identity(result.user.id, IdentityProvider.GITHUB)


async def test_unlink_identity_that_is_not_linked_raises_not_found(env: AuthEnv) -> None:
    user = await env.github.complete_callback("code", await start_login(env.github))
    env.identities.identities.clear()

    with pytest.raises(NotFoundError):
        await env.users_service.unlink_identity(user.user.id, IdentityProvider.GITHUB)


@pytest.mark.parametrize(
    ("role", "minimum", "allowed"),
    [
        (UserRole.STUDENT, UserRole.STUDENT, True),
        (UserRole.STUDENT, UserRole.TEACHER, False),
        (UserRole.STUDENT, UserRole.ADMIN, False),
        (UserRole.TEACHER, UserRole.TEACHER, True),
        (UserRole.TEACHER, UserRole.ADMIN, False),
        (UserRole.ADMIN, UserRole.TEACHER, True),
        (UserRole.ADMIN, UserRole.ADMIN, True),
    ],
)
def test_ensure_role_allows_only_equal_or_higher_role(
    role: UserRole,
    minimum: UserRole,
    allowed: bool,
) -> None:
    user = User(login="someone", role=role, is_active=True)

    if allowed:
        ensure_role(user, minimum)
    else:
        with pytest.raises(ForbiddenError):
            ensure_role(user, minimum)
