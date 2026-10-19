"""Backend client: short schedule for heartbeats, long schedule for the terminal phase, memoised artifacts."""

from __future__ import annotations

import json

import httpx
import numpy as np
import pytest

from trainer.api_client import Backend


def _backend(handler, **kw) -> tuple[Backend, list[float]]:
    sleeps: list[float] = []
    b = Backend("http://b", 1, "tok", sleep=sleeps.append, **kw)
    b.client = httpx.Client(transport=httpx.MockTransport(handler), headers={"Authorization": "Bearer tok"})
    return b, sleeps


def test_short_schedule_gives_up_within_budget():
    calls: list[str] = []

    def down(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.path)
        raise httpx.ConnectError("refused")

    b, sleeps = _backend(down, retry_short_s=30, retry_long_s=600)
    with pytest.raises(RuntimeError, match="unreachable"):
        b.status(progress=5, stage="training")
    assert sum(sleeps) <= 30 and 3 <= len(calls) <= 6


def test_long_schedule_outlasts_a_backend_restart():
    state = {"n": 0}

    def flaky(request: httpx.Request) -> httpx.Response:
        state["n"] += 1
        if state["n"] <= 8:
            return httpx.Response(503, text="restarting")
        return httpx.Response(201, json={"id": 9, "version": 2})

    b, sleeps = _backend(flaky, retry_short_s=30, retry_long_s=600, backoff_cap_s=30)
    r = b.artifact(name="m", kind="model", path="model", framework="sklearn")
    assert r == {"id": 9, "version": 2} and state["n"] == 9
    assert sum(sleeps) > 30 and max(sleeps) == 30  # kept going past the short budget, capped backoff


def test_four_hundred_is_not_retried():
    def bad(request: httpx.Request) -> httpx.Response:
        return httpx.Response(409, json={"detail": {"code": "STORAGE_QUOTA_EXCEEDED"}})

    b, sleeps = _backend(bad)
    with pytest.raises(RuntimeError, match="409"):
        b.result(result={}, output_path="x")
    assert sleeps == []


def test_artifact_registration_is_memoised():
    posted: list[dict] = []

    def ok(request: httpx.Request) -> httpx.Response:
        posted.append(json.loads(request.content))
        return httpx.Response(201, json={"id": len(posted), "version": len(posted)})

    b, _ = _backend(ok)
    first = b.artifact(name="m", kind="model", path="model", framework="sklearn")
    again = b.artifact(name="m", kind="model", path="model", framework="sklearn", retry="none")
    other = b.artifact(name="metrics", kind="metrics", path="metrics/metrics.json", framework="sklearn")
    assert first == again == {"id": 1, "version": 1} and other["id"] == 2 and len(posted) == 2
    assert posted[0]["idempotency_key"] == "model:m:model"


def test_payloads_never_carry_nan_or_numpy_scalars():
    posted: list[dict] = []

    def ok(request: httpx.Request) -> httpx.Response:
        assert b"NaN" not in request.content and b"Infinity" not in request.content
        posted.append(json.loads(request.content))
        return httpx.Response(201, json={"id": 1, "version": 1})

    b, _ = _backend(ok)
    b.metrics({"rmse": float("nan"), "r2": np.float32(0.5)}, trial=1, leaderboard_row={"metric": float("inf")})
    b.artifact(
        name="r",
        kind="report",
        path="output/report.json",
        framework="numpy",
        metadata={"score": float("nan"), "nested": [1.0, float("-inf")]},
    )
    b.result(result={"silhouette": float("nan"), "n": np.int64(3)})
    b.status(progress=float("nan"), stage="x")
    assert posted[0]["metrics"] == {"rmse": None, "r2": 0.5} and posted[0]["leaderboard_row"] == {"metric": None}
    assert posted[1]["metadata"] == {"score": None, "nested": [1.0, None]}
    assert posted[2]["result"] == {"silhouette": None, "n": 3}
    assert posted[3]["progress"] is None


def test_env_configures_budgets(monkeypatch):
    monkeypatch.setenv("TRAINER_RETRY_SHORT_S", "5")
    monkeypatch.setenv("TRAINER_RETRY_LONG_S", "42")
    b = Backend("http://b", 1, "tok")
    assert b.budgets["short"] == 5 and b.budgets["long"] == 42 and b.budgets["none"] == 0
