"""Trainer → backend /internal API. Only the per-job token; retries on transient errors.

Two retry schedules (capped exponential backoff, configurable through the environment):

* ``short`` (``TRAINER_RETRY_SHORT_S``, default 30 s): spec, status heartbeats, per-epoch / per-trial metrics.
* ``long`` (``TRAINER_RETRY_LONG_S``, default 600 s): the terminal phase after training — final metrics,
  artifact registration, result, final status — so a backend restart does not turn hours of training into
  ``failed``.

Artifact registration is memoised per (kind, name, path) inside the process, so a second ``_register`` pass
(the cancel / timeout salvage path) never creates a duplicate version.
"""

from __future__ import annotations

import os
import time
from typing import Any, Literal

import httpx

from trainer.jsonsafe import finite
from trainer.log import warn

Retry = Literal["short", "long", "none"]


def _env_seconds(name: str, default: float) -> float:
    raw = os.environ.get(name) or ""
    try:
        return max(0.0, float(raw)) if raw else default
    except ValueError:
        return default


class Backend:
    def __init__(
        self,
        base_url: str,
        job_id: int,
        token: str,
        *,
        retry_short_s: float | None = None,
        retry_long_s: float | None = None,
        backoff_cap_s: float = 30.0,
        sleep=time.sleep,
    ) -> None:
        self.base = f"{base_url}/api/v1/internal/jobs/{job_id}"
        self.client = httpx.Client(timeout=30, headers={"Authorization": f"Bearer {token}"})
        self.budgets: dict[str, float] = {
            "short": retry_short_s if retry_short_s is not None else _env_seconds("TRAINER_RETRY_SHORT_S", 30.0),
            "long": retry_long_s if retry_long_s is not None else _env_seconds("TRAINER_RETRY_LONG_S", 600.0),
            "none": 0.0,
        }
        self.backoff_cap_s = backoff_cap_s
        self._sleep = sleep
        self._artifacts: dict[tuple[str, str, str], dict[str, Any]] = {}

    def _req(self, method: str, path: str, json: dict[str, Any] | None = None, *, retry: Retry = "short") -> Any:
        """The single place every payload leaves the trainer: NaN / ±inf → null, numpy scalars → Python, so a
        degenerate metric or metadata value can never make the backend answer 500 (its responses use
        ``allow_nan=False``)."""
        if json is not None:
            json = finite(json)
        budget = self.budgets[retry]
        started = time.monotonic()
        attempt = 0
        waited = 0.0
        last: Exception | None = None
        while True:
            try:
                r = self.client.request(method, self.base + path, json=json)
                if r.status_code >= 500:
                    raise httpx.HTTPStatusError(f"server {r.status_code}", request=r.request, response=r)
                if r.status_code >= 400:
                    raise RuntimeError(f"backend {r.status_code}: {r.text[:300]}")
                return r.json() if r.content else None
            except (httpx.TransportError, httpx.HTTPStatusError) as e:
                last = e
                elapsed = max(time.monotonic() - started, waited)
                wait = min(2.0**attempt, self.backoff_cap_s)
                if elapsed + wait > budget:
                    break
                attempt += 1
                waited += wait
                warn(f"backend call {path} failed ({e}); retry {attempt} in {wait:.0f}s ({retry} schedule)")
                self._sleep(wait)
        raise RuntimeError(f"backend unreachable after {max(time.monotonic() - started, waited):.0f}s: {last}")

    def spec(self) -> dict[str, Any]:
        return self._req("GET", "/spec")

    def status(
        self,
        *,
        status: str | None = None,
        progress: float | None = None,
        stage: str | None = None,
        message: str | None = None,
        retry: Retry = "short",
    ) -> None:
        self._req(
            "POST",
            "/status",
            {"status": status, "progress": progress, "stage": stage, "message": message},
            retry=retry,
        )

    def metrics(
        self,
        metrics: dict[str, Any],
        *,
        epoch: int | None = None,
        trial: int | None = None,
        leaderboard_row: dict[str, Any] | None = None,
        retry: Retry = "short",
    ) -> None:
        self._req(
            "POST",
            "/metrics",
            {
                "epoch": epoch,
                "trial": trial,
                "metrics": metrics,
                "leaderboard_row": leaderboard_row,
            },
            retry=retry,
        )

    def artifact(
        self,
        *,
        name: str,
        kind: str,
        path: str,
        framework: str,
        metrics: dict[str, Any] | None = None,
        metadata: dict[str, Any] | None = None,
        set_default: bool = False,
        retry: Retry = "long",
    ) -> dict[str, Any]:
        key = (kind, name, path)
        if key in self._artifacts:
            return self._artifacts[key]
        r = self._req(
            "POST",
            "/artifacts",
            {
                "name": name,
                "kind": kind,
                "path": path,
                "framework": framework,
                "metrics": metrics,
                "metadata": metadata,
                "set_default": set_default,
                # dedupe hint for the backend (ignored until it learns the field): same job + name + path
                "idempotency_key": f"{kind}:{name}:{path}",
            },
            retry=retry,
        )
        self._artifacts[key] = r or {}
        return self._artifacts[key]

    def result(
        self, result: dict[str, Any] | None = None, output_path: str | None = None, *, retry: Retry = "long"
    ) -> None:
        self._req("POST", "/result", {"result": result, "output_path": output_path}, retry=retry)
