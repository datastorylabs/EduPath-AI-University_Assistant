"""Bounded auth rate limiting; Redis is mandatory in production, memory is dev/test only."""
from __future__ import annotations

from functools import lru_cache
import hashlib
import hmac
import threading
import time

from fastapi import HTTPException, Request

from backend.app.config import get_settings


class _MemoryFixedWindow:
    """Bounded process-local limiter; not suitable for multi-worker production."""

    def __init__(self) -> None:
        self._entries: dict[str, tuple[int, int]] = {}
        self._lock = threading.Lock()

    def hit(self, key: str, limit: int, window_seconds: int) -> tuple[int, int]:
        now = int(time.time())
        window_start = now - (now % window_seconds)
        with self._lock:
            start, count = self._entries.get(key, (window_start, 0))
            if start != window_start:
                start, count = window_start, 0
            count += 1
            self._entries[key] = (start, count)
            # Bound memory even if many unique client addresses hit auth routes.
            if len(self._entries) > 10_000:
                self._entries = {
                    entry_key: value for entry_key, value in self._entries.items()
                    if value[0] >= window_start
                }
                if len(self._entries) > 20_000:
                    self._entries = dict(list(self._entries.items())[-10_000:])
        return count, max(1, window_start + window_seconds - now)

    def clear(self) -> None:
        with self._lock:
            self._entries.clear()


_memory_limiter = _MemoryFixedWindow()


@lru_cache(maxsize=4)
def _redis_client(redis_url: str):
    """Reuse a bounded Redis connection pool rather than opening a pool per request."""
    from redis import Redis
    return Redis.from_url(redis_url, socket_connect_timeout=1, socket_timeout=1)


def reset_memory_limiter_for_tests() -> None:
    _memory_limiter.clear()


def enforce_rate_limit(request: Request, scope: str, limit: int) -> None:
    """Raise 429 when a client exceeds the configured fixed-window limit."""
    settings = get_settings()
    host = request.client.host if request.client else "unknown"
    secret = settings.secret_key.get_secret_value().encode() or b"edupath-dev-rate-key"
    ip_fingerprint = hmac.new(secret, host.encode(), hashlib.sha256).hexdigest()
    key = f"edupath:rate:{scope}:{ip_fingerprint}"
    window = settings.auth_rate_window_seconds

    if settings.redis_url:
        try:
            client = _redis_client(settings.redis_url)
            count = int(client.eval(
                "local n=redis.call('INCR',KEYS[1]); "
                "if n==1 then redis.call('EXPIRE',KEYS[1],ARGV[1]) end; return n",
                1, key, window,
            ))
            ttl = int(client.ttl(key))
            retry_after = max(1, ttl)
        except Exception:
            # Never disable brute-force protection silently in production.
            if settings.app_env == "production":
                raise HTTPException(status_code=503, detail="Authentication temporarily unavailable") from None
            count, retry_after = _memory_limiter.hit(key, limit, window)
    else:
        if settings.app_env == "production":
            raise HTTPException(status_code=503, detail="Authentication temporarily unavailable")
        count, retry_after = _memory_limiter.hit(key, limit, window)

    if count > limit:
        raise HTTPException(
            status_code=429,
            detail="Too many authentication attempts. Please try again later.",
            headers={"Retry-After": str(retry_after)},
        )
