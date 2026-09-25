"""Keep newer Codex refresh behavior while supporting the released resolver."""
import pytest

from test_quota import api


@pytest.mark.parametrize('status', [401, 403])
def test_newer_codex_resolver_refreshes_only_after_unauthorized(monkeypatch, status):
    import agent.account_usage as usage
    resolutions, requests = [], []

    def credentials(base_url, api_key, *, force_refresh=False):
        resolutions.append(force_refresh)
        return ('fresh' if force_refresh else 'initial', 'https://chatgpt.com/backend-api', 'account')

    rejected = api.QuotaError('synthetic rejection', status=status)

    def get_json(url, headers):
        requests.append(headers['Authorization'])
        if len(requests) == 1:
            raise rejected
        return {'rate_limit': {'primary_window': {'used_percent': 12, 'limit_window_seconds': 18000}}}

    monkeypatch.setattr(usage, '_resolve_codex_usage_credentials', credentials)
    monkeypatch.setattr(api, 'get_json', get_json)
    if status == 401:
        result = api.fetch_provider({'id': 'openai-codex'})
        assert result['windows'][0]['used_percent'] == 12
        assert resolutions == [False, True]
        assert requests == ['Bearer initial', 'Bearer fresh']
    else:
        with pytest.raises(api.QuotaError) as error:
            api.fetch_provider({'id': 'openai-codex'})
        assert error.value is rejected
        assert resolutions == [False]
        assert requests == ['Bearer initial']
