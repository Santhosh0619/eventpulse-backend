"""Attendee endpoints: check-in, listing, stats, CSV export, and QR codes."""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Response

from app.core.dependencies import DBSession, get_current_user
from app.features.attendees import services
from app.features.attendees.schemas import (
    AttendeeRead,
    AttendeeStats,
    CheckInRequest,
    CheckInResponse,
)
from app.features.users.models import User
from app.utils.qr import generate_qr_png

router = APIRouter()

CurrentUser = Annotated[User, Depends(get_current_user)]


@router.post(
    "/attendees/check-in",
    response_model=CheckInResponse,
    summary="Check in an attendee",
)
async def check_in(
    payload: CheckInRequest, current_user: CurrentUser, db: DBSession
) -> CheckInResponse:
    """Check in an attendee by ticket code (org member); idempotent."""
    attendee, already = await services.check_in(db, payload.ticket_code, current_user)
    message = "Attendee already checked in" if already else "Check-in successful"
    return CheckInResponse(
        success=True,
        already_checked_in=already,
        message=message,
        attendee=AttendeeRead.model_validate(attendee),
    )


@router.get(
    "/events/{event_id}/attendees",
    response_model=list[AttendeeRead],
    summary="List event attendees",
)
async def list_attendees(
    event_id: uuid.UUID, current_user: CurrentUser, db: DBSession
) -> list:
    """List an event's attendees (org member only)."""
    return await services.list_attendees(db, event_id, current_user)


@router.get(
    "/events/{event_id}/attendees/stats",
    response_model=AttendeeStats,
    summary="Attendee check-in stats",
)
async def attendee_stats(
    event_id: uuid.UUID, current_user: CurrentUser, db: DBSession
) -> AttendeeStats:
    """Return check-in statistics for an event (org member only)."""
    return await services.get_stats(db, event_id, current_user)


@router.get(
    "/events/{event_id}/attendees/export",
    summary="Export attendees as CSV",
)
async def export_attendees(
    event_id: uuid.UUID, current_user: CurrentUser, db: DBSession
) -> Response:
    """Export an event's attendees as a CSV file (org admin or owner)."""
    csv_data = await services.export_attendees_csv(db, event_id, current_user)
    return Response(
        content=csv_data,
        media_type="text/csv",
        headers={
            "Content-Disposition": f"attachment; filename=attendees-{event_id}.csv"
        },
    )


@router.get("/attendees/{attendee_id}/qr", summary="Get attendee QR code")
async def attendee_qr(
    attendee_id: uuid.UUID, current_user: CurrentUser, db: DBSession
) -> Response:
    """Return a PNG QR code encoding the attendee's ticket code (owner only)."""
    ticket_code = await services.get_attendee_qr(db, attendee_id, current_user)
    return Response(content=generate_qr_png(ticket_code), media_type="image/png")
