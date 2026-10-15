"""stdout is the job log: the scheduler parses the [LEVEL] prefix."""

from __future__ import annotations

import sys


def log(level: str, text: str) -> None:
    print(f"[{level}] {text}", flush=True, file=sys.stdout)


def info(text: str) -> None:
    log("INFO", text)


def warn(text: str) -> None:
    log("WARN", text)


def error(text: str) -> None:
    log("ERROR", text)
