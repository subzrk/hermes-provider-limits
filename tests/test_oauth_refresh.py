"""Owned OAuth refresh tests using Hermes credential objects and fake HTTP boundaries."""
import base64
import importlib.util
import json
import logging
import sys
from pathlib import Path

import pytest
from agent.credential_pool import CredentialPool, PooledCredential

ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "dashboard/oauth_refresh.py"


def load_oauth_module():
    assert MODULE_PATH.exists(), "oauth_refresh.py has not been implemented"
    spec = importlib.util.spec_from_file_location("provider_limits_oauth_refresh", MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def credential(provider, *, source, token, expires_at_ms=None, credential_id="owned", refresh="refresh"):
    return PooledCredential(
        provider=provider,
        id=credential_id,
        label="synthetic",
        auth_type="oauth",
        priority=0,
        source=source,
        access_token=token,
        refresh_token=refresh,
        expires_at_ms=expires_at_ms,
    )


class FakePool:
    def __init__(self, selected, refreshed=None, *, terminal=False):
        self.selected = selected
        self.refreshed = refreshed
        self.terminal = terminal
        self.refresh_calls = []

    def select(self):
        return self.selected

    def entries(self):
        return [self.selected]

    def try_refresh_matching(self, *, api_key_hint=None, credential_id=None):
        self.refresh_calls.append((api_key_hint, credential_id))
        if self.refreshed is not None:
            self.selected = self.refreshed
        elif self.terminal:
            self.selected.last_status = "dead"
        return self.refreshed


class HTTP401(Exception):
    status = 401


def test_proactively_refreshes_owned_grant_near_expiry(monkeypatch):
    oauth = load_oauth_module()
    current = credential(
        "anthropic", source="hermes_pkce", token="sk-ant-oat-old", expires_at_ms=1_100_000,
    )
    refreshed = credential(
        "anthropic", source="hermes_pkce", token="sk-ant-oat-new", expires_at_ms=9_000_000,
    )
    pool = FakePool(current, refreshed)
    monkeypatch.setattr(oauth, "load_pool", lambda provider: pool)
    observed = []

    result = oauth.request_with_owned_oauth(
        "anthropic",
        lambda selected: observed.append(selected.token) or {"windows": []},
        now=lambda: 1000.0,
    )

    assert result == {"windows": []}
    assert observed == ["sk-ant-oat-new"]
    assert pool.refresh_calls == [("sk-ant-oat-old", "owned")]


def test_401_triggers_one_refresh_and_one_retry(monkeypatch):
    oauth = load_oauth_module()
    current = credential(
        "anthropic", source="hermes_pkce", token="sk-ant-oat-old", expires_at_ms=9_000_000,
    )
    refreshed = credential(
        "anthropic", source="hermes_pkce", token="sk-ant-oat-new", expires_at_ms=9_000_000,
    )
    pool = FakePool(current, refreshed)
    monkeypatch.setattr(oauth, "load_pool", lambda provider: pool)
    observed = []

    def request(selected):
        observed.append(selected.token)
        if len(observed) == 1:
            raise HTTP401()
        return {"ok": True}

    result = oauth.request_with_owned_oauth("anthropic", request, now=lambda: 1000.0)

    assert result == {"ok": True}
    assert observed == ["sk-ant-oat-old", "sk-ant-oat-new"]
    assert len(pool.refresh_calls) == 1


def test_proactive_refresh_followed_by_401_never_refreshes_twice(monkeypatch):
    oauth = load_oauth_module()
    current = credential(
        "anthropic", source="hermes_pkce", token="sk-ant-oat-old", expires_at_ms=1_100_000,
    )
    refreshed = credential(
        "anthropic", source="hermes_pkce", token="sk-ant-oat-new", expires_at_ms=9_000_000,
    )
    pool = FakePool(current, refreshed)
    monkeypatch.setattr(oauth, "load_pool", lambda provider: pool)

    with pytest.raises(HTTP401):
        oauth.request_with_owned_oauth(
            "anthropic", lambda _selected: (_ for _ in ()).throw(HTTP401()),
            now=lambda: 1000.0,
        )

    assert len(pool.refresh_calls) == 1


def test_retrying_request_gets_no_second_refresh(monkeypatch):
    oauth = load_oauth_module()
    current = credential(
        "anthropic", source="hermes_pkce", token="sk-ant-oat-old", expires_at_ms=9_000_000,
    )
    refreshed = credential(
        "anthropic", source="hermes_pkce", token="sk-ant-oat-new", expires_at_ms=9_000_000,
    )
    pool = FakePool(current, refreshed)
    monkeypatch.setattr(oauth, "load_pool", lambda provider: pool)

    with pytest.raises(HTTP401):
        oauth.request_with_owned_oauth(
            "anthropic", lambda _selected: (_ for _ in ()).throw(HTTP401()),
            now=lambda: 1000.0,
        )

    assert len(pool.refresh_calls) == 1


def test_borrowed_claude_code_grant_is_rejected_without_mutation(monkeypatch):
    oauth = load_oauth_module()
    borrowed = credential(
        "anthropic", source="claude_code", token="sk-ant-oat-borrowed", expires_at_ms=1_100_000,
    )
    pool = FakePool(borrowed, borrowed)
    monkeypatch.setattr(oauth, "load_pool", lambda provider: pool)

    with pytest.raises(oauth.OAuthFailure) as rejected:
        oauth.request_with_owned_oauth("anthropic", lambda _selected: {}, now=lambda: 1000.0)

    assert rejected.value.code == "auth.ownedOAuthRequired"
    assert rejected.value.hard is True
    assert pool.refresh_calls == []


def test_borrowed_grant_is_validated_before_refreshing_selection(monkeypatch):
    oauth = load_oauth_module()
    borrowed = credential(
        "anthropic", source="claude_code", token="sk-ant-oat-borrowed", expires_at_ms=1_100_000,
    )

    class AutoRefreshingSelectionPool(FakePool):
        def __init__(self, selected):
            super().__init__(selected)
            self.select_calls = 0

        def select(self):
            self.select_calls += 1
            self.refresh_calls.append(("implicit", self.selected.id))
            return self.selected

    pool = AutoRefreshingSelectionPool(borrowed)
    monkeypatch.setattr(oauth, "load_pool", lambda provider: pool)

    with pytest.raises(oauth.OAuthFailure):
        oauth.request_with_owned_oauth("anthropic", lambda _selected: {}, now=lambda: 1000.0)

    assert pool.select_calls == 0
    assert pool.refresh_calls == []


def test_real_hermes_pool_does_not_refresh_near_expiry_borrowed_grant(monkeypatch):
    oauth = load_oauth_module()
    borrowed = credential(
        "anthropic", source="claude_code", token="sk-ant-oat-borrowed", expires_at_ms=1_100_000,
    )
    pool = CredentialPool("anthropic", [borrowed])
    monkeypatch.setattr(oauth, "load_pool", lambda provider: pool)
    monkeypatch.setattr(
        pool,
        "try_refresh_matching",
        lambda **_kwargs: (_ for _ in ()).throw(AssertionError("borrowed grant mutated")),
    )

    with pytest.raises(oauth.OAuthFailure) as rejected:
        oauth.request_with_owned_oauth("anthropic", lambda _selected: {}, now=lambda: 1000.0)

    assert rejected.value.code == "auth.ownedOAuthRequired"


def test_owned_source_allowlists_are_exact():
    oauth = load_oauth_module()
    assert oauth.OWNED_SOURCES == {
        "anthropic": {"hermes_pkce", "manual:hermes_pkce", "manual:dashboard_pkce"},
        "openai-codex": {"device_code", "manual:device_code"},
    }


def synthetic_jwt(account, exp=9000):
    def part(value):
        return base64.urlsafe_b64encode(json.dumps(value).encode()).decode().rstrip("=")
    return f"{part({'alg': 'none'})}.{part({'exp': exp, 'https://api.openai.com/auth': {'chatgpt_account_id': account}})}.sig"


def test_refresh_rejects_changed_selected_account_identity(monkeypatch):
    oauth = load_oauth_module()
    current = credential(
        "openai-codex", source="device_code", token=synthetic_jwt("account-a"),
    )
    changed = credential(
        "openai-codex", source="device_code", token=synthetic_jwt("account-b"),
    )
    pool = FakePool(current, changed)
    monkeypatch.setattr(oauth, "load_pool", lambda provider: pool)

    with pytest.raises(oauth.OAuthFailure) as rejected:
        oauth.request_with_owned_oauth(
            "openai-codex", lambda _selected: (_ for _ in ()).throw(HTTP401()),
            now=lambda: 1000.0,
        )

    assert rejected.value.code == "account.changed"
    assert rejected.value.hard is True


def test_codex_without_account_claim_fails_closed(monkeypatch):
    oauth = load_oauth_module()
    opaque = credential(
        "openai-codex", source="device_code", token="opaque-access-token",
    )
    pool = FakePool(opaque)
    monkeypatch.setattr(oauth, "load_pool", lambda provider: pool)

    with pytest.raises(oauth.OAuthFailure) as rejected:
        oauth.request_with_owned_oauth("openai-codex", lambda _selected: {}, now=lambda: 1000.0)

    assert rejected.value.code == "auth.accountIdentityUnavailable"
    assert rejected.value.hard is True


def test_successful_exact_refresh_ignores_unrelated_round_robin_selection(monkeypatch):
    oauth = load_oauth_module()
    current = credential(
        "openai-codex", source="device_code", token=synthetic_jwt("account-a"),
    )
    refreshed = credential(
        "openai-codex", source="device_code", token=synthetic_jwt("account-a", exp=10000),
    )
    unrelated = credential(
        "openai-codex", source="manual:device_code", token=synthetic_jwt("account-b"),
        credential_id="other",
    )

    class RoundRobinPool(FakePool):
        def select(self):
            return unrelated if self.refresh_calls else self.selected

    pool = RoundRobinPool(current, refreshed)
    monkeypatch.setattr(oauth, "load_pool", lambda provider: pool)

    result = oauth.request_with_owned_oauth(
        "openai-codex",
        lambda selected: (_ for _ in ()).throw(HTTP401()) if selected.token == current.access_token else {"ok": True},
        now=lambda: 1000.0,
    )

    assert result == {"ok": True}
    assert len(pool.refresh_calls) == 1


def test_manual_codex_row_cannot_adopt_a_different_singleton_grant(monkeypatch):
    oauth = load_oauth_module()
    current = credential(
        "openai-codex", source="manual:device_code", token=synthetic_jwt("account-a"),
    )
    pool = FakePool(current, current)
    monkeypatch.setattr(oauth, "load_pool", lambda provider: pool)
    monkeypatch.setattr(
        oauth,
        "codex_singleton_tokens",
        lambda: {"access_token": synthetic_jwt("account-b"), "refresh_token": "other-refresh"},
        raising=False,
    )

    with pytest.raises(oauth.OAuthFailure) as rejected:
        oauth.request_with_owned_oauth(
            "openai-codex", lambda _selected: (_ for _ in ()).throw(HTTP401()),
            now=lambda: 1000.0,
        )

    assert rejected.value.code == "auth.ownedOAuthUnavailable"
    assert pool.refresh_calls == []


@pytest.mark.parametrize(
    ("terminal", "code", "hard"),
    [(True, "auth.invalidGrant", True), (False, "auth.refreshFailed", False)],
)
def test_refresh_failure_classifies_terminal_and_transient(monkeypatch, terminal, code, hard):
    oauth = load_oauth_module()
    current = credential(
        "anthropic", source="hermes_pkce", token="sk-ant-oat-old", expires_at_ms=1_100_000,
    )
    pool = FakePool(current, terminal=terminal)
    monkeypatch.setattr(oauth, "load_pool", lambda provider: pool)

    with pytest.raises(oauth.OAuthFailure) as failed:
        oauth.request_with_owned_oauth("anthropic", lambda _selected: {}, now=lambda: 1000.0)

    assert failed.value.code == code
    assert failed.value.hard is hard


def test_unclassified_refresh_exception_becomes_transient_stable_failure(monkeypatch):
    oauth = load_oauth_module()
    current = credential(
        "anthropic", source="hermes_pkce", token="sk-ant-oat-old", expires_at_ms=1_100_000,
    )

    class RaisingPool(FakePool):
        def try_refresh_matching(self, **_kwargs):
            raise RuntimeError("synthetic private upstream detail")

    monkeypatch.setattr(oauth, "load_pool", lambda provider: RaisingPool(current))

    with pytest.raises(oauth.OAuthFailure) as failed:
        oauth.request_with_owned_oauth("anthropic", lambda _selected: {}, now=lambda: 1000.0)

    assert failed.value.code == "auth.refreshFailed"
    assert failed.value.hard is False
    assert "private" not in str(failed.value)


def test_core_refresh_logs_are_suppressed_for_the_owned_refresh_call(monkeypatch, caplog):
    oauth = load_oauth_module()
    current = credential(
        "anthropic", source="hermes_pkce", token="sk-ant-oat-old", expires_at_ms=1_100_000,
    )

    class LoggingPool(FakePool):
        def try_refresh_matching(self, **_kwargs):
            for logger_name in (
                "agent.credential_pool", "agent.anthropic_credentials", "hermes_cli.auth",
            ):
                logging.getLogger(logger_name).warning(
                    "upstream echoed private-token-value"
                )
            return None

    monkeypatch.setattr(oauth, "load_pool", lambda provider: LoggingPool(current))
    caplog.set_level(logging.DEBUG)

    with pytest.raises(oauth.OAuthFailure):
        oauth.request_with_owned_oauth("anthropic", lambda _selected: {}, now=lambda: 1000.0)

    assert "private-token-value" not in caplog.text


def test_unreadable_credential_pool_is_a_redacted_hard_failure(monkeypatch):
    oauth = load_oauth_module()
    monkeypatch.setattr(
        oauth,
        "load_pool",
        lambda _provider: (_ for _ in ()).throw(OSError("private filesystem detail")),
    )

    with pytest.raises(oauth.OAuthFailure) as failed:
        oauth.request_with_owned_oauth("anthropic", lambda _selected: {}, now=lambda: 1000.0)

    assert failed.value.code == "credentials.unreadable"
    assert failed.value.hard is True
    assert "private" not in str(failed.value)
