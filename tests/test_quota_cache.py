"""Process-local quota cache reliability tests."""
import importlib.util
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "dashboard/quota_cache.py"


def load_cache_module():
    assert MODULE_PATH.exists(), "quota_cache.py has not been implemented"
    spec = importlib.util.spec_from_file_location("provider_limits_quota_cache", MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_provider_fetch_is_reused_inside_its_floor():
    cache_module = load_cache_module()
    now = [1000.0]
    cache = cache_module.QuotaCache(clock=lambda: now[0], randomness=lambda _a, _b: 0)
    calls = []

    def fetch():
        calls.append(now[0])
        return {"windows": [{"used_percent": 12}]}

    first = cache.get("openai-codex", "profile:credential", fetch)
    now[0] += 119
    second = cache.get("openai-codex", "profile:credential", fetch)

    assert first.good == second.good
    assert second.status == "cached"
    assert calls == [1000.0]


class FetchFailure(Exception):
    def __init__(self, code="network.unreachable", *, status=None, retry_after=0, hard=False):
        super().__init__(code)
        self.code = code
        self.status = status
        self.retry_after = retry_after
        self.hard = hard


def test_one_provider_failure_does_not_invalidate_another_provider():
    cache_module = load_cache_module()
    cache = cache_module.QuotaCache(clock=lambda: 1000.0, randomness=lambda _a, _b: 0)
    codex = cache.get("openai-codex", "same-identity", lambda: {"quota": 42})

    claude = cache.get(
        "anthropic",
        "same-identity",
        lambda: (_ for _ in ()).throw(FetchFailure()),
    )
    codex_again = cache.get("openai-codex", "same-identity", lambda: {"quota": 99})

    assert claude.status == "unavailable"
    assert claude.good is None
    assert codex_again.good == codex.good == {"quota": 42}


def test_soft_failure_retains_good_data_before_stale_limit():
    cache_module = load_cache_module()
    now = [1000.0]
    cache = cache_module.QuotaCache(clock=lambda: now[0], randomness=lambda _a, _b: 0)
    cache.get("openai-codex", "identity", lambda: {"quota": 42})
    now[0] += 120

    result = cache.get(
        "openai-codex", "identity", lambda: (_ for _ in ()).throw(FetchFailure())
    )

    assert result.status == "stale"
    assert result.good == {"quota": 42}
    assert result.age_seconds == 120
    assert result.problem_code == "network.unreachable"


def test_soft_failure_drops_data_after_stale_limit():
    cache_module = load_cache_module()
    now = [1000.0]
    cache = cache_module.QuotaCache(clock=lambda: now[0], randomness=lambda _a, _b: 0)
    cache.get("openai-codex", "identity", lambda: {"quota": 42})
    now[0] += cache_module.MAX_STALE_SECONDS + 1

    result = cache.get(
        "openai-codex", "identity", lambda: (_ for _ in ()).throw(FetchFailure())
    )

    assert result.status == "unavailable"
    assert result.good is None
    assert result.fetched_at is None


def test_stale_data_expires_even_while_failure_floor_is_active():
    cache_module = load_cache_module()
    now = [1000.0]
    cache = cache_module.QuotaCache(clock=lambda: now[0], randomness=lambda _a, _b: 0)
    cache.get("openai-codex", "identity", lambda: {"quota": 42})
    now[0] += 850
    assert cache.get(
        "openai-codex", "identity", lambda: (_ for _ in ()).throw(FetchFailure())
    ).status == "stale"
    now[0] += 51

    expired = cache.get(
        "openai-codex", "identity", lambda: (_ for _ in ()).throw(AssertionError("floor active"))
    )

    assert expired.status == "unavailable"
    assert expired.good is None
    assert expired.fetched_at is None


def test_hard_auth_failure_clears_good_data_immediately():
    cache_module = load_cache_module()
    now = [1000.0]
    cache = cache_module.QuotaCache(clock=lambda: now[0], randomness=lambda _a, _b: 0)
    cache.get("anthropic", "identity", lambda: {"quota": 42})
    now[0] += 180

    result = cache.get(
        "anthropic",
        "identity",
        lambda: (_ for _ in ()).throw(FetchFailure("auth.rejected", status=401)),
    )

    assert result.status == "unavailable"
    assert result.good is None
    assert result.fetched_at is None
    assert result.problem_code == "auth.rejected"


def test_transient_oauth_refresh_failure_retains_bounded_stale_data():
    cache_module = load_cache_module()
    now = [1000.0]
    cache = cache_module.QuotaCache(clock=lambda: now[0], randomness=lambda _a, _b: 0)
    cache.get("anthropic", "identity", lambda: {"quota": 42})
    now[0] += 180

    result = cache.get(
        "anthropic",
        "identity",
        lambda: (_ for _ in ()).throw(FetchFailure("auth.refreshFailed", hard=False)),
    )

    assert result.status == "stale"
    assert result.good == {"quota": 42}
    assert result.problem_code == "auth.refreshFailed"


def test_terminal_invalid_grant_revokes_stale_data():
    cache_module = load_cache_module()
    now = [1000.0]
    cache = cache_module.QuotaCache(clock=lambda: now[0], randomness=lambda _a, _b: 0)
    cache.get("anthropic", "identity", lambda: {"quota": 42})
    now[0] += 180

    result = cache.get(
        "anthropic",
        "identity",
        lambda: (_ for _ in ()).throw(FetchFailure("auth.invalidGrant", hard=True)),
    )

    assert result.status == "unavailable"
    assert result.good is None


def test_credential_or_profile_identity_change_cannot_reuse_old_data():
    cache_module = load_cache_module()
    cache = cache_module.QuotaCache(clock=lambda: 1000.0, randomness=lambda _a, _b: 0)
    cache.get("openai-codex", "profile-a:credential-a", lambda: {"quota": 42})

    changed = cache.get(
        "openai-codex",
        "profile-b:credential-b",
        lambda: (_ for _ in ()).throw(FetchFailure()),
    )

    assert changed.status == "unavailable"
    assert changed.good is None


def test_rate_limit_retry_after_is_clamped_between_floor_and_backoff_cap():
    cache_module = load_cache_module()
    now = [1000.0]
    cache = cache_module.QuotaCache(clock=lambda: now[0], randomness=lambda _a, _b: 0)

    too_large = cache.get(
        "openai-codex",
        "large-retry-after",
        lambda: (_ for _ in ()).throw(
            FetchFailure("upstream.rateLimited", status=429, retry_after=9999)
        ),
    )
    too_small = cache.get(
        "openai-codex",
        "small-retry-after",
        lambda: (_ for _ in ()).throw(
            FetchFailure("upstream.rateLimited", status=429, retry_after=1)
        ),
    )

    assert too_large.next_refresh_at == 1300.0
    assert too_small.next_refresh_at == 1120.0


def test_repeated_rate_limits_use_bounded_exponential_backoff():
    cache_module = load_cache_module()
    now = [1000.0]
    cache = cache_module.QuotaCache(clock=lambda: now[0], randomness=lambda _a, _b: 0)
    failure = lambda: (_ for _ in ()).throw(
        FetchFailure("upstream.rateLimited", status=429)
    )

    waits = []
    for _ in range(4):
        result = cache.get("openai-codex", "identity", failure)
        waits.append(result.next_refresh_at - now[0])
        now[0] = result.next_refresh_at

    assert waits == [120.0, 120.0, 240.0, 300.0]


def test_entry_and_lock_tables_are_bounded_together():
    cache_module = load_cache_module()
    cache = cache_module.QuotaCache(
        clock=lambda: 1000.0, randomness=lambda _a, _b: 0, max_entries=4,
    )

    for index in range(12):
        cache.get("openai-codex", f"identity-{index}", lambda: {"quota": 42})

    assert len(cache._entries) <= 4
    assert len(cache._locks) <= 4


def test_concurrent_callers_for_one_identity_perform_one_fetch():
    cache_module = load_cache_module()
    cache = cache_module.QuotaCache(clock=lambda: 1000.0, randomness=lambda _a, _b: 0)
    calls = []
    fetch_started = threading.Event()

    def fetch():
        calls.append(1)
        fetch_started.set()
        time.sleep(0.05)
        return {"quota": 42}

    with ThreadPoolExecutor(max_workers=2) as executor:
        first = executor.submit(cache.get, "openai-codex", "identity", fetch)
        assert fetch_started.wait(timeout=1)
        second = executor.submit(cache.get, "openai-codex", "identity", fetch)
        results = [first.result(timeout=2), second.result(timeout=2)]

    assert len(calls) == 1
    assert [result.good for result in results] == [{"quota": 42}, {"quota": 42}]
