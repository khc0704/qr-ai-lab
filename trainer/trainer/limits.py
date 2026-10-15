"""Make the resource grant stick inside the job process.

The scheduler already limits the process from the outside (cgroup cpuset / CPUQuota / MemoryMax, or
sched_setaffinity + a memory watchdog) and sets every *_NUM_THREADS variable before Python starts. Native
libraries that size their pools from ``os.cpu_count()`` instead of the affinity mask (OpenMP in scikit-learn's
TSNE / HistGradientBoosting, OpenBLAS, MKL, torch intra-op) would still spin up one thread per physical core
and then fight over the few cores they are pinned to. ``apply`` clamps them from the inside and logs what is
in effect so the job log shows the real limits.

GPU: when the scheduler shares a GPU (JOB_GPU_MEMORY_MB), the process caps its CUDA caching allocator with
``torch.cuda.set_per_process_memory_fraction`` so one job cannot grow into the other job's share.
"""

from __future__ import annotations

import contextlib
import os
from dataclasses import dataclass, field

from trainer.log import info, warn


@dataclass
class Limits:
    cpu: int
    affinity: list[int] | None = None
    gpu_memory_mb: int | None = None
    threadpools: dict[str, int] = field(default_factory=dict)
    torch_threads: int | None = None
    gpu_fractions: dict[int, float] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)


def _affinity() -> list[int] | None:
    try:
        return sorted(os.sched_getaffinity(0))  # type: ignore[attr-defined]
    except (AttributeError, OSError):
        return None


def apply(cpu: int, gpu_memory_mb: int | None = None) -> Limits:
    cpu = max(1, int(cpu))
    lim = Limits(cpu=cpu, affinity=_affinity(), gpu_memory_mb=gpu_memory_mb)
    if lim.affinity is not None and len(lim.affinity) < cpu:
        lim.notes.append(f"affinity mask has {len(lim.affinity)} cores, below the grant of {cpu}; using the mask")
        cpu = max(1, len(lim.affinity))
        lim.cpu = cpu
    # Thread-pool knobs for libraries imported later (the scheduler sets these too; a direct `python -m trainer`
    # run or a unit test would otherwise inherit the machine size).
    for var in (
        "OMP_NUM_THREADS",
        "MKL_NUM_THREADS",
        "OPENBLAS_NUM_THREADS",
        "BLIS_NUM_THREADS",
        "VECLIB_MAXIMUM_THREADS",
        "NUMEXPR_NUM_THREADS",
        "NUMEXPR_MAX_THREADS",
        "TBB_NUM_THREADS",
        "NUMBA_NUM_THREADS",
        "RAYON_NUM_THREADS",
        "POLARS_MAX_THREADS",
        "LOKY_MAX_CPU_COUNT",
    ):
        os.environ[var] = str(cpu)
    # Libraries already loaded (numpy / scipy / scikit-learn pull in OpenBLAS / OpenMP at import) are clamped
    # through threadpoolctl; the limit stays in effect for the rest of the process.
    try:
        from threadpoolctl import threadpool_info, threadpool_limits

        threadpool_limits(limits=cpu)
        for pool in threadpool_info():
            key = f"{pool.get('user_api')}/{pool.get('internal_api')}"
            lim.threadpools[key] = int(pool.get("num_threads") or 0)
    except Exception as e:  # threadpoolctl is a scikit-learn dependency; never fail a job over it
        lim.notes.append(f"threadpoolctl unavailable: {e}")
    try:
        import torch

        torch.set_num_threads(cpu)
        with contextlib.suppress(RuntimeError):  # already started a parallel region; the env var covers it
            torch.set_num_interop_threads(1)
        lim.torch_threads = torch.get_num_threads()
        if gpu_memory_mb and torch.cuda.is_available():
            for i in range(torch.cuda.device_count()):
                total_mb = torch.cuda.get_device_properties(i).total_memory / 2**20
                frac = max(0.05, min(1.0, gpu_memory_mb / total_mb))
                torch.cuda.set_per_process_memory_fraction(frac, i)
                lim.gpu_fractions[i] = round(frac, 3)
    except ImportError:
        pass
    except Exception as e:
        lim.notes.append(f"torch limits: {e}")
    return lim


def apply_from_env(cpu: int) -> Limits:
    raw = os.environ.get("JOB_GPU_MEMORY_MB") or ""
    gpu_mb = int(raw) if raw.isdigit() else None
    lim = apply(cpu, gpu_mb)
    aff = f"{len(lim.affinity)} cores {lim.affinity}" if lim.affinity is not None else "n/a"
    pools = ", ".join(f"{k}={v}" for k, v in sorted(lim.threadpools.items())) or "none loaded"
    info(f"limits: cpu={lim.cpu} affinity={aff} threadpools[{pools}] torch_threads={lim.torch_threads}")
    if gpu_mb:
        info(
            f"limits: gpu memory cap {gpu_mb} MB per visible GPU"
            + (f" → fractions {lim.gpu_fractions}" if lim.gpu_fractions else " (no CUDA device visible)")
        )
    for n in lim.notes:
        warn(f"limits: {n}")
    return lim
