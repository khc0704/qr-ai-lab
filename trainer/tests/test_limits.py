"""The in-process resource clamp: thread pools follow the CPU grant, env knobs are set, GPU cap is parsed."""

from __future__ import annotations

import os

import numpy as np

from trainer import limits


def test_apply_clamps_threadpools_and_env(monkeypatch):
    monkeypatch.delenv("JOB_GPU_MEMORY_MB", raising=False)
    np.dot(np.ones((64, 64)), np.ones((64, 64)))  # make sure a BLAS is loaded
    lim = limits.apply(1)
    assert lim.cpu == 1
    assert os.environ["OMP_NUM_THREADS"] == "1" and os.environ["LOKY_MAX_CPU_COUNT"] == "1"
    assert all(v <= 1 for v in lim.threadpools.values()), lim.threadpools
    try:
        import torch

        assert torch.get_num_threads() == 1 and lim.torch_threads == 1
    except ImportError:
        pass
    from threadpoolctl import threadpool_info

    assert all(int(p.get("num_threads") or 0) <= 1 for p in threadpool_info())


def test_apply_respects_affinity_mask():
    lim = limits.apply(10_000)
    if lim.affinity is not None:
        assert lim.cpu == len(lim.affinity) and lim.notes
    assert os.environ["OMP_NUM_THREADS"] == str(lim.cpu)


def test_apply_from_env_parses_gpu_cap(monkeypatch):
    monkeypatch.setenv("JOB_GPU_MEMORY_MB", "4096")
    lim = limits.apply_from_env(2)
    assert lim.gpu_memory_mb == 4096 and lim.cpu >= 1
    monkeypatch.setenv("JOB_GPU_MEMORY_MB", "")
    assert limits.apply_from_env(2).gpu_memory_mb is None
