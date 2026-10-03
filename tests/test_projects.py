from dataclasses import dataclass
from datetime import timedelta
from typing import Any, cast

import pytest
from pydantic import ValidationError
from sqlalchemy.dialects import postgresql

from tests.fakes import (
    FakeAssetRepository,
    FakeCompanyRepository,
    FakeEmailJobRepository,
    FakeEmailRenderer,
    FakeIdentityRepository,
    FakeInterestRepository,
    FakeInviteQuota,
    FakeProfileLayoutRepository,
    FakeProjectInviteRepository,
    FakeProjectRepository,
    FakeSession,
    FakeUniversityRepository,
    FakeUserRepository,
)
from tests.test_tutor import FakeRedis
from tramplin.api.schemas.projects import (
    ProfileLayoutIn,
    ProfileProjectsOrderIn,
    ProjectCreate,
    ProjectInviteCreate,
    ProjectLinkIn,
    ProjectLinksIn,
    ProjectMemberUpdate,
    ProjectStatusIn,
    ProjectTransferIn,
    ProjectUpdate,
)
from tramplin.api.v1 import projects as projects_api
from tramplin.api.v1 import users as users_api
from tramplin.core.config import Settings
from tramplin.core.errors import (
    ConflictError,
    ForbiddenError,
    InvalidUpdateError,
    NotFoundError,
    TooManyRequestsError,
)
from tramplin.core.time import utc_now
from tramplin.infrastructure.email_renderer import EmailRenderer
from tramplin.infrastructure.project_invite_quota import ProjectInviteQuota
from tramplin.infrastructure.repositories import (
    ProfileLayoutRepository,
    ProjectInviteRepository,
    ProjectRepository,
)
from tramplin.models.assets import Asset
from tramplin.models.enums import (
    AssetMime,
    ProfileBlock,
    ProjectInviteStatus,
    ProjectLinkKind,
    ProjectRole,
    ProjectStatus,
    ProjectVisibility,
    UserRole,
)
from tramplin.models.projects import Project, ProjectMember, UserProfileBlock
from tramplin.models.users import User
from tramplin.services.profile_layout import (
    DEFAULT_PROFILE_LAYOUT,
    ProfileLayoutItem,
    ProfileLayoutService,
    resolve_layout,
)
from tramplin.services.projects import (
    ProfileProjectOrder,
    ProjectAction,
    ProjectCatalogFilters,
    ProjectLinkInput,
    ProjectService,
    ensure_can,
    slugify,
)
from tramplin.services.users import UserService


class TrackingSession(FakeSession):
    def __init__(self) -> None:
        super().__init__()
        self.flushes = 0

    async def flush(self) -> None:
        self.flushes += 1


@dataclass(slots=True)
class Env:
    service: ProjectService
    session: TrackingSession
    projects: FakeProjectRepository
    invites: FakeProjectInviteRepository
    users: FakeUserRepository
    assets: FakeAssetRepository
    email_jobs: FakeEmailJobRepository
    quota: FakeInviteQuota
    settings: Settings

    def user(self, login: str, *, role: UserRole = UserRole.STUDENT, **extra: Any) -> User:
        user = User(login=login, role=role, is_active=True, **extra)
        return self.users.add(user)


@pytest.fixture
def env(settings: Settings) -> Env:
    session = TrackingSession()
    projects = FakeProjectRepository()
    invites = FakeProjectInviteRepository()
    users = FakeUserRepository()
    assets = FakeAssetRepository()
    email_jobs = FakeEmailJobRepository()
    quota = FakeInviteQuota()
    service = ProjectService(
        session,
        projects,
        invites,
        users,
        assets,
        email_jobs,
        FakeEmailRenderer(),
        quota,
        settings,
    )
    return Env(service, session, projects, invites, users, assets, email_jobs, quota, settings)


async def team(
    env: Env, visibility: ProjectVisibility = ProjectVisibility.PRIVATE
) -> dict[str, Any]:
    """Проект с участником каждой роли плюс посторонний и админ."""
    owner = env.user("owner", email="owner@example.com")
    view = await env.service.create(owner, title="Трамплин", visibility=visibility)
    people: dict[str, Any] = {"owner": owner, "slug": view.project.slug, "project": view.project}
    for role in (ProjectRole.MAINTAINER, ProjectRole.CONTRIBUTOR, ProjectRole.VIEWER):
        member = env.user(role.value, email=f"{role.value}@example.com")
        invite = await env.service.invite(view.project.slug, owner, login=member.login, role=role)
        await env.service.accept_invite(member, invite.id)
        people[role.value] = member
    people["outsider"] = env.user("outsider")
    people["admin"] = env.user("admin", role=UserRole.ADMIN)
    people["anon"] = None
    return people


# --- Права и видимость --------------------------------------------------------

ALLOWED: dict[ProjectAction, set[str]] = {
    ProjectAction.VIEW: {"owner", "maintainer", "contributor", "viewer", "admin"},
    ProjectAction.EDIT_CONTENT: {"owner", "maintainer", "contributor", "admin"},
    ProjectAction.MANAGE_LINKS: {"owner", "maintainer", "contributor", "admin"},
    ProjectAction.CHANGE_STATUS: {"owner", "maintainer", "admin"},
    ProjectAction.EDIT_SETTINGS: {"owner", "maintainer", "admin"},
    ProjectAction.MANAGE_MEMBERS: {"owner", "maintainer", "admin"},
    ProjectAction.CHANGE_ROLES: {"owner", "admin"},
    ProjectAction.TRANSFER: {"owner", "admin"},
    ProjectAction.DELETE: {"owner", "admin"},
}
ACTORS = ("owner", "maintainer", "contributor", "viewer", "outsider", "anon", "admin")


@pytest.mark.parametrize("action", list(ProjectAction))
@pytest.mark.parametrize("actor", ACTORS)
async def test_permission_matrix_on_private_project(
    env: Env, action: ProjectAction, actor: str
) -> None:
    people = await team(env)
    if actor in ALLOWED[action]:
        ensure_can(people["project"], people[actor], action)
    elif actor in {"outsider", "anon"}:
        with pytest.raises(NotFoundError):
            ensure_can(people["project"], people[actor], action)
    else:
        with pytest.raises(ForbiddenError):
            ensure_can(people["project"], people[actor], action)


@pytest.mark.parametrize("actor", ["outsider", "anon"])
async def test_strangers_may_only_view_a_public_project(env: Env, actor: str) -> None:
    people = await team(env, ProjectVisibility.PUBLIC)
    assert ensure_can(people["project"], people[actor], ProjectAction.VIEW) is None
    with pytest.raises(ForbiddenError):
        ensure_can(people["project"], people[actor], ProjectAction.EDIT_CONTENT)


@pytest.mark.parametrize(
    ("visibility", "actor", "visible"),
    [
        (ProjectVisibility.PUBLIC, "anon", True),
        (ProjectVisibility.AUTHENTICATED, "anon", False),
        (ProjectVisibility.AUTHENTICATED, "outsider", True),
        (ProjectVisibility.PRIVATE, "outsider", False),
        (ProjectVisibility.PRIVATE, "viewer", True),
        (ProjectVisibility.PRIVATE, "admin", True),
    ],
)
async def test_hidden_project_is_404_everywhere(
    env: Env, visibility: ProjectVisibility, actor: str, visible: bool
) -> None:
    people = await team(env, visibility)
    reads = (
        env.service.get(people["slug"], people[actor]),
        env.service.members(people["slug"], people[actor]),
        env.service.status_events(people["slug"], people[actor]),
    )
    for read in reads:
        if visible:
            await read
        else:
            with pytest.raises(NotFoundError):
                await read


async def test_teachers_get_no_special_access(env: Env) -> None:
    people = await team(env)
    teacher = env.user("teacher", role=UserRole.TEACHER)
    with pytest.raises(NotFoundError):
        await env.service.get(people["slug"], teacher)


async def test_catalog_never_shows_private_projects(env: Env) -> None:
    people = await team(env)
    filters = ProjectCatalogFilters(query="трамп")

    anon_page = await env.service.catalog(None, filters)
    member_page = await env.service.catalog(people["owner"], filters)

    assert anon_page.items == member_page.items == []
    assert [visibilities for _, visibilities in env.projects.catalog_calls] == [
        [ProjectVisibility.PUBLIC],
        [ProjectVisibility.PUBLIC, ProjectVisibility.AUTHENTICATED],
    ]


# --- Проект, статусы, ссылки --------------------------------------------------


def test_slugify_transliterates_and_falls_back() -> None:
    assert slugify("Мой Пет-проект 2026!") == "moi-pet-proekt-2026"
    assert slugify("🚀") == "project"
    assert len(slugify("щ" * 100)) <= 80


async def test_create_makes_private_idea_with_owner_and_history(env: Env) -> None:
    author = env.user("author")
    view = await env.service.create(author, title="Трамплин", summary="Платформа")

    project = view.project
    assert (project.slug, project.status, project.visibility) == (
        "tramplin",
        ProjectStatus.IDEA,
        ProjectVisibility.PRIVATE,
    )
    assert [(m.user_id, m.role) for m in project.members] == [(author.id, ProjectRole.OWNER)]
    assert view.viewer_role is ProjectRole.OWNER
    events = await env.projects.status_events(project.id)
    assert [(e.from_status, e.to_status) for e in events] == [(None, ProjectStatus.IDEA)]


async def test_slug_collision_gets_a_numeric_suffix(env: Env) -> None:
    author = env.user("author")
    first = await env.service.create(author, title="Трамплин")
    second = await env.service.create(author, title="Трамплин")
    third = await env.service.create(author, title="Трамплин")

    assert [first.project.slug, second.project.slug, third.project.slug] == [
        "tramplin",
        "tramplin-2",
        "tramplin-3",
    ]
    assert [view.project.members[0].profile_position for view in (first, second, third)] == [
        0,
        1,
        2,
    ]


async def test_contributor_edits_readme_but_not_settings(env: Env) -> None:
    people = await team(env)
    contributor = people["contributor"]

    view = await env.service.update(people["slug"], contributor, {"readme_md": "# Привет"})
    assert view.project.readme_md == "# Привет"
    with pytest.raises(ForbiddenError):
        await env.service.update(people["slug"], contributor, {"slug": "new-slug"})
    with pytest.raises(ForbiddenError):
        await env.service.update(people["slug"], people["viewer"], {})


async def test_maintainer_renames_and_changes_slug(env: Env) -> None:
    people = await team(env)
    other = await env.service.create(people["owner"], title="Занято")

    with pytest.raises(ConflictError):
        await env.service.update(people["slug"], people["maintainer"], {"slug": other.project.slug})
    view = await env.service.update(
        people["slug"],
        people["maintainer"],
        {"slug": "new-home", "title": " Новое ", "visibility": ProjectVisibility.PUBLIC},
    )
    assert (view.project.slug, view.project.title, view.project.visibility) == (
        "new-home",
        "Новое",
        ProjectVisibility.PUBLIC,
    )
    with pytest.raises(InvalidUpdateError):
        await env.service.update("new-home", people["owner"], {"title": None})


async def test_logo_must_be_an_image(env: Env) -> None:
    people = await team(env)
    pdf = env.assets.add(Asset(filename="a.pdf", s3_key="a.pdf", mime=AssetMime.PDF, size=1))
    png = env.assets.add(Asset(filename="a.png", s3_key="a.png", mime=AssetMime.PNG, size=1))

    with pytest.raises(InvalidUpdateError):
        await env.service.update(people["slug"], people["owner"], {"logo_asset_id": pdf.id})
    view = await env.service.update(people["slug"], people["owner"], {"logo_asset_id": png.id})
    assert view.project.logo_asset_id == png.id
    cleared = await env.service.update(people["slug"], people["owner"], {"logo_asset_id": None})
    assert cleared.project.logo_asset is None


async def test_status_changes_are_recorded_and_archive_freezes_edits(env: Env) -> None:
    people = await team(env)
    slug = people["slug"]

    with pytest.raises(ForbiddenError):
        await env.service.change_status(slug, people["contributor"], ProjectStatus.DONE)
    await env.service.change_status(slug, people["maintainer"], ProjectStatus.IN_PROGRESS)
    await env.service.change_status(slug, people["maintainer"], ProjectStatus.IN_PROGRESS)
    await env.service.change_status(slug, people["owner"], ProjectStatus.ARCHIVED)

    events = await env.service.status_events(slug, people["viewer"])
    assert [(e.from_status, e.to_status) for e in events] == [
        (ProjectStatus.IN_PROGRESS, ProjectStatus.ARCHIVED),
        (ProjectStatus.IDEA, ProjectStatus.IN_PROGRESS),
        (None, ProjectStatus.IDEA),
    ]
    with pytest.raises(ConflictError):
        await env.service.update(slug, people["owner"], {"readme_md": "x"})
    with pytest.raises(ConflictError):
        await env.service.replace_links(slug, people["owner"], [])
    with pytest.raises(ConflictError):
        await env.service.invite(slug, people["owner"], login="outsider", role=ProjectRole.VIEWER)

    await env.service.change_status(slug, people["owner"], ProjectStatus.PAUSED)
    await env.service.update(slug, people["owner"], {"readme_md": "снова в деле"})


async def test_links_are_replaced_in_the_given_order(env: Env) -> None:
    people = await team(env)
    links = [
        ProjectLinkInput(ProjectLinkKind.DEMO, "https://demo.example.com", "Демо"),
        ProjectLinkInput(ProjectLinkKind.REPOSITORY, "https://github.com/a/b"),
    ]

    view = await env.service.replace_links(people["slug"], people["contributor"], links)
    assert [(link.kind, link.position) for link in view.project.links] == [
        (ProjectLinkKind.DEMO, 0),
        (ProjectLinkKind.REPOSITORY, 1),
    ]
    with pytest.raises(ForbiddenError):
        await env.service.replace_links(people["slug"], people["viewer"], links)


def test_link_schema_rejects_foreign_schemes_and_too_many_links() -> None:
    for url in ("javascript:alert(1)", "ftp://example.com", "https://", "example.com"):
        with pytest.raises(ValidationError):
            ProjectLinkIn(kind=ProjectLinkKind.OTHER, url=url)
    link = {"kind": "demo", "url": "https://example.com"}
    assert len(ProjectLinksIn.model_validate({"links": [link] * 20}).links) == 20
    with pytest.raises(ValidationError):
        ProjectLinksIn.model_validate({"links": [link] * 21})
    with pytest.raises(ValidationError):
        ProjectUpdate(readme_md="x" * 100_001)


async def test_delete_is_owner_only(env: Env) -> None:
    people = await team(env)
    with pytest.raises(ForbiddenError):
        await env.service.delete(people["slug"], people["maintainer"])
    await env.service.delete(people["slug"], people["owner"])
    assert env.projects.projects == {}


# --- Участники и владение -----------------------------------------------------


async def test_owner_cannot_leave_but_others_can(env: Env) -> None:
    people = await team(env)
    with pytest.raises(ConflictError):
        await env.service.remove_member(people["slug"], people["owner"], "owner")
    await env.service.remove_member(people["slug"], people["viewer"], "viewer")
    assert "viewer" not in {m.user.login for m in people["project"].members}


async def test_members_are_removed_only_below_own_role(env: Env) -> None:
    people = await team(env)
    slug = people["slug"]
    second = env.user("second")
    people["project"].members.append(
        _member(people["project"], second, ProjectRole.MAINTAINER, position=0)
    )

    with pytest.raises(ForbiddenError):
        await env.service.remove_member(slug, people["maintainer"], "second")
    with pytest.raises(ForbiddenError):
        await env.service.remove_member(slug, people["contributor"], "viewer")
    with pytest.raises(NotFoundError):
        await env.service.remove_member(slug, people["owner"], "ghost")
    await env.service.remove_member(slug, people["maintainer"], "contributor")
    await env.service.remove_member(slug, people["owner"], "second")
    assert {m.user.login for m in people["project"].members} == {"owner", "maintainer", "viewer"}


async def test_roles_and_titles(env: Env) -> None:
    people = await team(env)
    slug = people["slug"]

    await env.service.update_member(slug, people["viewer"], "viewer", {"title": "Дизайнер"})
    with pytest.raises(ForbiddenError):
        await env.service.update_member(slug, people["viewer"], "contributor", {"title": "x"})
    await env.service.update_member(slug, people["maintainer"], "contributor", {"title": "Бэк"})
    with pytest.raises(ForbiddenError):
        await env.service.update_member(
            slug, people["maintainer"], "viewer", {"role": ProjectRole.CONTRIBUTOR}
        )
    with pytest.raises(ConflictError):
        await env.service.update_member(
            slug, people["owner"], "viewer", {"role": ProjectRole.OWNER}
        )
    with pytest.raises(ConflictError):
        await env.service.update_member(
            slug, people["owner"], "owner", {"role": ProjectRole.VIEWER}
        )
    with pytest.raises(InvalidUpdateError):
        await env.service.update_member(slug, people["owner"], "viewer", {"role": None})
    member = await env.service.update_member(
        slug, people["owner"], "viewer", {"role": ProjectRole.CONTRIBUTOR}
    )
    assert (member.role, member.title) == (ProjectRole.CONTRIBUTOR, "Дизайнер")


async def test_transfer_swaps_owner_and_maintainer(env: Env) -> None:
    people = await team(env)
    slug = people["slug"]

    with pytest.raises(ForbiddenError):
        await env.service.transfer(slug, people["maintainer"], "contributor")
    with pytest.raises(ConflictError):
        await env.service.transfer(slug, people["owner"], "owner")
    await env.service.transfer(slug, people["owner"], "contributor")

    roles = {m.user.login: m.role for m in people["project"].members}
    assert roles["contributor"] is ProjectRole.OWNER
    assert roles["owner"] is ProjectRole.MAINTAINER
    assert list(roles.values()).count(ProjectRole.OWNER) == 1
    assert env.session.flushes == 1


async def test_admin_transfers_ownership_of_a_deactivated_owner(env: Env) -> None:
    people = await team(env)
    people["owner"].is_active = False
    people["viewer"].is_active = False

    with pytest.raises(ConflictError):
        await env.service.transfer(people["slug"], people["admin"], "viewer")
    await env.service.transfer(people["slug"], people["admin"], "maintainer")
    assert {m.user.login: m.role for m in people["project"].members}["maintainer"] is (
        ProjectRole.OWNER
    )


# --- Приглашения --------------------------------------------------------------


async def test_invite_sends_email_and_respects_rules(env: Env) -> None:
    people = await team(env)
    slug = people["slug"]
    newcomer = env.user("newcomer", email="new@example.com")
    quiet = env.user("quiet")
    sent_before = len(env.email_jobs.jobs)

    invite = await env.service.invite(
        slug, people["maintainer"], login="newcomer", role=ProjectRole.CONTRIBUTOR, title="QA"
    )
    await env.service.invite(slug, people["maintainer"], login="quiet", role=ProjectRole.VIEWER)

    assert (invite.status, invite.role, invite.title) == (
        ProjectInviteStatus.PENDING,
        ProjectRole.CONTRIBUTOR,
        "QA",
    )
    assert invite.expires_at - utc_now() > timedelta(days=13)
    jobs = env.email_jobs.jobs[sent_before:]
    assert [(job.to_email, job.category) for job in jobs] == [("new@example.com", "project_invite")]
    assert [item.invitee_id for item in await env.service.my_invites(newcomer)] == [newcomer.id]
    assert len(await env.service.project_invites(slug, people["owner"])) == 2
    assert quiet.id in {item.invitee_id for item in env.invites.invites.values()}


@pytest.mark.parametrize(
    ("actor", "login", "role", "error"),
    [
        ("maintainer", "outsider", ProjectRole.MAINTAINER, ForbiddenError),
        ("contributor", "outsider", ProjectRole.VIEWER, ForbiddenError),
        ("owner", "owner", ProjectRole.VIEWER, ConflictError),
        ("owner", "viewer", ProjectRole.VIEWER, ConflictError),
        ("owner", "ghost", ProjectRole.VIEWER, NotFoundError),
        ("owner", "outsider", ProjectRole.OWNER, InvalidUpdateError),
    ],
)
async def test_invalid_invites(
    env: Env, actor: str, login: str, role: ProjectRole, error: type[Exception]
) -> None:
    people = await team(env)
    with pytest.raises(error):
        await env.service.invite(people["slug"], people[actor], login=login, role=role)


async def test_inactive_users_cannot_be_invited(env: Env) -> None:
    people = await team(env)
    people["outsider"].is_active = False
    with pytest.raises(NotFoundError):
        await env.service.invite(
            people["slug"], people["owner"], login="outsider", role=ProjectRole.VIEWER
        )


async def test_duplicate_pending_invite_conflicts_until_answered(env: Env) -> None:
    people = await team(env)
    slug, owner, outsider = people["slug"], people["owner"], people["outsider"]
    first = await env.service.invite(slug, owner, login="outsider", role=ProjectRole.VIEWER)

    with pytest.raises(ConflictError):
        await env.service.invite(slug, owner, login="outsider", role=ProjectRole.VIEWER)
    await env.service.decline_invite(outsider, first.id)
    assert first.status is ProjectInviteStatus.DECLINED
    second = await env.service.invite(slug, owner, login="outsider", role=ProjectRole.VIEWER)
    await env.service.revoke_invite(slug, owner, second.id)
    assert second.status is ProjectInviteStatus.REVOKED
    with pytest.raises(ConflictError):
        await env.service.revoke_invite(slug, owner, second.id)
    with pytest.raises(NotFoundError):
        await env.service.revoke_invite(slug, owner, people["project"].id)


async def test_expired_invite_is_closed_lazily_and_can_be_resent(env: Env) -> None:
    people = await team(env)
    slug, owner, outsider = people["slug"], people["owner"], people["outsider"]
    stale = await env.service.invite(slug, owner, login="outsider", role=ProjectRole.VIEWER)
    stale.expires_at = utc_now() - timedelta(seconds=1)

    assert await env.service.my_invites(outsider) == []
    assert stale.status is ProjectInviteStatus.EXPIRED
    with pytest.raises(ConflictError):
        await env.service.accept_invite(outsider, stale.id)
    fresh = await env.service.invite(slug, owner, login="outsider", role=ProjectRole.VIEWER)
    assert fresh.status is ProjectInviteStatus.PENDING


async def test_someone_elses_invite_is_404(env: Env) -> None:
    people = await team(env)
    invite = await env.service.invite(
        people["slug"], people["owner"], login="outsider", role=ProjectRole.VIEWER
    )
    with pytest.raises(NotFoundError):
        await env.service.accept_invite(people["viewer"], invite.id)
    with pytest.raises(NotFoundError):
        await env.service.decline_invite(people["viewer"], invite.id)


async def test_accepting_makes_a_member_with_the_invited_role(env: Env) -> None:
    people = await team(env)
    invite = await env.service.invite(
        people["slug"], people["owner"], login="outsider", role=ProjectRole.CONTRIBUTOR, title="ML"
    )
    view = await env.service.accept_invite(people["outsider"], invite.id)

    member = next(m for m in view.project.members if m.user_id == people["outsider"].id)
    assert (member.role, member.title, view.viewer_role) == (
        ProjectRole.CONTRIBUTOR,
        "ML",
        ProjectRole.CONTRIBUTOR,
    )
    assert invite.status is ProjectInviteStatus.ACCEPTED


async def test_invites_are_rate_limited(env: Env) -> None:
    people = await team(env)
    env.quota.limit = len(env.quota.taken)
    with pytest.raises(TooManyRequestsError):
        await env.service.invite(
            people["slug"], people["owner"], login="outsider", role=ProjectRole.VIEWER
        )


async def test_invite_quota_counts_per_hour(settings: Settings) -> None:
    redis = FakeRedis()
    limited = settings.model_copy(update={"project_invites_hourly_quota": 2})
    quota = ProjectInviteQuota(cast(Any, redis), limited)
    user = User(login="u")

    await quota.take(user.id)
    await quota.take(user.id)
    with pytest.raises(TooManyRequestsError):
        await quota.take(user.id)
    assert list(redis.expires.values()) == [7200]


def test_invite_email_template_renders() -> None:
    rendered = EmailRenderer().render(
        "project_invite",
        {
            "project_title": "Трамплин",
            "inviter_name": "Аня",
            "role_label": "участник",
            "invites_url": "https://example.com/me",
            "logo_url": "https://example.com/logo.png",
        },
    )
    assert "Трамплин" in rendered.subject
    assert "https://example.com/me" in rendered.html
    assert "Аня" in rendered.text


def test_invite_schema_rejects_owner_role() -> None:
    with pytest.raises(ValidationError):
        ProjectInviteCreate(login="someone", role=ProjectRole.OWNER)


# --- Профиль ------------------------------------------------------------------


def test_layout_defaults_and_appends_new_blocks() -> None:
    assert [item.block for item in resolve_layout([])] == list(DEFAULT_PROFILE_LAYOUT)
    user = User(login="u")
    saved = [
        UserProfileBlock(user_id=user.id, block=ProfileBlock.STATS, position=0, is_visible=False),
        UserProfileBlock(user_id=user.id, block=ProfileBlock.ABOUT, position=1, is_visible=True),
    ]
    layout = resolve_layout(saved)
    assert [(item.block, item.visible) for item in layout] == [
        (ProfileBlock.STATS, False),
        (ProfileBlock.ABOUT, True),
        (ProfileBlock.PROJECTS, True),
        (ProfileBlock.COURSES, True),
        (ProfileBlock.RESUME, True),
    ]


async def test_layout_save_validates_and_replaces_rows() -> None:
    session = FakeSession()
    rows = FakeProfileLayoutRepository()
    service = ProfileLayoutService(session, rows)
    user = User(login="u")
    full = [
        ProfileLayoutItem(block, block is not ProfileBlock.STATS)
        for block in reversed(DEFAULT_PROFILE_LAYOUT)
    ]

    with pytest.raises(InvalidUpdateError):
        await service.save(user.id, full[:-1])
    with pytest.raises(InvalidUpdateError):
        await service.save(user.id, [*full, full[0]])
    await service.save(user.id, full)
    await service.save(user.id, full)

    assert len(rows.rows) == len(DEFAULT_PROFILE_LAYOUT)
    assert await service.visible_blocks(user.id) == [
        ProfileBlock.RESUME,
        ProfileBlock.COURSES,
        ProfileBlock.PROJECTS,
        ProfileBlock.ABOUT,
    ]
    with pytest.raises(ValidationError):
        ProfileLayoutIn.model_validate({"blocks": [{"block": "secret", "visible": True}]})


async def test_profile_shows_only_visible_projects_in_member_order(env: Env) -> None:
    people = await team(env, ProjectVisibility.PUBLIC)
    owner = people["owner"]
    hidden = await env.service.create(owner, title="Секрет")
    shown = await env.service.create(
        owner, title="Витрина", visibility=ProjectVisibility.AUTHENTICATED
    )

    mine = await env.service.list_mine(owner)
    order = [shown.project.id, people["project"].id, hidden.project.id]
    await env.service.reorder_profile(
        owner,
        [ProfileProjectOrder(pid, pid != people["project"].id) for pid in order],
    )

    assert len(mine) == 3
    as_member = await env.service.list_for_profile(owner, people["viewer"])
    as_anon = await env.service.list_for_profile(owner, None)
    assert [view.project.id for view in as_member] == [shown.project.id]
    assert as_anon == []
    with pytest.raises(ConflictError):
        await env.service.reorder_profile(owner, [ProfileProjectOrder(order[0], True)])


# --- HTTP-слой ----------------------------------------------------------------


async def test_routes_map_projects_for_the_viewer(env: Env, settings: Settings) -> None:
    people = await team(env, ProjectVisibility.PUBLIC)
    owner, slug = people["owner"], people["slug"]
    people["viewer"].is_active = False
    await env.service.replace_links(
        slug, owner, [ProjectLinkInput(ProjectLinkKind.REPOSITORY, "https://gitlab.com/a")]
    )

    as_member = await projects_api.get_project(slug, owner, env.service, settings)
    as_anon = await projects_api.get_project(slug, None, env.service, settings)
    catalog = await projects_api.list_projects(
        None,
        env.service,
        settings,
        q=" трамп ",
        statuses=None,
        link_kind=None,
        member=None,
        sort="title",
        limit=24,
        offset=0,
    )
    events = await projects_api.list_status_events(slug, None, env.service)
    mine = await projects_api.my_projects(owner, env.service, settings)

    assert as_member.my_role is ProjectRole.OWNER
    assert len(as_member.members) == 4
    assert as_anon.my_role is None
    assert "viewer" not in {member.login for member in as_anon.members}
    assert as_anon.members_count == 3
    assert [link.kind for link in as_anon.links] == [ProjectLinkKind.REPOSITORY]
    assert [card.slug for card in catalog.items] == [slug]
    assert env.projects.catalog_calls[-1][0].query == "трамп"
    assert events[0].actor_login == "owner"
    assert [(card.member_title, card.show_in_profile) for card in mine] == [(None, True)]


async def test_routes_cover_the_full_project_lifecycle(env: Env, settings: Settings) -> None:
    owner = env.user("owner")
    guest = env.user("guest", email="guest@example.com")
    created = await projects_api.create_project(
        ProjectCreate(title="Новый"), owner, env.service, settings
    )
    slug = created.slug
    await projects_api.update_project(
        slug, ProjectUpdate(summary="Кратко"), owner, env.service, settings
    )
    await projects_api.change_project_status(
        slug,
        ProjectStatusIn(status=ProjectStatus.PLANNING),
        owner,
        env.service,
        settings,
    )
    await projects_api.replace_links(
        slug,
        ProjectLinksIn.model_validate({"links": [{"kind": "demo", "url": "https://x.dev"}]}),
        owner,
        env.service,
        settings,
    )
    invite = await projects_api.create_invite(
        slug,
        ProjectInviteCreate(login="guest", role=ProjectRole.MAINTAINER),
        owner,
        env.service,
        settings,
    )
    assert [
        item.id
        for item in await projects_api.list_project_invites(slug, owner, env.service, settings)
    ] == [invite.id]
    assert [item.id for item in await projects_api.my_invites(guest, env.service, settings)] == [
        invite.id
    ]
    card = await projects_api.accept_invite(invite.id, guest, env.service, settings)
    assert card.my_role is ProjectRole.MAINTAINER

    members = await projects_api.update_member(
        slug, "guest", ProjectMemberUpdate(title="Фронт"), guest, env.service
    )
    assert {m.login: m.title for m in members}["guest"] == "Фронт"
    assert len(await projects_api.list_members(slug, owner, env.service)) == 2
    transferred = await projects_api.transfer_ownership(
        slug, ProjectTransferIn(login="guest"), owner, env.service, settings
    )
    assert transferred.my_role is ProjectRole.MAINTAINER
    await projects_api.remove_member(slug, "owner", owner, env.service)
    await projects_api.reorder_my_projects(
        ProfileProjectsOrderIn.model_validate(
            {"items": [{"project_id": str(created.id), "show_in_profile": False}]}
        ),
        guest,
        env.service,
    )
    second = await projects_api.create_invite(
        slug,
        ProjectInviteCreate(login="owner", role=ProjectRole.VIEWER),
        guest,
        env.service,
        settings,
    )
    await projects_api.revoke_invite(slug, second.id, guest, env.service)
    third = await projects_api.create_invite(
        slug,
        ProjectInviteCreate(login="owner", role=ProjectRole.VIEWER),
        guest,
        env.service,
        settings,
    )
    await projects_api.decline_invite(third.id, owner, env.service)
    await projects_api.delete_project(slug, guest, env.service)
    assert env.projects.projects == {}


async def test_profile_route_drops_hidden_blocks(env: Env, settings: Settings) -> None:
    owner = env.user("owner", bio="Обо мне")
    await env.service.create(owner, title="Публичный", visibility=ProjectVisibility.PUBLIC)
    layouts = ProfileLayoutService(FakeSession(), FakeProfileLayoutRepository())
    users = UserService(
        FakeSession(),
        env.users,
        FakeIdentityRepository(env.users.users),
        FakeCompanyRepository(),
        FakeUniversityRepository(),
        FakeInterestRepository(),
        env.assets,
    )

    full = await users_api.get_user_profile("owner", owner, users, layouts, env.service, settings)
    assert full.layout == list(DEFAULT_PROFILE_LAYOUT)
    assert (full.bio, full.completed_lessons, [p.title for p in full.projects]) == (
        "Обо мне",
        0,
        ["Публичный"],
    )

    saved = await projects_api.save_profile_layout(
        ProfileLayoutIn.model_validate(
            {
                "blocks": [
                    {"block": "resume", "visible": True},
                    {"block": "about", "visible": False},
                    {"block": "projects", "visible": False},
                    {"block": "stats", "visible": False},
                    {"block": "courses", "visible": False},
                ]
            }
        ),
        owner,
        layouts,
    )
    assert (await projects_api.get_profile_layout(owner, layouts)) == saved
    trimmed = await users_api.get_user_profile(
        "owner", owner, users, layouts, env.service, settings
    )
    assert trimmed.layout == [ProfileBlock.RESUME]
    assert (trimmed.bio, trimmed.completed_lessons, trimmed.projects, trimmed.interests) == (
        None,
        None,
        [],
        [],
    )


# --- SQL репозиториев ---------------------------------------------------------


class _Scalars:
    def __init__(self, values: list[Any]) -> None:
        self._values = values

    def __iter__(self) -> Any:
        return iter(self._values)

    def one_or_none(self) -> Any:
        return self._values[0] if self._values else None

    def first(self) -> Any:
        return self.one_or_none()


DIALECT = postgresql.dialect()  # type: ignore[no-untyped-call]


class RecordingSession:
    def __init__(self, *, scalar: Any = 0, values: list[Any] | None = None) -> None:
        self.statements: list[str] = []
        self._scalar = scalar
        self._values = values or []

    def _record(self, stmt: Any) -> None:
        self.statements.append(
            str(stmt.compile(dialect=DIALECT, compile_kwargs={"literal_binds": True}))
        )

    async def scalar(self, stmt: Any) -> Any:
        self._record(stmt)
        return self._scalar

    async def scalars(self, stmt: Any) -> _Scalars:
        self._record(stmt)
        return _Scalars(self._values)

    async def execute(self, stmt: Any) -> None:
        self._record(stmt)

    def add(self, entity: Any) -> None:
        pass


async def test_catalog_sql_combines_every_filter() -> None:
    session = RecordingSession(scalar=0)
    repository = ProjectRepository(session)  # type: ignore[arg-type]
    filters = ProjectCatalogFilters(
        query="bot",
        statuses=[ProjectStatus.IN_PROGRESS, ProjectStatus.DONE],
        link_kinds=[ProjectLinkKind.REPOSITORY, ProjectLinkKind.DEMO],
        member_login="alice",
        sort="title",
    )

    assert await repository.catalog(
        filters, visibilities=[ProjectVisibility.PUBLIC], limit=24, offset=0
    ) == ([], 0)
    count_sql, list_sql = session.statements
    assert "projects.visibility IN ('public')" in count_sql
    assert "projects.title ILIKE '%%bot%%'" in count_sql
    assert "projects.summary ILIKE '%%bot%%'" in count_sql
    assert "projects.status IN ('in_progress', 'done')" in count_sql
    assert "project_links.kind = 'repository'" in count_sql
    assert "project_links.kind = 'demo'" in count_sql
    assert "users.login = 'alice'" in count_sql
    assert "project_members.show_in_profile IS true" in count_sql
    assert "ORDER BY lower(projects.title)" in list_sql


@pytest.mark.parametrize(
    ("sort", "column"),
    [
        ("updated", "projects.updated_at DESC"),
        ("created", "projects.created_at DESC"),
        ("status_changed", "projects.status_changed_at DESC"),
    ],
)
async def test_catalog_sorts_by_date_newest_first(sort: Any, column: str) -> None:
    session = RecordingSession()
    await ProjectRepository(session).catalog(  # type: ignore[arg-type]
        ProjectCatalogFilters(sort=sort), visibilities=[], limit=1, offset=0
    )
    assert f"ORDER BY {column}" in session.statements[-1]


async def test_project_repositories_issue_their_queries() -> None:
    session = RecordingSession(scalar=None)
    projects = ProjectRepository(session)  # type: ignore[arg-type]
    user = User(login="u")

    assert await projects.list_for_member(user.id) == []
    assert await projects.get_by_slug("x") is None
    assert await projects.slug_exists("x") is False
    assert await projects.status_events(user.id) == []
    assert await projects.next_profile_position(user.id) == 0
    session._scalar = 4
    assert await projects.next_profile_position(user.id) == 5

    invites = ProjectInviteRepository(session)  # type: ignore[arg-type]
    assert await invites.get(user.id) is None
    assert await invites.list_pending_for_project(user.id) == []
    assert await invites.list_pending_for_user(user.id) == []
    assert await invites.find_pending(user.id, user.id) is None

    layouts = ProfileLayoutRepository(session)  # type: ignore[arg-type]
    assert await layouts.list_for_user(user.id) == []
    await layouts.delete_for_user(user.id)
    assert session.statements[-1].startswith("DELETE FROM user_profile_blocks")
    assert any("project_invites.status = 'pending'" in sql for sql in session.statements)


def _member(project: Project, user: User, role: ProjectRole, *, position: int) -> ProjectMember:
    member = ProjectMember(
        project_id=project.id,
        user_id=user.id,
        role=role,
        show_in_profile=True,
        profile_position=position,
        joined_at=utc_now(),
    )
    member.user = user
    return member
