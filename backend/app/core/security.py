"""Passwords, access tokens (local mode), Keycloak token verification, per-job tokens, Fernet."""

from __future__ import annotations

import base64
import hashlib
import json
import time
from functools import lru_cache
from typing import Any

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError
from cryptography.fernet import Fernet

from app.core.config import Settings, get_settings
from app.core.errors import unauthorized

ISSUER = "qr-ai-lab"
_hasher = PasswordHasher()


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password: str, password_hash: str | None) -> bool:
    if not password_hash:
        return False
    try:
        return _hasher.verify(password_hash, password)
    except VerifyMismatchError:
        return False


# --- access tokens (auth_mode = local) ---------------------------------------------------------


def create_access_token(*, user_id: int, username: str, role: str, settings: Settings | None = None) -> str:
    s = settings or get_settings()
    now = int(time.time())
    payload = {
        "iss": ISSUER,
        "aud": ISSUER,
        "sub": str(user_id),
        "username": username,
        "role": role,
        "iat": now,
        "exp": now + s.access_token_minutes * 60,
    }
    return jwt.encode(payload, s.auth_secret, algorithm="HS256")


def decode_access_token(token: str, settings: Settings | None = None) -> dict[str, Any]:
    s = settings or get_settings()
    try:
        return jwt.decode(token, s.auth_secret, algorithms=["HS256"], audience=ISSUER, issuer=ISSUER)
    except jwt.PyJWTError as e:
        raise unauthorized("INVALID_TOKEN", f"token 無效：{e}") from e


# --- Keycloak (auth_mode = keycloak) -----------------------------------------------------------


@lru_cache
def _jwks_client(issuer: str) -> jwt.PyJWKClient:
    return jwt.PyJWKClient(f"{issuer}/protocol/openid-connect/certs", cache_keys=True, lifespan=3600)


def decode_keycloak_token(token: str, settings: Settings | None = None) -> dict[str, Any]:
    s = settings or get_settings()
    if not s.keycloak_issuer:
        raise unauthorized("AUTH_MISCONFIGURED", "KEYCLOAK_ISSUER 未設定")
    try:
        key = _jwks_client(s.keycloak_issuer).get_signing_key_from_jwt(token).key
        return jwt.decode(
            token,
            key,
            algorithms=["RS256"],
            issuer=s.keycloak_issuer,
            audience=s.keycloak_audience,
            options={"verify_aud": bool(s.keycloak_audience)},
        )
    except jwt.PyJWTError as e:
        raise unauthorized("INVALID_TOKEN", f"token 無效：{e}") from e


# --- per-job tokens for /internal/* -----------------------------------------------------------


def create_job_token(job_id: int, kind: str, ttl_seconds: int, settings: Settings | None = None) -> str:
    s = settings or get_settings()
    now = int(time.time())
    return jwt.encode(
        {"iss": ISSUER, "aud": "job", "sub": str(job_id), "kind": kind, "iat": now, "exp": now + ttl_seconds},
        s.job_token_secret,
        algorithm="HS256",
    )


def decode_job_token(token: str, settings: Settings | None = None) -> dict[str, Any]:
    s = settings or get_settings()
    try:
        return jwt.decode(token, s.job_token_secret, algorithms=["HS256"], audience="job", issuer=ISSUER)
    except jwt.PyJWTError as e:
        raise unauthorized("INVALID_JOB_TOKEN", f"job token 無效：{e}") from e


# --- Fernet for data-source credentials -------------------------------------------------------


@lru_cache
def _fernet(key: str | None, fallback_secret: str) -> Fernet:
    if key:
        return Fernet(key.encode())
    # Dev convenience: a deterministic key derived from AUTH_SECRET. Production must set DATASET_SECRET_KEY.
    derived = base64.urlsafe_b64encode(hashlib.sha256(fallback_secret.encode()).digest())
    return Fernet(derived)


def encrypt_json(data: dict[str, Any], settings: Settings | None = None) -> bytes:
    s = settings or get_settings()
    return _fernet(s.dataset_secret_key, s.auth_secret).encrypt(json.dumps(data).encode())


def decrypt_json(blob: bytes | None, settings: Settings | None = None) -> dict[str, Any]:
    if not blob:
        return {}
    s = settings or get_settings()
    return json.loads(_fernet(s.dataset_secret_key, s.auth_secret).decrypt(bytes(blob)))
