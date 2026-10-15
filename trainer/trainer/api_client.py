"""Trainer → backend /internal API. Only the per-job token; retries on transient errors."""

from __future__ import annotations

import time
from typing import Any

import httpx

from trainer.log import warn


class Backend:
    def __init__(self, base_url: str, job_id: int, token: str) -> None:
        self.base = f"{base_url}/api/v1/internal/jobs/{job_id}"
        self.client = httpx.Client(timeout=30, headers={"Authorization": f"Bearer {token}"})

    def _req(self, method: str, path: str, json: dict[str, Any] | None = None) -> Any:
        last: Exception | None = None
        for attempt in range(5):
            try:
                r = self.client.request(method, self.base + path, json=json)
                if r.status_code >= 500:
                    raise httpx.HTTPStatusError(f"server {r.status_code}", request=r.request, response=r)
                if r.status_code >= 400:
                    raise RuntimeError(f"backend {r.status_code}: {r.text[:300]}")
                return r.json() if r.content else None
            except (httpx.TransportError, httpx.HTTPStatusError) as e:
                last = e
                warn(f"backend call {path} failed ({e}); retry {attempt + 1}/5")
                time.sleep(min(2**attempt, 15))
        raise RuntimeError(f"backend unreachable: {last}")

    def spec(self) -> dict[str, Any]:
        return self._req("GET", "/spec")

    def status(
        self,
        *,
        status: str | None = None,
        progress: float | None = None,
        stage: str | None = None,
        message: str | None = None,
    ) -> None:
        self._req(
            "POST",
            "/status",
            {"status": status, "progress": progress, "stage": stage, "message": message},
        )

    def metrics(
        self,
        metrics: dict[str, Any],
        *,
        epoch: int | None = None,
        trial: int | None = None,
        leaderboard_row: dict[str, Any] | None = None,
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
    ) -> dict[str, Any]:
        return self._req(
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
            },
        )

    def result(self, result: dict[str, Any] | None = None, output_path: str | None = None) -> None:
        self._req("POST", "/result", {"result": result, "output_path": output_path})
