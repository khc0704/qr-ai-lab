"""A NaN / ±inf reported by the trainer never fails a job: the /internal endpoints store and echo null.

Python's json parser accepts the non-standard ``NaN`` / ``Infinity`` tokens an older trainer (httpx < 0.28) can
emit, FastAPI's responses do not (``allow_nan=False``) — without the sanitising in ``services/internal.py`` the
artifact registration answered 500 and the job failed.
"""

from __future__ import annotations

from app.core.config import get_settings
from app.core.security import create_job_token
from app.db.session import get_sessionmaker
from app.models import Project
from app.services import jobs as jobs_svc
from app.utils.jsonsafe import finite
from tests.conftest import make_project
from tests.test_uploads_internal import CSV

JSON = {"Content-Type": "application/json"}


def test_finite_replaces_nan_and_inf_recursively():
    src = {"score": float("nan"), "nested": [1.0, float("inf"), (float("-inf"), 2)], "ok": 1, "flag": True, "s": "x"}
    assert finite(src) == {"score": None, "nested": [1.0, None, [None, 2]], "ok": 1, "flag": True, "s": "x"}
    assert finite(None) is None and finite(3.5) == 3.5 and finite(float("nan")) is None and finite(True) is True


async def _live_job(client, admin, user) -> tuple[dict, dict]:
    project = await make_project(client, admin, user)
    async with get_sessionmaker()() as session:  # the internal protocol needs a live job in an active project
        p = await session.get(Project, project["id"])
        p.status = "active"
        await session.commit()
    r = await client.post(
        f"/api/v1/projects/{project['slug']}/uploads", files={"file": ("train.csv", CSV, "text/csv")}, headers=user
    )
    assert r.status_code == 201, r.text
    r = await client.post(
        f"/api/v1/projects/{project['slug']}/jobs",
        json={
            "kind": "train",
            "name": "nan-run",
            "mode": "manual",
            "model_family": "tabular.linear",
            "input": {"kind": "upload", "upload_id": r.json()["id"], "spec": {"target": "yield_pct"}},
            "requested_cpu": 1,
            "requested_memory_mb": 1024,
        },
        headers=user,
    )
    assert r.status_code == 202, r.text
    job = r.json()
    async with get_sessionmaker()() as session:
        await jobs_svc.mark_scheduled(session, await jobs_svc.get(session, job["id"]), [])
    return job, {"Authorization": f"Bearer {create_job_token(job['id'], 'train', 3600)}", **JSON}


async def test_internal_endpoints_turn_nan_into_null(client, admin, user):
    job, token = await _live_job(client, admin, user)
    base = f"/api/v1/internal/jobs/{job['id']}"

    # metrics + leaderboard: NaN metric → null, ranked after the scored rows
    r = await client.post(
        base + "/metrics",
        content=b'{"trial": 1, "metrics": {"rmse": NaN, "r2": [0.5, Infinity]}, '
        b'"leaderboard_row": {"trial": 1, "family": "tabular.linear", "metric": NaN, "params": {}}}',
        headers=token,
    )
    assert r.status_code == 200, r.text
    r = await client.post(
        base + "/metrics",
        json={
            "trial": 2,
            "metrics": {"rmse": 0.1},
            "leaderboard_row": {"trial": 2, "family": "tabular.linear", "metric": 0.1, "params": {}},
        },
        headers=token,
    )
    assert r.status_code == 200, r.text
    m = (await client.get(f"/api/v1/jobs/{job['id']}", headers=user)).json()["metrics"]
    assert m["rmse"] == 0.1 and m["r2"] == [0.5, None]
    assert [row["trial"] for row in m["leaderboard"]] == [2, 1] and m["leaderboard"][1]["metric"] is None

    # artifact: 201 (not 500), metadata / metrics stored and echoed with null
    out = get_settings().data_root / job["output_path"] / "output"
    out.mkdir(parents=True, exist_ok=True)
    (out / "report.json").write_text("{}", encoding="utf-8")
    r = await client.post(
        base + "/artifacts",
        content=b'{"name": "analysis-1", "kind": "report", "path": "output/report.json", "framework": "numpy", '
        b'"metrics": {"silhouette": NaN}, "metadata": {"score": NaN, "nested": [1.0, Infinity]}}',
        headers=token,
    )
    assert r.status_code == 201, r.text
    art = r.json()
    assert art["metadata"] == {"score": None, "nested": [1.0, None]} and art["metrics"] == {"silhouette": None}
    listed = (await client.get(f"/api/v1/jobs/{job['id']}/artifacts", headers=user)).json()
    assert listed[0]["id"] == art["id"] and listed[0]["metadata"] == {"score": None, "nested": [1.0, None]}

    # result
    r = await client.post(
        base + "/result",
        content=b'{"result": {"analysis": "image_quality", "silhouette": NaN, "drift": [{"p_value": -Infinity}]}}',
        headers=token,
    )
    assert r.status_code == 200, r.text
    j = (await client.get(f"/api/v1/jobs/{job['id']}", headers=user)).json()
    assert j["result"]["analysis"] == "image_quality" and j["result"]["silhouette"] is None
    assert j["result"]["drift"] == [{"p_value": None}]
