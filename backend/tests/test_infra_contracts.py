"""Deployment contracts: env templates, documented variables and the pip requirement exports must match the code."""

from __future__ import annotations

import re
import shutil
import subprocess
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


def _normalize(text: str) -> list[str]:
    return [line.strip() for line in text.splitlines() if line.strip() and not line.lstrip().startswith("#")]


@pytest.mark.parametrize(("subdir", "extra"), [("backend", "gpu"), ("trainer", "dl")])
def test_requirements_export_matches_lockfile(subdir: str, extra: str):
    """The server installs requirements.txt with pip; it must be the lockfile (scripts/export_requirements.sh)."""
    if shutil.which("uv") is None:
        pytest.skip("uv not installed")
    out = subprocess.run(
        ["uv", "export", "--frozen", "--no-dev", "--no-hashes", "--extra", extra],  # stdout (never "-o -")
        cwd=ROOT / subdir,
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    committed = (ROOT / subdir / "requirements.txt").read_text()
    assert _normalize(out) == _normalize(committed), f"run scripts/export_requirements.sh ({subdir} drifted)"


def test_install_script_uses_pip_not_uv():
    script = (ROOT / "infra/install.sh").read_text()
    assert "uv sync" not in script and "requirements.txt" in script
