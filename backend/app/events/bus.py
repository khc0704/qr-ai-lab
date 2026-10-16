"""Job event bus: Redis streams in production, in-process queues for dev/tests.

Event = {"id": stream id, "type": status|progress|metric|log|end, "ts": iso, "data": {...}}
"""

from __future__ import annotations

import asyncio
import json
import time
from collections import defaultdict, deque
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Any, Protocol

from app.core.config import get_settings

MAXLEN = 10_000
REPLAY = 200


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


class EventBus(Protocol):
    async def publish(self, job_id: int, type_: str, data: dict[str, Any]) -> str: ...
    async def replay(self, job_id: int, limit: int = REPLAY) -> list[dict[str, Any]]: ...
    async def last_id(self, job_id: int) -> str | None: ...
    def subscribe(self, job_id: int, last_id: str | None = None) -> AsyncIterator[dict[str, Any]]: ...
    async def forget(self, job_id: int) -> None: ...
    async def close(self) -> None: ...


KEEPALIVE_S = 15  # below nginx's default 60 s proxy_read_timeout
STREAM_TTL_S = 7 * 24 * 3600  # a finished job's stream disappears from Redis after a week


class MemoryEventBus:
    def __init__(self) -> None:
        self._buffers: dict[int, deque[dict[str, Any]]] = defaultdict(lambda: deque(maxlen=MAXLEN))
        self._queues: dict[int, list[asyncio.Queue[dict[str, Any]]]] = defaultdict(list)
        self._seq = 0

    async def publish(self, job_id: int, type_: str, data: dict[str, Any]) -> str:
        self._seq += 1
        ev = {"id": f"{int(time.time() * 1000)}-{self._seq}", "type": type_, "ts": _now_iso(), "data": data}
        self._buffers[job_id].append(ev)
        for q in list(self._queues[job_id]):
            q.put_nowait(ev)
        return ev["id"]

    async def replay(self, job_id: int, limit: int = REPLAY) -> list[dict[str, Any]]:
        return list(self._buffers[job_id])[-limit:]

    async def last_id(self, job_id: int) -> str | None:
        buf = self._buffers.get(job_id)
        return buf[-1]["id"] if buf else None

    async def subscribe(self, job_id: int, last_id: str | None = None) -> AsyncIterator[dict[str, Any]]:
        q: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        self._queues[job_id].append(q)
        try:
            for ev in await self.replay(job_id):
                if last_id is None or _after(ev["id"], last_id):
                    yield ev
                    if ev["type"] == "end":
                        return
            while True:
                try:
                    ev = await asyncio.wait_for(q.get(), timeout=KEEPALIVE_S)
                except TimeoutError:
                    yield {"id": last_id or "0-0", "type": "keepalive", "ts": _now_iso(), "data": {}}
                    continue
                yield ev
                if ev["type"] == "end":
                    return
        finally:
            self._queues[job_id].remove(q)

    async def forget(self, job_id: int) -> None:
        self._buffers.pop(job_id, None)

    async def close(self) -> None:
        return None


def _after(event_id: str, last_id: str) -> bool:
    """Stream ids are "<ms>-<seq>"; compare numerically (string order breaks across digit counts)."""

    def key(v: str) -> tuple[int, int]:
        ms, _, seq = v.partition("-")
        try:
            return int(ms), int(seq or 0)
        except ValueError:
            return (0, 0)

    return key(event_id) > key(last_id)


class RedisEventBus:
    def __init__(self, url: str) -> None:
        import redis.asyncio as redis

        self._r = redis.from_url(url, decode_responses=True)

    @staticmethod
    def _key(job_id: int) -> str:
        return f"job:{job_id}:events"

    async def publish(self, job_id: int, type_: str, data: dict[str, Any]) -> str:
        key = self._key(job_id)
        sid = await self._r.xadd(
            key,
            {"type": type_, "ts": _now_iso(), "data": json.dumps(data, ensure_ascii=False)},
            maxlen=MAXLEN,
            approximate=True,
        )
        if type_ == "end":
            await self._r.expire(key, STREAM_TTL_S)  # streams are per job; without a TTL Redis grows forever
        return sid

    async def last_id(self, job_id: int) -> str | None:
        rows = await self._r.xrevrange(self._key(job_id), count=1)
        return rows[0][0] if rows else None

    async def forget(self, job_id: int) -> None:
        await self._r.delete(self._key(job_id))

    @staticmethod
    def _decode(sid: str, fields: dict[str, str]) -> dict[str, Any]:
        return {"id": sid, "type": fields["type"], "ts": fields["ts"], "data": json.loads(fields["data"])}

    async def replay(self, job_id: int, limit: int = REPLAY) -> list[dict[str, Any]]:
        rows = await self._r.xrevrange(self._key(job_id), count=limit)
        return [self._decode(sid, f) for sid, f in reversed(rows)]

    async def subscribe(self, job_id: int, last_id: str | None = None) -> AsyncIterator[dict[str, Any]]:
        cursor = last_id
        if cursor is None:
            for ev in await self.replay(job_id):
                yield ev
                cursor = ev["id"]
                if ev["type"] == "end":
                    return
            cursor = cursor or "0-0"
        while True:
            rows = await self._r.xread({self._key(job_id): cursor}, block=KEEPALIVE_S * 1000, count=100)
            if not rows:
                yield {"id": cursor, "type": "keepalive", "ts": _now_iso(), "data": {}}
                continue
            for _key, entries in rows:
                for sid, fields in entries:
                    ev = self._decode(sid, fields)
                    cursor = sid
                    yield ev
                    if ev["type"] == "end":
                        return

    async def close(self) -> None:
        await self._r.aclose()


_bus: EventBus | None = None


def get_bus() -> EventBus:
    global _bus
    if _bus is None:
        url = get_settings().redis_url
        _bus = RedisEventBus(url) if url else MemoryEventBus()
    return _bus


def reset_bus() -> None:
    global _bus
    _bus = None
