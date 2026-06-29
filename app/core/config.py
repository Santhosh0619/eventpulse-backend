"""Application configuration via Pydantic Settings.

All configuration is sourced from environment variables (or a local ``.env`` file
in development). No configuration value is ever hardcoded elsewhere in the codebase.
"""

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Strongly-typed application settings loaded from the environment."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="ignore",
    )

    # App
    APP_NAME: str = "EventPulse"
    APP_ENV: str = "development"
    DEBUG: bool = True
    API_V1_PREFIX: str = "/api/v1"
    BACKEND_CORS_ORIGINS: list[str] = Field(
        default=["http://localhost:5173", "http://localhost:8081"]
    )

    # Database
    DATABASE_URL: str = (
        "postgresql+asyncpg://postgres:postgres@localhost:5432/eventpulse"
    )
    DATABASE_POOL_SIZE: int = 20
    DATABASE_MAX_OVERFLOW: int = 10

    # Redis
    REDIS_URL: str = "redis://localhost:6379/0"

    # Rate limiting (slowapi). Limits are per identity (auth token or client IP).
    RATE_LIMIT_ENABLED: bool = True
    RATE_LIMIT_DEFAULT: str = "100/minute"
    RATE_LIMIT_AUTH: str = "5/minute"  # brute-force-sensitive auth endpoints
    # The Stripe webhook is exempt from rate limiting (signature-verified + idempotent).
    # Trust the X-Forwarded-For header for the client IP. Enable ONLY when behind a
    # trusted reverse proxy (nginx) that sets it, else clients can spoof their IP.
    TRUST_PROXY_HEADERS: bool = False

    # Security hardening
    LOGIN_MAX_FAILED_ATTEMPTS: int = 10  # lock the account after this many failures
    LOGIN_LOCKOUT_SECONDS: int = 900  # 15-minute lockout window
    # Global request-body cap. Kept comfortably above MAX_UPLOAD_SIZE_MB (10 MB) so a
    # max-size multipart upload (Content-Length > file size due to framing) isn't
    # rejected by this middleware before reaching the endpoint's own size check.
    MAX_REQUEST_BODY_BYTES: int = 15 * 1024 * 1024  # 15 MiB
    # Send HSTS (only meaningful over HTTPS; safe to enable behind a TLS proxy).
    ENABLE_HSTS: bool = False

    # JWT
    JWT_SECRET_KEY: str = "change-me"
    JWT_ALGORITHM: str = "HS256"
    JWT_ACCESS_TOKEN_EXPIRE_MINUTES: int = 15
    JWT_REFRESH_TOKEN_EXPIRE_DAYS: int = 7

    # Email (SMTP)
    SMTP_HOST: str = "localhost"
    SMTP_PORT: int = 1025
    SMTP_USERNAME: str = ""
    SMTP_PASSWORD: str = ""
    SMTP_USE_TLS: bool = False
    FROM_EMAIL: str = "noreply@eventpulse.com"

    # Stripe
    STRIPE_SECRET_KEY: str = "sk_test_xxxxx"
    STRIPE_WEBHOOK_SECRET: str = "whsec_xxxxx"
    STRIPE_PUBLISHABLE_KEY: str = "pk_test_xxxxx"

    # Local file storage
    UPLOAD_DIR: str = "uploads"
    MAX_UPLOAD_SIZE_MB: int = 10
    ALLOWED_IMAGE_TYPES: str = "image/jpeg,image/png,image/webp"
    SERVE_UPLOADS_URL: str = "/uploads"

    # Firebase
    FIREBASE_CREDENTIALS_JSON: str = '{"type":"service_account"}'

    # Frontend URLs
    WEB_APP_URL: str = "http://localhost:5173"

    @property
    def allowed_image_types_list(self) -> list[str]:
        """Return ALLOWED_IMAGE_TYPES parsed into a list of MIME strings."""
        return [t.strip() for t in self.ALLOWED_IMAGE_TYPES.split(",") if t.strip()]

    @property
    def max_upload_size_bytes(self) -> int:
        """Return the maximum upload size expressed in bytes."""
        return self.MAX_UPLOAD_SIZE_MB * 1024 * 1024


@lru_cache
def get_settings() -> Settings:
    """Return a cached singleton ``Settings`` instance."""
    return Settings()


settings = get_settings()
