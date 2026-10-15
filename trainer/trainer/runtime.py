"""One job, start to finish: spec → fetch → load → train / infer → export → register → status.

Exit codes: 0 succeeded, 1 failed, 143 cancelled (SIGTERM).
"""

from __future__ import annotations

import csv
import json
import shutil
import signal
import time
import traceback
from pathlib import Path
from typing import Any

from trainer import dataset, limits
from trainer.api_client import Backend
from trainer.config import Env
from trainer.fetch import fetch_data_source
from trainer.log import error, info, warn
from trainer.models import registry, zoo
from trainer.models.base import ArtifactOut, BaseTrainer, Cancelled, Context

# stage → (start, end) of the overall progress bar
TRAIN_PHASES = {
    "fetching": (0, 10),
    "preparing": (10, 15),
    "training": (15, 85),
    "exporting": (85, 97),
}
INFER_PHASES = {
    "fetching": (0, 10),
    "loading": (10, 20),
    "preparing": (20, 30),
    "predicting": (30, 90),
    "exporting": (90, 98),
}


class Reporter:
    """Throttled progress → backend (at most one POST per 2 s unless the stage changes)."""

    def __init__(self, backend: Backend, phases: dict[str, tuple[int, int]]) -> None:
        self.backend = backend
        self.phases = phases
        self.stage = "starting"
        self.last_sent = -1.0
        self.last_time = 0.0

    def set_stage(self, stage: str) -> None:
        self.stage = stage
        lo, _ = self.phases.get(stage, (0, 0))
        info(f"stage: {stage}")
        self._send(float(lo), force=True)

    def within(self, frac: float, sub_stage: str | None = None) -> None:
        lo, hi = self.phases.get(self.stage, (0, 100))
        self._send(lo + (hi - lo) * frac)

    def _send(self, progress: float, *, force: bool = False) -> None:
        now = time.monotonic()
        if not force and (progress - self.last_sent < 1 or now - self.last_time < 2):
            return
        self.last_sent, self.last_time = progress, now
        try:
            self.backend.status(progress=round(progress, 1), stage=self.stage)
        except Exception as e:  # progress is best effort
            warn(f"progress update failed: {e}")


def run(backend: Backend | None = None) -> int:
    env = Env.from_environ()
    zoo.force_offline()
    backend = backend or Backend(env.backend_url, env.job_id, env.token)
    work_dir = env.output_dir / "_work"
    work_dir.mkdir(parents=True, exist_ok=True)
    ctx = Context(work_dir=work_dir)

    def _on_term(signum, frame):
        ctx.cancelled = True
        raise Cancelled()

    signal.signal(signal.SIGTERM, _on_term)
    try:
        spec = backend.spec()
        res = spec.get("resources") or {}
        ctx.cpu = max(1, int(float(res.get("cpu") or 1)))
        ctx.gpu = int(res.get("gpu") or 0)
        limits.apply_from_env(ctx.cpu)  # clamp BLAS / OpenMP / torch pools to the grant, cap shared-GPU memory
        ctx.zoo = zoo.resolver(env.zoo_root, spec.get("zoo_weights") or {})
        info(
            f"job {spec['job_id']} kind={spec['kind']} project={spec['project_slug']} data_type={spec['data_type']} "
            f"task={spec.get('task_type')} mode={spec.get('mode')} family={spec.get('model_family')} "
            f"cpu={ctx.cpu} gpu={ctx.gpu} device={ctx.device}"
        )
        backend.status(status="running", progress=0, stage="starting")
        if spec["kind"] == "train":
            result, output_path = _train(spec, env, ctx, backend)
        else:
            result, output_path = _infer(spec, env, ctx, backend)
        backend.result(result=result, output_path=output_path)
        backend.status(status="succeeded", progress=100, stage="done")
        info("done")
        return 0
    except Cancelled:
        warn("cancelled by request; stopping")
        _safe(lambda: backend.status(status="failed", stage="cancelled", message="cancelled"))
        return 143
    except Exception as e:
        for line in traceback.format_exc().rstrip().splitlines():
            error(line)
        msg = f"{type(e).__name__}: {e}"[:2000]
        _safe(lambda: backend.status(status="failed", stage="failed", message=msg))
        return 1
    finally:
        shutil.rmtree(work_dir, ignore_errors=True)


def _safe(fn) -> None:
    try:
        fn()
    except Exception as e:
        warn(f"final status update failed: {e}")


# --- train --------------------------------------------------------------------------------------


def _fetch(spec: dict[str, Any], env: Env, reporter: Reporter) -> None:
    if spec["input"].get("kind") == "data_source":
        if not env.data_source:
            raise RuntimeError("job uses a data source but no DATA_SOURCE_* environment was provided")
        reporter.set_stage("fetching")
        fetch_data_source(env.data_source, env.input_dir, lambda f: reporter.within(f))


def _train(spec: dict[str, Any], env: Env, ctx: Context, backend: Backend) -> tuple[dict[str, Any], str | None]:
    reporter = Reporter(backend, TRAIN_PHASES)
    ctx.on_progress = reporter.within
    _fetch(spec, env, reporter)
    reporter.set_stage("preparing")
    ds = dataset.load(
        spec["data_type"],
        spec.get("task_type"),
        env.input_dir,
        spec["input"].get("spec") or {},
        ctx.work_dir,
    )
    if len(ds) == 0:
        raise ValueError("輸入資料沒有任何樣本")
    reporter.set_stage("training")
    deadline_s = spec["timeout_minutes"] * 60 * 0.85
    if spec.get("mode") == "auto":
        from trainer import automl

        trainer, summary = automl.run(spec, ds, ctx, backend, deadline_s=deadline_s)
    else:
        fid = spec["model_family"]
        fam = (spec.get("families") or {}).get(fid) or {}
        params = {
            **(fam.get("defaults") or {}),
            **{k: v for k, v in spec["config"].items() if k != "search"},
        }
        trainer = registry.create_trainer(fid, spec.get("task_type"), params, ctx)
        trainer.fit(ds)
        metrics = trainer.evaluate()
        backend.metrics(metrics)
        summary = {"family": fid, "params": params, "metrics": metrics}
    reporter.set_stage("exporting")
    trainer.finalize(ds)
    artifacts = trainer.export(env.output_dir)
    if ds.preprocess:
        model_dir = env.output_dir / "model"
        model_dir.mkdir(parents=True, exist_ok=True)
        (model_dir / "preprocess.json").write_text(json.dumps(ds.preprocess, ensure_ascii=False), encoding="utf-8")
    metrics_dir = env.output_dir / "metrics"
    metrics_dir.mkdir(parents=True, exist_ok=True)
    (metrics_dir / "metrics.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2, default=str), encoding="utf-8"
    )
    artifacts.append(
        ArtifactOut(name="metrics", kind="metrics", path="metrics/metrics.json", framework=trainer.framework)
    )
    registered = _register(backend, artifacts, family=summary["family"], ds=ds, trainer=trainer)
    result = {
        "model_family": summary["family"],
        "metrics": summary["metrics"],
        "params": summary.get("params"),
        "n_samples": len(ds),
        "artifacts": registered,
    }
    if "leaderboard" in summary:
        result.update({k: summary[k] for k in ("n_trials", "trial", "metric", "direction")})
    return result, "metrics/metrics.json"


def _register(
    backend: Backend,
    artifacts: list[ArtifactOut],
    *,
    family: str,
    ds=None,
    trainer: BaseTrainer | None = None,
) -> list[dict[str, Any]]:
    out = []
    for a in artifacts:
        meta = dict(a.metadata or {})
        if a.kind == "model":
            meta.setdefault("family", family)
            if trainer is not None and ds is not None:
                meta = {**trainer.metadata(ds), **meta}
        r = backend.artifact(
            name=a.name,
            kind=a.kind,
            path=a.path,
            framework=a.framework,
            metrics=a.metrics,
            metadata=meta or None,
            set_default=a.set_default,
        )
        info(f"artifact: {a.kind} {a.name} v{r.get('version')} ← {a.path}")
        out.append(
            {
                "id": r.get("id"),
                "kind": a.kind,
                "name": a.name,
                "version": r.get("version"),
                "path": a.path,
            }
        )
    return out


# --- inference ----------------------------------------------------------------------------------


def _infer(spec: dict[str, Any], env: Env, ctx: Context, backend: Backend) -> tuple[dict[str, Any], str | None]:
    reporter = Reporter(backend, INFER_PHASES)
    ctx.on_progress = reporter.within
    art = spec.get("artifact")
    if not art:
        raise RuntimeError("推論任務沒有指定模型")
    if env.model_dir is None:
        raise RuntimeError("model dir is not mounted")
    _fetch(spec, env, reporter)
    reporter.set_stage("loading")
    fid = art.get("model_family") or spec.get("model_family")
    meta = dict(art.get("metadata") or {})
    inferencer = registry.create_inferencer(fid, ctx)
    model_path = env.model_dir / art["file"]
    inferencer.load(model_path, meta)
    modes = meta.get("inference_modes") or ["predict"]
    mode = spec["config"].get("mode") or modes[0]
    info(f"model: {art['name']} v{art['version']} ({fid}) mode={mode}")
    reporter.set_stage("preparing")
    task = meta.get("task_type") or spec.get("task_type")
    state = meta.get("preprocess")
    if state is None:
        local = model_path / "preprocess.json"
        state = json.loads(local.read_text(encoding="utf-8")) if local.exists() else None
    ds = dataset.load(
        spec["data_type"],
        task,
        env.input_dir,
        {**(meta.get("spec") or {}), **(spec["input"].get("spec") or {})},
        ctx.work_dir,
        inline_rows=spec["input"].get("rows"),
        preprocess_state=state,
    )
    if len(ds) == 0:
        raise ValueError("輸入資料沒有任何樣本")
    reporter.set_stage("predicting")
    out_dir = env.output_dir / "output"
    out_dir.mkdir(parents=True, exist_ok=True)
    res = inferencer.predict(ds, mode, spec["config"], out_dir)
    reporter.set_stage("exporting")
    csv_path = out_dir / "predictions.csv"
    _write_rows(res.rows, csv_path)
    (out_dir / "summary.json").write_text(
        json.dumps(res.summary, ensure_ascii=False, indent=2, default=str), encoding="utf-8"
    )
    artifacts = [
        ArtifactOut(
            name=f"predictions-{spec['job_id']}",
            kind="report",
            path="output/predictions.csv",
            framework=art.get("framework") or "unknown",
        )
    ]
    artifacts += res.extra_artifacts
    registered = _register(backend, artifacts, family=fid)
    info(f"predictions: {len(res.rows)} rows → output/predictions.csv")
    result = {
        "mode": mode,
        "model_artifact_id": art["id"],
        **res.summary,
        "preview": res.rows[:20],
        "artifacts": registered,
    }
    return result, "output/predictions.csv"


def _write_rows(rows: list[dict[str, Any]], path: Path) -> None:
    keys: list[str] = []
    for r in rows:
        for k in r:
            if k not in keys:
                keys.append(k)
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=keys or ["id"])
        w.writeheader()
        for r in rows:
            w.writerow(
                {k: (json.dumps(v, ensure_ascii=False) if isinstance(v, (list, dict)) else v) for k, v in r.items()}
            )
    with path.with_suffix(".jsonl").open("w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False, default=str) + "\n")
