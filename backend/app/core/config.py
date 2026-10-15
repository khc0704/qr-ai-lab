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
    keycloak_issuer: str | None = None  # https://sso.example.com/realms/<realm>
    keycloak_audience: str | None = None  # verify `aud` when set (Keycloak needs an audience mapper for that)
    keycloak_client_id: str | None = None  # also look at resource_access[<client>].roles for the role map
    # "<keycloak role>:<system role>" pairs. A login whose token carries a mapped role sets users.role to the most
    # privileged match; a token without any mapped role leaves the role as managed in the UI.
    keycloak_role_map: Annotated[list[str], NoDecode] = ["superadmin:superadmin", "admin:admin"]
    # Bootstrap: these usernames (preferred_username / local username) are always superadmin after login.
    superadmin_usernames: Annotated[list[str], NoDecode] = []
    seed_superadmin_password: str = "superadmin1234"
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
    gpu_busy_threshold: float = 0.10  # exclusive jobs: do not start on a GPU whose memory is already >10% used
    gpu_reserve_mb: int = 512  # VRAM kept free per GPU when packing shared jobs (driver / context overhead)
    gpu_warmup_s: int = 120  # a freshly started job counts as using its requested VRAM until measured, this long
    gpu_reset_command: str | None = None  # e.g. "sudo -n nvidia-smi --gpu-reset -i {index}" (needs sudoers entry)
    usage_sample_interval_s: int = 30
    usage_retention_days: int = 90
    internal_backend_url: str = "http://localhost:8000"  # how a job reaches the backend
    scheduler_interval_s: float = 3.0
    upload_max_mb: int = 2048
    preview_timeout_s: float = 30.0  # preprocessing preview runs in a worker thread of the API process
    tool_process_timeout_s: float = 600.0  # standalone preprocessing tool: whole-file run, same worker thread
    upload_ttl_minutes: int = 60
    log_max_mb: int = 50
    default_job_timeout_minutes: int = 240

    @field_validator(
        "cors_origins", "model_zoo_allowed_hosts", "keycloak_role_map", "superadmin_usernames", mode="before"
    )
    @classmethod
    def _split_list(cls, v: object) -> object:
        if isinstance(v, str):
            return [s.strip() for s in v.split(",") if s.strip()]
        return v

    @property
    def role_map(self) -> dict[str, str]:
        """{keycloak role: system role} parsed from KEYCLOAK_ROLE_MAP."""
        out: dict[str, str] = {}
        for pair in self.keycloak_role_map:
            k, _, v = pair.partition(":")
            if k.strip() and v.strip():
                out[k.strip()] = v.strip()
        return out

    @property
    def zoo_root(self) -> Path:
        return self.model_zoo_root or (self.data_root / "model_zoo")

    @property
    def is_sqlite(self) -> bool:
        return self.database_url.startswith("sqlite")


@lru_cache
def get_settings() -> Settings:
    return Settings()
