"""AutoML: Optuna over the candidate families' search spaces, sequential trials, median pruning, time budget."""

from __future__ import annotations

import time
from typing import Any

from trainer.dataset import Dataset
from trainer.log import info, warn
from trainer.models import registry
from trainer.models.base import BaseTrainer, Cancelled, Context, Pruned


def _sample(trial, fid: str, space: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for name, d in space.items():
        key = f"{fid}.{name}"
        t = d.get("type")
        if t == "float":
            out[name] = trial.suggest_float(key, float(d["low"]), float(d["high"]), log=bool(d.get("log", False)))
        elif t == "int":
            out[name] = trial.suggest_int(key, int(d["low"]), int(d["high"]), log=bool(d.get("log", False)))
        elif t == "categorical":
            out[name] = trial.suggest_categorical(key, list(d["choices"]))
    return out


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

    study = optuna.create_study(
        direction=direction,
        sampler=optuna.samplers.TPESampler(seed=42),
        pruner=optuna.pruners.MedianPruner(n_startup_trials=3, n_warmup_steps=2),
    )
    info(
        f"automl: candidates={candidates} metric={metric} ({direction}) "
        f"max_trials={max_trials} budget={budget_s / 60:g}min"
    )
    outer_progress = ctx.on_progress
    best: dict[str, Any] = {"value": None}
    rows: list[dict[str, Any]] = []
    done = 0
    try:
        for i in range(max_trials):
            if time.monotonic() > deadline:
                info("automl: time budget reached")
                break
            trial = study.ask()
            fid = trial.suggest_categorical("family", candidates)
            fam = families.get(fid) or {}
            params = {
                **(fam.get("defaults") or {}),
                **_sample(trial, fid, fam.get("search_space") or {}),
                **user_overrides,
            }
            trainer = registry.create_trainer(fid, task, params, ctx)
            ctx.on_progress = _scoped_progress(outer_progress, i, max_trials)
            ctx.on_epoch = _pruning_hook(trial, metric)
            t0 = time.monotonic()
            try:
                trainer.fit(ds)
                m = trainer.evaluate()
                value = m.get(metric)
                if value is None:
                    value = next(iter(m.values()))
                study.tell(trial, float(value))
            except Pruned:
                study.tell(trial, state=optuna.trial.TrialState.PRUNED)
                info(f"trial {i + 1}/{max_trials} {fid} pruned")
                continue
            except Cancelled:
                raise
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
            backend.metrics(m, trial=i, leaderboard_row=row)
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
    if best.get("trainer") is None:
        raise RuntimeError("AutoML 沒有任何成功的 trial，請檢查資料與欄位設定")
    rows.sort(key=lambda r: r["metric"], reverse=(direction == "maximize"))
    info(f"automl: best trial {best['trial'] + 1} {best['family']} {metric}={best['value']:.4f} ({done} trials)")
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
