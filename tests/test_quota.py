"""Synthetic protocol fixtures; live integration is a separate explicit probe."""
import importlib.util
import json
import sys
from pathlib import Path
import pytest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('limits_api', ROOT / 'dashboard/plugin_api.py')
api = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = api
spec.loader.exec_module(api)


def test_codex_duration_not_position_and_every_additional_limit():
    payload = {'rate_limit': {'primary_window': {'used_percent': 71, 'limit_window_seconds': 604800}, 'secondary_window': None},
               'additional_rate_limits': [{'limit_name': 'GPT-5.3-Codex-Spark', 'rate_limit': {
                   'primary_window': {'used_percent': 0, 'limit_window_seconds': 18000},
                   'secondary_window': {'used_percent': 22, 'limit_window_seconds': 604800}}}],
               'code_review_rate_limit': {'primary_window': {'used_percent': 12, 'limit_window_seconds': 3600}}}
    windows = api.normalize_codex(payload)['windows']
    assert [(w['group'], w['label']) for w in windows] == [('Codex', '7 d'), ('Revisão de código', '1 h'), ('GPT-5.3-Codex-Spark', '5 h'), ('GPT-5.3-Codex-Spark', '7 d')]
    assert windows[0]['remaining_percent'] == 29
    assert windows[2]['remaining_percent'] == 100
    assert all(w['limit'] is None for w in windows)


def test_claude_small_percent_and_unknown_windows_not_discarded():
    windows = api.normalize_claude({'five_hour': {'utilization': 0.5}, 'seven_day': None,
                                  'seven_day_new_model': {'utilization': 42},
                                  'extra_usage': {'is_enabled': True, 'monthly_limit': 1000, 'used_credits': 125}})['windows']
    assert windows[0]['used_percent'] == 0.5
    assert windows[0]['remaining_percent'] == 99.5
    assert windows[1]['used_percent'] == 42
    assert windows[2]['remaining'] == 875


def test_zai_all_windows_absolute_and_percentage():
    windows = api.normalize_zai({'data': {'level': 'MAX', 'limits': [
        {'type': 'TOKENS_LIMIT', 'unit': 3, 'number': 5, 'percentage': 18, 'nextResetTime': 1790000000000},
        {'type': 'TOKENS_LIMIT', 'unit': 6, 'number': 1, 'percentage': 0},
        {'type': 'TIME_LIMIT', 'unit': 5, 'number': 1, 'usage': 100, 'currentValue': 17, 'remaining': 83, 'percentage': 17,
         'usageDetails': [{'modelCode': 'search', 'usage': 17}]},
        {'type': 'NEW_LIMIT', 'unit': 4, 'number': 2, 'percentage': 32}]}})['windows']
    assert len(windows) == 4
    assert [w['label'] for w in windows] == ['5 h', '1 semana', '1 mês', '2 d']
    assert windows[0]['used'] is None  # do not fabricate absolute usage from rounded %
    assert windows[0]['reset_at'].startswith('2026-')
    assert windows[2]['remaining'] == 83
    assert windows[3]['group'] == 'NEW_LIMIT'


@pytest.mark.parametrize('v', [None, '', True, float('inf'), float('nan'), 'unlimited'])
def test_missing_and_invalid_never_become_zero(v):
    w = api.window('a', 'a', percent=v)
    assert w['used_percent'] is None
    assert w['remaining_percent'] is None


def test_overage_kept_and_zero_limit_not_infinite():
    w = api.window('a', 'a', used=120, limit=100)
    assert w['used_percent'] == 120 and w['remaining'] == 0
    assert api.window('a', 'a', used=0, limit=0)['used_percent'] is None


def test_cache_dedup_stale_error_redacted_and_profile_isolated(monkeypatch):
    api._cache.clear()
    api._locks.clear()
    now = [1000]
    monkeypatch.setattr(api.time, 'monotonic', lambda: now[0])
    calls = []
    def fetch(p):
        calls.append(p)
        return {'windows': [api.window('a', '7 d', percent=12)], 'facts': []}
    monkeypatch.setattr(api, 'fetch_provider', fetch)
    p = {'id': 'openai-codex'}
    a = api.cached_provider(p, ('A', 'sigA'))
    assert api.cached_provider(p, ('A', 'sigA')) == a
    assert len(calls) == 1
    api.cached_provider(p, ('B', 'sigB'))
    assert len(calls) == 2
    now[0] += 61
    def failure(p):
        raise RuntimeError('secret-should-never-render')
    monkeypatch.setattr(api, 'fetch_provider', failure)
    stale = api.cached_provider(p, ('A', 'sigA'))
    assert stale['status'] == 'stale' and stale['fetched_at'] == a['fetched_at']
    assert 'secret-should-never-render' not in json.dumps(stale)
    new_account = api.cached_provider(p, ('A', 'changed-signature'))
    assert new_account['status'] == 'unavailable' and new_account['windows'] == []


def test_discovery_real_scoped_homes_A_B_A(tmp_path, monkeypatch):
    from hermes_cli.web_server_profiles import _hermes_home_scope as hermes_home_override
    from agent.secret_scope import set_secret_scope, reset_secret_scope, set_multiplex_active
    import yaml
    homes = [tmp_path / 'A', tmp_path / 'B']
    for home in homes:
        home.mkdir()
    (homes[0] / 'config.yaml').write_text(yaml.safe_dump({'model': {'provider': 'openai-codex'}, 'providers': {
        'deepseek': {'base_url': 'https://api.deepseekv4pro.com/v1', 'enabled': True},
        'anthropic': {'enabled': False}}}))
    (homes[0] / 'auth.json').write_text(json.dumps({'credential_pool': {'anthropic': [{'access_token': 'synthetic-not-real'}]}}))
    (homes[1] / 'config.yaml').write_text(yaml.safe_dump({'model': {'provider': 'local'}, 'providers': {
        'zai': {'enabled': True}, 'deepseek': {'base_url': 'https://api.deepseekv4pro.com/v1', 'enabled': False}},
        'custom_providers': [{'name': 'Old duplicate', 'base_url': 'https://api.deepseekv4pro.com/v1'}]}))
    token = set_secret_scope({})
    try:
        outputs = []
        for home in [homes[0], homes[1], homes[0]]:
            with hermes_home_override(home):
                outputs.append({p['id'] for p in api.discover()})
        assert outputs == [{'openai-codex', 'deepseekv4pro'}, {'zai'}, {'openai-codex', 'deepseekv4pro'}]
    finally:
        reset_secret_scope(token)


def test_no_redirects_or_wrong_hosts():
    with pytest.raises(api.QuotaError):
        api.get_json('https://example.com/usage', {'Authorization': 'synthetic'})
    with pytest.raises(api.QuotaError):
        api.get_json('https://api.z.ai.evil.test/usage', {})
    with pytest.raises(api.QuotaError):
        api.get_json('http://api.z.ai/usage', {})
    with pytest.raises(api.QuotaError):
        api.NoRedirect().redirect_request(None, None, 302, '', {}, 'https://evil.test')
