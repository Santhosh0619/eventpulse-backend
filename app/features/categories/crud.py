"""Database operations for event categories."""

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.features.categories.models import Category


async def slug_exists(db: AsyncSession, slug: str) -> bool:
    """Return ``True`` if a category already uses the given slug."""
    result = await db.execute(select(Category.id).where(Category.slug == slug))
    return result.first() is not None


async def name_exists(db: AsyncSession, name: str) -> bool:
    """Return ``True`` if a category already uses the given name."""
    result = await db.execute(select(Category.id).where(Category.name == name))
    return result.first() is not None


async def get_category(db: AsyncSession, category_id: uuid.UUID) -> Category | None:
    """Return a category by id, or ``None``."""
    return await db.get(Category, category_id)


async def list_categories(
    db: AsyncSession, is_active: bool | None = None
) -> list[Category]:
    """List categories ordered by sort_order, optionally filtered by active flag."""
    stmt = select(Category)
    if is_active is not None:
        stmt = stmt.where(Category.is_active == is_active)
    stmt = stmt.order_by(Category.sort_order, Category.name)
    result = await db.execute(stmt)
    return list(result.scalars().all())


async def create_category(db: AsyncSession, **fields: object) -> Category:
    """Create and persist a category."""
    category = Category(**fields)
    db.add(category)
    await db.commit()
    await db.refresh(category)
    return category


async def update_category(
    db: AsyncSession, category: Category, fields: dict
) -> Category:
    """Apply fields to a category and persist."""
    for key, value in fields.items():
        setattr(category, key, value)
    await db.commit()
    await db.refresh(category)
    return category


async def delete_category(db: AsyncSession, category: Category) -> None:
    """Delete a category."""
    await db.delete(category)
    await db.commit()
