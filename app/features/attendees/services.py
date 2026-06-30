"""Business logic for attendees: generation, check-in, stats, and export."""

import csv
import io
import secrets
import uuid
from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ForbiddenError, NotFoundError
from app.features.attendees import crud
from app.features.attendees.models import Attendee
from app.features.attendees.schemas import AttendeeStats
from app.features.events import services as events_services
from app.features.organizations import services as orgs_services
from app.features.users.models import User
from app.shared.enums import CheckInStatus, OrgMemberRole, UserRole

MEMBER_ROLES = (
    OrgMemberRole.OWNER.value,
    OrgMemberRole.ADMIN.value,
    OrgMemberRole.MEMBER.value,
)
ADMIN_ROLES = (OrgMemberRole.OWNER.value, OrgMemberRole.ADMIN.value)


async def _generate_ticket_code(db: AsyncSession) -> str:
    """Return a unique attendee ticket code (EP-ATT-XXXXXXXX)."""
    for _ in range(10):
        candidate = f"EP-ATT-{secrets.token_hex(4)}"
        if not await crud.ticket_code_exists(db, candidate):
            return candidate
    raise RuntimeError("Could not generate a unique ticket code")


async def generate_attendees_for_order(
    db: AsyncSession, order, buyer: User
) -> list[Attendee]:
    """Create one attendee row per ticket in a confirmed order (no commit).

    Names/email default to the buyer's profile. The caller owns the transaction.
    """
    first = buyer.profile.first_name if buyer.profile else "Guest"
    last = buyer.profile.last_name if buyer.profile else ""
    attendees: list[Attendee] = []
    for item in order.items:
        for _ in range(item.quantity):
            attendee = Attendee(
                order_item_id=item.id,
                user_id=order.user_id,
                event_id=order.event_id,
                ticket_code=await _generate_ticket_code(db),
                first_name=first,
                last_name=last,
                email=buyer.email,
            )
            db.add(attendee)
            attendees.append(attendee)
    await db.flush()
    return attendees


async def _require_event_member(
    db: AsyncSession, event_id: uuid.UUID, user: User, allowed: tuple[str, ...]
):
    """Verify the user has one of ``allowed`` roles in the event's organization."""
    event = await events_services.get_event(db, event_id)  # 404
    role = await orgs_services.get_user_org_role(db, event.organization_id, user.id)
    if role is None or role not in allowed:
        raise ForbiddenError("You are not authorized for this event")
    return event


async def check_in(db: AsyncSession, ticket_code: str, staff: User):
    """Check in an attendee by ticket code (idempotent). Returns (attendee, already)."""
    attendee = await crud.get_by_ticket_code(db, ticket_code)
    if attendee is None:
        raise NotFoundError("Ticket not found")
    await _require_event_member(db, attendee.event_id, staff, MEMBER_ROLES)

    if attendee.check_in_status == CheckInStatus.CHECKED_IN.value:
        return attendee, True

    attendee.check_in_status = CheckInStatus.CHECKED_IN.value
    attendee.checked_in_at = datetime.now(UTC)
    attendee.checked_in_by = staff.id
    await db.commit()
    await db.refresh(attendee)
    return attendee, False


async def has_checked_in_attendee(
    db: AsyncSession, event_id: uuid.UUID, user_id: uuid.UUID
) -> bool:
    """Return whether a user has a checked-in attendee for the event.

    Cross-feature helper used by reviews to verify attendance.
    """
    return await crud.has_checked_in(db, event_id, user_id)


async def list_attendees(
    db: AsyncSession, event_id: uuid.UUID, user: User
) -> list[Attendee]:
    """List an event's attendees (org member only)."""
    await _require_event_member(db, event_id, user, MEMBER_ROLES)
    return await crud.list_for_event(db, event_id)


async def list_my_attendees(
    db: AsyncSession, user: User, event_id: uuid.UUID | None = None
) -> list[Attendee]:
    """List the authenticated user's own attendee records (their tickets)."""
    return await crud.list_for_user(db, user.id, event_id)


async def get_stats(db: AsyncSession, event_id: uuid.UUID, user: User) -> AttendeeStats:
    """Return check-in statistics for an event (org member only)."""
    await _require_event_member(db, event_id, user, MEMBER_ROLES)
    total, checked_in = await crud.count_for_event(db, event_id)
    rate = round(checked_in / total, 4) if total else 0.0
    return AttendeeStats(
        event_id=event_id,
        total=total,
        checked_in=checked_in,
        not_checked_in=total - checked_in,
        check_in_rate=rate,
    )


async def export_attendees_csv(
    db: AsyncSession, event_id: uuid.UUID, user: User
) -> str:
    """Return an event's attendees as a CSV string (org admin or owner)."""
    await _require_event_member(db, event_id, user, ADMIN_ROLES)
    attendees = await crud.list_for_event(db, event_id)

    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(
        [
            "ticket_code",
            "first_name",
            "last_name",
            "email",
            "check_in_status",
            "checked_in_at",
        ]
    )
    for a in attendees:
        writer.writerow(
            [
                a.ticket_code,
                a.first_name,
                a.last_name,
                a.email,
                a.check_in_status,
                a.checked_in_at.isoformat() if a.checked_in_at else "",
            ]
        )
    return buffer.getvalue()


async def get_attendee_qr(db: AsyncSession, attendee_id: uuid.UUID, user: User) -> str:
    """Return the ticket code for an attendee the caller owns (for QR rendering).

    Raises 404 if missing, 403 if the caller is neither the ticket holder nor an
    admin.
    """
    attendee = await crud.get_attendee(db, attendee_id)
    if attendee is None:
        raise NotFoundError("Attendee not found")
    if attendee.user_id != user.id and user.role != UserRole.ADMIN.value:
        raise ForbiddenError("You do not have access to this ticket")
    return attendee.ticket_code
