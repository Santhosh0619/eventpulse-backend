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
    RATE_LIMIT_WEBHOOK: str = "50/minute"
    # Trust the X-Forwarded-For header for the client IP. Enable ONLY when behind a
    # trusted reverse proxy (nginx) that sets it, else clients can spoof their IP.
    TRUST_PROXY_HEADERS: bool = False

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
