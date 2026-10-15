"""Job runners: DockerRunner (GPU server) and SubprocessRunner (dev / CPU families without docker)."""

from __future__ import annotations

import asyncio
import contextlib
import os
import sys
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol


@dataclass
class LaunchSpec:
    job_id: int
    kind: str
    image: str
    env: dict[str, str]
    input_dir: Path
    output_dir: Path
    model_dir: Path | None
    zoo_dir: Path | None
    host_input_dir: Path
    host_output_dir: Path
    host_model_dir: Path | None
    host_zoo_dir: Path | None
    gpus: list[int] = field(default_factory=list)
    cpu: float = 1.0
    memory_mb: int = 2048
    network: str | None = None
    input_writable: bool = False  # data_source jobs download into /job/input; uploads stay read-only


@dataclass
class RunState:
    running: bool
    exit_code: int | None


class Runner(Protocol):
    async def start(self, spec: LaunchSpec) -> str: ...
    async def inspect(self, handle: str) -> RunState: ...
    async def stop(self, handle: str, grace: int = 10) -> None: ...
    def logs(self, handle: str) -> AsyncIterator[str]: ...
    async def find(self, job_id: int) -> str | None: ...
    async def remove(self, handle: str) -> None: ...


class DockerRunner:
    """Each job is a hardened container: read-only rootfs, no capabilities, its own input/output mounts only."""

    def __init__(self) -> None:
        import docker

        self.client = docker.from_env()

    async def start(self, spec: LaunchSpec) -> str:
        def _start() -> str:
            from docker.types import DeviceRequest

            volumes = {
                str(spec.host_input_dir): {"bind": "/job/input", "mode": "rw" if spec.input_writable else "ro"},
                str(spec.host_output_dir): {"bind": "/job/output", "mode": "rw"},
            }
            if spec.host_model_dir:
                volumes[str(spec.host_model_dir)] = {"bind": "/job/model", "mode": "ro"}
            if spec.host_zoo_dir:
                volumes[str(spec.host_zoo_dir)] = {"bind": "/job/zoo", "mode": "ro"}
            kwargs: dict = {
                "image": spec.image,
                "command": ["python", "-m", "trainer", "run"],
                "environment": spec.env,
                "detach": True,
                "volumes": volumes,
                "nano_cpus": int(spec.cpu * 1e9),
                "mem_limit": f"{spec.memory_mb}m",
                "memswap_limit": f"{spec.memory_mb}m",
                "read_only": True,
                "tmpfs": {"/tmp": "size=4g"},
                "cap_drop": ["ALL"],
                "security_opt": ["no-new-privileges"],
                "user": "1000:1000",
                "labels": {"qr-ai-lab.job_id": str(spec.job_id), "qr-ai-lab.kind": spec.kind},
                "name": f"qr-job-{spec.job_id}",
                "shm_size": "2g",
            }
            if spec.network:
                kwargs["network"] = spec.network
            if spec.gpus:
                ids = [str(g) for g in spec.gpus]
                kwargs["device_requests"] = [DeviceRequest(device_ids=ids, capabilities=[["gpu"]])]
            return self.client.containers.run(**kwargs).id

        return await asyncio.to_thread(_start)

    async def inspect(self, handle: str) -> RunState:
        def _inspect() -> RunState:
            from docker.errors import NotFound

            try:
                c = self.client.containers.get(handle)
            except NotFound:
                return RunState(False, None)
            c.reload()
            st = c.attrs["State"]
            return RunState(bool(st.get("Running")), None if st.get("Running") else st.get("ExitCode"))

        return await asyncio.to_thread(_inspect)

    async def stop(self, handle: str, grace: int = 10) -> None:
        def _stop() -> None:
            from docker.errors import NotFound

            with contextlib.suppress(NotFound):
                self.client.containers.get(handle).stop(timeout=grace)

        await asyncio.to_thread(_stop)

    async def logs(self, handle: str) -> AsyncIterator[str]:
        loop = asyncio.get_running_loop()
        queue: asyncio.Queue[str | None] = asyncio.Queue()

        def _pump() -> None:
            try:
                c = self.client.containers.get(handle)
                for chunk in c.logs(stream=True, follow=True, stdout=True, stderr=True):
                    for line in chunk.decode("utf-8", errors="replace").splitlines():
                        loop.call_soon_threadsafe(queue.put_nowait, line)
            except Exception as e:
                loop.call_soon_threadsafe(queue.put_nowait, f"[ERROR] log stream ended: {e}")
            finally:
                loop.call_soon_threadsafe(queue.put_nowait, None)

        task = loop.run_in_executor(None, _pump)
        while True:
            line = await queue.get()
            if line is None:
                break
            yield line
        await task

    async def find(self, job_id: int) -> str | None:
        def _find() -> str | None:
            cs = self.client.containers.list(all=True, filters={"label": f"qr-ai-lab.job_id={job_id}"})
            return cs[0].id if cs else None

        return await asyncio.to_thread(_find)

    async def remove(self, handle: str) -> None:
        def _rm() -> None:
            from docker.errors import NotFound

            with contextlib.suppress(NotFound):
                self.client.containers.get(handle).remove(force=True)

        await asyncio.to_thread(_rm)


class SubprocessRunner:
    """Runs `python -m trainer run` from the trainer checkout (its own venv if present). Dev only, no isolation."""

    def __init__(self, trainer_dir: Path) -> None:
        self.trainer_dir = trainer_dir.resolve()
        self.procs: dict[str, asyncio.subprocess.Process] = {}

    def _python(self) -> str:
        venv = self.trainer_dir / ".venv" / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
        return str(venv) if venv.exists() else sys.executable

    async def start(self, spec: LaunchSpec) -> str:
        env = {
            **os.environ,
            **spec.env,
            "JOB_INPUT_DIR": str(spec.input_dir),
            "JOB_OUTPUT_DIR": str(spec.output_dir),
            "JOB_MODEL_DIR": str(spec.model_dir or ""),
            "MODEL_ZOO_ROOT": str(spec.zoo_dir or ""),
            "PYTHONUNBUFFERED": "1",
        }
        proc = await asyncio.create_subprocess_exec(
            self._python(),
            "-m",
            "trainer",
            "run",
            cwd=self.trainer_dir,
            env=env,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
        handle = f"pid:{proc.pid}"
        self.procs[handle] = proc
        return handle

    async def inspect(self, handle: str) -> RunState:
        proc = self.procs.get(handle)
        if proc is None:
            return RunState(False, None)
        return RunState(proc.returncode is None, proc.returncode)

    async def stop(self, handle: str, grace: int = 10) -> None:
        proc = self.procs.get(handle)
        if proc is None or proc.returncode is not None:
            return
        proc.terminate()
        try:
            await asyncio.wait_for(proc.wait(), timeout=grace)
        except TimeoutError:
            proc.kill()

    async def logs(self, handle: str) -> AsyncIterator[str]:
        proc = self.procs.get(handle)
        if proc is None or proc.stdout is None:
            return
        while True:
            raw = await proc.stdout.readline()
            if not raw:
                break
            yield raw.decode("utf-8", errors="replace").rstrip("\r\n")
        await proc.wait()

    async def find(self, job_id: int) -> str | None:
        return None  # child processes do not survive a scheduler restart

    async def remove(self, handle: str) -> None:
        self.procs.pop(handle, None)
