"""Dedicated thread pools for work that must not starve the default executor."""

from __future__ import annotations

import asyncio
import functools
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from typing import Any

# Previews run on their own small pool: a runaway preview (huge zip entry, pathological regex) must not exhaust the
# pool everything else shares (log reads, hashing, uploads).
PREVIEW_POOL = ThreadPoolExecutor(max_workers=2, thread_name_prefix="preview")


def in_preview_pool[T](fn: Callable[..., T], *args: Any, **kwargs: Any) -> asyncio.Future[T]:
    return asyncio.get_running_loop().run_in_executor(PREVIEW_POOL, functools.partial(fn, *args, **kwargs))
