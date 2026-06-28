"""Local filesystem storage helpers for uploaded files.

Files are written under ``settings.UPLOAD_DIR`` and served back via the
``/uploads`` static mount configured in ``app.main``.
"""

import uuid
from pathlib import Path

import aiofiles
from PIL import Image

from app.core.config import settings

# Sub-directories created under the upload root.
SUBDIRS = (
    "avatars",
    "logos",
    "events/originals",
    "events/thumbnails",
    "qr",
)


def ensure_upload_dirs() -> None:
    """Create the upload directory tree if it does not already exist."""
    root = Path(settings.UPLOAD_DIR)
    for sub in SUBDIRS:
        (root / sub).mkdir(parents=True, exist_ok=True)


def _unique_filename(original_name: str) -> str:
    """Return a collision-resistant filename preserving the original extension."""
    ext = Path(original_name).suffix.lower()
    return f"{uuid.uuid4().hex}{ext}"


async def save_upload(
    content: bytes, subdir: str, original_name: str
) -> tuple[str, str]:
    """Save ``content`` under ``subdir`` and return ``(relative_path, public_url)``.

    Args:
        content: Raw file bytes.
        subdir: Sub-directory under the upload root (e.g. ``"avatars"``).
        original_name: Original filename, used to derive the extension.

    Returns:
        A tuple of the stored relative path and its public ``/uploads`` URL.
    """
    ensure_upload_dirs()
    filename = _unique_filename(original_name)
    relative_path = f"{subdir}/{filename}"
    full_path = Path(settings.UPLOAD_DIR) / relative_path
    full_path.parent.mkdir(parents=True, exist_ok=True)

    async with aiofiles.open(full_path, "wb") as f:
        await f.write(content)

    public_url = f"{settings.SERVE_UPLOADS_URL}/{relative_path}"
    return relative_path, public_url


def delete_file(relative_path: str) -> bool:
    """Delete a previously stored file. Returns ``True`` if a file was removed."""
    full_path = Path(settings.UPLOAD_DIR) / relative_path
    if full_path.is_file():
        full_path.unlink()
        return True
    return False


def generate_thumbnail(
    source_relative_path: str, max_size: tuple[int, int] = (400, 400)
) -> str | None:
    """Generate a thumbnail for an image and return its public URL.

    Returns ``None`` if the source is not a valid image.
    """
    source = Path(settings.UPLOAD_DIR) / source_relative_path
    if not source.is_file():
        return None

    thumb_dir = Path(settings.UPLOAD_DIR) / "events/thumbnails"
    thumb_dir.mkdir(parents=True, exist_ok=True)
    thumb_name = f"thumb_{source.name}"
    thumb_path = thumb_dir / thumb_name

    try:
        with Image.open(source) as img:
            img.thumbnail(max_size)
            img.save(thumb_path)
    except OSError:
        return None

    return f"{settings.SERVE_UPLOADS_URL}/events/thumbnails/{thumb_name}"
