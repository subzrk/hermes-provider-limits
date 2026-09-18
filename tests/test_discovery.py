"""Regressions found by independent review; no network or real credentials."""
import json
import pytest
import yaml
from test_quota import api


def discover_config(tmp_path, config):
    from hermes_cli.web_server_profiles import _hermes_home_scope
    from agent.secret_scope import set_secret_scope, reset_secret_scope
    (tmp_path/'config.yaml').write_text(yaml.safe_dump(config))
    token=set_secret_scope({})
    try:
        with _hermes_home_scope(tmp_path):
            return api.discover()
    finally:
        reset_secret_scope(token)


@pytest.mark.parametrize('disabled', ['false', 'off', 'no', '0', False])
def test_native_enabled_semantics(tmp_path, disabled):
    rows=discover_config(tmp_path, {'providers': {'anthropic': {'enabled': disabled}}})
    assert rows == []


def test_disabled_url_alias_takes_precedence_over_legacy_duplicate(tmp_path):
    rows=discover_config(tmp_path, {
        'providers': {'reseller': {'url':'https://api.deepseekv4pro.com/v1/', 'enabled': False}},
        'custom_providers': [{'name':'Legacy reseller', 'base_url':'https://api.deepseekv4pro.com/v1'}]})
    assert rows == []


def test_disabled_entry_does_not_veto_enabled_same_host(tmp_path):
    rows=discover_config(tmp_path, {'providers': {
        'old': {'base_url':'https://api.deepseekv4pro.com/v1', 'enabled':False},
        'live': {'base_url':'https://api.deepseekv4pro.com/v1', 'enabled':True}}})
    assert rows == [{'id':'deepseekv4pro','route':'live','base_url':'https://api.deepseekv4pro.com/v1'}]


def test_legacy_disabled_stays_disabled(tmp_path):
    assert discover_config(tmp_path, {'custom_providers':[{'name':'Old','base_url':'https://api.deepseekv4pro.com/v1','enabled':'false'}]}) == []


def test_disabled_different_path_does_not_block_legacy_route(tmp_path):
    rows=discover_config(tmp_path, {
        'providers': {'old': {'url':'https://api.deepseekv4pro.com/other','enabled':False}},
        'custom_providers': [{'name':'Live','base_url':'https://api.deepseekv4pro.com/v1'}]})
    assert len(rows)==1 and rows[0]['route']=='Live'
