"""AutoML: Optuna over the candidate families' search spaces, sequential trials, median pruning, time budget.

The search stops early, keeping the best trainer so far, when the time budget / job deadline passes mid-trial
(``TrialTimeout`` from ``ctx.epoch`` / ``ctx.progress``) or when the job is cancelled (SIGTERM) after at least
one trial finished; ``summary["stopped"]`` tells the runtime why.
"""

from __future__ import annotations

import time
from typing import Any

from trainer.dataset import Dataset
from trainer.log import info, warn
from trainer.models import registry
from trainer.models.base import BaseTrainer, Cancelled, Context, Pruned, TrialTimeout

# metrics every family reports without ground truth (anomaly scores on the holdout, reconstruction loss)
LABEL_FREE_METRICS = frozenset({"score_mean", "score_std", "flagged_ratio", "threshold", "val_loss", "loss"})


YOLO_SUFFIX = {"detection": "", "segmentation": "-seg", "classification": "-cls"}


def weight_id(fid: str, task: str | None, name: str, value: Any) -> str | None:
    """The zoo weight a categorical choice stands for (``backbone`` → itself; YOLO ``model`` → + task suffix)."""
    if name == "backbone":
        return str(value)
    if name == "model" and fid == "vision.yolo":
        return f"{value}{YOLO_SUFFIX.get(task or 'detection', '')}"
    return None


def available_choices(ctx: Context, fid: str, task: str | None, name: str, choices: list[Any]) -> list[Any]:
    """Drop the choices whose pretrained weight is not in the zoo (a family is a candidate as soon as one of its
    alternatives is present; sampling a missing one would just burn a trial). Everything else passes through;
    if nothing is left the original list is kept so the trial fails with the usual "weight missing" message."""
    if ctx.zoo is None:
        return choices
    kept = []
    for c in choices:
        wid = weight_id(fid, task, name, c)
        if wid is None:
            kept.append(c)
            continue
        try:
            ctx.zoo(wid)
        except FileNotFoundError:
            continue
        kept.append(c)
    if len(kept) < len(choices):
        info(f"automl: {fid}.{name} limited to {kept or choices} (weights in the zoo)")
    return kept or choices


def _release_previous_trial() -> None:
    """Free the previous trial's model (host and GPU memory) before the next one starts: the trainer objects
    are dropped, but torch keeps cached blocks and Python keeps cycles until asked."""
    import gc

    gc.collect()
    try:
        import torch

        if torch.cuda.is_available():
            torch.cuda.empty_cache()
    except ImportError:
        pass


def _sample(
    trial, fid: str, space: dict[str, Any], task: str | None = None, ctx: Context | None = None
) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for name, d in space.items():
        key = f"{fid}.{name}"
        t = d.get("type")
        if t == "float":
            out[name] = trial.suggest_float(key, float(d["low"]), float(d["high"]), log=bool(d.get("log", False)))
        elif t == "int":
            out[name] = trial.suggest_int(key, int(d["low"]), int(d["high"]), log=bool(d.get("log", False)))
        elif t == "categorical":
            choices = list(d["choices"])
            if ctx is not None:
                choices = available_choices(ctx, fid, task, name, choices)
            out[name] = trial.suggest_categorical(key, choices)
    return out


def check_metric_available(metric: str, ds: Dataset, task: str | None, candidates: list[str]) -> None:
    """Fail before the first trial when the search metric cannot be computed on this data (it needs labels the
    dataset does not have), instead of silently ranking trials by whatever metric came first."""
    if metric in LABEL_FREE_METRICS:
        return
    hint = f"請改用手動模式指定單一模型（候選：{', '.join(candidates)}）"
    if task == "anomaly_detection":
        from trainer.models.tabular import _binary_anomaly_labels

        if not ds.has_labels or set(_binary_anomaly_labels(ds.y).tolist()) != {0, 1}:
            raise ValueError(
                f"AutoML 的評分指標 {metric} 需要「正常」與「異常」兩種標籤才能計算，"
                "但這份異常偵測資料沒有標籤（或只有一類）。"
                f"{hint}，或提供含標籤的資料（good / normal 與異常資料夾、或標籤欄位）。"
            )
        return
    if not ds.has_labels:
        raise ValueError(f"AutoML 的評分指標 {metric} 需要標籤，但資料沒有標籤欄位。{hint}，或補上標籤再訓練。")


def run(
    spec: dict[str, Any], ds: Dataset, ctx: Context, backend, *, deadline_s: float | None = None
) -> tuple[BaseTrainer, dict[str, Any]]:
    import optuna

    optuna.logging.set_verbosity(optuna.logging.WARNING)
    search = spec["config"]["search"]
    candidates: list[str] = list(search["candidates"])
    metric: str = search["metric"]
    direction: str = search.get("direction", "maximize")
    max_trials = int(search.get("max_trials", 10))
    budget_s = float(search.get("time_budget_minutes", 60)) * 60
    deadline = time.monotonic() + (min(budget_s, deadline_s) if deadline_s else budget_s)
    task = spec["task_type"]
    families: dict[str, Any] = spec.get("families") or {}
    user_overrides = {k: v for k, v in spec["config"].items() if k != "search"}
    check_metric_available(metric, ds, task, candidates)

    study = optuna.create_study(
        direction=direction,
        sampler=optuna.samplers.TPESampler(seed=42),
        pruner=optuna.pruners.MedianPruner(n_startup_trials=3, n_warmup_steps=2),
    )
    info(
        f"automl: candidates={candidates} metric={metric} ({direction}) "
        f"max_trials={max_trials} budget={budget_s / 60:g}min deadline={(deadline - time.monotonic()) / 60:.1f}min"
    )
    outer_progress = ctx.on_progress
    best: dict[str, Any] = {"value": None}
    rows: list[dict[str, Any]] = []
    done = 0
    stopped: str | None = None
    ctx.deadline = deadline
    try:
        for i in range(max_trials):
            if time.monotonic() > deadline:
                info("automl: time budget reached")
                stopped = "deadline"
                break
            trial = study.ask()
            fid = trial.suggest_categorical("family", candidates)
            fam = families.get(fid) or {}
            params = {
                **(fam.get("defaults") or {}),
                **_sample(trial, fid, fam.get("search_space") or {}, task, ctx),
                **user_overrides,
            }
            _release_previous_trial()
            trainer = registry.create_trainer(fid, task, params, ctx)
            ctx.on_progress = _scoped_progress(outer_progress, i, max_trials)
            ctx.on_epoch = _pruning_hook(trial, metric)
            t0 = time.monotonic()
            try:
                trainer.fit(ds)
                m = trainer.evaluate()
                value = m.get(metric)
                if value is None:
                    study.tell(trial, state=optuna.trial.TrialState.FAIL)
                    warn(f"trial {i + 1}/{max_trials} {fid} 沒有回報指標 {metric}（只有 {sorted(m)}），不計入")
                    continue
                study.tell(trial, float(value))
            except TrialTimeout:
                study.tell(trial, state=optuna.trial.TrialState.PRUNED)
                warn(f"trial {i + 1}/{max_trials} {fid} 超過時間上限，停止搜尋（{time.monotonic() - t0:.0f}s）")
                stopped = "deadline"
                break
            except Pruned:
                study.tell(trial, state=optuna.trial.TrialState.PRUNED)
                info(f"trial {i + 1}/{max_trials} {fid} pruned")
                continue
            except Cancelled:
                if best.get("trainer") is None:
                    raise
                warn(f"trial {i + 1}/{max_trials} {fid} 被中斷；保留目前最佳模型")
                stopped = "cancelled"
                break
            except Exception as e:
                study.tell(trial, state=optuna.trial.TrialState.FAIL)
                warn(f"trial {i + 1}/{max_trials} {fid} failed: {e!r}")
                continue
            finally:
                ctx.on_epoch = None
            dt = time.monotonic() - t0
            done += 1
            row = {
                "trial": i,
                "family": fid,
                "params": _plain(params),
                "metric": float(value),
                "metrics": m,
                "seconds": round(dt, 1),
            }
            rows.append(row)
            try:
                backend.metrics(m, trial=i, leaderboard_row=row)
            except Exception as e:  # a lost leaderboard row must not fail the job
                warn(f"leaderboard row for trial {i + 1} not delivered: {e}")
            info(f"trial {i + 1}/{max_trials} {fid} {metric}={float(value):.4f} ({dt:.1f}s) {_short(params)}")
            if best["value"] is None or _better(float(value), best["value"], direction):
                best = {
                    "value": float(value),
                    "trainer": trainer,
                    "family": fid,
                    "params": params,
                    "trial": i,
                    "metrics": m,
                }
    finally:
        ctx.on_progress = outer_progress
        ctx.on_epoch = None
        ctx.deadline = None
    if best.get("trainer") is None:
        if stopped == "deadline":
            raise RuntimeError("AutoML 在時間上限內沒有完成任何 trial，請拉長時間上限或改用手動模式")
        raise RuntimeError("AutoML 沒有任何成功的 trial，請檢查資料與欄位設定")
    rows.sort(key=lambda r: r["metric"], reverse=(direction == "maximize"))
    info(
        f"automl: best trial {best['trial'] + 1} {best['family']} {metric}={best['value']:.4f} ({done} trials"
        + (f", stopped: {stopped}" if stopped else "")
        + ")"
    )
    summary = {
        "family": best["family"],
        "params": _plain(best["params"]),
        "metrics": best["metrics"],
        "trial": best["trial"],
        "n_trials": done,
        "metric": metric,
        "direction": direction,
        "leaderboard": rows[:20],
    }
    if stopped:
        summary["stopped"] = stopped
    return best["trainer"], summary


def _better(a: float, b: float, direction: str) -> bool:
    return a > b if direction == "maximize" else a < b


def _scoped_progress(outer, i: int, n: int):
    def hook(frac: float, stage: str | None) -> None:
        if outer:
            outer((i + frac) / n, stage)

    return hook


def _pruning_hook(trial, metric: str):
    def hook(epoch: int, m: dict[str, float]) -> None:
        value = m.get(metric)
        if value is None:
            return
        trial.report(float(value), epoch)
        if trial.should_prune():
            raise Pruned()

    return hook


def _plain(params: dict[str, Any]) -> dict[str, Any]:
    return {k: (v if isinstance(v, (int, float, str, bool, type(None))) else str(v)) for k, v in params.items()}


def _short(params: dict[str, Any]) -> str:
    parts = []
    for k, v in params.items():
        parts.append(f"{k}={v:.4g}" if isinstance(v, float) else f"{k}={v}")
    return " ".join(parts)[:300]
