"""Offline regressions against released Hermes, not substitute pool implementations."""
import base64
import json
import os
from pathlib import Path
from unittest.mock import patch


def jwt(account, exp=9_999_999_999):
    claims = {'exp': exp, 'https://api.openai.com/auth': {'chatgpt_account_id': account}}
    payload = base64.urlsafe_b64encode(json.dumps(claims).encode()).decode().rstrip('=')
    return f'e30.{payload}.synthetic'


def probe_codex_login_change(api):
    import hermes_cli.auth as auth

    home = Path(os.environ['HERMES_HOME'])
    path = home / 'auth.json'
    initial, replacement = jwt('account-a'), jwt('account-b')
    evidence = []
    for source in ('device_code', 'manual:device_code'):
        store = {'version': 1, 'credential_pool': {'openai-codex': [{
            'id': 'owned', 'source': source, 'auth_type': 'oauth', 'priority': 0,
            'access_token': initial, 'refresh_token': 'synthetic-refresh-a',
        }]}, 'providers': {'openai-codex': {'tokens': {
            'access_token': initial, 'refresh_token': 'synthetic-refresh-a',
        }}}}
        path.write_text(json.dumps(store))
        after_login = []
        requests = []

        def transport(url, headers):
            requests.append(headers['Authorization'])
            assert requests == [f'Bearer {initial}']
            # A real login commits B while the request issued with A is in flight.
            with auth._auth_store_lock():
                current = json.loads(path.read_text())
                current['providers']['openai-codex']['tokens'] = {
                    'access_token': replacement, 'refresh_token': 'synthetic-refresh-b',
                }
                path.write_text(json.dumps(current))
                after_login.append(path.read_bytes())
            raise api.QuotaError('synthetic unauthorized', status=401)

        with patch.object(api, 'get_json', side_effect=transport), patch.object(
            auth, 'refresh_codex_oauth_pure', return_value={
                'access_token': jwt('account-b', 9_999_999_998),
                'refresh_token': 'synthetic-rotated-b',
            },
        ) as refresh:
            try:
                api.fetch_provider({'id': 'openai-codex'})
            except Exception as exc:
                assert getattr(exc, 'hard', False), type(exc).__name__
            else:
                raise AssertionError('account change accepted')
            assert refresh.call_count == 0, 'recovery consumed the replacement account grant'
            assert path.read_bytes() == after_login[0], 'recovery mutated the replacement login'
        evidence.append(f'{source}:login-change-no-refresh-or-write')
    path.unlink()
    return evidence


def probe_codex_atomic_guard(api):
    """Try a real competing login immediately after the singleton was read.

    Observe the plugin read boundary; do not replace core refresh, persistence,
    or locking. A precheck outside the transaction lets the competing writer in.
    """
    import threading
    import hermes_cli.auth as auth
    from hermes_constants import set_hermes_home_override, reset_hermes_home_override

    oauth = api._oauth_refresh
    root = Path(os.environ['HERMES_HOME'])
    evidence = []
    for named in (False, True):
        profile = root / 'profiles' / 'atomic' if named else root
        profile.mkdir(parents=True, exist_ok=True)
        scope = set_hermes_home_override(profile)
        path = root / 'auth.json'
        initial = jwt('account-a')
        path.write_text(json.dumps({'version': 1, 'providers': {'openai-codex': {'tokens': {
            'access_token': initial, 'refresh_token': 'synthetic-refresh-a',
        }}}}))
        attempted, acquired = threading.Event(), threading.Event()
        errors, workers = [], []
        original_read = oauth.codex_singleton_tokens

        def login():
            try:
                attempted.set()
                with auth._auth_store_lock(target_path=path):
                    acquired.set()
                    store = json.loads(path.read_text())
                    store['providers']['openai-codex']['tokens'] = {
                        'access_token': jwt('account-b'), 'refresh_token': 'synthetic-refresh-b',
                    }
                    path.write_text(json.dumps(store))
            except Exception as exc:
                errors.append(exc)

        def observed_read():
            tokens = original_read()
            worker = threading.Thread(target=login)
            workers.append(worker)
            worker.start()
            assert attempted.wait(2), 'competing login did not start'
            assert not acquired.wait(0.2), 'singleton precheck was outside the auth transaction'
            return tokens

        def refresh(access, refresh_token):
            assert access == initial and refresh_token == 'synthetic-refresh-a'
            assert not acquired.is_set(), 'login entered during refresh'
            return {'access_token': jwt('account-a', 9_999_999_998),
                    'refresh_token': 'synthetic-rotated-a'}

        requests = []

        def transport(url, headers):
            requests.append(headers['Authorization'])
            if len(requests) == 1:
                raise api.QuotaError('synthetic unauthorized', status=401)
            assert headers['ChatGPT-Account-Id'] == 'account-a'
            return {'rate_limit': {'primary_window': {'used_percent': 12, 'limit_window_seconds': 604800}}}

        try:
            with patch.object(oauth, 'codex_singleton_tokens', side_effect=observed_read), \
                 patch.object(auth, 'refresh_codex_oauth_pure', side_effect=refresh) as post, \
                 patch.object(api, 'get_json', side_effect=transport):
                result = api.fetch_provider({'id': 'openai-codex'})
                assert result['windows'][0]['used_percent'] == 12
                assert post.call_count == 1 and len(requests) == 2
        finally:
            for worker in workers:
                worker.join(3)
                assert not worker.is_alive(), 'auth transaction leaked its lock'
            reset_hermes_home_override(scope)
        assert not errors and acquired.is_set()
        assert json.loads(path.read_text())['providers']['openai-codex']['tokens']['access_token'] == jwt('account-b')
        path.unlink()
        if named:
            (profile / 'auth.json').unlink(missing_ok=True)
        evidence.append(f'codex:{"root-fallback" if named else "local"}:atomic-login-boundary')
    return evidence


def probe_anthropic_invalid_grant_revokes_cache(api):
    import io
    from email.message import Message
    import time
    import urllib.error
    import urllib.request
    import agent.anthropic_credentials as anthropic

    path = Path(os.environ['HERMES_HOME']) / 'auth.json'
    now = [time.time()]
    path.write_text(json.dumps({'version': 1, 'credential_pool': {'anthropic': [{
        'id': 'owned', 'source': 'manual:hermes_pkce', 'auth_type': 'oauth',
        'priority': 0, 'access_token': 'synthetic-access', 'refresh_token': 'synthetic-refresh',
        'expires_at_ms': (now[0] + 300) * 1000,
    }]}}))
    cache = api.QuotaCache(clock=lambda: now[0])
    usage_requests, refresh_requests = [], []

    def usage(credential):
        usage_requests.append(credential.token)
        return {'windows': [{'id': 'weekly', 'used_percent': 12}]}

    def fetch():
        return api.request_with_owned_oauth('anthropic', usage, now=lambda: now[0])

    first = cache.get('anthropic', 'synthetic-identity', fetch)
    assert first.status == 'fresh' and first.good is not None
    now[0] += 240

    def invalid_grant(request, **kwargs):
        assert request.full_url in anthropic._OAUTH_TOKEN_URLS
        assert request.method == 'POST'
        assert json.loads(request.data)['refresh_token'] == 'synthetic-refresh'
        refresh_requests.append(request.full_url)
        raise urllib.error.HTTPError(request.full_url, 400, 'Bad Request', Message(),
                                     io.BytesIO(b'{"error":"invalid_grant"}'))

    # Exercise real refresh parsing, recovery and exhaustion persistence. Only
    # HTTP is replaced: the released core deliberately swallows the exception.
    with patch.object(urllib.request, 'urlopen', side_effect=invalid_grant):
        failed = cache.get('anthropic', 'synthetic-identity', fetch)
    persisted = json.loads(path.read_text())['credential_pool']['anthropic'][0]
    assert persisted['last_status'] == 'exhausted', 'release mechanism changed'
    assert refresh_requests == list(anthropic._OAUTH_TOKEN_URLS)
    assert usage_requests == ['synthetic-access']
    assert failed.good is None, 'invalid_grant retained previously authorized quota'
    assert failed.status == 'unavailable' and failed.fetched_at is None
    assert failed.problem_code in ('auth.invalidGrant', 'auth.refreshFailed')
    # An ordinary poll within the cooldown must not resurrect the old quota.
    retained = cache.get('anthropic', 'synthetic-identity', fetch)
    assert retained.good is None and retained.status == 'unavailable'
    path.unlink()
    return ['anthropic:real-invalid-grant-exhausted-cache-revoked']
