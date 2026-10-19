"""Deployment contracts: env templates, documented variables and the pip requirement exports must match the code."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from app.core.config import Settings

ROOT = Path(__file__).resolve().parents[2]
SYSTEMD_TEMPLATES = [ROOT / "infra/systemd/qrlab.env.example", ROOT / "infra/systemd/frontend.env.example"]
ENV_FILES = [*SYSTEMD_TEMPLATES, ROOT / "infra/.env.example"]
KEY_RE = re.compile(r"^#?\s*([A-Z][A-Z0-9_]*)=")


def _keys(path: Path) -> set[str]:
    """KEY=… lines, including commented-out examples (# KEY=…)."""
    return {m.group(1) for line in path.read_text().splitlines() if (m := KEY_RE.match(line))}


def test_env_templates_have_no_inline_comments():
    """systemd's EnvironmentFile (and docker compose) keep a trailing `# comment` as part of the value."""
    bad = [
        f"{p.name}:{n}: {line}"
        for p in ENV_FILES
        for n, line in enumerate(p.read_text().splitlines(), 1)
        if re.match(r"^[A-Za-z_][A-Za-z0-9_]*=.*\s#", line)
    ]
    assert not bad, "\n".join(bad)


def test_backend_settings_match_templates_and_docs():
    fields = {name.upper() for name in Settings.model_fields}
    dev = _keys(ROOT / "backend/.env.example")
    prod = _keys(ROOT / "infra/systemd/qrlab.env.example")
    documented = set(re.findall(r"`([A-Z][A-Z0-9_]+)`", (ROOT / "docs/ENVIRONMENT.md").read_text()))
    assert fields - prod == set(), f"settings missing from infra/systemd/qrlab.env.example: {sorted(fields - prod)}"
    assert fields - dev == set(), f"settings missing from backend/.env.example: {sorted(fields - dev)}"
    assert fields - documented == set(), f"settings missing from docs/ENVIRONMENT.md: {sorted(fields - documented)}"
    assert prod - fields == set(), f"unknown variables in qrlab.env.example (dead settings?): {sorted(prod - fields)}"
    assert dev - fields == set(), f"unknown variables in backend/.env.example: {sorted(dev - fields)}"


def test_frontend_env_reads_are_in_template_and_docs():
    src = ROOT / "frontend/src"
    reads: set[str] = set()
    for f in [*src.rglob("*.ts"), *src.rglob("*.tsx")]:
        reads |= set(re.findall(r"process\.env\.([A-Z][A-Z0-9_]+)", f.read_text()))
    reads -= {"NODE_ENV"}  # set by `next start`
    template = _keys(ROOT / "infra/systemd/frontend.env.example") | _keys(ROOT / "frontend/.env.local.example")
    documented = set(re.findall(r"`([A-Z][A-Z0-9_]+)`", (ROOT / "docs/ENVIRONMENT.md").read_text()))
    assert reads - template == set(), f"frontend reads not in any env template: {sorted(reads - template)}"
    assert reads - documented == set(), f"frontend reads not documented: {sorted(reads - documented)}"


def _pins(path: Path) -> dict[str, str]:
    pins: dict[str, str] = {}
    for line in path.read_text().splitlines():
        line = line.strip()
        if "==" in line and not line.startswith(("#", "-")):
            name, _, version = line.partition("==")
            pins[re.sub(r"[-_.]+", "-", name.split("[")[0]).lower()] = version.split(";")[0].strip()
    return pins


def _declared(pyproject: Path, extras: tuple[str, ...]) -> set[str]:
    import tomllib

    data = tomllib.loads(pyproject.read_text())["project"]
    specs = list(data["dependencies"]) + [d for e in extras for d in data.get("optional-dependencies", {}).get(e, [])]
    return {re.sub(r"[-_.]+", "-", re.split(r"[<>=!~\[; ]", spec, maxsplit=1)[0]).lower() for spec in specs}


@pytest.mark.parametrize(("subdir", "extras"), [("backend", ("gpu",)), ("trainer", ("dl",))])
def test_requirements_cover_pyproject(subdir: str, extras: tuple[str, ...]):
    """pip installs requirements*.txt (no uv): every declared dependency must be pinned there, and the dev file must
    carry the runtime pins unchanged (scripts/pin_requirements.sh regenerates both)."""
    runtime = _pins(ROOT / subdir / "requirements.txt")
    dev = _pins(ROOT / subdir / "requirements-dev.txt")
    torch_file = ROOT / subdir / "requirements-torch.txt"
    if torch_file.exists():  # torch is pinned apart (CUDA flavour depends on the host driver)
        runtime |= _pins(torch_file)
        dev |= _pins(torch_file)
        banned = [k for k in runtime if k.startswith(("nvidia-", "triton", "cuda-")) and k != "nvidia-ml-py"]
        assert not banned, f"{subdir}: CUDA wheels must not be pinned (they come with torch): {banned}"
    declared = _declared(ROOT / subdir / "pyproject.toml", extras)
    missing = sorted(declared - set(runtime))
    assert not missing, f"{subdir}: not pinned in requirements.txt: {missing}"
    drift = {k: (v, dev.get(k)) for k, v in runtime.items() if dev.get(k) != v}
    assert not drift, f"{subdir}: requirements-dev.txt disagrees with requirements.txt: {drift}"
    for f in ("requirements.txt", "requirements-dev.txt"):
        assert "-e ../libs/preprocess" in (ROOT / subdir / f).read_text(), f"{subdir}/{f}: no libs/preprocess line"
    assert {"pytest", "ruff"} <= set(dev), f"{subdir}: dev tools missing from requirements-dev.txt"


def test_nothing_uses_uv():
    """The project is installed with pip everywhere (dev, CI, server)."""
    for name in ("install-00-base.sh", "install-01-docker.sh", "install-02-backend.sh", "install-03-frontend.sh"):
        script = (ROOT / "infra" / name).read_text()
        assert "uv " not in script, name
    assert "requirements.txt" in (ROOT / "infra/install-02-backend.sh").read_text()
    assert not (ROOT / "backend/uv.lock").exists() and not (ROOT / "trainer/uv.lock").exists()
    ci = (ROOT / ".github/workflows/ci.yml").read_text()
    assert "uv" not in ci.replace("ubuntu", "")


def test_source_packages_are_not_gitignored():
    """`.gitignore` has broad rules (data/, runs/ …); none of them may swallow a Python package (trainer/trainer/data
    went missing from the repo this way)."""
    import subprocess

    pkgs = [
        p
        for root in ("backend/app", "trainer/trainer", "libs/preprocess/qrlab_preprocess")
        for p in (ROOT / root).rglob("__init__.py")
        if "__pycache__" not in p.parts
    ]
    assert pkgs
    rel = [str(p.relative_to(ROOT)) for p in pkgs]
    res = subprocess.run(["git", "check-ignore", "--no-index", *rel], cwd=ROOT, capture_output=True, text=True)
    assert res.stdout.strip() == "", f"gitignored source packages: {res.stdout}"


def test_torch_requirements_carry_their_index():
    """The torch index is written inside the requirements files (a file-level --index-url overrides the CLI flag, so a
    flag on the command line is not needed and would be ignored); the CPU twin must pin the same versions."""
    gpu = ROOT / "trainer/requirements-torch.txt"
    cpu = ROOT / "trainer/requirements-torch-cpu.txt"
    idx = {p: [ln.split()[1] for ln in p.read_text().splitlines() if ln.startswith("--index-url ")] for p in (gpu, cpu)}
    assert idx[gpu] == ["https://download.pytorch.org/whl/cu126"], idx
    assert idx[cpu] == ["https://download.pytorch.org/whl/cpu"], idx
    assert _pins(gpu) == _pins(cpu) and {"torch", "torchvision"} <= set(_pins(gpu))
