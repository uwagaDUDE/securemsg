import time
from collections import defaultdict


class RateLimiter:
    def __init__(self):
        self._store: dict[str, list[float]] = defaultdict(list)
        self._login_failures: dict[str, list[float]] = defaultdict(list)
        self._login_blocks: dict[str, float] = {}
        self._last_cleanup = time.time()

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

    def check(self, key: str, limit: int, window_seconds: int) -> tuple[bool, int, int]:
        self._cleanup()
        now = time.time()
        cutoff = now - window_seconds
        timestamps = self._store[key]
        self._store[key] = timestamps = [t for t in timestamps if t > cutoff]
        remaining = max(0, limit - len(timestamps))
        if len(timestamps) >= limit:
            retry_after = int(timestamps[0] + window_seconds - now) + 1
            print(f"Rate limit exceeded for key={key}, limit={limit}/{window_seconds}s, retry_after={retry_after}s")
            return False, 0, retry_after
        timestamps.append(now)
        return True, remaining - 1, 0

    def check_login(self, ip: str, max_failures: int, window_seconds: int, block_seconds: int) -> tuple[bool, int, int]:
        self._cleanup()
        now = time.time()

        block_until = self._login_blocks.get(ip)
        if block_until and block_until > now:
            retry_after = int(block_until - now) + 1
            print(f"Login blocked for ip={ip}, retry_after={retry_after}s")
            return False, 0, retry_after

        cutoff = now - window_seconds
        failures = self._login_failures[ip]
        self._login_failures[ip] = failures = [t for t in failures if t > cutoff]
        remaining = max(0, max_failures - len(failures))
        if len(failures) >= max_failures:
            self._login_blocks[ip] = now + block_seconds
            retry_after = block_seconds
            print(f"Login rate limit exceeded for ip={ip}, {len(failures)} failures in {window_seconds}s, blocked for {block_seconds}s")
            return False, 0, retry_after
        return True, remaining, 0

    def record_login_failure(self, ip: str):
        self._login_failures[ip].append(time.time())
