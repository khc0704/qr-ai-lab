"""Single files from a job's output/ folder (attention overlays, heatmaps): viewers may read them, paths cannot
escape the folder, only image / text types are served."""

from __future__ import annotations

from app.core.config import get_settings
from tests.test_uploads_internal import _upload_and_job


async def test_output_file_is_served_and_sandboxed(client, admin, user, other):
    _project, _up, job = await _upload_and_job(client, admin, user)
    out = get_settings().data_root / job["output_path"] / "output" / "attention"
    out.mkdir(parents=True)
    (out / "q__a0.png").write_bytes(b"\x89PNG\r\n\x1a\n" + b"0" * 32)
    (get_settings().data_root / job["output_path"] / "secret.key").write_text("nope", encoding="utf-8")
    r = await client.get(f"/api/v1/jobs/{job['id']}/output/attention/q__a0.png", headers=user)
    assert (
        r.status_code == 200 and r.headers["content-type"].startswith("image/png") and r.content.startswith(b"\x89PNG")
    )
    # members of the project (other) see it too; strangers do not exist for the job
    assert (await client.get(f"/api/v1/jobs/{job['id']}/output/attention/q__a0.png", headers=other)).status_code == 200
    assert (await client.get(f"/api/v1/jobs/{job['id']}/output/attention/missing.png", headers=user)).status_code == 404
    assert (await client.get(f"/api/v1/jobs/{job['id']}/output/../secret.key", headers=user)).status_code == 404
    assert (await client.get(f"/api/v1/jobs/{job['id']}/output/..%2Fsecret.key", headers=user)).status_code == 404
    (out / "model.bin").write_bytes(b"x")
    assert (await client.get(f"/api/v1/jobs/{job['id']}/output/attention/model.bin", headers=user)).status_code == 404
