""".venv/bin/python -m app.scheduler"""

from __future__ import annotations

import asyncio

from app.core.config import get_settings
from app.core.logging import setup_logging
from app.scheduler.loop import Scheduler


def main() -> None:
    s = get_settings()
    setup_logging(s.log_level)
    s.data_root.mkdir(parents=True, exist_ok=True)
    asyncio.run(Scheduler().run_forever())


if __name__ == "__main__":
    main()
