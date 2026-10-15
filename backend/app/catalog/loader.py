"""Loads model_catalog.yaml, validates family/task compatibility and expands AutoML candidates."""

from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

CATALOG_PATH = Path(__file__).with_name("model_catalog.yaml")


@lru_cache
def load_catalog() -> dict[str, Any]:
    with CATALOG_PATH.open(encoding="utf-8") as f:
        return yaml.safe_load(f)


def family(fid: str) -> dict[str, Any]:
    fam = load_catalog()["families"].get(fid)
    if not fam:
        raise KeyError(fid)
    return fam


def supports(fid: str, data_type: str, task_type: str) -> bool:
    try:
        return task_type in family(fid)["supports"].get(data_type, [])
    except KeyError:
        return False


def families_for(data_type: str, task_type: str) -> list[str]:
    return [fid for fid in load_catalog()["families"] if supports(fid, data_type, task_type)]


def needs_gpu(fid: str) -> bool:
    return family(fid)["resources"].get("gpu") == "required"


def task_metric(task_type: str) -> tuple[str, str]:
    t = load_catalog()["tasks"][task_type]
    return t["metrics"][0], t["direction"]


_RULE = re.compile(r"^(row_count)\s*(<|>|<=|>=)\s*(\d+)$")


def _rule_matches(expr: str, ctx: dict[str, Any]) -> bool:
    m = _RULE.match(expr.strip())
    if not m:
        return False
    key, op, num = m.group(1), m.group(2), int(m.group(3))
    v = ctx.get(key)
    if v is None:
        return False
    return {"<": v < num, ">": v > num, "<=": v <= num, ">=": v >= num}[op]


def automl_search(data_type: str, task_type: str, spec: dict[str, Any] | None) -> dict[str, Any]:
    """Candidate families + budget + metric for mode=auto. Deterministic so the trainer only follows it."""
    ctx = {"row_count": (spec or {}).get("row_count") or (spec or {}).get("image_count")}
    for entry in load_catalog()["automl"]:
        if entry["data_type"] != data_type or task_type not in entry["tasks"]:
            continue
        candidates = list(entry["candidates"])
        for rule in entry.get("rules", []):
            if _rule_matches(rule["if"], ctx):
                for d in rule.get("drop", []):
                    if d in candidates:
                        candidates.remove(d)
                for p in reversed(rule.get("prefer", [])):
                    if p in candidates:
                        candidates.remove(p)
                        candidates.insert(0, p)
        metric, direction = task_metric(task_type)
        return {"candidates": candidates, "metric": metric, "direction": direction, **entry["budget"]}
    raise ValueError(f"no automl candidates for {data_type}/{task_type}")


def required_weights() -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for fid, fam in load_catalog()["families"].items():
        for w in fam.get("weights", []):
            if w["id"] in seen:
                continue
            seen.add(w["id"])
            out.append({**w, "family": fid})
    return out


def public_catalog() -> dict[str, Any]:
    """Catalog without the download sources (the UI does not need them)."""
    cat = load_catalog()
    fams = {
        fid: {k: v for k, v in fam.items() if k != "weights"} | {"weights": [w["id"] for w in fam.get("weights", [])]}
        for fid, fam in cat["families"].items()
    }
    return {
        "version": cat["version"],
        "data_types": cat["data_types"],
        "tasks": cat["tasks"],
        "families": fams,
        "automl": cat["automl"],
    }
