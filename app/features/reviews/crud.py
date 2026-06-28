"""Database operations for reviews."""

import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.features.reviews.models import Review


async def get_review(db: AsyncSession, review_id: uuid.UUID) -> Review | None:
    """Return a review by id, or ``None``."""
    return await db.get(Review, review_id)


async def get_user_review_for_event(
    db: AsyncSession, event_id: uuid.UUID, user_id: uuid.UUID
) -> Review | None:
    """Return the user's existing review for an event, or ``None``."""
    result = await db.execute(
        select(Review).where(Review.event_id == event_id, Review.user_id == user_id)
    )
    return result.scalar_one_or_none()


async def list_for_event(
    db: AsyncSession, event_id: uuid.UUID, visible_only: bool = True
) -> list[Review]:
    """Return an event's reviews, newest first."""
    stmt = select(Review).where(Review.event_id == event_id)
    if visible_only:
        stmt = stmt.where(Review.is_visible.is_(True))
    stmt = stmt.order_by(Review.created_at.desc())
    result = await db.execute(stmt)
    return list(result.scalars().all())


async def create_review(db: AsyncSession, **fields) -> Review:
    """Create and persist a review."""
    review = Review(**fields)
    db.add(review)
    await db.commit()
    await db.refresh(review)
    return review


async def update_review(db: AsyncSession, review: Review, fields: dict) -> Review:
    """Apply fields to a review and persist."""
    for key, value in fields.items():
        setattr(review, key, value)
    await db.commit()
    await db.refresh(review)
    return review


async def delete_review(db: AsyncSession, review: Review) -> None:
    """Delete a review."""
    await db.delete(review)
    await db.commit()


async def rating_distribution(db: AsyncSession, event_id: uuid.UUID) -> dict[int, int]:
    """Return a {rating: count} map over visible reviews for an event."""
    result = await db.execute(
        select(Review.rating, func.count())
        .where(Review.event_id == event_id, Review.is_visible.is_(True))
        .group_by(Review.rating)
    )
    counts = {row[0]: int(row[1]) for row in result.all()}
    return {star: counts.get(star, 0) for star in range(1, 6)}
