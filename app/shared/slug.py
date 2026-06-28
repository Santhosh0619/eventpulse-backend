"""Slug generation with collision handling (slug, slug-2, slug-3, ...)."""

import re
from collections.abc import Awaitable, Callable

_NON_SLUG_CHARS = re.compile(r"[^a-z0-9]+")
_EDGE_HYPHENS = re.compile(r"^-+|-+$")


def slugify(value: str) -> str:
    """Convert an arbitrary string into a lowercase, hyphenated slug."""
    value = value.lower().strip()
    value = _NON_SLUG_CHARS.sub("-", value)
    value = _EDGE_HYPHENS.sub("", value)
    return value or "item"


async def generate_unique_slug(
    value: str,
    exists: Callable[[str], Awaitable[bool]],
) -> str:
    """Return a unique slug for ``value``, appending ``-2``, ``-3`` on collisions.

    Args:
        value: Source text to slugify.
        exists: Async predicate returning ``True`` if a slug is already taken.

    Returns:
        A slug guaranteed unique according to the ``exists`` predicate.
    """
    base = slugify(value)
    candidate = base
    suffix = 2
    while await exists(candidate):
        candidate = f"{base}-{suffix}"
        suffix += 1
    return candidate
