"""Reusable pagination utility for async SQLAlchemy queries."""

from math import ceil
from typing import TypeVar

from sqlalchemy import Select, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.shared.base_schemas import PaginatedResponse

T = TypeVar("T")


async def paginate(
    session: AsyncSession,
    query: Select,
    page: int = 1,
    limit: int = 20,
) -> PaginatedResponse:
    """Execute ``query`` with offset pagination and return a ``PaginatedResponse``.

    Args:
        session: Active async database session.
        query: A SQLAlchemy ``Select`` statement (without limit/offset applied).
        page: 1-indexed page number.
        limit: Maximum number of items per page.

    Returns:
        A ``PaginatedResponse`` with items and pagination metadata.
    """
    page = max(page, 1)
    limit = max(min(limit, 100), 1)

    count_query = select(func.count()).select_from(query.subquery())
    total = (await session.execute(count_query)).scalar_one()

    offset = (page - 1) * limit
    result = await session.execute(query.offset(offset).limit(limit))
    items = list(result.scalars().all())

    pages = ceil(total / limit) if total else 0

    return PaginatedResponse(
        items=items,
        total=total,
        page=page,
        limit=limit,
        pages=pages,
    )
