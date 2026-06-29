"""Database operations for organizations and memberships."""

import uuid
from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.features.organizations.models import Organization, OrganizationMember
from app.shared.enums import InvitationStatus, OrgMemberRole


async def slug_exists(db: AsyncSession, slug: str) -> bool:
    """Return ``True`` if an organization already uses the given slug."""
    result = await db.execute(select(Organization.id).where(Organization.slug == slug))
    return result.first() is not None


async def get_org(db: AsyncSession, org_id: uuid.UUID) -> Organization | None:
    """Return an organization by id, or ``None``."""
    return await db.get(Organization, org_id)


async def create_org_with_owner(
    db: AsyncSession, *, fields: dict, owner_id: uuid.UUID, commit: bool = True
) -> Organization:
    """Create an organization and its owner membership in one transaction.

    With ``commit=False`` the rows are only flushed so the caller can commit
    them atomically alongside related writes (e.g. an audit log entry).
    """
    org = Organization(**fields)
    org.members = [
        OrganizationMember(
            user_id=owner_id,
            role=OrgMemberRole.OWNER.value,
            invitation_status=InvitationStatus.ACCEPTED.value,
            joined_at=datetime.now(UTC),
        )
    ]
    db.add(org)
    if commit:
        await db.commit()
    else:
        await db.flush()
    await db.refresh(org)
    return org


async def update_org(db: AsyncSession, org: Organization, fields: dict) -> Organization:
    """Apply the given fields to an organization and persist."""
    for key, value in fields.items():
        setattr(org, key, value)
    await db.commit()
    await db.refresh(org)
    return org


async def delete_org(db: AsyncSession, org: Organization) -> None:
    """Delete an organization (cascades to its memberships)."""
    await db.delete(org)
    await db.commit()


async def get_membership(
    db: AsyncSession, org_id: uuid.UUID, user_id: uuid.UUID
) -> OrganizationMember | None:
    """Return an accepted membership for ``user_id`` in ``org_id``, or ``None``."""
    result = await db.execute(
        select(OrganizationMember).where(
            OrganizationMember.organization_id == org_id,
            OrganizationMember.user_id == user_id,
            OrganizationMember.invitation_status == InvitationStatus.ACCEPTED.value,
        )
    )
    return result.scalar_one_or_none()


async def get_member_record(
    db: AsyncSession, org_id: uuid.UUID, user_id: uuid.UUID
) -> OrganizationMember | None:
    """Return any membership row (any status) for ``user_id`` in ``org_id``."""
    result = await db.execute(
        select(OrganizationMember).where(
            OrganizationMember.organization_id == org_id,
            OrganizationMember.user_id == user_id,
        )
    )
    return result.scalar_one_or_none()


async def get_pending_invite(
    db: AsyncSession, org_id: uuid.UUID, email: str
) -> OrganizationMember | None:
    """Return a pending invitation for ``email`` in ``org_id``, or ``None``."""
    result = await db.execute(
        select(OrganizationMember).where(
            OrganizationMember.organization_id == org_id,
            OrganizationMember.invited_email == email,
            OrganizationMember.invitation_status == InvitationStatus.PENDING.value,
        )
    )
    return result.scalar_one_or_none()


async def count_owners(db: AsyncSession, org_id: uuid.UUID) -> int:
    """Return the number of accepted owners in an organization."""
    result = await db.execute(
        select(func.count())
        .select_from(OrganizationMember)
        .where(
            OrganizationMember.organization_id == org_id,
            OrganizationMember.role == OrgMemberRole.OWNER.value,
            OrganizationMember.invitation_status == InvitationStatus.ACCEPTED.value,
        )
    )
    return result.scalar_one()


async def list_members(db: AsyncSession, org_id: uuid.UUID) -> list[OrganizationMember]:
    """Return all membership rows for an organization."""
    result = await db.execute(
        select(OrganizationMember)
        .where(OrganizationMember.organization_id == org_id)
        .order_by(OrganizationMember.role)
    )
    return list(result.scalars().all())


async def add_invitation(
    db: AsyncSession,
    *,
    org_id: uuid.UUID,
    email: str,
    role: str,
    token: str,
    invited_by: uuid.UUID,
) -> OrganizationMember:
    """Create a pending invitation membership row."""
    member = OrganizationMember(
        organization_id=org_id,
        user_id=None,
        role=role,
        invited_email=email,
        invitation_token=token,
        invitation_status=InvitationStatus.PENDING.value,
        invited_by=invited_by,
    )
    db.add(member)
    await db.commit()
    await db.refresh(member)
    return member


async def get_member_by_token(
    db: AsyncSession, token: str
) -> OrganizationMember | None:
    """Return the membership row holding the given invitation token, or ``None``."""
    result = await db.execute(
        select(OrganizationMember).where(OrganizationMember.invitation_token == token)
    )
    return result.scalar_one_or_none()


async def accept_invitation(
    db: AsyncSession, member: OrganizationMember, user_id: uuid.UUID
) -> OrganizationMember:
    """Bind an accepting user to an invitation and mark it accepted."""
    member.user_id = user_id
    member.invitation_status = InvitationStatus.ACCEPTED.value
    member.invitation_token = None
    member.joined_at = datetime.now(UTC)
    await db.commit()
    await db.refresh(member)
    return member


async def update_member_role(
    db: AsyncSession, member: OrganizationMember, role: str
) -> OrganizationMember:
    """Change a member's role and persist."""
    member.role = role
    await db.commit()
    await db.refresh(member)
    return member


async def remove_member(db: AsyncSession, member: OrganizationMember) -> None:
    """Delete a membership row."""
    await db.delete(member)
    await db.commit()


async def list_user_organizations(
    db: AsyncSession, user_id: uuid.UUID
) -> list[tuple[Organization, str]]:
    """Return ``(organization, role)`` pairs for a user's accepted memberships."""
    result = await db.execute(
        select(Organization, OrganizationMember.role)
        .join(
            OrganizationMember,
            OrganizationMember.organization_id == Organization.id,
        )
        .where(
            OrganizationMember.user_id == user_id,
            OrganizationMember.invitation_status == InvitationStatus.ACCEPTED.value,
        )
    )
    return [(org, role) for org, role in result.all()]
