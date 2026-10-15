"""stdout is the job log file: one line per event, `<UTC iso>Z [LEVEL] text` (the scheduler tails the file and
the UI parses the prefix). The timestamp is written here because the trainer now writes the file itself."""

from __future__ import annotations

import sys
from datetime import UTC, datetime


def log(level: str, text: str) -> None:
    ts = datetime.now(UTC).replace(tzinfo=None).isoformat(timespec="milliseconds")
    print(f"{ts}Z [{level}] {text}", flush=True, file=sys.stdout)


def info(text: str) -> None:
    log("INFO", text)


def warn(text: str) -> None:
    log("WARN", text)


def error(text: str) -> None:
    log("ERROR", text)
