"""Reusable Pydantic base schemas: response envelope, pagination, errors."""

from typing import Generic, TypeVar

from pydantic import BaseModel, ConfigDict, Field

T = TypeVar("T")


class ORMSchema(BaseModel):
    """Base schema for responses populated directly from ORM objects."""

    model_config = ConfigDict(from_attributes=True)


class APIResponse(BaseModel, Generic[T]):
    """Standard success envelope wrapping a typed payload."""

    success: bool = True
    message: str | None = None
    data: T | None = None


class PaginationMeta(BaseModel):
    """Pagination metadata returned alongside a page of items."""

    total: int = Field(..., description="Total number of matching records")
    page: int = Field(..., description="Current page number (1-indexed)")
    limit: int = Field(..., description="Page size")
    pages: int = Field(..., description="Total number of pages")


class PaginatedResponse(BaseModel, Generic[T]):
    """A page of items plus pagination metadata."""

    items: list[T]
    total: int
    page: int
    limit: int
    pages: int


class ErrorDetail(BaseModel):
    """Single structured error detail."""

    field: str | None = None
    message: str


class ErrorResponse(BaseModel):
    """Standard error envelope returned by global exception handlers."""

    success: bool = False
    message: str
    errors: list[ErrorDetail] | None = None
