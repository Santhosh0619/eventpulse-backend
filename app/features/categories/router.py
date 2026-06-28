"""Category endpoints: public list, admin create/update/delete."""

import uuid

from fastapi import APIRouter, Depends, status

from app.core.dependencies import DBSession, require_role
from app.features.categories import services
from app.features.categories.models import Category
from app.features.categories.schemas import (
    CategoryCreate,
    CategoryRead,
    CategoryUpdate,
)
from app.shared.enums import UserRole

router = APIRouter()

# Admin-only guard reused across write endpoints.
AdminRequired = Depends(require_role(UserRole.ADMIN.value))


@router.get("", response_model=list[CategoryRead], summary="List categories")
async def list_categories(
    db: DBSession, is_active: bool | None = None
) -> list[Category]:
    """List categories, optionally filtered by the active flag (public)."""
    return await services.list_categories(db, is_active=is_active)


@router.post(
    "",
    response_model=CategoryRead,
    status_code=status.HTTP_201_CREATED,
    dependencies=[AdminRequired],
    summary="Create a category",
)
async def create_category(payload: CategoryCreate, db: DBSession) -> Category:
    """Create a new category (admin only)."""
    return await services.create_category(db, payload.model_dump(exclude_none=True))


@router.put(
    "/{category_id}",
    response_model=CategoryRead,
    dependencies=[AdminRequired],
    summary="Update a category",
)
async def update_category(
    category_id: uuid.UUID, payload: CategoryUpdate, db: DBSession
) -> Category:
    """Update a category (admin only)."""
    return await services.update_category(
        db, category_id, payload.model_dump(exclude_unset=True)
    )


@router.delete(
    "/{category_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[AdminRequired],
    summary="Delete a category",
)
async def delete_category(category_id: uuid.UUID, db: DBSession) -> None:
    """Delete a category (admin only)."""
    await services.delete_category(db, category_id)
