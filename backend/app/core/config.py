"""Settings: everything comes from environment variables (or backend/.env). See docs/ARCHITECTURE.md §13."""

from __future__ import annotations

import warnings
from functools import lru_cache
from pathlib import Path
from typing import Annotated, Literal

from pydantic import field_validator, model_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

_DEFAULT_SECRETS = {
    "dev-secret-change-me",
    "dev-job-secret-change-me",
    "change-me",
    "change-me-too",
    "superadmin1234",
    "admin1234",
    "user1234",
}


def _weak_secret(value: str | None, min_len: int = 32) -> bool:
    return not value or value in _DEFAULT_SECRETS or value.startswith("change-me") or len(value) < min_len


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_env: Literal["dev", "test", "prod"] = "dev"
    cors_origins: Annotated[list[str], NoDecode] = ["http://localhost:3000"]  # comma separated in env
    # External path prefix when nginx strips it before proxying (https://qrit.tsmc.com/ai-lab-api → /): keeps
    # /docs and the OpenAPI "servers" entry correct. Empty when the API is served at the origin root.
    root_path: str = ""
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
    # Keycloak supplies identity only: system roles live in users.role (managed at /admin/users). The role map is an
    # opt-in for the future: "<keycloak role>:<system role>" pairs (a mapping to superadmin is capped at admin). A
    # login whose token carries a mapped role sets users.role to the most privileged match; empty = never override.
    keycloak_role_map: Annotated[list[str], NoDecode] = []
    # Exactly one superadmin, fixed by configuration: this username (local username / Keycloak preferred_username)
    # always holds the role and nobody else can (the UI assigns at most admin). Empty string = nobody is superadmin.
    superadmin_username: str = "superadmin"
    # Deprecated spelling (comma-separated list): still read, only the first entry counts. Use SUPERADMIN_USERNAME.
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

    @field_validator("superadmin_username", mode="before")
    @classmethod
    def _strip_username(cls, v: object) -> object:
        return v.strip() if isinstance(v, str) else v

    @model_validator(mode="after")
    def _legacy_superadmin_usernames(self) -> Settings:
        """SUPERADMIN_USERNAMES (old comma list) still works so existing env files do not break: its first entry
        becomes SUPERADMIN_USERNAME unless the new variable is set explicitly."""
        if self.superadmin_usernames:
            warnings.warn(
                "SUPERADMIN_USERNAMES is deprecated: set SUPERADMIN_USERNAME=<one username> instead "
                "(only the first entry is used)",
                DeprecationWarning,
                stacklevel=2,
            )
            if "superadmin_username" not in self.model_fields_set:
                self.superadmin_username = self.superadmin_usernames[0]
        return self

    @model_validator(mode="after")
    def _check_production(self) -> Settings:
        """Refuse to start a production deployment on development defaults (see docs/ENVIRONMENT.md)."""
        if self.app_env != "prod":
            return self
        problems: list[str] = []
        for name, value in (("AUTH_SECRET", self.auth_secret), ("JOB_TOKEN_SECRET", self.job_token_secret)):
            if _weak_secret(value):
                problems.append(f"{name} 仍是預設值或少於 32 字元（openssl rand -hex 32）")
        if not self.dataset_secret_key:
            problems.append("DATASET_SECRET_KEY 未設定（python -c 'from cryptography.fernet import Fernet; ...'）")
        else:
            try:
                from cryptography.fernet import Fernet

                Fernet(self.dataset_secret_key.encode())
            except Exception:  # any failure means the key is unusable
                problems.append("DATASET_SECRET_KEY 不是合法的 Fernet 金鑰")
        if self.auth_mode == "keycloak":
            if not self.keycloak_issuer:
                problems.append("AUTH_MODE=keycloak 需要 KEYCLOAK_ISSUER")
            if not self.keycloak_client_id and not self.keycloak_audience:
                problems.append(
                    "AUTH_MODE=keycloak 需要 KEYCLOAK_CLIENT_ID 或 KEYCLOAK_AUDIENCE（確認 token 是發給本服務）"
                )
        elif _weak_secret(self.seed_superadmin_password, 12) or _weak_secret(self.seed_admin_password, 12):
            problems.append(
                "AUTH_MODE=local 的正式環境必須設定 SEED_SUPERADMIN_PASSWORD / SEED_ADMIN_PASSWORD（12 字元以上）"
            )
        if not self.scheduler_embedded and not self.redis_url:
            problems.append("排程器獨立執行時需要 REDIS_URL（否則事件 / SSE 不會送達）")
        if self.is_sqlite:
            problems.append("正式環境請使用 MariaDB（DATABASE_URL=mariadb+asyncmy://...）")
        if problems:
            raise ValueError("APP_ENV=prod 設定檢查失敗：\n- " + "\n- ".join(problems))
        return self

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
