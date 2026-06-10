import os
import time
from collections import defaultdict
from typing import Optional

import redis.asyncio as redis
from sqlalchemy import delete, select

from .config import REDIS_URL
from .database import async_session
from .models import RateLimitEntry
from .logging_config import get_logger

logger = get_logger(__name__)


class RedisRateLimiter:
    """Redis-backed rate limiter with in-memory fallback."""

    def __init__(self, redis_url: Optional[str] = None):
        self._redis_url = redis_url or os.getenv("REDIS_URL", "redis://localhost:6379/0")
        self._redis: Optional[redis.Redis] = None
        self._use_redis = False
        self._store: dict[str, list[float]] = defaultdict(list)
        self._login_failures: dict[str, list[float]] = defaultdict(list)
        self._login_blocks: dict[str, float] = {}
        self._last_cleanup = time.time()
        self._dirty = False
        self._loaded = False

    async def _connect_redis(self) -> bool:
        try:
            self._redis = redis.from_url(self._redis_url, encoding="utf-8", decode_responses=True)
            await self._redis.ping()
            self._use_redis = True
            logger.info("Connected to Redis for rate limiting")
            return True
        except Exception as e:
            logger.warning("Failed to connect to Redis, using in-memory fallback", error=str(e))
            self._use_redis = False
            return False

    async def _ensure_redis(self):
        if self._redis is None:
            await self._connect_redis()

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
        except Exception as e:
            logger.warning("Failed to load rate limit data from DB", error=str(e))

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
        except Exception as e:
            logger.warning("Failed to persist rate limit data to DB", error=str(e))

    async def _persist_to_redis(self, key: str, timestamps: list[float], window_seconds: int):
        if not self._use_redis or not self._redis:
            return
        try:
            pipe = self._redis.pipeline()
            pipe.delete(f"rl:{key}")
            if timestamps:
                pipe.lpush(f"rl:{key}", *[str(t) for t in timestamps])
                pipe.expire(f"rl:{key}", window_seconds + 60)
            await pipe.execute()
        except Exception as e:
            logger.warning("Failed to persist rate limit to Redis", key=key, error=str(e))

    async def _persist_block_to_redis(self, key: str, block_until: float):
        if not self._use_redis or not self._redis:
            return
        try:
            ttl = int(block_until - time.time()) + 1
            if ttl > 0:
                await self._redis.setex(f"block:{key}", ttl, "1")
        except Exception as e:
            logger.warning("Failed to persist block to Redis", key=key, error=str(e))

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

    async def check_async(self, key: str, limit: int, window_seconds: int) -> tuple[bool, int, int]:
        await self._ensure_redis()
        now = time.time()
        cutoff = now - window_seconds

        if self._use_redis and self._redis:
            try:
                key_redis = f"rl:{key}"
                pipe = self._redis.pipeline()
                pipe.lrange(key_redis, 0, -1)
                pipe.ttl(key_redis)
                results = await pipe.execute()
                timestamps = [float(t) for t in results[0] if float(t) > cutoff]
                await self._redis.ltrim(key_redis, 0, len(timestamps) - 1)
                remaining = max(0, limit - len(timestamps))
                if len(timestamps) >= limit:
                    retry_after = int(timestamps[0] + window_seconds - now) + 1
                    return False, 0, retry_after
                timestamps.append(now)
                await self._redis.lpush(key_redis, str(now))
                await self._redis.expire(key_redis, window_seconds + 60)
                return True, remaining - 1, 0
            except Exception as e:
                logger.warning("Redis rate limit check failed, falling back to memory", error=str(e))

        return self.check(key, limit, window_seconds)

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

    async def check_login_async(self, ip: str, max_failures: int, window_seconds: int, block_seconds: int) -> tuple[bool, int, int]:
        await self._ensure_redis()
        now = time.time()

        if self._use_redis and self._redis:
            try:
                block_key = f"block:{ip}"
                blocked = await self._redis.exists(block_key)
                if blocked:
                    ttl = await self._redis.ttl(block_key)
                    return False, 0, ttl if ttl > 0 else block_seconds

                fail_key = f"fail:{ip}"
                pipe = self._redis.pipeline()
                pipe.lrange(fail_key, 0, -1)
                pipe.ttl(fail_key)
                results = await pipe.execute()
                failures = [float(t) for t in results[0] if float(t) > now - window_seconds]
                await self._redis.ltrim(fail_key, 0, len(failures) - 1)
                remaining = max(0, max_failures - len(failures))
                if len(failures) >= max_failures:
                    await self._redis.setex(block_key, block_seconds, "1")
                    return False, 0, block_seconds
                return True, remaining, 0
            except Exception as e:
                logger.warning("Redis login check failed, falling back to memory", error=str(e))

        return self.check_login(ip, max_failures, window_seconds, block_seconds)

    def record_login_failure(self, ip: str):
        self._login_failures[ip].append(time.time())
        self._dirty = True

    async def record_login_failure_async(self, ip: str):
        await self._ensure_redis()
        if self._use_redis and self._redis:
            try:
                fail_key = f"fail:{ip}"
                await self._redis.lpush(fail_key, str(time.time()))
                await self._redis.expire(fail_key, 3600)
                return
            except Exception as e:
                logger.warning("Redis record login failure failed", error=str(e))
        self.record_login_failure(ip)

    async def persist(self):
        if self._use_redis:
            return
        await self._persist_to_db()

    async def load(self):
        await self._load_from_db()
        await self._ensure_redis()


_limiter_instance: Optional[RedisRateLimiter] = None


def get_limiter() -> RedisRateLimiter:
    global _limiter_instance
    if _limiter_instance is None:
        _limiter_instance = RedisRateLimiter()
    return _limiter_instance