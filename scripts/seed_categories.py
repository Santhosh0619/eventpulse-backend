"""Seed the default set of event categories.

Placeholder for Phase 0. The full seeding logic (10 default categories) and the
``seed_default_categories()`` service are implemented in Phase 4.
"""

import asyncio

DEFAULT_CATEGORIES = [
    "Conference",
    "Workshop",
    "Concert",
    "Festival",
    "Sports",
    "Meetup",
    "Exhibition",
    "Webinar",
    "Charity",
    "Other",
]


async def main() -> None:
    """Entry point for seeding categories. Implemented in Phase 4."""
    raise NotImplementedError("Category seeding is implemented in Phase 4")


if __name__ == "__main__":
    asyncio.run(main())
