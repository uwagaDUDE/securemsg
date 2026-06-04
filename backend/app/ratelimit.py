import asyncio
import json
import time
from collections import defaultdict

from sqlalchemy import delete, select

from .database import async_session
from .models import RateLimitEntry


class RateLimiter:
    def __init__(self):
        self._store: dict[str, list[float]] = defaultdict(list)
        self._login_failures: dict[str, list[float]] = defaultdict(list)
        self._login_blocks: dict[str, float] = {}
        self._last_cleanup = time.time()
        self._dirty = False
        self._loaded = False

    async def _load_from_db(self):
        if self._loaded:
            return
        self._loaded = True
        try:
            async with async_session() as db:
                result = await db.execute(select(RateLimitEntry))
                for entry in result.scalars().all():
                    if entry.is_block:
                        if entry.block_until > time.time():
                            self._login_blocks[entry.key] = entry.block_until
                    else:
                        if entry.timestamp > time.time() - 3600:
                            self._store[entry.key].append(entry.timestamp)
        except Exception:
            pass

    async def _persist_to_db(self):
        if not self._dirty:
            return
        self._dirty = False
        try:
            async with async_session() as db:
                now = time.time()
                await db.execute(delete(RateLimitEntry).where(RateLimitEntry.timestamp < now - 3600))
                for key, timestamps in self._store.items():
                    for ts in timestamps:
                        if ts > now - 3600:
                            db.add(RateLimitEntry(key=f"rl:{key}", timestamp=ts, is_block=False, block_until=0.0))
                for key, block_until in self._login_blocks.items():
                    if block_until > now:
                        db.add(RateLimitEntry(key=f"block:{key}", timestamp=0.0, is_block=True, block_until=block_until))
                await db.commit()
        except Exception:
            pass

    def _cleanup(self):
        now = time.time()
        if now - self._last_cleanup < 60:
            return
        self._last_cleanup = now
        expired_keys = [
            k for k, timestamps in self._store.items()
            if not timestamps or timestamps[-1] < now - 3600
        ]
        for k in expired_keys:
            del self._store[k]
        expired_blocks = [k for k, t in self._login_blocks.items() if t < now]
        for k in expired_blocks:
            del self._login_blocks[k]
        if expired_keys or expired_blocks:
            self._dirty = True

    def check(self, key: str, limit: int, window_seconds: int) -> tuple[bool, int, int]:
        self._cleanup()
        now = time.time()
        cutoff = now - window_seconds
        timestamps = self._store[key]
        self._store[key] = timestamps = [t for t in timestamps if t > cutoff]
        remaining = max(0, limit - len(timestamps))
        if len(timestamps) >= limit:
            retry_after = int(timestamps[0] + window_seconds - now) + 1
            return False, 0, retry_after
        timestamps.append(now)
        self._dirty = True
        return True, remaining - 1, 0

    def check_login(self, ip: str, max_failures: int, window_seconds: int, block_seconds: int) -> tuple[bool, int, int]:
        self._cleanup()
        now = time.time()

        block_until = self._login_blocks.get(ip)
        if block_until and block_until > now:
            retry_after = int(block_until - now) + 1
            return False, 0, retry_after

        cutoff = now - window_seconds
        failures = self._login_failures[ip]
        self._login_failures[ip] = failures = [t for t in failures if t > cutoff]
        remaining = max(0, max_failures - len(failures))
        if len(failures) >= max_failures:
            self._login_blocks[ip] = now + block_seconds
            self._dirty = True
            retry_after = block_seconds
            return False, 0, retry_after
        return True, remaining, 0

    def record_login_failure(self, ip: str):
        self._login_failures[ip].append(time.time())
        self._dirty = True

    async def persist(self):
        await self._persist_to_db()

    async def load(self):
        await self._load_from_db()
