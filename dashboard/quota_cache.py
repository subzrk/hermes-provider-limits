"""Bounded, process-local provider quota caching."""
from __future__ import annotations

import copy
from dataclasses import dataclass
import math
import random
import re
import threading
import time
from typing import Callable

POLL_FLOOR = {
    "anthropic": 180.0,
    "openai-codex": 120.0,
    "zai": 180.0,
    "deepseekv4pro": 180.0,
}
MAX_STALE_SECONDS = 900.0
BACKOFF_CAP_SECONDS = 300.0


@dataclass
class CacheEntry:
    good: dict | None
    fetched_at: float | None
    next_refresh_at: float
    attempts: int
    problem_code: str | None
    identity_key: str


@dataclass(frozen=True)
class CacheView:
    good: dict | None
    fetched_at: float | None
    next_refresh_at: float
    status: str
    age_seconds: float | None
    problem_code: str | None


class QuotaCache:
    def __init__(self, *, clock: Callable[[], float] = time.time,
                 randomness: Callable[[float, float], float] = random.uniform,
                 max_entries: int = 64):
        self._clock = clock
        self._randomness = randomness
        self._max_entries = max(2, max_entries)
        self._entries: dict[tuple[str, str], CacheEntry] = {}
        self._locks: dict[tuple[str, str], threading.Lock] = {}
        self._guard = threading.Lock()

    def clear(self) -> None:
        with self._guard:
            self._entries.clear()
            self._locks.clear()

    def get(self, provider_id: str, identity_key: str, fetch: Callable[[], dict]) -> CacheView:
        key = (identity_key, provider_id)
        with self._guard:
            lock = self._locks.setdefault(key, threading.Lock())
        with lock:
            return self._get_locked(key, provider_id, identity_key, fetch)

    def _get_locked(self, key: tuple[str, str], provider_id: str, identity_key: str,
                    fetch: Callable[[], dict]) -> CacheView:
        now = self._clock()
        entry = self._entries.get(key)
        if entry is not None and now < entry.next_refresh_at:
            age = None if entry.fetched_at is None else now - entry.fetched_at
            if entry.problem_code and entry.good is not None and (
                    age is None or age < 0 or age > MAX_STALE_SECONDS):
                entry.good = None
                entry.fetched_at = None
            status = "stale" if entry.problem_code and entry.good is not None else (
                "unavailable" if entry.problem_code else "cached"
            )
            return self._view(entry, now, status)

        try:
            good = copy.deepcopy(fetch())
        except Exception as exc:
            failed_at = self._clock()
            code = getattr(exc, "code", None)
            if not isinstance(code, str) or not re.fullmatch(r"[a-z][A-Za-z0-9.-]{0,63}", code):
                code = "provider.fetchFailed"
            age = (failed_at - entry.fetched_at
                   if entry is not None and entry.fetched_at is not None else None)
            hard = (bool(getattr(exc, "hard", False))
                    or getattr(exc, "status", None) in (401, 403)
                    or code.startswith(("auth.", "credentials."))
                    or code == "account.changed")
            retain = (entry is not None and entry.good is not None and age is not None
                      and 0 <= age <= MAX_STALE_SECONDS and not hard)
            retained_good = copy.deepcopy(entry.good) if entry is not None and retain else None
            retained_at = entry.fetched_at if entry is not None and retain else None
            is_rate_limit = getattr(exc, "status", None) == 429 or code == "upstream.rateLimited"
            attempts = min((entry.attempts if entry is not None else 0) + 1, 10) if is_rate_limit else 0
            wait = POLL_FLOOR.get(provider_id, 180.0)
            if is_rate_limit:
                raw_retry_after = getattr(exc, "retry_after", 0)
                retry_after = float(raw_retry_after) if isinstance(raw_retry_after, (int, float)) else 0.0
                if not math.isfinite(retry_after):
                    retry_after = 0.0
                exponential = min(60.0 * 2 ** (attempts - 1), BACKOFF_CAP_SECONDS)
                wait = min(BACKOFF_CAP_SECONDS, max(
                    wait,
                    exponential + self._randomness(0.0, 15.0),
                    max(0.0, min(retry_after, BACKOFF_CAP_SECONDS)),
                ))
            entry = CacheEntry(
                good=retained_good,
                fetched_at=retained_at,
                next_refresh_at=failed_at + wait,
                attempts=attempts,
                problem_code=code,
                identity_key=identity_key,
            )
            self._store(key, entry)
            return self._view(entry, failed_at, "stale" if retain else "unavailable")
        fetched_at = self._clock()
        entry = CacheEntry(
            good=good,
            fetched_at=fetched_at,
            next_refresh_at=fetched_at + POLL_FLOOR.get(provider_id, 180.0),
            attempts=0,
            problem_code=None,
            identity_key=identity_key,
        )
        self._store(key, entry)
        return self._view(entry, fetched_at, "fresh")

    def _store(self, key: tuple[str, str], entry: CacheEntry) -> None:
        with self._guard:
            self._entries[key] = entry
            if len(self._entries) <= self._max_entries:
                return
            target = max(1, self._max_entries // 2)
            oldest = sorted(self._entries, key=lambda item: self._entries[item].next_refresh_at)
            for obsolete in oldest:
                if len(self._entries) <= target:
                    break
                obsolete_lock = self._locks.get(obsolete)
                if obsolete == key or (obsolete_lock is not None and obsolete_lock.locked()):
                    continue
                self._entries.pop(obsolete, None)
                self._locks.pop(obsolete, None)

    @staticmethod
    def _view(entry: CacheEntry, now: float, status: str) -> CacheView:
        age = None if entry.fetched_at is None else max(0.0, now - entry.fetched_at)
        return CacheView(copy.deepcopy(entry.good), entry.fetched_at, entry.next_refresh_at,
                         status, age, entry.problem_code)
