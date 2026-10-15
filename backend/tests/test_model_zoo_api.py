"""Admin model zoo: status, browser upload (sha256 check), import from a mounted path and from an intranet URL,
delete; non-admins are refused; job creation refuses families whose weights are missing."""

from __future__ import annotations

import asyncio
import hashlib
import http.server
import json
import threading
import zipfile
from pathlib import Path

from app.core.config import get_settings
from app.services import model_zoo as zoo


def _serve(directory: Path) -> tuple[http.server.ThreadingHTTPServer, int]:
    handler = lambda *a, **k: http.server.SimpleHTTPRequestHandler(*a, directory=str(directory), **k)  # noqa: E731
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, srv.server_address[1]


async def _wait_task(client, admin, weight_id: str, timeout: float = 20) -> dict:
    for _ in range(int(timeout / 0.2)):
        tasks = (await client.get("/api/v1/admin/model-zoo/tasks", headers=admin)).json()
        t = next((t for t in tasks if t["weight_id"] == weight_id), None)
        if t and t["state"] != "running":
            return t
        await asyncio.sleep(0.2)
    raise AssertionError("import did not finish")


async def test_zoo_status_upload_import_delete(client, admin, user, tmp_path, monkeypatch, superadmin):
    s = get_settings()
    monkeypatch.setattr(type(s), "zoo_root", property(lambda self: tmp_path / "zoo"))
    transfer = tmp_path / "transfer"
    transfer.mkdir()
    s.model_zoo_import_root = transfer
    s.model_zoo_allowed_hosts = ["127.0.0.1"]

    # everything missing at first; the catalog tells the wizard which families are not ready
    rows = (await client.get("/api/v1/admin/model-zoo", headers=admin)).json()
    ids = {r["id"] for r in rows}
    assert {"yolo11n", "dinov2-small", "bert-base-chinese"} <= ids and all(r["status"] == "missing" for r in rows)
    cat = (await client.get("/api/v1/catalog", headers=user)).json()
    assert cat["families"]["vision.yolo"]["weights_ready"] is False
    assert cat["families"]["tabular.xgboost"]["weights_ready"] is True
    assert (await client.get("/api/v1/admin/model-zoo", headers=user)).status_code == 403

    # 1) browser upload of a single-file weight
    blob = b"PK-not-really-a-model" * 1000
    r = await client.post(
        "/api/v1/admin/model-zoo/yolo11n/upload",
        files={"file": ("yolo11n.pt", blob, "application/octet-stream")},
        headers=superadmin,
    )
    assert r.status_code == 200, r.text
    e = r.json()
    assert e["status"] == "present" and e["size_bytes"] == len(blob) and e["imported_from"] == "upload:yolo11n.pt"
    assert (tmp_path / "zoo" / "yolo11n.pt").read_bytes() == blob
    manifest = json.loads((tmp_path / "zoo" / "manifest.json").read_text())
    assert manifest["weights"]["yolo11n"]["sha256"] == hashlib.sha256(blob).hexdigest()

    # an HF repo must come as an archive containing config.json
    bad = await client.post(
        "/api/v1/admin/model-zoo/dinov2-small/upload",
        files={"file": ("model.safetensors", b"x", "application/octet-stream")},
        headers=superadmin,
    )
    assert bad.status_code == 400 and bad.json()["detail"]["code"] == "ARCHIVE_REQUIRED"
    zpath = tmp_path / "dinov2-small.zip"
    with zipfile.ZipFile(zpath, "w") as z:
        z.writestr("dinov2-small/config.json", '{"model_type": "dinov2"}')
        z.writestr("dinov2-small/model.safetensors", b"\x00" * 100)
    r = await client.post(
        "/api/v1/admin/model-zoo/dinov2-small/upload",
        files={"file": ("dinov2-small.zip", zpath.read_bytes(), "application/zip")},
        headers=superadmin,
    )
    assert r.status_code == 200, r.text
    assert (tmp_path / "zoo" / "dinov2-small" / "config.json").exists()
    cat = (await client.get("/api/v1/catalog", headers=user)).json()
    assert cat["families"]["vision.dino_fewshot"]["weights_ready"]

    # 2) import from a folder mounted on the server (only under MODEL_ZOO_IMPORT_ROOT)
    (transfer / "yolo11s.pt").write_bytes(b"s" * 5000)
    r = await client.post(
        "/api/v1/admin/model-zoo/yolo11s/import", json={"source": "path", "path": "yolo11s.pt"}, headers=superadmin
    )
    assert r.status_code == 202, r.text
    t = await _wait_task(client, admin, "yolo11s")
    assert t["state"] == "done", t
    assert (tmp_path / "zoo" / "yolo11s.pt").stat().st_size == 5000
    r = await client.post(
        "/api/v1/admin/model-zoo/yolo11m/import",
        json={"source": "path", "path": "../../etc/passwd"},
        headers=superadmin,
    )
    assert r.status_code == 400 and r.json()["detail"]["code"] == "PATH_NOT_ALLOWED"

    # 3) fetch from an intranet URL (host whitelist)
    srv, port = _serve(transfer)
    try:
        (transfer / "yolo11n-cls.pt").write_bytes(b"c" * 7000)
        r = await client.post(
            "/api/v1/admin/model-zoo/yolo11n-cls/import",
            json={"source": "url", "url": f"http://127.0.0.1:{port}/yolo11n-cls.pt"},
            headers=superadmin,
        )
        assert r.status_code == 202, r.text
        t = await _wait_task(client, admin, "yolo11n-cls")
        assert t["state"] == "done" and t["downloaded_mb"] >= 0, t
        assert (tmp_path / "zoo" / "yolo11n-cls.pt").stat().st_size == 7000
        r = await client.post(
            "/api/v1/admin/model-zoo/yolo11m/import",
            json={"source": "url", "url": f"http://example.com:{port}/x.pt"},
            headers=superadmin,
        )
        assert r.status_code == 400 and r.json()["detail"]["code"] == "URL_NOT_ALLOWED"
    finally:
        srv.shutdown()

    # verify recomputes sha256 and flags tampering
    (tmp_path / "zoo" / "yolo11s.pt").write_bytes(b"tampered")
    rows = {r["id"]: r for r in (await client.get("/api/v1/admin/model-zoo?verify=true", headers=admin)).json()}
    assert rows["yolo11s"]["status"] == "mismatch" and rows["yolo11n"]["status"] == "present"

    # delete
    r = await client.delete("/api/v1/admin/model-zoo/yolo11n", headers=superadmin)
    assert r.status_code == 200 and not (tmp_path / "zoo" / "yolo11n.pt").exists()
    audit = {a["action"] for a in (await client.get("/api/v1/admin/audit", headers=admin)).json()["items"]}
    assert {"model_zoo.upload", "model_zoo.import", "model_zoo.delete"} <= audit


async def test_job_creation_refuses_missing_weights(client, admin, user, tmp_path, monkeypatch, superadmin):
    from tests.conftest import APPROVE, REQUEST, make_data_source

    s = get_settings()
    monkeypatch.setattr(type(s), "zoo_root", property(lambda self: tmp_path / "empty-zoo"))
    slug = "defect-images"
    body = {**REQUEST, "proposed_slug": slug, "data_type": "IMAGE", "task_type": "classification"}
    rid = (await client.post("/api/v1/project-requests", json=body, headers=user)).json()["id"]
    r = await client.post(f"/api/v1/project-requests/{rid}/approve", json={**APPROVE, "slug": slug}, headers=admin)
    assert r.status_code == 201, r.text
    await client.patch(
        f"/api/v1/projects/{slug}/quota",
        json={"gpu_limit": 1, "cpu_limit": 4, "memory_limit_mb": 8192, "max_concurrent_jobs": 1},
        headers=superadmin,
    )
    ds = await make_data_source(client, user, slug)
    r = await client.post(
        f"/api/v1/projects/{slug}/jobs",
        json={
            "kind": "train",
            "name": "needs-weights",
            "mode": "manual",
            "model_family": "vision.dino_fewshot",
            "input": {"kind": "data_source", "data_source_id": ds["id"], "spec": {}},
            "requested_gpu": 1,
            "requested_cpu": 2,
            "requested_memory_mb": 4096,
        },
        headers=user,
    )
    assert r.status_code == 400 and r.json()["detail"]["code"] == "WEIGHTS_MISSING"
    assert zoo.family_ready("tabular.linear") and not zoo.family_ready("vision.yolo")
