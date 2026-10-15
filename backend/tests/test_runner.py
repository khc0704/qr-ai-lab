"""Host-process runners: the subprocess runner (process group, affinity, log file, re-attach) and the systemd
runner (argv with cgroup properties, unit lookup) with a stand-in trainer and stand-in systemd binaries."""

from __future__ import annotations

import asyncio
import os
import stat
import textwrap
from pathlib import Path

import psutil
import pytest

from app.core.config import get_settings
from app.scheduler.loop import Scheduler
from app.scheduler.runner import LaunchSpec, SubprocessRunner, SystemdRunner, job_env
from tests.conftest import make_data_source, make_project

FAKE_TRAINER = """
import os, sys, time
mode = os.environ.get("FAKE_MODE", "ok")
print("[INFO] fake trainer start", flush=True)
if mode == "hog":
    blob = bytearray(300 * 1024 * 1024)   # ~300 MB resident
    for i in range(0, len(blob), 4096):
        blob[i] = 1
    print("[INFO] allocated 300 MB", flush=True)
    time.sleep(30)
elif mode == "sleep":
    time.sleep(30)
print("[INFO] fake trainer done", flush=True)
"""


def make_fake_trainer(tmp: Path) -> Path:
    pkg = tmp / "trainer"
    pkg.mkdir(parents=True)
    (pkg / "__init__.py").write_text("")
    (pkg / "__main__.py").write_text(textwrap.dedent(FAKE_TRAINER))
    return tmp


def spec_for(tmp: Path, job_id: int = 1, **kw) -> LaunchSpec:
    out = tmp / "out"
    out.mkdir(exist_ok=True)
    return LaunchSpec(
        job_id=job_id,
        kind="train",
        env=kw.pop("env", {}),
        input_dir=tmp / "in",
        output_dir=out,
        model_dir=None,
        zoo_dir=None,
        log_path=out / "job.log",
        gpus=kw.pop("gpus", []),
        cpus=kw.pop("cpus", []),
        cpu=kw.pop("cpu", 1.0),
        memory_mb=kw.pop("memory_mb", 512),
        timeout_s=60,
    )


def test_job_env_is_offline_and_thread_limited(tmp_path):
    spec = spec_for(tmp_path, cpu=2.5, gpus=[1], env={"JOB_ID": "7"})
    env = job_env(spec, base={})
    assert env["HF_HUB_OFFLINE"] == "1" and env["YOLO_OFFLINE"] == "1" and env["WANDB_DISABLED"] == "true"
    assert env["OMP_NUM_THREADS"] == "3" and env["CUDA_VISIBLE_DEVICES"] == "1" and env["JOB_ID"] == "7"
    assert env["JOB_OUTPUT_DIR"] == str(spec.output_dir)


async def test_subprocess_runner_writes_log_sets_affinity_and_reattaches(tmp_path):
    runner = SubprocessRunner(make_fake_trainer(tmp_path), Path(os.sys.executable))
    cores = sorted(os.sched_getaffinity(0))[:1]
    spec = spec_for(tmp_path, cpus=cores, env={"FAKE_MODE": "sleep"})
    handle = await runner.start(spec)
    assert handle.startswith("pid:")
    pid = int(handle.split(":")[1])
    await asyncio.sleep(0.5)
    assert psutil.Process(pid).cpu_affinity() == cores
    assert "fake trainer start" in spec.log_path.read_text()
    assert (await runner.inspect(handle)).running
    assert pid in runner.pids(handle)
    # a fresh runner (as after a scheduler restart) finds the same process from the stored handle
    other = SubprocessRunner(tmp_path, Path(os.sys.executable))
    assert await other.find(1, handle) == handle
    assert (await other.inspect(handle)).running
    await other.stop(handle, grace=2)
    assert not (await other.inspect(handle)).running
    assert await other.find(1, handle) is None
    await runner.remove(handle)


async def test_subprocess_runner_exit_code(tmp_path):
    runner = SubprocessRunner(make_fake_trainer(tmp_path), Path(os.sys.executable))
    spec = spec_for(tmp_path, env={"FAKE_MODE": "ok"})
    handle = await runner.start(spec)
    for _ in range(50):
        st = await runner.inspect(handle)
        if not st.running:
            break
        await asyncio.sleep(0.1)
    assert not st.running and st.exit_code == 0
    assert "fake trainer done" in spec.log_path.read_text()


async def test_memory_watchdog_stops_a_job_over_its_grant(client, admin, user, tmp_path, monkeypatch):
    """subprocess runner cannot enforce memory, so the scheduler's watchdog must: 300 MB used vs 128 MB granted."""
    project = await make_project(client, admin, user)
    slug = project["slug"]
    await client.patch(
        f"/api/v1/projects/{slug}/quota",
        json={"gpu_limit": 0, "cpu_limit": 4, "memory_limit_mb": 8192, "max_concurrent_jobs": 1},
        headers=admin,
    )
    ds = await make_data_source(client, user, slug)
    body = {
        "kind": "train",
        "name": "hog",
        "mode": "manual",
        "model_family": "tabular.linear",
        "input": {"kind": "data_source", "data_source_id": ds["id"], "spec": {"target": "yield_pct"}},
        "requested_gpu": 0,
        "requested_cpu": 1,
        "requested_memory_mb": 1024,
    }
    job = (await client.post(f"/api/v1/projects/{slug}/jobs", json=body, headers=user)).json()
    runner = SubprocessRunner(make_fake_trainer(tmp_path), Path(os.sys.executable))
    monkeypatch.setenv("FAKE_MODE", "hog")
    settings = get_settings().model_copy(update={"memory_watchdog": True})
    sched = Scheduler(runner=runner, settings=settings)
    await sched.tick()
    active = sched.active[job["id"]]
    # pretend the grant was 128 MB: the watchdog compares the process tree against job.requested_memory_mb
    from app.db.session import get_sessionmaker
    from app.models import Job

    async with get_sessionmaker()() as s:
        j = await s.get(Job, job["id"])
        j.requested_memory_mb = 128
        await s.commit()
    stopped = False
    for _ in range(40):
        await asyncio.sleep(0.5)
        await sched.tick()
        if job["id"] not in sched.active:
            stopped = True
            break
    assert stopped, "watchdog did not stop the job"
    r = (await client.get(f"/api/v1/jobs/{job['id']}", headers=user)).json()
    assert r["status"] == "failed" and "memory limit exceeded" in r["error_message"]
    text = "\n".join((await client.get(f"/api/v1/jobs/{job['id']}/logs", headers=user)).json()["lines"])
    assert "exceeds the grant" in text and "peak memory" in text
    assert active.peak_memory_mb >= 200


def _fake_systemd(bin_dir: Path) -> None:
    """systemd-run that records its arguments and execs the command; systemctl that answers is-active/stop."""
    bin_dir.mkdir(parents=True, exist_ok=True)
    run = bin_dir / "systemd-run"
    run.write_text(
        "#!/bin/sh\n"
        'printf "%s\\n" "$@" > "$FAKE_SYSTEMD_LOG"\n'
        'while [ "$1" != "--" ]; do shift; done\nshift\nexec "$@"\n'
    )
    ctl = bin_dir / "systemctl"
    ctl.write_text('#!/bin/sh\ncase "$*" in *is-active*) exit 0;; *stop*) exit 0;; esac\nexit 0\n')
    for f in (run, ctl):
        f.chmod(f.stat().st_mode | stat.S_IEXEC)


async def test_systemd_runner_builds_cgroup_scope(tmp_path, monkeypatch):
    bin_dir = tmp_path / "bin"
    _fake_systemd(bin_dir)
    monkeypatch.setenv("PATH", f"{bin_dir}:{os.environ['PATH']}")
    monkeypatch.setenv("FAKE_SYSTEMD_LOG", str(tmp_path / "systemd-run.args"))
    runner = SystemdRunner(make_fake_trainer(tmp_path), Path(os.sys.executable), user=True)
    runner.enforcement.cpuset = True
    spec = spec_for(tmp_path, job_id=42, cpus=[0, 1], cpu=1.5, memory_mb=3072, env={"FAKE_MODE": "ok"})
    argv = runner.argv(spec)
    assert argv[:3] == ["systemd-run", "--scope", "--quiet"] and "--unit=qrlab-job-42.scope" in argv
    props = {argv[i + 1] for i, a in enumerate(argv) if a == "-p"}
    assert {"MemoryMax=3072M", "MemorySwapMax=0", "CPUQuota=150%", "AllowedCPUs=0,1", "RuntimeMaxSec=60"} <= props
    handle = await runner.start(spec)
    assert handle.startswith("scope:qrlab-job-42.scope:")
    args_file = tmp_path / "systemd-run.args"
    for _ in range(50):  # the stand-in writes its argv right after exec; give it a moment
        if args_file.exists():
            break
        await asyncio.sleep(0.05)
    recorded = args_file.read_text().split("\n")
    assert "MemoryMax=3072M" in recorded
    for _ in range(100):
        st = await runner.inspect(handle)
        if not st.running:
            break
        await asyncio.sleep(0.1)
    assert st.exit_code == 0 and "fake trainer done" in spec.log_path.read_text()
    # unit lookup goes through systemctl (the fake says active)
    assert await runner.find(42, handle) == handle
    assert await runner.find(42, "pid:1:0") is None


@pytest.mark.skipif(os.name == "nt", reason="posix only")
def test_detect_cgroup_controllers_handles_missing_files():
    from app.scheduler.runner import detect_cgroup_controllers

    enf = detect_cgroup_controllers(user=True)
    assert set(enf.as_dict()) == {"memory", "cpu", "cpuset"}
