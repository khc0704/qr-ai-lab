"""Settings: everything comes from environment variables (or backend/.env). See docs/ARCHITECTURE.md §13."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_env: Literal["dev", "test", "prod"] = "dev"
    public_url: str = "http://localhost:3000"
    cors_origins: list[str] = ["http://localhost:3000"]
    log_level: str = "INFO"

    # Persistence
    database_url: str = "sqlite+aiosqlite:///./dev.db"
    redis_url: str | None = None  # None → in-process event bus (dev/tests only)
    data_root: Path = Path("./data")
    data_root_host: Path | None = None  # host path of data_root when the scheduler itself runs in docker
    model_zoo_root: Path | None = None  # default: data_root / "model_zoo"

    # Auth. "local" = username/password accounts in the users table (interim until Keycloak).
    auth_mode: Literal["local", "keycloak"] = "local"
    auth_secret: str = "dev-secret-change-me"
    access_token_minutes: int = 12 * 60
    keycloak_issuer: str | None = None
    keycloak_audience: str | None = None
    seed_admin_password: str = "admin1234"
    seed_user_password: str = "user1234"

    # Secrets for data-source credentials and per-job tokens
    dataset_secret_key: str | None = None  # Fernet key; derived from auth_secret in dev when unset
    job_token_secret: str = "dev-job-secret-change-me"

    # Scheduler / trainer
    job_runner: Literal["docker", "subprocess"] = "docker"
    trainer_image: str = "qr-ai-lab/trainer:dev"
    trainer_dir: Path = Path("../trainer")  # subprocess runner only
    internal_backend_url: str = "http://localhost:8000"  # how a job reaches the backend
    scheduler_interval_s: float = 3.0
    job_network: str = "qr-ai-lab_jobs"
    upload_max_mb: int = 2048
    upload_ttl_minutes: int = 60
    log_max_mb: int = 50
    default_job_timeout_minutes: int = 240

    @field_validator("cors_origins", mode="before")
    @classmethod
    def _split_origins(cls, v: object) -> object:
        if isinstance(v, str):
            return [s.strip() for s in v.split(",") if s.strip()]
        return v

    @property
    def zoo_root(self) -> Path:
        return self.model_zoo_root or (self.data_root / "model_zoo")

    @property
    def is_sqlite(self) -> bool:
        return self.database_url.startswith("sqlite")


@lru_cache
def get_settings() -> Settings:
    return Settings()
