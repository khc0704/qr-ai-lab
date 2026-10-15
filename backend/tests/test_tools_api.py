"""Standalone preprocessing tool: upload → preview → process → download (then gone)."""

from __future__ import annotations

import io
import json
import zipfile

from app.storage.local import get_storage

CSV = b"x1,x2,yield_pct\n1.0,2.0,91.2\n,3.0,88.1\n3.0,,90.0\n50.0,1.0,70.0\n"


async def test_tool_roundtrip_tabular(client, user, other):
    r = await client.post(
        "/api/v1/tools/uploads",
        files={"file": ("wat.csv", CSV, "text/csv")},
        data={"data_type": "TABULAR"},
        headers=user,
    )
    assert r.status_code == 201, r.text
    up = r.json()
    uid = up["id"]
    assert up["format"] == "csv" and up["detected_spec"]["row_count"] == 4 and up["data_type"] == "TABULAR"
    assert get_storage().abs(f"tools/{uid}/data.csv").exists()
    # another user cannot see it
    assert (await client.get(f"/api/v1/tools/uploads/{uid}", headers=other)).status_code == 404
    steps = [{"op": "tabular.impute", "params": {"strategy": "median"}}, {"op": "tabular.standardize"}]
    r = await client.post(
        f"/api/v1/tools/uploads/{uid}/preview", json={"steps": steps, "spec": {"target": "yield_pct"}}, headers=user
    )
    assert r.status_code == 200, r.text
    assert {s["column"]: s for s in r.json()["after"]["stats"]}["x1"]["missing"] == 0
    r = await client.post(
        f"/api/v1/tools/uploads/{uid}/process", json={"steps": steps, "spec": {"target": "yield_pct"}}, headers=user
    )
    assert r.status_code == 200, r.text
    res = r.json()
    assert res["summary"]["after"]["rows"] == 4 and res["download_path"].endswith("/download")
    assert (await client.get(f"/api/v1/tools/uploads/{uid}/download", headers=other)).status_code == 404
    r = await client.get(f"/api/v1/tools/uploads/{uid}/download", headers=user)
    assert r.status_code == 200 and r.headers["content-type"] == "application/zip"
    assert "wat-preprocessed.zip" in r.headers["content-disposition"]
    with zipfile.ZipFile(io.BytesIO(r.content)) as z:
        names = set(z.namelist())
        assert {"processed.csv", "pipeline.json", "summary.json"} <= names
        pipe = json.loads(z.read("pipeline.json"))
        assert pipe["steps"][0]["op"] == "tabular.impute" and "state" in pipe["steps"][0]
        assert b"yield_pct" in z.read("processed.csv")
    # downloaded → removed, nothing left on disk or reachable
    assert not get_storage().abs(f"tools/{uid}").exists()
    assert (await client.get(f"/api/v1/tools/uploads/{uid}", headers=user)).status_code == 404


async def test_tool_rejects_bad_type_and_deletes(client, user):
    r = await client.post(
        "/api/v1/tools/uploads",
        files={"file": ("wat.csv", CSV, "text/csv")},
        data={"data_type": "IMAGE"},
        headers=user,
    )
    assert r.status_code == 400 and r.json()["detail"]["code"] == "UNKNOWN_FORMAT"
    r = await client.post(
        "/api/v1/tools/uploads",
        files={"file": ("wat.csv", CSV, "text/csv")},
        data={"data_type": "NOPE"},
        headers=user,
    )
    assert r.status_code == 400 and r.json()["detail"]["code"] == "BAD_DATA_TYPE"
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        from PIL import Image

        for i in range(2):
            b = io.BytesIO()
            Image.new("RGB", (32, 24), (10 * i, 20, 30)).save(b, format="PNG")
            z.writestr(f"a/img{i}.png", b.getvalue())
    r = await client.post(
        "/api/v1/tools/uploads",
        files={"file": ("imgs.zip", buf.getvalue(), "application/zip")},
        data={"data_type": "IMAGE"},
        headers=user,
    )
    assert r.status_code == 201, r.text
    uid = r.json()["id"]
    assert r.json()["detected_spec"]["image_count"] == 2
    r = await client.post(
        f"/api/v1/tools/uploads/{uid}/process",
        json={"steps": [{"op": "image.grayscale"}, {"op": "image.resize", "params": {"width": 16, "height": 12}}]},
        headers=user,
    )
    assert r.status_code == 200, r.text
    assert r.json()["summary"]["after"]["images"] == 2
    assert (await client.delete(f"/api/v1/tools/uploads/{uid}", headers=user)).status_code == 200
    assert not get_storage().abs(f"tools/{uid}").exists()
    assert (await client.get(f"/api/v1/tools/uploads/{uid}/download", headers=user)).status_code == 404
