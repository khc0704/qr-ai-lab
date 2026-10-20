"""Inference jobs never carry their own preprocessing when the model was trained with one: the model's fitted
pipeline is replayed by the trainer, so steps sent along are dropped and the job records where they come from."""

from __future__ import annotations

from app.core.security import create_job_token
from tests.test_ephemeral import _register_model
from tests.test_uploads_internal import _upload_and_job


async def _register_with_preprocess(client, job: dict) -> dict:
    token = {"Authorization": f"Bearer {create_job_token(job['id'], 'train', 3600)}"}
    model = await _register_model(client, job)
    # the trainer lists the steps (ids + params, has_state) in the artifact metadata when it registers the model
    r = await client.get(f"/api/v1/internal/jobs/{job['id']}/spec", headers=token)
    assert r.status_code == 200
    return model


async def test_inference_drops_steps_when_the_model_has_its_own(client, admin, user, db):
    from app.db.session import get_sessionmaker
    from app.models import Artifact

    project, _up, job = await _upload_and_job(client, admin, user)
    model = await _register_with_preprocess(client, job)
    async with get_sessionmaker()() as session:
        art = await session.get(Artifact, model["id"])
        art.metadata_ = {
            **(art.metadata_ or {}),
            "preprocess": [{"op": "tabular.impute", "params": {}, "has_state": True}],
        }
        await session.commit()
    body = {
        "kind": "inference",
        "name": "run",
        "artifact_id": model["id"],
        "config": {"mode": "predict"},
        "input": {
            "kind": "inline",
            "rows": [{"a": 1, "b": 2}],
            "spec": {"preprocess": [{"op": "tabular.standardize"}]},
        },
        "requested_cpu": 1,
        "requested_memory_mb": 512,
    }
    r = await client.post(f"/api/v1/projects/{project['slug']}/jobs", json=body, headers=user)
    assert r.status_code == 202, r.text
    j = r.json()
    assert "preprocess" not in j["input"]["spec"] and j["input"]["preprocess_from_model"] == ["tabular.impute"]
    # a model without preprocessing still accepts (validated) steps of its own
    async with get_sessionmaker()() as session:
        art = await session.get(Artifact, model["id"])
        art.metadata_ = {k: v for k, v in (art.metadata_ or {}).items() if k != "preprocess"}
        await session.commit()
    r = await client.post(f"/api/v1/projects/{project['slug']}/jobs", json=body, headers=user)
    assert r.status_code == 202, r.text
    j = r.json()
    assert j["input"]["spec"]["preprocess"] == [{"op": "tabular.standardize"}]
    assert "preprocess_from_model" not in j["input"]
    body["input"]["spec"]["preprocess"] = [{"op": "nope.unknown"}]
    r = await client.post(f"/api/v1/projects/{project['slug']}/jobs", json=body, headers=user)
    assert r.status_code == 400 and r.json()["detail"]["code"] == "PREPROCESS_INVALID"
