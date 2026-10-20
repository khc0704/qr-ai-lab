"""One job, start to finish: spec → fetch → load → train / infer → export → register → status.

Exit codes: 0 succeeded, 1 failed, 143 cancelled (SIGTERM).
"""

from __future__ import annotations

import csv
import json
import math
import os
import shutil
import signal
import time
import traceback
from pathlib import Path
from typing import Any

from trainer import dataset, jsonsafe, limits
from trainer.api_client import Backend
from trainer.config import Env
from trainer.fetch import fetch_data_source
from trainer.log import error, info, warn
from trainer.models import registry, zoo
from trainer.models.base import (
    PREPROCESS_STATE_FILE,
    ArtifactOut,
    BaseTrainer,
    Cancelled,
    Context,
    preprocess_state_is_complete,
)

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
        ctx.cpu = max(1, math.ceil(float(res.get("cpu") or 1)))  # the runner pins ceil(cpu) cores
        ctx.gpu = int(res.get("gpu") or 0)
        lim = limits.apply_from_env(ctx.cpu)  # clamp BLAS / OpenMP / torch pools to the grant, cap shared-GPU memory
        info(
            f"limits: dataloader workers={ctx.workers} (cpu={ctx.cpu}, memory={os.environ.get('JOB_MEMORY_MB') or '?'} "
            f"MB; gpu={ctx.gpu}; the main process needs ~{3 if ctx.gpu else 1.5} GB, each worker ~0.5–0.75 GB)"
        )
        ctx.gpu_memory_mb = lim.gpu_memory_mb
        ctx.zoo = zoo.resolver(env.zoo_root, spec.get("zoo_weights") or {})
        info(
            f"job {spec['job_id']} kind={spec['kind']} project={spec['project_slug']} data_type={spec['data_type']} "
            f"task={spec.get('task_type')} mode={spec.get('mode')} family={spec.get('model_family')} "
            f"cpu={ctx.cpu} gpu={ctx.gpu} device={ctx.device}"
        )
        backend.status(status="running", progress=0, stage="starting")
        if spec["kind"] == "train":
            result, output_path = _train(spec, env, ctx, backend)
        elif spec["kind"] == "preprocess":
            result, output_path = _preprocess(spec, env, ctx, backend)
        elif spec["kind"] == "analysis":
            result, output_path = _analysis(spec, env, ctx, backend)
        else:
            result, output_path = _infer(spec, env, ctx, backend)
        backend.result(result=result, output_path=output_path)
        backend.status(status="succeeded", progress=100, stage="done", retry="long")
        info("done")
        return 0
    except Cancelled:
        warn("cancelled by request; stopping")
        _safe(lambda: backend.status(status="failed", stage="cancelled", message="cancelled", retry="none"))
        return 143
    except Exception as e:
        for line in traceback.format_exc().rstrip().splitlines():
            error(line)
        msg = f"{type(e).__name__}: {e}"[:2000]
        _safe(lambda: backend.status(status="failed", stage="failed", message=msg, retry="short"))
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
    stopped: str | None = None
    if spec.get("mode") == "auto":
        from trainer import automl

        trainer, summary = automl.run(spec, ds, ctx, backend, deadline_s=deadline_s)
        stopped = summary.get("stopped")
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
        backend.metrics(metrics, retry="long")
        summary = {"family": fid, "params": params, "metrics": metrics}
    if stopped == "cancelled":
        info("stage: exporting (cancelled; salvaging the best model so far, no progress heartbeat)")
    else:
        reporter.set_stage("exporting")
    if stopped:
        warn(f"training stopped early ({stopped}): exporting the best model so far, skipping the final refit")
    else:
        trainer.finalize(ds)
    artifacts = trainer.export(env.output_dir)
    if ds.preprocess:
        model_dir = env.output_dir / "model"
        model_dir.mkdir(parents=True, exist_ok=True)
        (model_dir / PREPROCESS_STATE_FILE).write_text(json.dumps(ds.preprocess, ensure_ascii=False), encoding="utf-8")
    metrics_dir = env.output_dir / "metrics"
    metrics_dir.mkdir(parents=True, exist_ok=True)
    (metrics_dir / "metrics.json").write_text(jsonsafe.dumps(summary, indent=2, default=str), encoding="utf-8")
    artifacts.append(
        ArtifactOut(name="metrics", kind="metrics", path="metrics/metrics.json", framework=trainer.framework)
    )
    # cancelled: SIGTERM gives 10 s before SIGKILL, so the salvage is one attempt per call, best effort
    retry = "none" if stopped == "cancelled" else "long"
    result: dict[str, Any] = {
        "model_family": summary["family"],
        "metrics": summary["metrics"],
        "params": summary.get("params"),
        "n_samples": len(ds),
    }
    if "leaderboard" in summary:
        result.update({k: summary[k] for k in ("n_trials", "trial", "metric", "direction")})
    if stopped:
        result["stopped"] = stopped
    if stopped == "cancelled":
        try:
            result["artifacts"] = _register(
                backend, artifacts, family=summary["family"], ds=ds, trainer=trainer, retry=retry
            )
            backend.result(result=result, output_path="metrics/metrics.json", retry=retry)
            info("cancelled: best-so-far model registered")
        except Exception as e:  # the job is cancelled either way
            warn(f"cancelled: could not register the best-so-far model: {e}")
        raise Cancelled()
    result["artifacts"] = _register(backend, artifacts, family=summary["family"], ds=ds, trainer=trainer, retry=retry)
    return result, "metrics/metrics.json"


def _register(
    backend: Backend,
    artifacts: list[ArtifactOut],
    *,
    family: str,
    ds=None,
    trainer: BaseTrainer | None = None,
    retry: str = "long",
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
            retry=retry,
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


PREVIEW_ROWS = 20
EPHEMERAL_PREVIEW_ROWS = 500  # a one-off run shows its rows on the page instead of in a CSV artifact


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
    # the fitted preprocessing state travels with the model dir; artifact metadata only lists the steps
    state = meta.get("preprocess")
    local = model_path / PREPROCESS_STATE_FILE
    if local.exists():
        state = json.loads(local.read_text(encoding="utf-8"))
    elif not preprocess_state_is_complete(state):
        raise RuntimeError(f"模型缺少前處理狀態檔 model/{PREPROCESS_STATE_FILE}，無法重現訓練時的前處理")
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
    if local.exists():
        # a model produced by this run (e.g. few-shot `extend`) replays the same preprocessing as the one it extends:
        # copy the fitted state next to it, or the next inference fails with "模型缺少前處理狀態檔"
        for extra in res.extra_artifacts:
            new_dir = env.output_dir / extra.path
            if extra.kind == "model" and new_dir.is_dir() and not (new_dir / PREPROCESS_STATE_FILE).exists():
                shutil.copy2(local, new_dir / PREPROCESS_STATE_FILE)
    for n, row in enumerate(res.rows):  # lets the result page map a row back to the sample in the input file
        if isinstance(row, dict):
            row.setdefault("row_index", n)
    reporter.set_stage("exporting")
    csv_path = out_dir / "predictions.csv"
    _write_rows(res.rows, csv_path)
    (out_dir / "summary.json").write_text(jsonsafe.dumps(res.summary, indent=2, default=str), encoding="utf-8")
    ephemeral = bool(spec.get("ephemeral"))
    if ephemeral:
        # a one-off run: the rows go into the result for the page to show, nothing becomes a project artifact
        registered: list[dict[str, Any]] = []
        info(f"predictions: {len(res.rows)} rows (one-off: not registered as artifacts)")
    else:
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
        "preview": res.rows[: (EPHEMERAL_PREVIEW_ROWS if ephemeral else PREVIEW_ROWS)],
        "preview_truncated": len(res.rows) > (EPHEMERAL_PREVIEW_ROWS if ephemeral else PREVIEW_ROWS),
        "artifacts": registered,
    }
    return result, "output/predictions.csv"


# --- tool jobs: whole-file preprocessing and data exploration ---------------------------------------

TOOL_PHASES = {"preparing": (0, 10), "processing": (10, 85), "exporting": (85, 98)}


def _tool_input(spec: dict[str, Any], env: Env) -> Path:
    name = spec["input"].get("file")
    path = env.input_dir / name if name else None
    if path is None or not path.exists():
        candidates = [p for p in env.input_dir.iterdir() if p.is_file()] if env.input_dir.exists() else []
        if not candidates:
            raise RuntimeError("找不到輸入檔")
        path = candidates[0]
    return path


def _preprocess(spec: dict[str, Any], env: Env, ctx: Context, backend: Backend) -> tuple[dict[str, Any], str | None]:
    import shutil
    import zipfile

    from qrlab_preprocess.process import run_full

    reporter = Reporter(backend, TOOL_PHASES)
    reporter.set_stage("preparing")
    cfg = spec.get("config") or {}
    path = _tool_input(spec, env)
    steps = list(cfg.get("steps") or spec["input"].get("spec", {}).get("preprocess") or [])
    fmt = spec["input"].get("format") or path.suffix.lstrip(".")
    data_type = cfg.get("data_type") or spec["data_type"]
    in_spec = {k: v for k, v in (spec["input"].get("spec") or {}).items() if k != "preprocess"}
    info(f"preprocess: {data_type} {path.name} ({path.stat().st_size} bytes), {len(steps)} step(s)")
    work = ctx.work_dir / "preprocessed"
    reporter.set_stage("processing")
    summary = run_full(data_type, path, fmt, steps, work, spec=in_spec, task_type=cfg.get("task_type"))
    ctx.check()
    reporter.set_stage("exporting")
    out_dir = env.output_dir / "output"
    out_dir.mkdir(parents=True, exist_ok=True)
    zip_path = out_dir / "preprocessed.zip"
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as z:
        for p in sorted(work.rglob("*")):
            if p.is_file():
                z.write(p, p.relative_to(work).as_posix())
    shutil.rmtree(work, ignore_errors=True)
    (out_dir / "summary.json").write_text(jsonsafe.dumps(summary, indent=2, default=str), encoding="utf-8")
    for line in summary.get("steps") or []:
        info(f"step: {line}")
    info(
        f"result: output/preprocessed.zip ({zip_path.stat().st_size} bytes) "
        f"with {', '.join(summary.get('files') or [])}"
    )
    result = {**summary, "zip_size_bytes": zip_path.stat().st_size}
    return result, "output/preprocessed.zip"


def _analysis(spec: dict[str, Any], env: Env, ctx: Context, backend: Backend) -> tuple[dict[str, Any], str | None]:
    from trainer.analysis import image as image_analysis
    from trainer.analysis import tabular as tabular_analysis

    reporter = Reporter(backend, TOOL_PHASES)
    reporter.set_stage("preparing")
    cfg = spec.get("config") or {}
    kind = cfg.get("analysis")
    path = _tool_input(spec, env)
    in_spec = spec["input"].get("spec") or {}
    out_dir = env.output_dir / "output"
    out_dir.mkdir(parents=True, exist_ok=True)
    reporter.set_stage("processing")
    if kind == "tabular_profile":
        from qrlab_preprocess.process import _read_frame_all

        df = _read_frame_all(path, spec["input"].get("format") or "csv")
        target = cfg.get("target") or in_spec.get("target") or None
        ids = [
            c for c in (cfg.get("id_column") or in_spec.get("id_column"), cfg.get("id_columns")) if isinstance(c, str)
        ]
        info(f"tabular profile: {len(df)} rows × {df.shape[1]} columns, target={target or '-'}")
        report = tabular_analysis.profile(
            df, target=target, task=cfg.get("task_type"), id_columns=ids, n_jobs=ctx.cpu, progress=reporter.within
        )
        compact = tabular_analysis.compact(report)
        framework = "scikit-learn"
    elif kind == "image_quality":
        from trainer.data.image import materialize

        root = materialize(env.input_dir, ctx.work_dir)
        info(f"image quality: scanning {root}")
        report = image_analysis.quality_report(
            root,
            embedding=str(cfg.get("embedding") or "metrics"),
            backbone=str(cfg.get("backbone") or "dinov2-small"),
            ctx=ctx,
            progress=reporter.within,
        )
        compact = report
        framework = "numpy"
    else:
        raise ValueError(f"未知的分析 {kind}")
    ctx.check()
    reporter.set_stage("exporting")
    (out_dir / "report.json").write_text(jsonsafe.dumps(report, indent=2, default=str), encoding="utf-8")
    for r in report.get("recommendations") or []:
        info(f"{r.get('level', 'info')}: {r.get('text')}")
    registered = _register(
        backend,
        [ArtifactOut(name=f"analysis-{spec['job_id']}", kind="report", path="output/report.json", framework=framework)],
        family=f"analysis.{kind}",
    )
    result = {"analysis": kind, **compact, "artifacts": registered}
    return result, "output/report.json"


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
            w.writerow({k: (jsonsafe.dumps(v) if isinstance(v, (list, dict)) else v) for k, v in r.items()})
    with path.with_suffix(".jsonl").open("w", encoding="utf-8") as f:
        for r in rows:
            f.write(jsonsafe.dumps(r, default=str) + "\n")
