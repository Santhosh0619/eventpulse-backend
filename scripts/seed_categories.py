"""Seed the default set of event categories.

Run inside the api container:
    docker compose run --rm api python -m scripts.seed_categories
"""

import asyncio

from app.core.database import async_session_factory
from app.features.categories.services import seed_default_categories


async def main() -> None:
    """Seed default categories and report how many were added."""
    async with async_session_factory() as session:
        added = await seed_default_categories(session)
    print(f"Seeded {added} new categories.")


if __name__ == "__main__":
    asyncio.run(main())
