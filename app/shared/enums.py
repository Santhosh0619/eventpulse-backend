"""Shared enumerations used across features.

Each enum subclasses ``str`` so values serialize cleanly to JSON and map directly
to the VARCHAR + CHECK constraint columns defined in the database schema.
"""

from enum import Enum


class UserRole(str, Enum):
    """Platform-level role assigned to every user."""

    ADMIN = "admin"
    ORGANIZER = "organizer"
    ATTENDEE = "attendee"


class OrgMemberRole(str, Enum):
    """Role of a user within a single organization."""

    OWNER = "owner"
    ADMIN = "admin"
    MEMBER = "member"


class InvitationStatus(str, Enum):
    """Lifecycle status of an organization membership invitation."""

    PENDING = "pending"
    ACCEPTED = "accepted"
    DECLINED = "declined"


class EventStatus(str, Enum):
    """Lifecycle status of an event."""

    DRAFT = "draft"
    PUBLISHED = "published"
    CANCELLED = "cancelled"
    COMPLETED = "completed"


class MediaType(str, Enum):
    """Type of media attached to an event."""

    IMAGE = "image"
    VIDEO = "video"


class OrderStatus(str, Enum):
    """Lifecycle status of an order."""

    PENDING = "pending"
    CONFIRMED = "confirmed"
    CANCELLED = "cancelled"
    REFUNDED = "refunded"


class PaymentStatus(str, Enum):
    """Lifecycle status of a payment record."""

    PENDING = "pending"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    REFUNDED = "refunded"
    PARTIALLY_REFUNDED = "partially_refunded"


class CheckInStatus(str, Enum):
    """Check-in status of an attendee."""

    NOT_CHECKED_IN = "not_checked_in"
    CHECKED_IN = "checked_in"


class NotificationChannel(str, Enum):
    """Delivery channel for a notification."""

    IN_APP = "in_app"
    PUSH = "push"
    EMAIL = "email"
