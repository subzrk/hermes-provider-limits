"""Synthetic accounting contracts; production probes use the real read-only store."""
from test_quota import api
import json
import sqlite3
from pathlib import Path
import pytest

hist = api._history


def session(sid='s', **kw):
    return {'id':sid,'title':'Sessão de teste','source':'desktop','model':'codex-a',
            'billing_provider':'openai-codex','billing_base_url':'https://chatgpt.com/backend-api/codex',
            'started_at':1,'last_activity_at':2,**kw}


def record(sid='s', **kw):
    return {'session_id':sid,'model':'codex-a','billing_provider':'openai-codex',
            'billing_base_url':'https://chatgpt.com/backend-api/codex','task':'',
            'first_seen':1,'last_seen':2, 'input_tokens':100,'output_tokens':20,
            'cache_read_tokens':30,'cache_write_tokens':5,'reasoning_tokens':7,'api_call_count':1,
            'actual_cost_usd':0,'estimated_cost_usd':0,**kw}


def test_ledger_split_models_plus_aux_not_summary_duplicate():
    sessions=[session(input_tokens=300,output_tokens=40,cache_read_tokens=60,cache_write_tokens=10)]
    ledger=[record(),record(model='codex-b',input_tokens=200),record(model='codex-aux',task='vision',input_tokens=10,output_tokens=2,cache_read_tokens=0,cache_write_tokens=0)]
    out=hist.build_history(sessions,ledger,'openai-codex')
    assert out['total_sessions']==1
    assert out['totals']['total_tokens']==422  # 155 + 255 + 12, never add sessions again
    assert out['totals']['reasoning_tokens']==21  # tracked but not summed into total
    assert {r['model'] for r in out['by_model']}=={'codex-a','codex-b','codex-aux'}
    assert out['coverage']['unattributed_main_tokens_in_profile']==0


def test_provider_route_owns_same_model_and_aux_are_independent():
    rows=[record(model='same-model'),record(model='same-model',billing_provider='custom',billing_base_url='https://api.deepseekv4pro.com/v1',task='vision')]
    codex=hist.build_history([session()],rows,'openai-codex')
    ds=hist.build_history([session()],rows,'deepseekv4pro')
    assert codex['totals']['total_tokens']==155==ds['totals']['total_tokens']
    assert hist.classify({'model':'deepseek-flash','billing_provider':'custom','billing_base_url':'https://api.deepseek.com/v1'}) is None
    assert hist.classify({'billing_provider':'anthropic','billing_base_url':'https://unrelated.test/v1'}) is None


@pytest.mark.parametrize('status,expected',[('unknown','unknown'),(None,'unknown'),('included','included'),('estimated','estimated'),('actual','actual')])
def test_zero_usd_does_not_invent_known_bill_or_credits(status,expected):
    out=hist.build_history([session()],[record(cost_status=status)],'openai-codex')
    total=out['totals']
    assert total['cost_state']==expected
    assert total['credits'] is None
    assert (total['actual_cost_usd'] == 0) is (status=='actual')
    assert (total['estimated_cost_usd'] == 0) is (status=='estimated')


def test_legacy_fallback_main_and_ledger_aux_preserved():
    out=hist.build_history([session(input_tokens=100,output_tokens=20)],
                          [record(task='compression',input_tokens=5,output_tokens=1,cache_read_tokens=0,cache_write_tokens=0)],'openai-codex')
    assert out['totals']['total_tokens']==126
    assert out['coverage']['legacy_sessions']==1
    assert {r['attribution'] for r in out['sessions'][0]['models']}=={'ledger','session_summary'}


def test_mixed_model_residual_is_not_blindly_attributed_to_latest():
    out=hist.build_history([session(input_tokens=500,output_tokens=20,cache_read_tokens=30,cache_write_tokens=5)], [record()], 'openai-codex')
    assert out['totals']['total_tokens']==155
    assert out['coverage']['unattributed_main_tokens_in_profile']==400


def test_pagination_total_and_search_not_limited_to_first_page():
    sessions=[session(str(i),title=f'Session {i}') for i in range(57)]
    ledger=[record(str(i),input_tokens=i+1,model='tiny' if i%2 else 'large') for i in range(57)]
    one=hist.build_history(sessions,ledger,'openai-codex',offset=0,limit=25)
    two=hist.build_history(sessions,ledger,'openai-codex',offset=25,limit=25)
    three=hist.build_history(sessions,ledger,'openai-codex',offset=50,limit=25)
    ids=[r['session_id'] for p in [one,two,three] for r in p['sessions']]
    assert len(ids)==len(set(ids))==57
    assert one['totals']==two['totals']==three['totals']
    assert one['total_sessions']==57 and not three['has_more']
    filtered=hist.build_history(sessions,ledger,'openai-codex',query='SESSION 3',model='tiny')
    assert all('session 3' in r['title'].lower() and all(m['model']=='tiny' for m in r['models']) for r in filtered['sessions'])
    assert hist.build_history(sessions,ledger,'openai-codex',query="' OR 1=1 --")['total_sessions']==0


def test_read_only_missing_and_legacy_schema(tmp_path):
    path=tmp_path/'state.db'
    assert hist.load_history(path,'openai-codex')['total_sessions']==0 and not path.exists()
    db=sqlite3.connect(path)
    db.execute('CREATE TABLE sessions(id TEXT,model TEXT,billing_provider TEXT,input_tokens INTEGER,output_tokens INTEGER)')
    db.execute('INSERT INTO sessions VALUES(?,?,?,?,?)',('old','codex-old','openai-codex',20,5))
    db.commit();db.close()
    before=path.read_bytes()
    out=hist.load_history(path,'openai-codex')
    assert out['totals']['total_tokens']==25
    assert not out['coverage']['ledger_available']
    assert path.read_bytes()==before


def test_query_validation_and_inactive_provider(monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from contextlib import nullcontext
    import hermes_cli.web_server_profiles as profiles
    monkeypatch.setattr(profiles,'_config_profile_scope',lambda p:nullcontext())
    monkeypatch.setattr(api,'discover',lambda:[{'id':'openai-codex'}])
    app=FastAPI();app.include_router(api.router)
    client=TestClient(app)
    assert client.get('/history?provider=zai').status_code==404
    for suffix in ['provider=other','provider=openai-codex&limit=99999','provider=openai-codex&offset=-1','provider=openai-codex&sort=sql']:
        assert client.get('/history?'+suffix).status_code==422
