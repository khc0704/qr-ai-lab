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


async def test_preview_column_stats_encode_and_to_numeric_warning(client, admin, user):
    project = await make_project(client, admin, user)
    slug = project["slug"]
    up = await client.post(
        f"/api/v1/projects/{slug}/uploads",
        files={"file": ("wat.csv", CSV, "text/csv")},
        data={"format": "csv"},
        headers=user,
    )
    assert up.status_code == 201, up.text
    url = f"/api/v1/projects/{slug}/uploads/{up.json()['id']}/preview"

    # no steps: per-column statistics of the sample, output == input
    r = await client.post(url, json={"steps": [], "spec": {"target": "yield_pct"}}, headers=user)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["rows_in"] == 5 and body["rows_out"] == 5 and body["step_details"] == [] and body["warnings"] == []
    cin = {c["name"]: c for c in body["columns_in"]}
    assert list(cin) == ["x1", "x2", "line", "yield_pct"]
    assert cin["x1"] == {
        "name": "x1",
        "dtype": "number",
        "missing": 1,
        "missing_ratio": 0.2,
        "unique": 4,
        "min": 1.0,
        "max": 50.0,
        "mean": 14.0,
        "top": [],
    }
    assert cin["line"]["dtype"] == "text" and cin["line"]["missing"] == 0 and cin["line"]["unique"] == 2
    assert cin["line"]["top"] == [{"value": "A", "count": 3}, {"value": "B", "count": 2}]
    assert cin["line"]["min"] is None and cin["yield_pct"]["dtype"] == "number"
    assert body["columns_out"] == body["columns_in"]
    assert body["before"]["row_count"] == 5 and body["after"]["stats"]  # the fields the current UI reads

    # categorical encoding previews: one-hot columns replace the text column, nothing to warn about
    r = await client.post(
        url,
        json={
            "steps": [
                {"op": "tabular.encode", "params": {"columns": ["line"], "method": "onehot"}},
                {"op": "tabular.impute"},
            ],
            "spec": {"target": "yield_pct"},
        },
        headers=user,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert [c["name"] for c in body["columns_out"]] == ["x1", "x2", "line__A", "line__B", "yield_pct"]
    cout = {c["name"]: c for c in body["columns_out"]}
    assert cout["line__A"]["dtype"] == "number" and cout["line__A"]["mean"] == 0.6 and cout["x1"]["missing"] == 0
    assert [s["op"] for s in body["step_details"]] == ["tabular.encode", "tabular.impute"]
    assert body["step_details"][0]["label"] == "類別編碼" and body["step_details"][0]["fitted"] is True
    assert body["step_details"][0]["params"]["method"] == "onehot" and body["warnings"] == []
    assert body["after"]["rows"][0]["line__A"] == 1 and "line" not in body["after"]["columns"]
    cat = (await client.get("/api/v1/catalog/preprocess?data_type=TABULAR", headers=user)).json()
    assert {o["id"]: o["label"] for o in cat}["tabular.encode"] == "類別編碼"

    # to_numeric on a categorical column: the step runs, but warns that the column became missing
    r = await client.post(
        url,
        json={
            "steps": [{"op": "tabular.to_numeric", "params": {"columns": ["line"]}}],
            "spec": {"target": "yield_pct"},
        },
        headers=user,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["step_details"][0]["warnings"] == [
        "欄位 line：100% 的值無法轉成數字，會變成缺值；若這是類別欄請改用「類別編碼」"
    ]
    assert body["warnings"] == ["步驟 1（文字數字轉成數值）" + body["step_details"][0]["warnings"][0]]
    cout = {c["name"]: c for c in body["columns_out"]}
    assert cout["line"]["dtype"] == "number" and cout["line"]["missing"] == 5 and cout["line"]["missing_ratio"] == 1.0

    # too many categories is a clear error, not a silent giant one-hot
    r = await client.post(
        url,
        json={"steps": [{"op": "tabular.encode", "params": {"columns": ["x1"], "max_categories": 2}}]},
        headers=user,
    )
    assert r.status_code == 400 and r.json()["detail"]["code"] == "PREPROCESS_INVALID"
    assert "欄位 x1 有 4 種類別，超過上限 2" in r.json()["detail"]["message"]
    assert "移除欄位" in r.json()["detail"]["message"]


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
