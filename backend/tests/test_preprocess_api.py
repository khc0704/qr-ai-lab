"""Preprocessing: op catalog, sample preview on an upload, validation when creating jobs."""

from __future__ import annotations

import io
import zipfile

from tests.conftest import make_project

CSV = b"x1,x2,line,yield_pct\n1.0,2.0,A,91.2\n,3.0,B,88.1\n3.0,,A,90.0\n50.0,1.0,A,70.0\n2.0,2.5,B,89.5\n"


async def test_catalog_and_preview_tabular(client, admin, user):
    cat = (await client.get("/api/v1/catalog/preprocess?data_type=TABULAR", headers=user)).json()
    ids = {o["id"] for o in cat}
    assert {"tabular.impute", "tabular.standardize", "tabular.filter_rows"} <= ids and "image.resize" not in ids
    assert all({"id", "label", "params", "fitted", "geometric"} <= set(o) for o in cat)

    project = await make_project(client, admin, user)
    slug = project["slug"]
    up = await client.post(
        f"/api/v1/projects/{slug}/uploads",
        files={"file": ("wat.csv", CSV, "text/csv")},
        data={"format": "csv"},
        headers=user,
    )
    assert up.status_code == 201, up.text
    upload_id = up.json()["id"]

    r = await client.post(
        f"/api/v1/projects/{slug}/uploads/{upload_id}/preview",
        json={
            "steps": [
                {"op": "tabular.impute", "params": {"strategy": "median"}},
                {"op": "tabular.clip_outliers", "params": {"method": "zscore", "factor": 1.0, "action": "clip"}},
                {"op": "tabular.standardize"},
            ],
            "sample": 3,
            "spec": {"target": "yield_pct"},
        },
        headers=user,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["data_type"] == "TABULAR" and len(body["steps"]) == 3
    before = {s["column"]: s for s in body["before"]["stats"]}
    after = {s["column"]: s for s in body["after"]["stats"]}
    assert before["x1"]["missing"] == 1 and after["x1"]["missing"] == 0
    assert abs(after["x1"]["mean"]) < 1e-6 and after["yield_pct"] == before["yield_pct"]  # target untouched
    assert len(body["after"]["rows"]) == 3 and body["before"]["row_count"] == 5

    bad = await client.post(
        f"/api/v1/projects/{slug}/uploads/{upload_id}/preview",
        json={"steps": [{"op": "tabular.filter_rows", "params": {"column": "nope", "operator": "==", "value": "1"}}]},
        headers=user,
    )
    assert bad.status_code == 400 and bad.json()["detail"]["code"] == "PREPROCESS_INVALID"
    assert (
        await client.post(f"/api/v1/projects/{slug}/uploads/{upload_id}/preview", json={"steps": []}, headers=admin)
    ).status_code == 200

    # preprocessing travels with the job in input.spec and is validated
    r = await client.post(
        f"/api/v1/projects/{slug}/jobs",
        json={
            "kind": "train",
            "name": "pre",
            "mode": "manual",
            "model_family": "tabular.linear",
            "input": {
                "kind": "upload",
                "upload_id": upload_id,
                "spec": {
                    "target": "yield_pct",
                    "preprocess": [{"op": "tabular.impute"}, {"op": "tabular.standardize"}],
                },
            },
            "requested_gpu": 0,
            "requested_cpu": 1,
            "requested_memory_mb": 1024,
        },
        headers=user,
    )
    assert r.status_code == 202, r.text
    assert [s["op"] for s in r.json()["input"]["spec"]["preprocess"]] == ["tabular.impute", "tabular.standardize"]


async def test_job_rejects_invalid_preprocess(client, admin, user):
    project = await make_project(client, admin, user)
    slug = project["slug"]
    up = await client.post(
        f"/api/v1/projects/{slug}/uploads",
        files={"file": ("wat.csv", CSV, "text/csv")},
        data={"format": "csv"},
        headers=user,
    )
    r = await client.post(
        f"/api/v1/projects/{slug}/jobs",
        json={
            "kind": "train",
            "name": "bad",
            "mode": "manual",
            "model_family": "tabular.linear",
            "input": {
                "kind": "upload",
                "upload_id": up.json()["id"],
                "spec": {"target": "yield_pct", "preprocess": [{"op": "image.resize"}]},
            },
            "requested_gpu": 0,
            "requested_cpu": 1,
            "requested_memory_mb": 1024,
        },
        headers=user,
    )
    assert r.status_code == 400 and r.json()["detail"]["code"] == "PREPROCESS_INVALID"


async def test_preview_images_from_zip(client, admin, user):
    from PIL import Image

    project = await make_project(client, admin, user)  # project data_type is TABULAR in the fixture
    slug = project["slug"]
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for cls in ("good", "bad"):
            for i in range(2):
                b = io.BytesIO()
                Image.new("L", (64, 48), 40 + 50 * i).save(b, format="PNG")
                z.writestr(f"{cls}/{i}.png", b.getvalue())
    up = await client.post(
        f"/api/v1/projects/{slug}/uploads",
        files={"file": ("imgs.zip", buf.getvalue(), "application/zip")},
        data={"format": "image_folder"},
        headers=user,
    )
    assert up.status_code == 201, up.text
    # the preview follows the project's data_type; a TABULAR project cannot preview image ops
    r = await client.post(
        f"/api/v1/projects/{slug}/uploads/{up.json()['id']}/preview",
        json={"steps": [{"op": "image.grayscale"}], "sample": 4},
        headers=user,
    )
    assert r.status_code == 400 and r.json()["detail"]["code"] == "PREPROCESS_INVALID"
