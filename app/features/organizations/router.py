"""Organization endpoints: CRUD, membership management, and invitations."""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, status

from app.core.dependencies import DBSession, get_current_user
from app.features.organizations import services
from app.features.organizations.models import Organization, OrganizationMember
from app.features.organizations.schemas import (
    InviteRequest,
    InviteResponse,
    MemberRead,
    MemberRoleUpdate,
    OrgCreate,
    OrgRead,
    OrgUpdate,
    OrgWithRole,
)
from app.features.users.models import User

router = APIRouter()
# Routes that live under /api/v1/users but belong to the organizations feature.
user_orgs_router = APIRouter()

CurrentUser = Annotated[User, Depends(get_current_user)]


@user_orgs_router.get(
    "/me/organizations",
    response_model=list[OrgWithRole],
    summary="List my organizations",
)
async def list_my_organizations(
    current_user: CurrentUser, db: DBSession
) -> list[OrgWithRole]:
    """Return the organizations the authenticated user belongs to, with role."""
    pairs = await services.list_my_organizations(db, current_user)
    return [
        OrgWithRole(**OrgRead.model_validate(org).model_dump(), my_role=role)
        for org, role in pairs
    ]


@router.post(
    "",
    response_model=OrgRead,
    status_code=status.HTTP_201_CREATED,
    summary="Create an organization",
)
async def create_organization(
    payload: OrgCreate, current_user: CurrentUser, db: DBSession
) -> Organization:
    """Create an organization with the caller as owner."""
    return await services.create_organization(
        db, current_user, payload.model_dump(exclude_none=True)
    )


@router.post(
    "/invitations/{token}/accept",
    response_model=MemberRead,
    summary="Accept an invitation",
)
async def accept_invitation(
    token: str, current_user: CurrentUser, db: DBSession
) -> OrganizationMember:
    """Accept a pending organization invitation."""
    return await services.accept_invitation(db, token, current_user)


@router.get("/{org_id}", response_model=OrgRead, summary="Get an organization")
async def get_organization(org_id: uuid.UUID, db: DBSession) -> Organization:
    """Return a single organization by id (public)."""
    return await services.get_organization(db, org_id)


@router.put("/{org_id}", response_model=OrgRead, summary="Update an organization")
async def update_organization(
    org_id: uuid.UUID,
    payload: OrgUpdate,
    current_user: CurrentUser,
    db: DBSession,
) -> Organization:
    """Update an organization (owner or admin)."""
    return await services.update_organization(
        db, org_id, current_user, payload.model_dump(exclude_unset=True)
    )


@router.delete(
    "/{org_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete an organization",
)
async def delete_organization(
    org_id: uuid.UUID, current_user: CurrentUser, db: DBSession
) -> None:
    """Delete an organization (owner only)."""
    await services.delete_organization(db, org_id, current_user)


@router.post(
    "/{org_id}/members/invite",
    response_model=InviteResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Invite a member",
)
async def invite_member(
    org_id: uuid.UUID,
    payload: InviteRequest,
    current_user: CurrentUser,
    db: DBSession,
) -> OrganizationMember:
    """Invite a member to the organization by email (owner or admin)."""
    return await services.invite_member(
        db, org_id, current_user, email=payload.email, role=payload.role.value
    )


@router.get(
    "/{org_id}/members",
    response_model=list[MemberRead],
    summary="List organization members",
)
async def list_members(
    org_id: uuid.UUID, current_user: CurrentUser, db: DBSession
) -> list[OrganizationMember]:
    """List the members of an organization (any member)."""
    return await services.list_members(db, org_id, current_user)


@router.put(
    "/{org_id}/members/{user_id}/role",
    response_model=MemberRead,
    summary="Change a member's role",
)
async def change_member_role(
    org_id: uuid.UUID,
    user_id: uuid.UUID,
    payload: MemberRoleUpdate,
    current_user: CurrentUser,
    db: DBSession,
) -> OrganizationMember:
    """Change a member's role (owner only)."""
    return await services.change_member_role(
        db, org_id, user_id, current_user, payload.role.value
    )


@router.delete(
    "/{org_id}/members/{user_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Remove a member",
)
async def remove_member(
    org_id: uuid.UUID,
    user_id: uuid.UUID,
    current_user: CurrentUser,
    db: DBSession,
) -> None:
    """Remove a member from the organization (owner or admin)."""
    await services.remove_member(db, org_id, user_id, current_user)
