"""Settings: everything comes from environment variables (or backend/.env). See docs/ARCHITECTURE.md §13."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Annotated, Literal

from pydantic import field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_env: Literal["dev", "test", "prod"] = "dev"
    public_url: str = "http://localhost:3000"
    cors_origins: Annotated[list[str], NoDecode] = ["http://localhost:3000"]  # comma separated in env
    log_level: str = "INFO"

    # Persistence
    database_url: str = "sqlite+aiosqlite:///./dev.db"
    redis_url: str | None = None  # None → in-process event bus (dev/tests only)
    data_root: Path = Path("./data")
    model_zoo_root: Path | None = None  # default: data_root / "model_zoo"
    model_zoo_import_root: Path | None = None  # admins may import weights from files under this host path
    model_zoo_allowed_hosts: Annotated[list[str], NoDecode] = []  # comma separated; empty = any host
    model_zoo_max_mb: int = 20480

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

    # Scheduler / trainer. Jobs are host processes from the trainer venv (no containers):
    #   auto → systemd (cgroup limits) when a systemd user/system manager can start transient scopes, else subprocess.
    job_runner: Literal["auto", "systemd", "subprocess"] = "auto"
    systemd_user: bool = True  # systemd-run --user (needs `loginctl enable-linger`); False = system manager (root)
    trainer_dir: Path = Path("../trainer")
    trainer_python: Path | None = None  # default: <trainer_dir>/.venv/bin/python
    scheduler_embedded: bool = False  # run the scheduler loop inside the API process (single process, no Redis)
    memory_watchdog: bool = True  # kill a job that exceeds its memory grant when the runner cannot enforce it
    gpu_busy_threshold: float = 0.10  # do not start a job on a GPU whose memory is already >10% used
    internal_backend_url: str = "http://localhost:8000"  # how a job reaches the backend
    scheduler_interval_s: float = 3.0
    upload_max_mb: int = 2048
    preview_timeout_s: float = 30.0  # preprocessing preview runs in a worker thread of the API process
    upload_ttl_minutes: int = 60
    log_max_mb: int = 50
    default_job_timeout_minutes: int = 240

    @field_validator("cors_origins", "model_zoo_allowed_hosts", mode="before")
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
