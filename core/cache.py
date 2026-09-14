"""Smart cache for search results.

The same query fired twice in a row should not cost two YouTube round trips.
Entries are keyed by region + normalised query and expire after
`config.SEARCH_CACHE_TTL` seconds. Expired entries are swept lazily on read
and in bulk by `prune()`, which the bot calls from a background loop.
"""
from __future__ import annotations

import time
from typing import Generic, TypeVar

import config

T = TypeVar("T")


class TTLCache(Generic[T]):
    def __init__(self, ttl: float) -> None:
        self.ttl = ttl
        self._entries: dict[str, tuple[float, T]] = {}

    def get(self, key: str) -> T | None:
        entry = self._entries.get(key)
        if entry is None:
            return None
        stored_at, value = entry
        if time.monotonic() - stored_at > self.ttl:
            del self._entries[key]
            return None
        return value

    def set(self, key: str, value: T) -> None:
        self._entries[key] = (time.monotonic(), value)

    def prune(self) -> None:
        cutoff = time.monotonic() - self.ttl
        for key in [k for k, (stored_at, _) in self._entries.items() if stored_at < cutoff]:
            del self._entries[key]

    def clear(self) -> None:
        self._entries.clear()

    def __len__(self) -> int:
        return len(self._entries)


def search_key(query: str, region: str) -> str:
    return f"{region.upper()}_{query.strip().lower()}"


# Shared instance used by the search cog.
searches: TTLCache[list] = TTLCache(config.SEARCH_CACHE_TTL)
