from tramplin.api.schemas.projects import (
    ProjectCardOut,
    ProjectInviteOut,
    ProjectInviteProjectOut,
    ProjectLinkOut,
    ProjectMemberOut,
    ProjectOut,
    ProjectStatusEventOut,
)
from tramplin.models.projects import Project, ProjectInvite, ProjectMember, ProjectStatusEvent
from tramplin.services.projects import ProjectView


def _logo_url(project: Project, *, asset_base_url: str) -> str | None:
    logo = project.logo_asset
    return f"{asset_base_url}/{logo.s3_key}" if logo is not None else None


def _visible_members(view: ProjectView) -> list[ProjectMember]:
    """Отключённых пользователей видят только сами участники (и админы)."""
    members = view.project.members
    if view.viewer_role is not None:
        return list(members)
    return [member for member in members if member.user.is_active]


def member_out(member: ProjectMember) -> ProjectMemberOut:
    return ProjectMemberOut(
        user_id=member.user_id,
        login=member.user.login,
        name=member.user.name,
        avatar_url=member.user.avatar_url,
        role=member.role,
        title=member.title,
        joined_at=member.joined_at,
    )


def project_card_out(view: ProjectView, *, asset_base_url: str) -> ProjectCardOut:
    project = view.project
    return ProjectCardOut(
        id=project.id,
        slug=project.slug,
        title=project.title,
        summary=project.summary,
        status=project.status,
        visibility=project.visibility,
        logo_url=_logo_url(project, asset_base_url=asset_base_url),
        members_count=len(_visible_members(view)),
        my_role=view.viewer_role,
        member_title=view.member.title if view.member else None,
        show_in_profile=view.member.show_in_profile if view.member else None,
        updated_at=project.updated_at,
    )


def project_out(view: ProjectView, *, asset_base_url: str) -> ProjectOut:
    project = view.project
    return ProjectOut(
        **project_card_out(view, asset_base_url=asset_base_url).model_dump(),
        readme_md=project.readme_md,
        logo_asset_id=project.logo_asset_id,
        links=[ProjectLinkOut.model_validate(link) for link in project.links],
        members=[member_out(member) for member in _visible_members(view)],
        status_changed_at=project.status_changed_at,
        created_at=project.created_at,
    )


def members_out(view: ProjectView) -> list[ProjectMemberOut]:
    return [member_out(member) for member in _visible_members(view)]


def status_event_out(event: ProjectStatusEvent) -> ProjectStatusEventOut:
    return ProjectStatusEventOut(
        id=event.id,
        from_status=event.from_status,
        to_status=event.to_status,
        actor_login=event.actor.login if event.actor else None,
        created_at=event.created_at,
    )


def invite_out(invite: ProjectInvite, *, asset_base_url: str) -> ProjectInviteOut:
    return ProjectInviteOut(
        id=invite.id,
        project=ProjectInviteProjectOut(
            slug=invite.project.slug,
            title=invite.project.title,
            logo_url=_logo_url(invite.project, asset_base_url=asset_base_url),
        ),
        invitee_login=invite.invitee.login,
        inviter_login=invite.inviter.login if invite.inviter else None,
        role=invite.role,
        title=invite.title,
        status=invite.status,
        expires_at=invite.expires_at,
        created_at=invite.created_at,
    )
