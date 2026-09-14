"""Rate limiters for incoming commands and outgoing requests.

Two separate layers:
  * TokenBucket / RateLimiter -> the flood of commands from users
  * Throttle                  -> the pace of requests going out to YouTube
"""
from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass


class RateLimited(Exception):
    """Raised once the quota is spent; retry_after is in seconds."""

    def __init__(self, retry_after: float) -> None:
        super().__init__(f"rate limited for {retry_after:.1f}s")
        self.retry_after = retry_after


@dataclass
class _Bucket:
    tokens: float
    updated: float


class TokenBucket:
    """One token bucket per key (user, guild, channel...)."""

    def __init__(self, capacity: int, per_seconds: float) -> None:
        self.capacity = float(capacity)
        self.rate = capacity / per_seconds
        self._buckets: dict[int | str, _Bucket] = {}

    def consume(self, key: int | str, amount: float = 1.0) -> None:
        now = time.monotonic()
        bucket = self._buckets.get(key)
        if bucket is None:
            bucket = _Bucket(self.capacity, now)
            self._buckets[key] = bucket

        bucket.tokens = min(self.capacity, bucket.tokens + (now - bucket.updated) * self.rate)
        bucket.updated = now

        if bucket.tokens < amount:
            raise RateLimited((amount - bucket.tokens) / self.rate)
        bucket.tokens -= amount

    def refund(self, key: int | str, amount: float = 1.0) -> None:
        """Gives tokens back when a later check in the same chain refuses."""
        bucket = self._buckets.get(key)
        if bucket is not None:
            bucket.tokens = min(self.capacity, bucket.tokens + amount)

    def prune(self, older_than: float = 600.0) -> None:
        """Drops buckets nobody has touched in a while, so memory stays flat."""
        cutoff = time.monotonic() - older_than
        for key in [k for k, b in self._buckets.items() if b.updated < cutoff]:
            del self._buckets[key]


class RateLimiter:
    """Manages the user and guild buckets from one place."""

    def __init__(self, user_rate: tuple[int, float], guild_rate: tuple[int, float]) -> None:
        self.user = TokenBucket(*user_rate)
        self.guild = TokenBucket(*guild_rate)

    def check(self, user_id: int, guild_id: int | None, cost: float = 1.0) -> None:
        """Charges `cost` tokens. A search costs more than a cheap command.

        The user bucket is charged first and, if the guild bucket then refuses,
        the user's tokens are handed back — otherwise a busy server would burn
        one person's quota for a command that never ran.
        """
        self.user.consume(user_id, cost)
        if guild_id is None:
            return
        try:
            self.guild.consume(guild_id, cost)
        except RateLimited:
            self.user.refund(user_id, cost)
            raise

    def prune(self) -> None:
        self.user.prune()
        self.guild.prune()


class Busy(Exception):
    """The heavy-work gate is full; the caller should ask the user to retry."""


class Gate:
    """Caps how many expensive operations run at once.

    Rate limits bound how often *one* user asks; this bounds how much work is
    in flight across *everyone*. That is the limit that matters on a small box:
    a single search holds nine decoded JPEGs plus a full-page canvas while it
    renders, so a burst of simultaneous searches is what would exhaust memory.
    Past the ceiling a caller waits briefly and is then told to come back,
    which degrades gracefully instead of taking the whole bot down.
    """

    def __init__(self, limit: int, wait_timeout: float) -> None:
        self._sem = asyncio.Semaphore(limit)
        self._wait_timeout = wait_timeout
        self.limit = limit
        self.waiting = 0
        # Counted here rather than read back out of the semaphore. The count
        # only feeds a log line, and reaching into `Semaphore._value` for it
        # bets a crash in the busy path on a private attribute staying put
        # across Python versions.
        self.in_flight = 0

    async def __aenter__(self) -> "Gate":
        self.waiting += 1
        try:
            await asyncio.wait_for(self._sem.acquire(), timeout=self._wait_timeout)
        except asyncio.TimeoutError as exc:
            raise Busy() from exc
        finally:
            self.waiting -= 1
        self.in_flight += 1
        return self

    async def __aexit__(self, *exc_info) -> None:
        self.in_flight -= 1
        self._sem.release()


class Throttle:
    """A concurrency ceiling plus a minimum gap between consecutive requests."""

    def __init__(self, concurrency: int, min_interval: float) -> None:
        self._sem = asyncio.Semaphore(concurrency)
        self._min_interval = min_interval
        self._lock = asyncio.Lock()
        self._last = 0.0

    async def __aenter__(self) -> "Throttle":
        await self._sem.acquire()
        async with self._lock:
            wait = self._min_interval - (time.monotonic() - self._last)
            if wait > 0:
                await asyncio.sleep(wait)
            self._last = time.monotonic()
        return self

    async def __aexit__(self, *exc_info) -> None:
        self._sem.release()
