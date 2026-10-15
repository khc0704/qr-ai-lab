"""Job runners: every job is `python -m trainer run` from the trainer venv on this host.

- SystemdRunner (Linux, default when available): the process tree lives in a transient systemd scope, so the
  kernel enforces MemoryMax / CPUQuota / AllowedCPUs (cgroups v2) and `systemctl stop` kills every child.
- SubprocessRunner (fallback, also dev on macOS / WSL without systemd): its own process group, CPU affinity to the
  assigned cores, and the scheduler's memory watchdog instead of a kernel limit.

Both write the child's stdout straight into the job log file (the scheduler tails it), so a scheduler restart
neither kills the job nor loses its log: the handle `pid:<pid>:<create_time>` / `scope:<unit>:<pid>` is enough
to find the process again.
"""

from __future__ import annotations

import asyncio
import contextlib
import math
import os
import shutil
import signal
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

import psutil

from app.core.logging import get_logger

log = get_logger("runner")

# Set for every job: weights come from the model zoo only, nothing phones home, threads follow the CPU grant.
OFFLINE_ENV = {
    "HF_HUB_OFFLINE": "1",
    "TRANSFORMERS_OFFLINE": "1",
    "HF_DATASETS_OFFLINE": "1",
    "HF_HUB_DISABLE_TELEMETRY": "1",
    "YOLO_OFFLINE": "1",
    "NO_ALBUMENTATIONS_UPDATE": "1",
    "WANDB_DISABLED": "true",
    "WANDB_MODE": "disabled",
    "MLFLOW_TRACKING_URI": "",
    "PYTHONUNBUFFERED": "1",
}


@dataclass
class LaunchSpec:
    job_id: int
    kind: str
    env: dict[str, str]
    input_dir: Path
    output_dir: Path
    model_dir: Path | None
    zoo_dir: Path | None
    log_path: Path
    gpus: list[int] = field(default_factory=list)
    cpus: list[int] = field(default_factory=list)  # logical CPUs granted to this job (affinity / cpuset)
    cpu: float = 1.0
    memory_mb: int = 2048
    timeout_s: int | None = None


@dataclass
class RunState:
    running: bool
    exit_code: int | None


@dataclass
class Enforcement:
    """What the runner can enforce by itself (the scheduler's watchdog covers the rest)."""

    memory: bool = False
    cpu: bool = False
    cpuset: bool = False

    def as_dict(self) -> dict[str, bool]:
        return {"memory": self.memory, "cpu": self.cpu, "cpuset": self.cpuset}


class Runner(Protocol):
    kind: str
    enforcement: Enforcement

    async def start(self, spec: LaunchSpec) -> str: ...
    async def inspect(self, handle: str) -> RunState: ...
    async def stop(self, handle: str, grace: int = 10) -> None: ...
    async def find(self, job_id: int, handle: str | None) -> str | None: ...
    async def remove(self, handle: str) -> None: ...
    def pids(self, handle: str) -> list[int]: ...


def trainer_python(trainer_dir: Path, override: Path | None = None) -> str:
    if override:
        return str(override)
    venv = trainer_dir / ".venv" / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    return str(venv) if venv.exists() else sys.executable


def job_env(spec: LaunchSpec, base: dict[str, str] | None = None) -> dict[str, str]:
    threads = str(max(1, math.ceil(spec.cpu)))
    return {
        **(base if base is not None else os.environ),
        **OFFLINE_ENV,
        "OMP_NUM_THREADS": threads,
        "MKL_NUM_THREADS": threads,
        "OPENBLAS_NUM_THREADS": threads,
        "TORCH_NUM_THREADS": threads,
        "CUDA_VISIBLE_DEVICES": ",".join(str(g) for g in spec.gpus) if spec.gpus else "",
        **spec.env,
        "JOB_INPUT_DIR": str(spec.input_dir),
        "JOB_OUTPUT_DIR": str(spec.output_dir),
        "JOB_MODEL_DIR": str(spec.model_dir or ""),
        "MODEL_ZOO_ROOT": str(spec.zoo_dir or ""),
    }


def _proc_matches(pid: int, create_time: float) -> psutil.Process | None:
    try:
        p = psutil.Process(pid)
        if abs(p.create_time() - create_time) < 2 and p.status() != psutil.STATUS_ZOMBIE:
            return p
    except psutil.Error:
        return None
    return None


def _kill_tree(root: psutil.Process, sig: int) -> None:
    procs = [root, *root.children(recursive=True)]
    for p in procs:
        with contextlib.suppress(psutil.Error):
            p.send_signal(sig)


class SubprocessRunner:
    """Process group + CPU affinity; memory is watched by the scheduler (no kernel limit)."""

    kind = "subprocess"

    def __init__(self, trainer_dir: Path, python: Path | None = None) -> None:
        self.trainer_dir = trainer_dir.resolve()
        self.python = trainer_python(self.trainer_dir, python)
        self.procs: dict[str, asyncio.subprocess.Process] = {}
        self.enforcement = Enforcement(memory=False, cpu=False, cpuset=hasattr(psutil.Process, "cpu_affinity"))

    def argv(self, spec: LaunchSpec) -> list[str]:
        return [self.python, "-m", "trainer", "run"]

    async def start(self, spec: LaunchSpec) -> str:
        spec.log_path.parent.mkdir(parents=True, exist_ok=True)
        with spec.log_path.open("ab") as out:
            proc = await asyncio.create_subprocess_exec(
                *self.argv(spec),
                cwd=self.trainer_dir,
                env=job_env(spec),
                stdout=out,
                stderr=subprocess.STDOUT,
                stdin=subprocess.DEVNULL,
                start_new_session=True,  # its own process group / session: killpg reaches DataLoader workers
            )
        self._apply_affinity(proc.pid, spec.cpus)
        try:
            create_time = psutil.Process(proc.pid).create_time()
        except psutil.Error:
            create_time = 0.0
        handle = f"pid:{proc.pid}:{int(create_time)}"
        self.procs[handle] = proc
        return handle

    def _apply_affinity(self, pid: int, cpus: list[int]) -> None:
        if not cpus or not self.enforcement.cpuset:
            return
        try:
            psutil.Process(pid).cpu_affinity(cpus)
        except (psutil.Error, OSError, ValueError) as e:
            log.warning("cpu affinity not applied", pid=pid, cpus=cpus, error=repr(e))

    @staticmethod
    def _parse(handle: str) -> tuple[int, float]:
        _, pid, ct = handle.split(":", 2)
        return int(pid), float(ct)

    def _process(self, handle: str) -> psutil.Process | None:
        pid, ct = self._parse(handle)
        return _proc_matches(pid, ct)

    def pids(self, handle: str) -> list[int]:
        p = self._process(handle)
        if p is None:
            return []
        return [p.pid, *(c.pid for c in p.children(recursive=True))]

    async def inspect(self, handle: str) -> RunState:
        proc = self.procs.get(handle)
        if proc is not None:
            if proc.returncode is None:
                # reap without blocking; returncode is set once the child exits
                with contextlib.suppress(TimeoutError):
                    await asyncio.wait_for(proc.wait(), timeout=0)
            return RunState(proc.returncode is None, proc.returncode)
        # re-attached after a scheduler restart: alive or not, exit code unknown (the trainer reports its own status)
        return RunState(self._process(handle) is not None, None)

    async def stop(self, handle: str, grace: int = 10) -> None:
        p = self._process(handle)
        if p is None:
            return
        try:
            os.killpg(p.pid, signal.SIGTERM)
        except (ProcessLookupError, PermissionError, AttributeError):
            _kill_tree(p, signal.SIGTERM)
        deadline = asyncio.get_running_loop().time() + grace
        while asyncio.get_running_loop().time() < deadline:
            if self._process(handle) is None:
                break
            await asyncio.sleep(0.25)
        else:
            try:
                os.killpg(p.pid, signal.SIGKILL)
            except (ProcessLookupError, PermissionError, AttributeError):
                _kill_tree(p, signal.SIGKILL)
        proc = self.procs.get(handle)
        if proc is not None:
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(proc.wait(), timeout=5)

    async def find(self, job_id: int, handle: str | None) -> str | None:
        if not handle or not handle.startswith("pid:"):
            return None
        return handle if self._process(handle) is not None else None

    async def remove(self, handle: str) -> None:
        self.procs.pop(handle, None)


class SystemdRunner(SubprocessRunner):
    """`systemd-run --scope` puts the job in its own cgroup so the kernel enforces the limits."""

    kind = "systemd"

    def __init__(self, trainer_dir: Path, python: Path | None = None, *, user: bool = True) -> None:
        super().__init__(trainer_dir, python)
        self.user = user
        self.enforcement = detect_cgroup_controllers(user=user)
        self.enforcement.cpuset = self.enforcement.cpuset or hasattr(psutil.Process, "cpu_affinity")

    def _ctl(self) -> list[str]:
        return ["systemctl", "--user"] if self.user else ["systemctl"]

    @staticmethod
    def unit(job_id: int) -> str:
        return f"qrlab-job-{job_id}.scope"

    def argv(self, spec: LaunchSpec) -> list[str]:
        props = [
            f"MemoryMax={spec.memory_mb}M",
            "MemorySwapMax=0",
            f"CPUQuota={max(1, round(spec.cpu * 100))}%",
            "TasksMax=8192",
        ]
        if spec.cpus and self.enforcement.cpuset:
            props.append("AllowedCPUs=" + ",".join(str(c) for c in spec.cpus))
        if spec.timeout_s:
            props.append(f"RuntimeMaxSec={spec.timeout_s}")
        cmd = ["systemd-run", "--scope", "--quiet", "--collect", f"--unit={self.unit(spec.job_id)}"]
        if self.user:
            cmd.append("--user")
        for p in props:
            cmd += ["-p", p]
        cmd.append("--")
        return cmd + super().argv(spec)

    async def start(self, spec: LaunchSpec) -> str:
        pid_handle = await super().start(spec)
        handle = pid_handle.replace("pid:", f"scope:{self.unit(spec.job_id)}:", 1)
        self.procs[handle] = self.procs.pop(pid_handle)
        return handle

    @staticmethod
    def _parse(handle: str) -> tuple[int, float]:
        _, _unit, pid, ct = handle.split(":", 3)
        return int(pid), float(ct)

    def _unit_of(self, handle: str) -> str:
        return handle.split(":", 3)[1]

    async def _is_active(self, unit: str) -> bool:
        proc = await asyncio.create_subprocess_exec(
            *self._ctl(), "is-active", "--quiet", unit, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
        )
        return await proc.wait() == 0

    async def inspect(self, handle: str) -> RunState:
        proc = self.procs.get(handle)
        if proc is not None:
            if proc.returncode is None:
                with contextlib.suppress(TimeoutError):
                    await asyncio.wait_for(proc.wait(), timeout=0)
            return RunState(proc.returncode is None, proc.returncode)
        return RunState(await self._is_active(self._unit_of(handle)), None)

    async def stop(self, handle: str, grace: int = 10) -> None:
        unit = self._unit_of(handle)
        proc = await asyncio.create_subprocess_exec(
            *self._ctl(), "stop", "--no-block", unit, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
        )
        await proc.wait()
        await super().stop(handle, grace)

    async def find(self, job_id: int, handle: str | None) -> str | None:
        if not handle or not handle.startswith("scope:"):
            return None
        if await self._is_active(self._unit_of(handle)) or self._process(handle) is not None:
            return handle
        return None


def detect_cgroup_controllers(*, user: bool = True) -> Enforcement:
    """Which cgroup v2 controllers systemd can apply to our transient scopes."""
    try:
        if user:
            uid = os.getuid()
            path = Path(f"/sys/fs/cgroup/user.slice/user-{uid}.slice/user@{uid}.service/cgroup.subtree_control")
        else:
            path = Path("/sys/fs/cgroup/system.slice/cgroup.subtree_control")
        controllers = set(path.read_text().split())
    except OSError:
        controllers = set()
    return Enforcement(memory="memory" in controllers, cpu="cpu" in controllers, cpuset="cpuset" in controllers)


def systemd_available(*, user: bool = True) -> bool:
    """Can this process start transient scopes? (systemd running, user manager up, systemd-run on PATH)"""
    if os.name == "nt" or shutil.which("systemd-run") is None:
        return False
    cmd = ["systemd-run", "--scope", "--quiet", "--collect", "-p", "MemoryMax=64M"]
    if user:
        cmd.append("--user")
    cmd += ["--", "/bin/true"]
    try:
        return subprocess.run(cmd, capture_output=True, timeout=10).returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False
