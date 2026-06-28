"""Order endpoints: place, list mine, get, cancel."""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, status

from app.core.dependencies import DBSession, get_current_user
from app.features.orders import services
from app.features.orders.models import Order
from app.features.orders.schemas import OrderCreate, OrderRead
from app.features.users.models import User

router = APIRouter()
# Routes under /api/v1/users that belong to the orders feature.
user_orders_router = APIRouter()

CurrentUser = Annotated[User, Depends(get_current_user)]


@router.post(
    "/orders",
    response_model=OrderRead,
    status_code=status.HTTP_201_CREATED,
    summary="Place an order",
)
async def place_order(
    payload: OrderCreate, current_user: CurrentUser, db: DBSession
) -> Order:
    """Place an order for an event's tickets (authenticated)."""
    return await services.place_order(db, current_user, payload.model_dump())


@user_orders_router.get(
    "/me/orders", response_model=list[OrderRead], summary="List my orders"
)
async def list_my_orders(current_user: CurrentUser, db: DBSession) -> list[Order]:
    """Return the authenticated user's orders."""
    return await services.list_my_orders(db, current_user)


@router.get("/orders/{order_id}", response_model=OrderRead, summary="Get an order")
async def get_order(
    order_id: uuid.UUID, current_user: CurrentUser, db: DBSession
) -> Order:
    """Return an order the caller owns."""
    return await services.get_order(db, order_id, current_user)


@router.post(
    "/orders/{order_id}/cancel",
    response_model=OrderRead,
    summary="Cancel an order",
)
async def cancel_order(
    order_id: uuid.UUID, current_user: CurrentUser, db: DBSession
) -> Order:
    """Cancel an order the caller owns, releasing its reserved tickets."""
    return await services.cancel_order(db, order_id, current_user)
