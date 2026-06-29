"""Business logic for event reviews."""

import uuid
from datetime import UTC, datetime

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ConflictError, ForbiddenError, NotFoundError
from app.features.attendees import services as attendees_services
from app.features.events import services as events_services
from app.features.organizations import services as orgs_services
from app.features.reviews import crud
from app.features.reviews.models import Review
from app.features.reviews.schemas import ReviewSummary
from app.features.users.models import User
from app.shared.enums import NotificationType, OrgMemberRole, UserRole

MEMBER_ROLES = (
    OrgMemberRole.OWNER.value,
    OrgMemberRole.ADMIN.value,
    OrgMemberRole.MEMBER.value,
)


async def submit_review(
    db: AsyncSession, event_id: uuid.UUID, user: User, payload: dict
) -> Review:
    """Submit a review for an event the user has attended (one per user/event)."""
    await events_services.get_event(db, event_id)  # 404 if missing

    if not await attendees_services.has_checked_in_attendee(db, event_id, user.id):
        raise ForbiddenError("Only checked-in attendees can review this event")
    if await crud.get_user_review_for_event(db, event_id, user.id) is not None:
        raise ConflictError("You have already reviewed this event")

    try:
        return await crud.create_review(
            db, event_id=event_id, user_id=user.id, **payload
        )
    except IntegrityError as exc:
        # Backstop for a concurrent duplicate slipping past the existence check.
        await db.rollback()
        raise ConflictError("You have already reviewed this event") from exc


async def list_reviews(db: AsyncSession, event_id: uuid.UUID) -> list[Review]:
    """List an event's visible reviews (public)."""
    await events_services.get_event(db, event_id)
    return await crud.list_for_event(db, event_id, visible_only=True)


async def get_summary(db: AsyncSession, event_id: uuid.UUID) -> ReviewSummary:
    """Return aggregate rating statistics for an event (public)."""
    await events_services.get_event(db, event_id)
    distribution = await crud.rating_distribution(db, event_id)
    total = sum(distribution.values())
    average = (
        round(sum(star * count for star, count in distribution.items()) / total, 2)
        if total
        else 0.0
    )
    return ReviewSummary(
        event_id=event_id,
        total_reviews=total,
        average_rating=average,
        distribution=distribution,
    )


async def _require_own_review(
    db: AsyncSession, review_id: uuid.UUID, user: User
) -> Review:
    """Fetch a review and ensure the caller owns it (or is an admin)."""
    review = await crud.get_review(db, review_id)
    if review is None:
        raise NotFoundError("Review not found")
    if review.user_id != user.id and user.role != UserRole.ADMIN.value:
        raise ForbiddenError("You can only modify your own review")
    return review


async def update_review(
    db: AsyncSession, review_id: uuid.UUID, user: User, fields: dict
) -> Review:
    """Update the caller's own review."""
    review = await _require_own_review(db, review_id, user)
    if fields:
        await crud.update_review(db, review, fields)
    return review


async def delete_review(db: AsyncSession, review_id: uuid.UUID, user: User) -> None:
    """Delete the caller's own review."""
    review = await _require_own_review(db, review_id, user)
    await crud.delete_review(db, review)


async def respond_to_review(
    db: AsyncSession, review_id: uuid.UUID, user: User, response: str
) -> Review:
    """Add an organizer response to a review (any member of the event's org)."""
    review = await crud.get_review(db, review_id)
    if review is None:
        raise NotFoundError("Review not found")
    event = await events_services.get_event(db, review.event_id)
    role = await orgs_services.get_user_org_role(db, event.organization_id, user.id)
    if role is None or role not in MEMBER_ROLES:
        raise ForbiddenError("Only organization members can respond to reviews")

    updated = await crud.update_review(
        db,
        review,
        {"organizer_response": response, "responded_at": datetime.now(UTC)},
    )

    from app.features.notifications import services as notifications_services

    await notifications_services.send_notification(
        db,
        user_id=updated.user_id,
        type=NotificationType.REVIEW_REPLY.value,
        title="An organizer replied to your review",
        message="The organizer responded to your review.",
        data={"event_id": str(updated.event_id), "screen": "event_detail"},
    )
    return updated


async def set_visibility(
    db: AsyncSession, review_id: uuid.UUID, is_visible: bool
) -> Review:
    """Moderate a review's visibility (admin only — enforced at the router)."""
    review = await crud.get_review(db, review_id)
    if review is None:
        raise NotFoundError("Review not found")
    return await crud.update_review(db, review, {"is_visible": is_visible})
