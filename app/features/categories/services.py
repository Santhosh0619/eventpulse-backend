"""Business logic for event categories."""

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ConflictError, NotFoundError
from app.features.categories import crud
from app.features.categories.models import Category
from app.shared.slug import generate_unique_slug

# Default taxonomy seeded via scripts/seed_categories.py.
DEFAULT_CATEGORIES = [
    ("Conference", "presentation"),
    ("Workshop", "tools"),
    ("Concert", "music"),
    ("Festival", "sparkles"),
    ("Sports", "trophy"),
    ("Meetup", "users"),
    ("Exhibition", "image"),
    ("Webinar", "video"),
    ("Charity", "heart"),
    ("Other", "tag"),
]


async def list_categories(
    db: AsyncSession, is_active: bool | None = None
) -> list[Category]:
    """List categories, optionally filtered by active flag."""
    return await crud.list_categories(db, is_active=is_active)


async def create_category(db: AsyncSession, payload: dict) -> Category:
    """Create a category, generating a unique slug from its name.

    Raises:
        ConflictError: If a category with the same name already exists.
    """
    name = payload["name"]
    if await crud.name_exists(db, name):
        raise ConflictError("A category with this name already exists")
    slug = await generate_unique_slug(
        name, lambda candidate: crud.slug_exists(db, candidate)
    )
    return await crud.create_category(db, slug=slug, **payload)


async def update_category(
    db: AsyncSession, category_id: uuid.UUID, fields: dict
) -> Category:
    """Update a category, raising 404 if it does not exist."""
    category = await crud.get_category(db, category_id)
    if category is None:
        raise NotFoundError("Category not found")
    if "name" in fields and fields["name"] != category.name:
        if await crud.name_exists(db, fields["name"]):
            raise ConflictError("A category with this name already exists")
        fields["slug"] = await generate_unique_slug(
            fields["name"], lambda candidate: crud.slug_exists(db, candidate)
        )
    if fields:
        await crud.update_category(db, category, fields)
    return category


async def delete_category(db: AsyncSession, category_id: uuid.UUID) -> None:
    """Delete a category, raising 404 if it does not exist."""
    category = await crud.get_category(db, category_id)
    if category is None:
        raise NotFoundError("Category not found")
    await crud.delete_category(db, category)


async def toggle_category_active(db: AsyncSession, category_id: uuid.UUID) -> Category:
    """Flip a category's active flag."""
    category = await crud.get_category(db, category_id)
    if category is None:
        raise NotFoundError("Category not found")
    return await crud.update_category(
        db, category, {"is_active": not category.is_active}
    )


async def seed_default_categories(db: AsyncSession) -> int:
    """Insert the default categories that don't already exist. Returns count added."""
    added = 0
    for index, (name, icon) in enumerate(DEFAULT_CATEGORIES):
        if await crud.name_exists(db, name):
            continue
        slug = await generate_unique_slug(
            name, lambda candidate: crud.slug_exists(db, candidate)
        )
        await crud.create_category(
            db, name=name, slug=slug, icon=icon, sort_order=index, is_active=True
        )
        added += 1
    return added
