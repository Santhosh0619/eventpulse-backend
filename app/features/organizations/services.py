"""Business logic for organizations, memberships, and invitations."""

import secrets
import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.exceptions import (
    ConflictError,
    ForbiddenError,
    NotFoundError,
)
from app.features.organizations import crud
from app.features.organizations.models import Organization, OrganizationMember
from app.features.users import services as users_services
from app.features.users.models import User
from app.shared.enums import InvitationStatus, OrgMemberRole
from app.shared.slug import generate_unique_slug
from app.utils import email as email_utils


async def _require_org(db: AsyncSession, org_id: uuid.UUID) -> Organization:
    """Fetch an organization or raise 404."""
    org = await crud.get_org(db, org_id)
    if org is None:
        raise NotFoundError("Organization not found")
    return org


async def _require_role(
    db: AsyncSession,
    org_id: uuid.UUID,
    user: User,
    allowed: tuple[str, ...],
) -> OrganizationMember:
    """Ensure ``user`` is a member of ``org_id`` with one of ``allowed`` roles."""
    membership = await crud.get_membership(db, org_id, user.id)
    if membership is None:
        raise ForbiddenError("You are not a member of this organization")
    if membership.role not in allowed:
        raise ForbiddenError("Insufficient organization role for this action")
    return membership


async def get_user_org_role(
    db: AsyncSession, org_id: uuid.UUID, user_id: uuid.UUID
) -> str | None:
    """Return the user's accepted role in an org, or ``None`` if not a member.

    Cross-feature helper used by events/media/etc. to enforce org permissions.
    """
    membership = await crud.get_membership(db, org_id, user_id)
    return membership.role if membership else None


async def create_organization(
    db: AsyncSession, user: User, payload: dict
) -> Organization:
    """Create an organization with the caller as its owner."""
    name = payload["name"]
    slug = await generate_unique_slug(
        name, lambda candidate: crud.slug_exists(db, candidate)
    )
    fields = {**payload, "slug": slug, "created_by": user.id}
    return await crud.create_org_with_owner(db, fields=fields, owner_id=user.id)


async def get_organization(db: AsyncSession, org_id: uuid.UUID) -> Organization:
    """Return an organization by id, or raise 404."""
    return await _require_org(db, org_id)


async def update_organization(
    db: AsyncSession, org_id: uuid.UUID, user: User, fields: dict
) -> Organization:
    """Update an organization (requires owner or admin role)."""
    org = await _require_org(db, org_id)
    await _require_role(
        db, org_id, user, (OrgMemberRole.OWNER.value, OrgMemberRole.ADMIN.value)
    )
    if fields:
        await crud.update_org(db, org, fields)
    return org


async def delete_organization(db: AsyncSession, org_id: uuid.UUID, user: User) -> None:
    """Delete an organization (requires owner role)."""
    org = await _require_org(db, org_id)
    await _require_role(db, org_id, user, (OrgMemberRole.OWNER.value,))
    await crud.delete_org(db, org)


async def list_my_organizations(
    db: AsyncSession, user: User
) -> list[tuple[Organization, str]]:
    """Return the organizations the user belongs to, with their role in each."""
    return await crud.list_user_organizations(db, user.id)


async def list_members(
    db: AsyncSession, org_id: uuid.UUID, user: User
) -> list[OrganizationMember]:
    """List an organization's members (requires any membership)."""
    await _require_org(db, org_id)
    await _require_role(
        db,
        org_id,
        user,
        (
            OrgMemberRole.OWNER.value,
            OrgMemberRole.ADMIN.value,
            OrgMemberRole.MEMBER.value,
        ),
    )
    return await crud.list_members(db, org_id)


async def invite_member(
    db: AsyncSession, org_id: uuid.UUID, user: User, *, email: str, role: str
) -> OrganizationMember:
    """Invite a member by email (requires owner or admin role)."""
    await _require_org(db, org_id)
    await _require_role(
        db, org_id, user, (OrgMemberRole.OWNER.value, OrgMemberRole.ADMIN.value)
    )

    # Reject if the email already belongs to an accepted member.
    invitee = await users_services.get_user_by_email(db, email)
    if invitee is not None:
        existing = await crud.get_member_record(db, org_id, invitee.id)
        if existing is not None and (
            existing.invitation_status == InvitationStatus.ACCEPTED.value
        ):
            raise ConflictError("This user is already a member")

    # Reject a second pending invitation to the same email.
    if await crud.get_pending_invite(db, org_id, email) is not None:
        raise ConflictError("An invitation is already pending for this email")

    token = secrets.token_urlsafe(32)
    member = await crud.add_invitation(
        db,
        org_id=org_id,
        email=email,
        role=role,
        token=token,
        invited_by=user.id,
    )

    link = f"{settings.WEB_APP_URL}/invitations/{token}/accept"
    html = email_utils.render_template(
        "org_invitation.html", invitation_link=link, role=role
    )
    await email_utils.send_email(email, "You're invited to an organization", html)
    return member


async def accept_invitation(
    db: AsyncSession, token: str, user: User
) -> OrganizationMember:
    """Accept a pending invitation, binding it to the authenticated user."""
    member = await crud.get_member_by_token(db, token)
    if member is None or member.invitation_status != InvitationStatus.PENDING.value:
        raise NotFoundError("Invitation not found or already used")

    if member.invited_email and member.invited_email != user.email:
        raise ForbiddenError("This invitation was sent to a different email")

    already = await crud.get_member_record(db, member.organization_id, user.id)
    if already is not None:
        raise ConflictError("You are already a member of this organization")

    return await crud.accept_invitation(db, member, user.id)


async def change_member_role(
    db: AsyncSession,
    org_id: uuid.UUID,
    target_user_id: uuid.UUID,
    user: User,
    role: str,
) -> OrganizationMember:
    """Change a member's role (requires owner role)."""
    await _require_org(db, org_id)
    await _require_role(db, org_id, user, (OrgMemberRole.OWNER.value,))

    target = await crud.get_membership(db, org_id, target_user_id)
    if target is None:
        raise NotFoundError("Member not found")

    # Prevent demoting the last remaining owner.
    if (
        target.role == OrgMemberRole.OWNER.value
        and role != OrgMemberRole.OWNER.value
        and await _owner_count(db, org_id) <= 1
    ):
        raise ConflictError("An organization must have at least one owner")

    return await crud.update_member_role(db, target, role)


async def remove_member(
    db: AsyncSession,
    org_id: uuid.UUID,
    target_user_id: uuid.UUID,
    user: User,
) -> None:
    """Remove a member (requires owner or admin role)."""
    await _require_org(db, org_id)
    actor = await _require_role(
        db, org_id, user, (OrgMemberRole.OWNER.value, OrgMemberRole.ADMIN.value)
    )

    target = await crud.get_membership(db, org_id, target_user_id)
    if target is None:
        raise NotFoundError("Member not found")

    # Admins cannot remove owners; the last owner cannot be removed.
    if target.role == OrgMemberRole.OWNER.value:
        if actor.role != OrgMemberRole.OWNER.value:
            raise ForbiddenError("Only an owner can remove another owner")
        if await _owner_count(db, org_id) <= 1:
            raise ConflictError("An organization must have at least one owner")

    await crud.remove_member(db, target)


async def _owner_count(db: AsyncSession, org_id: uuid.UUID) -> int:
    """Return the number of accepted owners in an organization.

    Note: the count-then-mutate sequence is not fully race-safe under highly
    concurrent owner removals/demotions. At this scale that window is acceptable;
    a row-locking guard can be added if owner churn ever becomes contended.
    """
    return await crud.count_owners(db, org_id)
