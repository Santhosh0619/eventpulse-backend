"""Alembic migration environment configured for async SQLAlchemy.

The database URL is taken from the application settings so migrations run against
the same database the app uses (including the in-container ``postgres`` host).

MODEL IMPORTS: every feature's models must be imported here so Alembic's
autogenerate detects all tables. Imports are added phase by phase as models are
created. No feature models exist yet in Phase 0 (initial empty schema).
"""

import asyncio
from logging.config import fileConfig

from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

from alembic import context
from app.core.config import settings
from app.core.database import Base

# --- Model import section (extended per phase) -------------------------------
from app.features.users.models import User, UserProfile  # noqa: F401

# from app.features.organizations.models import Organization, OrganizationMember
# from app.features.categories.models import Category
# from app.features.events.models import Event
# from app.features.media.models import EventMedia
# from app.features.tickets.models import TicketType
# from app.features.orders.models import Order, OrderItem
# from app.features.payments.models import Payment
# from app.features.attendees.models import Attendee
# from app.features.reviews.models import Review
# from app.features.notifications.models import Notification
# from app.features.admin.models import AuditLog
# ----------------------------------------------------------------------------

config = context.config

# Inject the runtime database URL.
config.set_main_option("sqlalchemy.url", settings.DATABASE_URL)

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode (emitting SQL without a DBAPI connection)."""
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
        compare_server_default=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    """Configure the migration context against a live connection and run it."""
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        compare_type=True,
        compare_server_default=True,
    )
    with context.begin_transaction():
        context.run_migrations()


async def run_migrations_online() -> None:
    """Run migrations in 'online' mode using an async engine."""
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)

    await connectable.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_migrations_online())
