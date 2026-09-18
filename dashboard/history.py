"""Read-only Hermes accounting, preserving per-model/provider/task attribution.

The sessions table is a summary of the main loop; the model ledger contains the
same main-loop counters plus auxiliary calls. Never add both wholesale.
"""
from __future__ import annotations

from collections import defaultdict
from contextlib import closing
import math
import sqlite3
from pathlib import Path
from urllib.parse import urlsplit

TOKENS = ('input_tokens', 'output_tokens', 'cache_read_tokens', 'cache_write_tokens')
COUNTERS = TOKENS + ('reasoning_tokens', 'api_call_count')
COSTS = ('estimated_cost_usd', 'actual_cost_usd')
ROUTE_FIELDS = ('model', 'billing_provider', 'billing_base_url', 'billing_mode', 'cost_status')
SESSION_FIELDS = ('id', 'title', 'source', 'started_at', 'last_activity_at', 'parent_session_id') + ROUTE_FIELDS + COUNTERS + COSTS
LEDGER_FIELDS = ('session_id', 'task', 'first_seen', 'last_seen') + ROUTE_FIELDS + COUNTERS + COSTS
HOSTS = {'chatgpt.com': 'openai-codex', 'api.anthropic.com': 'anthropic',
         'api.deepseekv4pro.com': 'deepseekv4pro', 'deepseekv4pro.com': 'deepseekv4pro',
         'api.z.ai': 'zai', 'open.bigmodel.cn': 'zai'}
PROVIDERS = {'openai-codex': 'openai-codex', 'anthropic': 'anthropic', 'zai': 'zai', 'z-ai': 'zai'}


def numeric(value):
    if value is None or isinstance(value, bool):
        return None
    try:
        n = float(value)
        return n if math.isfinite(n) and n >= 0 else None
    except (ValueError, TypeError):
        return None


def classify(row):
    base = str(row.get('billing_base_url') or '').strip()
    if base:
        # A third-party Claude-compatible or official DeepSeek route is NOT the
        # reseller just because its model/provider name looks familiar.
        try:
            return HOSTS.get(urlsplit(base).hostname)
        except ValueError:
            return None
    return PROVIDERS.get(str(row.get('billing_provider') or '').lower())


def read_rows(db_path: Path):
    if not db_path.is_file():
        return [], [], False
    with closing(sqlite3.connect(db_path.as_uri() + '?mode=ro', uri=True, timeout=3)) as db:
        db.row_factory = sqlite3.Row
        db.execute('PRAGMA query_only=ON')
        db.execute('BEGIN')  # both tables from one coherent read snapshot
        tables = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        def project(table, fields):
            if table not in tables:
                return []
            cols = {r[1] for r in db.execute(f'PRAGMA table_info({table})')}
            # Names are compile-time constants, never request parameters. Only the
            # accounting projection is read: no prompts, messages, origin or keys.
            projection = ','.join(f'"{f}"' if f in cols else f'NULL AS "{f}"' for f in fields)
            return [dict(r) for r in db.execute(f'SELECT {projection} FROM {table}')]
        return project('sessions', SESSION_FIELDS), project('session_model_usage', LEDGER_FIELDS), 'session_model_usage' in tables


def accounting_rows(sessions, ledger):
    by_id = {s['id']: s for s in sessions}
    main = defaultdict(list)
    for row in ledger:
        if not row.get('task'):
            main[row['session_id']].append(row)
    rows = []
    for record in ledger:
        if record.get('session_id') in by_id:
            rows.append({**record, 'attribution': 'ledger'})
    unassigned = 0
    for session in sessions:
        records = main[session['id']]
        if not records:
            # Legacy sessions retain their only recorded route, explicitly labelled
            # as a session summary rather than a verified model-switch history.
            rows.append({**session, 'session_id': session['id'], 'task': '',
                         'first_seen': session.get('started_at'),
                         'last_seen': session.get('last_activity_at') or session.get('started_at'),
                         'attribution': 'session_summary'})
        else:
            # Cumulative-only updates can't safely be attributed to the session's
            # latest model after switches. Do not fabricate per-model usage.
            unassigned += sum(max(0, (numeric(session.get(k)) or 0) - sum(numeric(r.get(k)) or 0 for r in records)) for k in TOKENS)
    return rows, by_id, int(unassigned)


def costs(row):
    actual, estimated = (numeric(row.get(k)) for k in ('actual_cost_usd', 'estimated_cost_usd'))
    status = row.get('cost_status')
    # Ledger defaults both USD columns to zero even when no price was recorded.
    # Only status or a positive amount can make zero mean an actual free charge.
    if status == 'included' or row.get('billing_mode') == 'subscription_included':
        return {'actual_cost_usd': None, 'estimated_cost_usd': None, 'cost_state': 'included'}
    if status == 'actual' or (actual is not None and actual > 0):
        return {'actual_cost_usd': actual, 'estimated_cost_usd': None, 'cost_state': 'actual'}
    if status == 'estimated' or (estimated is not None and estimated > 0):
        return {'actual_cost_usd': None, 'estimated_cost_usd': estimated, 'cost_state': 'estimated'}
    return {'actual_cost_usd': None, 'estimated_cost_usd': None, 'cost_state': 'unknown'}


def item(record):
    counts = {k: int(numeric(record.get(k)) or 0) for k in COUNTERS}
    return {**counts, 'total_tokens': sum(counts[k] for k in TOKENS),
            'model': record.get('model') or 'Não registado', 'task': record.get('task') or 'main',
            'first_seen': numeric(record.get('first_seen')), 'last_seen': numeric(record.get('last_seen')),
            'attribution': record['attribution'], 'credits': None, **costs(record)}


def summarize(rows):
    out = {k: sum(r[k] for r in rows) for k in COUNTERS + ('total_tokens',)}
    for key in COSTS:
        known = [r[key] for r in rows if r[key] is not None]
        out[key] = sum(known) if known else None
    states = sorted({r['cost_state'] for r in rows})
    out.update(cost_state=states[0] if len(states) == 1 else 'mixed' if states else 'unknown',
               unknown_cost_rows=sum(r['cost_state'] == 'unknown' for r in rows),
               included_cost_rows=sum(r['cost_state'] == 'included' for r in rows), credits=None)
    return out


def build_history(sessions, ledger, provider, *, query='', model='', sort='tokens', offset=0, limit=25, ledger_available=True):
    raw, session_meta, unassigned = accounting_rows(sessions, ledger)
    buckets = defaultdict(list)
    for row in raw:
        if classify(row) != provider:
            continue
        value = item(row)
        if value['total_tokens'] or value['api_call_count'] or any(value[k] for k in COSTS):
            buckets[row['session_id']].append(value)
    model_names = sorted({r['model'] for records in buckets.values() for r in records})
    needle = query.casefold().strip()
    selected, flat = [], []
    for sid, records in buckets.items():
        meta = session_meta[sid]
        records = [r for r in records if not model or r['model'] == model]
        if not records:
            continue
        title = str(meta.get('title') or 'Sessão sem título')
        haystack = ' '.join([sid, title, *(r['model'] for r in records)]).casefold()
        if needle and needle not in haystack:
            continue
        flat.extend(records)
        selected.append({'session_id': sid, 'title': title, 'source': meta.get('source') or 'unknown',
                         'parent_session_id': meta.get('parent_session_id'),
                         'last_seen': max((r['last_seen'] or 0 for r in records), default=0),
                         'models': sorted(records, key=lambda r: (-r['total_tokens'], r['model'], r['task'])),
                         'summary': summarize(records)})
    grouped = defaultdict(list)
    for row in flat:
        grouped[row['model']].append(row)
    by_model = [{'model': name, **summarize(rows)} for name, rows in grouped.items()]
    by_model.sort(key=lambda r: (-r['total_tokens'], r['model']))
    selected.sort(key=lambda s: (-s['last_seen'], s['session_id']) if sort == 'recent' else (-s['summary']['total_tokens'], s['session_id']))
    total = len(selected)
    return {'provider': provider, 'sessions': selected[offset:offset + limit], 'total_sessions': total,
            'offset': offset, 'limit': limit, 'has_more': offset + limit < total,
            'totals': summarize(flat), 'by_model': by_model, 'model_options': model_names,
            'coverage': {'ledger_available': ledger_available,
                         'legacy_sessions': sum(any(r['attribution'] == 'session_summary' for r in s['models']) for s in selected),
                         'unattributed_main_tokens_in_profile': unassigned,
                         'credits_recorded': False},
            'source': 'Hermes · state.db / session_model_usage',
            'period': 'Histórico acumulado das sessões; não é o consumo da janela da subscrição.',
            'error': None}


def load_history(db_path, provider, **kwargs):
    try:
        sessions, ledger, available = read_rows(Path(db_path))
        return build_history(sessions, ledger, provider, ledger_available=available, **kwargs)
    except (sqlite3.Error, OSError):
        return {'provider': provider, 'error': 'Não foi possível ler o registo local do Hermes. Tente novamente.',
                'sessions': [], 'total_sessions': 0, 'has_more': False}
