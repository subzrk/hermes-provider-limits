from test_quota import api
import pytest


def test_deepseek_multiple_plans_and_unavailable_are_not_zero():
    result = api.normalize_deepseek({'plans': [
        {'planName': 'Coding', 'quota': {'fiveHour': {'limitCredits': 1000, 'usedCredits': 100, 'remainingCredits': 900, 'resetAt': None},
                                      'sevenDay': {'limitCredits': 6000, 'usedCredits': 200, 'remainingCredits': 5800},
                                      'usageByModel': {'deepseek-flash': {'chargedCredits': 100, 'promptTokens': 70, 'completionTokens': 30}}}},
        {'planName': 'Second', 'quotaStatus': 'unavailable', 'quota': None}]})
    assert len(result['windows']) == 2
    assert result['windows'][0]['remaining'] == 900
    assert result['windows'][0]['used_percent'] == 10
    assert result['windows'][0]['reset_at'] is None
    assert any(f['label'] == 'Second' and 'indisponível' in f['value'] for f in result['facts'])


def test_deepseek_session_wall_is_explicit(monkeypatch):
    def wall(*a, **kw):
        raise api.QuotaError('Autenticação recusada', status=401)
    monkeypatch.setattr(api, 'get_json', wall)
    with pytest.raises(api.QuotaError, match='sessão iniciada no site'):
        api.fetch_deepseek('synthetic-test-key')
