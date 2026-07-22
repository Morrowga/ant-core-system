"""Application settings loaded from environment variables via pydantic-settings."""
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # App
    APP_NAME: str = "Workforce Platform API"
    ENV: str = "local"  # local | staging | production
    DEBUG: bool = True
    API_V1_PREFIX: str = "/api/v1"
    FRONTEND_URL: str = "http://localhost:3000"

    # Database
    DATABASE_URL: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/workforce"
    DATABASE_URL_SYNC: str = "postgresql+psycopg2://postgres:postgres@localhost:5432/workforce"  # alembic + celery

    # Redis
    REDIS_URL: str = "redis://localhost:6379/0"
    CELERY_BROKER_URL: str = "redis://localhost:6379/1"
    CELERY_RESULT_BACKEND: str = "redis://localhost:6379/2"

    # JWT
    JWT_SECRET_KEY: str = "change-me"
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30
    REFRESH_TOKEN_EXPIRE_DAYS: int = 30

    # Stripe
    STRIPE_SECRET_KEY: str = ""
    STRIPE_WEBHOOK_SECRET: str = ""
    STRIPE_PRICE_STARTUP: str = ""
    STRIPE_PRICE_MID: str = ""
    STRIPE_PRICE_ENTERPRISE: str = ""

    # Firebase
    FIREBASE_CREDENTIALS_PATH: str = "firebase-service-account.json"

    # OpenAI
    OPENAI_API_KEY: str = ""
    OPENAI_TEXT_MODEL: str = "gpt-4o"
    OPENAI_EMBEDDING_MODEL: str = "text-embedding-3-small"

    # Email
    SMTP_HOST: str
    SMTP_PORT: int
    SMTP_USERNAME: str
    SMTP_PASSWORD: str
    SMTP_FROM_ADDRESS: str
    SMTP_USE_TLS: bool = True

    # Uploads
    UPLOAD_DIR: str = "/data/uploads"
    MAX_UPLOAD_MB: int = 10

    # Presence
    PRESENCE_TTL_SECONDS: int = 120  # heartbeat considered "active" within this window


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
