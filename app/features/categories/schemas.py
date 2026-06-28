"""Pydantic schemas for the categories feature."""

import uuid
from datetime import datetime

from pydantic import BaseModel, Field

from app.shared.base_schemas import ORMSchema


class CategoryCreate(BaseModel):
    """Payload for creating a category (admin only)."""

    name: str = Field(..., min_length=1, max_length=100)
    icon: str | None = Field(default=None, max_length=50)
    description: str | None = None
    sort_order: int = 0
    is_active: bool = True


class CategoryUpdate(BaseModel):
    """Editable category fields (all optional)."""

    name: str | None = Field(default=None, min_length=1, max_length=100)
    icon: str | None = Field(default=None, max_length=50)
    description: str | None = None
    sort_order: int | None = None
    is_active: bool | None = None


class CategoryRead(ORMSchema):
    """Category representation."""

    id: uuid.UUID
    name: str
    slug: str
    icon: str | None = None
    description: str | None = None
    sort_order: int
    is_active: bool
    created_at: datetime
