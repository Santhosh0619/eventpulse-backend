"""Business logic for event media: upload, list, delete, reorder."""

import uuid
from io import BytesIO

from PIL import Image, UnidentifiedImageError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.exceptions import BadRequestError, ForbiddenError, NotFoundError
from app.features.events import services as events_services
from app.features.media import crud
from app.features.media.models import EventMedia
from app.features.organizations import services as orgs_services
from app.features.users.models import User
from app.shared.enums import MediaType, OrgMemberRole
from app.shared.storage import delete_file, generate_thumbnail, save_upload

MEMBER_ROLES = (
    OrgMemberRole.OWNER.value,
    OrgMemberRole.ADMIN.value,
    OrgMemberRole.MEMBER.value,
)
ALLOWED_VIDEO_TYPES = ("video/mp4", "video/webm", "video/quicktime")


async def _require_event_membership(db: AsyncSession, event_id: uuid.UUID, user: User):
    """Return the event after verifying the user is a member of its org."""
    event = await events_services.get_event(db, event_id)  # raises 404
    role = await orgs_services.get_user_org_role(db, event.organization_id, user.id)
    if role is None or role not in MEMBER_ROLES:
        raise ForbiddenError("You are not a member of this event's organization")
    return event


async def list_media(db: AsyncSession, event_id: uuid.UUID) -> list[EventMedia]:
    """List an event's media (public). 404 if the event does not exist."""
    await events_services.get_event(db, event_id)
    return await crud.list_media(db, event_id)


async def upload_event_media(
    db: AsyncSession,
    event_id: uuid.UUID,
    user: User,
    *,
    content: bytes,
    content_type: str | None,
    filename: str,
    caption: str | None = None,
) -> EventMedia:
    """Validate, store, and record an uploaded media file (org member only)."""
    await _require_event_membership(db, event_id, user)

    if content_type in settings.allowed_image_types_list:
        media_type = MediaType.IMAGE.value
    elif content_type in ALLOWED_VIDEO_TYPES:
        media_type = MediaType.VIDEO.value
    else:
        raise BadRequestError("Unsupported media type")

    if len(content) > settings.max_upload_size_bytes:
        raise BadRequestError(
            f"File too large. Maximum size is {settings.MAX_UPLOAD_SIZE_MB} MB"
        )

    # For images, verify the bytes really are a decodable image (defends against
    # a spoofed Content-Type that labels a non-image payload as image/*).
    if media_type == MediaType.IMAGE.value:
        try:
            with Image.open(BytesIO(content)) as img:
                img.verify()
        except (UnidentifiedImageError, OSError) as exc:
            raise BadRequestError("File is not a valid image") from exc

    relative_path, public_url = await save_upload(content, "events/originals", filename)

    thumbnail_url = None
    if media_type == MediaType.IMAGE.value:
        thumbnail_url = generate_thumbnail(relative_path)

    return await crud.add_media(
        db,
        event_id=event_id,
        type=media_type,
        url=public_url,
        thumbnail_url=thumbnail_url,
        caption=caption,
        sort_order=await crud.next_sort_order(db, event_id),
        file_size_bytes=len(content),
        uploaded_by=user.id,
    )


async def delete_media(
    db: AsyncSession, event_id: uuid.UUID, media_id: uuid.UUID, user: User
) -> None:
    """Delete a media item belonging to an event (org member only)."""
    await _require_event_membership(db, event_id, user)
    media = await crud.get_media(db, media_id)
    if media is None or media.event_id != event_id:
        raise NotFoundError("Media not found")

    # Best-effort removal of the stored files.
    if media.url and media.url.startswith(settings.SERVE_UPLOADS_URL):
        delete_file(media.url[len(settings.SERVE_UPLOADS_URL) + 1 :])
    await crud.delete_media(db, media)


async def reorder(
    db: AsyncSession,
    event_id: uuid.UUID,
    user: User,
    media_ids: list[uuid.UUID],
) -> list[EventMedia]:
    """Reorder an event's media to match the given id sequence (org member only)."""
    await _require_event_membership(db, event_id, user)
    return await crud.apply_order(db, event_id, media_ids)
