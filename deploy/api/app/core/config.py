"""Configuration centrale MG-VMS (pydantic-settings, fail-fast sur variables critiques)."""
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # --- Critique (aucun défaut : échec immédiat si absent) ---
    DATABASE_URL: str
    JWT_SECRET: str

    # --- Redis / Celery ---
    REDIS_URL: str = "redis://redis:6379/0"
    CELERY_BROKER_URL: str = "redis://redis:6379/1"
    CELERY_RESULT_BACKEND: str = "redis://redis:6379/2"

    # --- Sécurité ---
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_MINUTES: int = 15
    REFRESH_TOKEN_DAYS: int = 7
    CORS_ORIGINS: str = "http://localhost"
    LOGIN_MAX_ATTEMPTS: int = 5
    LOGIN_LOCKOUT_MINUTES: int = 15

    # --- Admin initial ---
    ADMIN_EMAIL: str = "admin@mg-vms.local"
    ADMIN_PASSWORD: str = "ChangeMe@2026"

    # --- Stockage objets (MinIO/S3) ---
    S3_ENDPOINT: str = "http://minio:9000"
    S3_BUCKET: str = "recordings"
    S3_ACCESS_KEY: str = ""
    S3_SECRET_KEY: str = ""

    # --- Services internes ---
    STREAM_GATEWAY_URL: str = "http://ffmpeg-service:1984"  # go2rtc
    AI_ENGINE_URL: str = "http://ai-engine:8090"

    @property
    def cors_origins_list(self) -> list[str]:
        return [o.strip() for o in self.CORS_ORIGINS.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
