"""Read-only account quotas. Provider secrets never cross the renderer boundary."""
from __future__ import annotations

import asyncio
import copy
import hashlib
import importlib.util
import json
import math
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, HTTPException, Query

_history_spec = importlib.util.spec_from_file_location(__name__ + '_history', Path(__file__).with_name('history.py'))
_history = importlib.util.module_from_spec(_history_spec)
sys.modules[_history_spec.name] = _history
_history_spec.loader.exec_module(_history)

router = APIRouter()
TTL = 60
UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/130.0 Safari/537.36"
NAMES = {"openai-codex": "Codex", "anthropic": "Claude", "deepseekv4pro": "DeepSeek V4 Pro", "zai": "GLM · Z.ai"}
LINKS = {"openai-codex": "https://chatgpt.com/codex/settings/usage", "anthropic": "https://claude.ai/settings/usage", "deepseekv4pro": "https://deepseekv4pro.com/dashboard", "zai": "https://z.ai/manage-apikey/subscription"}
_cache = {}
_locks = {}
_guard = threading.Lock()


class QuotaError(Exception):
    """Only static, credential-free messages are exposed."""

    def __init__(self, message, status=None):
        super().__init__(message)
        self.status = status


def number(value):
    if value is None or value == "" or isinstance(value, bool):
        return None
    try:
        result = float(value)
        return result if math.isfinite(result) else None
    except (ValueError, TypeError):
        return None


def stamp(value):
    if value in (None, ""):
        return None
    try:
        n = number(value)
        if n is not None:
            if n <= 0:
                return None
            return datetime.fromtimestamp(n / 1000 if n > 1e11 else n, timezone.utc).isoformat()
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return dt.replace(tzinfo=dt.tzinfo or timezone.utc).isoformat()
    except (ValueError, TypeError, OverflowError, OSError):
        return None


def duration(seconds):
    n = number(seconds)
    if n is None or n <= 0:
        return "Janela não indicada"
    for size, unit in ((86400, "d"), (3600, "h"), (60, "min")):
        if n % size == 0:
            return f"{n / size:g} {unit}"
    return f"{n:g} s"


def window(key, label, group="Geral", *, used=None, limit=None, remaining=None,
           percent=None, reset=None, period=None, unit="%", details=None, unlimited=False):
    used, limit, remaining, percent = map(number, (used, limit, remaining, percent))
    if remaining is None and limit is not None and used is not None:
        remaining = max(0, limit - used)
    if used is None and limit is not None and remaining is not None:
        used = max(0, limit - remaining)
    if percent is None and used is not None and limit is not None and limit > 0:
        percent = used / limit * 100
    # A missing numeric value stays unknown, never zero; overage stays visible.
    if percent is not None and percent < 0:
        percent = None
    return {"id": key, "label": label, "group": group, "used": used, "limit": limit,
            "remaining": remaining, "used_percent": percent,
            "remaining_percent": max(0, 100 - percent) if percent is not None else None,
            "reset_at": stamp(reset), "period": period, "unit": unit,
            "details": details or [], "unlimited": unlimited}


def normalize_codex(payload):
    windows, facts = [], []
    groups = [("codex", "Codex", payload.get("rate_limit")),
              ("review", "Revisão de código", payload.get("code_review_rate_limit"))]
    for i, item in enumerate(payload.get("additional_rate_limits") or []):
        if isinstance(item, dict):
            groups.append((f"additional-{i}", str(item.get("limit_name") or item.get("metered_feature") or "Limite adicional"), item.get("rate_limit")))
    for prefix, group, limits in groups:
        if not isinstance(limits, dict):
            continue
        for key, row in limits.items():
            if not isinstance(row, dict) or not key.endswith("window"):
                continue
            label = duration(row.get("limit_window_seconds"))
            windows.append(window(f"{prefix}-{key}", label, group, percent=row.get("used_percent"),
                                  reset=row.get("reset_at"), period=label))
    credits = payload.get("credits") or {}
    if credits.get("unlimited"):
        facts.append({"label": "Créditos adicionais", "value": "Ilimitados"})
    elif number(credits.get("balance")) is not None:
        facts.append({"label": "Créditos adicionais", "value": credits["balance"]})
    resets = payload.get("rate_limit_reset_credits") or {}
    if number(resets.get("available_count")) is not None:
        facts.append({"label": "Reposições disponíveis", "value": resets["available_count"]})
    spend = payload.get("spend_control") or {}
    if number(spend.get("individual_limit")) is not None:
        facts.append({"label": "Limite individual de despesa", "value": spend["individual_limit"]})
    return {"windows": windows, "facts": facts, "plan": payload.get("plan_type"), "source": "chatgpt.com · wham/usage"}


def normalize_claude(payload):
    labels = {"five_hour": "5 h", "seven_day": "7 d", "seven_day_opus": "Opus · 7 d",
              "seven_day_sonnet": "Sonnet · 7 d", "seven_day_oauth_apps": "Apps OAuth · 7 d"}
    windows, facts = [], []
    for key, row in payload.items():
        if key == "extra_usage" or not isinstance(row, dict) or "utilization" not in row:
            continue
        # Anthropic utilization is already a percentage: 0.5 means 0.5%, NOT 50%.
        windows.append(window(key, labels.get(key, key.replace("_", " ")), "Claude",
                              percent=row.get("utilization"), reset=row.get("resets_at")))
    extra = payload.get("extra_usage") or {}
    if extra.get("is_enabled"):
        windows.append(window("extra_usage", "Utilização extra mensal", "Claude",
                              used=extra.get("used_credits"), limit=extra.get("monthly_limit"),
                              percent=extra.get("utilization"), reset=extra.get("resets_at"),
                              unit=str(extra.get("currency") or "créditos (API)")))
    elif "is_enabled" in extra:
        facts.append({"label": "Utilização extra", "value": "Desativada"})
    return {"windows": windows, "facts": facts, "plan": None, "source": "api.anthropic.com · oauth/usage"}


def normalize_zai(payload):
    data = payload.get("data", payload)
    if not isinstance(data, dict) or not isinstance(data.get("limits"), list):
        raise QuotaError("A API da Z.ai não devolveu os limites esperados.")
    windows = []
    for i, row in enumerate(data["limits"]):
        if not isinstance(row, dict):
            continue
        kind = row.get("type", "Limite")
        unit, count = number(row.get("unit")), number(row.get("number"))
        period = f"{count:g} { {1: 'min', 3: 'h', 4: 'd', 5: 'mês', 6: 'semana'}.get(unit, 'unid. de período')}" if count is not None else "Período não indicado"
        label = {"TOKENS_LIMIT": "Tokens", "TIME_LIMIT": "Ferramentas / MCP"}.get(kind, str(kind))
        cap = row.get("total") if "total" in row else row.get("usage")
        details = [{"label": str(d.get("modelCode", "Ferramenta")), "value": d["usage"]}
                   for d in row.get("usageDetails", []) if isinstance(d, dict) and number(d.get("usage")) is not None]
        windows.append(window(f"{kind}-{i}", period, label, used=row.get("currentValue"),
                              limit=cap, remaining=row.get("remaining"), percent=row.get("percentage"),
                              reset=row.get("nextResetTime"), period=period,
                              unit="chamadas" if kind == "TIME_LIMIT" else "tokens", details=details))
    return {"windows": windows, "facts": [], "plan": data.get("level"), "source": "api.z.ai · monitor/usage/quota/limit"}


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        # Quota credentials never follow redirects, even within a provider.
        raise QuotaError("O endpoint de utilização mudou de endereço; pedido interrompido por segurança.")


def get_json(url, headers):
    parsed = urllib.parse.urlsplit(url)
    allowed = {"chatgpt.com", "api.anthropic.com", "api.z.ai", "open.bigmodel.cn", "api.deepseekv4pro.com", "deepseekv4pro.com"}
    if parsed.scheme != "https" or parsed.hostname not in allowed or parsed.port not in (None, 443):
        raise QuotaError("Endpoint de utilização não autorizado.")
    request = urllib.request.Request(url, headers={"Accept": "application/json", "User-Agent": UA, **headers})
    try:
        with urllib.request.build_opener(NoRedirect()).open(request, timeout=15) as response:
            raw = response.read(2_000_001)
            if len(raw) > 2_000_000:
                raise QuotaError("Resposta de utilização demasiado grande.")
            result = json.loads(raw)
            if not isinstance(result, dict):
                raise QuotaError("Resposta de utilização inválida.")
            return result
    except urllib.error.HTTPError as exc:
        # Never expose bodies/URLs: some providers echo credentials in them.
        messages = {401: "Autenticação expirada ou recusada. Verifique o fornecedor no Hermes.",
                    403: "O fornecedor recusou acesso aos dados de utilização.",
                    429: "Pedidos de utilização temporariamente limitados pelo fornecedor."}
        raise QuotaError(messages.get(exc.code, f"A API de utilização respondeu HTTP {exc.code}."), status=exc.code) from None
    except (urllib.error.URLError, TimeoutError, OSError):
        raise QuotaError("Não foi possível contactar a API de utilização. Tente novamente dentro de um minuto.") from None
    except (ValueError, UnicodeError):
        raise QuotaError("O fornecedor não devolveu JSON de utilização válido.") from None


def _read_auth(home):
    try:
        return json.loads((home / "auth.json").read_text())
    except FileNotFoundError:
        return {}
    except (OSError, ValueError):
        raise QuotaError("Não foi possível ler as credenciais do perfil Hermes.") from None


def enabled_custom_routes(cfg):
    from hermes_cli.config_providers import is_provider_enabled, _normalize_custom_provider_entry

    def identity(entry):
        url = urllib.parse.urlsplit(entry["base_url"])
        return url._replace(scheme=url.scheme.lower(), netloc=url.netloc.lower(), path=url.path.rstrip("/"), fragment="").geturl()

    # Canonical route declarations supersede legacy duplicates, but disabling one
    # named entry must not veto a separate enabled entry sharing the same host.
    declared_routes, active = set(), []
    for key, raw in (cfg.get("providers") or {}).items():
        if not isinstance(raw, dict):
            continue
        entry = _normalize_custom_provider_entry({k: v for k, v in raw.items() if k != "enabled"}, provider_key=key)
        if entry:
            declared_routes.add(identity(entry))
            if is_provider_enabled(raw):
                active.append(entry)
    for raw in cfg.get("custom_providers") or []:
        if not isinstance(raw, dict) or not is_provider_enabled(raw):
            continue
        entry = _normalize_custom_provider_entry({k: v for k, v in raw.items() if k != "enabled"})
        if entry and identity(entry) not in declared_routes:
            active.append(entry)
    return active


def discover():
    """Current profile's configured/enabled providers only; never scan other homes."""
    from hermes_constants import get_hermes_home
    from hermes_cli.config_effective import load_user_config_effective
    from agent.secret_scope import get_secret
    from hermes_cli.config_providers import is_provider_enabled
    cfg = load_user_config_effective()
    auth = _read_auth(get_hermes_home())
    configs, auths, pools = cfg.get("providers") or {}, auth.get("providers") or {}, auth.get("credential_pool") or {}
    model = cfg.get("model") or {}
    main = model.get("provider") if isinstance(model, dict) else None
    envs = {"anthropic": ("ANTHROPIC_TOKEN", "CLAUDE_CODE_OAUTH_TOKEN", "ANTHROPIC_API_KEY"), "zai": ("ZAI_API_KEY", "Z_AI_API_KEY")}
    result = []
    for provider in ("openai-codex", "anthropic", "zai"):
        pc, ac = configs.get(provider) or {}, auths.get(provider) or {}
        if not is_provider_enabled(pc) or not is_provider_enabled(ac):
            continue
        enabled = bool(pc or ac or pools.get(provider) or main == provider or any(get_secret(k, "") for k in envs.get(provider, ())))
        if enabled:
            result.append({"id": provider, "route": provider})
    # Endpoint identity, not model name or a substring, identifies reseller credentials.
    hosts = {"api.deepseekv4pro.com": "deepseekv4pro", "deepseekv4pro.com": "deepseekv4pro", "api.z.ai": "zai", "open.bigmodel.cn": "zai"}
    seen = {row["id"] for row in result}
    for p in enabled_custom_routes(cfg):
        host = urllib.parse.urlsplit(p.get("base_url", "")).hostname
        kind = hosts.get(host)
        if kind is None or kind in seen:
            continue
        seen.add(kind)
        result.append({"id": kind, "route": p.get("provider_key") or p["name"], "base_url": p["base_url"]})
    return result


def fetch_provider(provider):
    kind = provider["id"]
    if kind == "openai-codex":
        from agent.account_usage import _resolve_codex_usage_credentials, _codex_backend_urls, _codex_headers
        token, base, account = _resolve_codex_usage_credentials(None, None)
        # Native credential resolution retains OAuth/pool/account selection semantics;
        # own parsing retains additional model windows omitted by Hermes' summary.
        try:
            payload = get_json(_codex_backend_urls(base)[0], _codex_headers(token, account))
        except QuotaError as exc:
            if exc.status != 401:
                raise
            token, base, account = _resolve_codex_usage_credentials(None, None, force_refresh=True)
            payload = get_json(_codex_backend_urls(base)[0], _codex_headers(token, account))
        return normalize_codex(payload)
    if kind == "anthropic":
        from agent.anthropic_credentials import resolve_anthropic_token, _is_oauth_token
        token = resolve_anthropic_token()
        if not token or not _is_oauth_token(token):
            raise QuotaError("Limites Claude requerem uma conta OAuth no Hermes; uma chave API não fornece a quota da subscrição.")
        return normalize_claude(get_json("https://api.anthropic.com/api/oauth/usage", {
            "Authorization": f"Bearer {token}", "anthropic-beta": "oauth-2025-04-20", "User-Agent": "claude-code/2.1.0"}))
    from hermes_cli.runtime_provider import resolve_runtime_provider
    runtime = resolve_runtime_provider(requested=provider["route"])
    token = runtime.get("api_key")
    if not isinstance(token, str) or not token:
        raise QuotaError("Não existe uma chave utilizável para este fornecedor no perfil Hermes.")
    host = urllib.parse.urlsplit(runtime.get("base_url") or provider.get("base_url") or "").hostname
    if kind == "zai":
        if host not in ("api.z.ai", "open.bigmodel.cn"):
            raise QuotaError("O endereço GLM configurado não corresponde à Z.ai/Zhipu.")
        data = get_json(f"https://{host}/api/monitor/usage/quota/limit", {"Authorization": token})
        if data.get("success") is False:
            raise QuotaError("A Z.ai não aceitou a consulta da quota do Coding Plan.")
        return normalize_zai(data)
    if host not in ("api.deepseekv4pro.com", "deepseekv4pro.com"):
        raise QuotaError("A credencial não pertence ao endpoint deepseekv4pro.com configurado.")
    return fetch_deepseek(token)


def normalize_deepseek(payload):
    if not isinstance(payload.get("plans"), list):
        raise QuotaError("O dashboard DeepSeek não devolveu a lista de planos esperada.")
    windows, facts, names = [], [], []
    for i, plan in enumerate(payload["plans"]):
        if not isinstance(plan, dict):
            continue
        name = str(plan.get("planName") or plan.get("planSlug") or f"Plano {i + 1}")
        names.append(name)
        quota = plan.get("quota")
        if plan.get("quotaStatus") == "unavailable" or not isinstance(quota, dict):
            facts.append({"label": name, "value": "Quota indisponível no fornecedor"})
            continue
        for key, row in quota.items():
            if not isinstance(row, dict) or not any(k in row for k in ("limitCredits", "usedCredits", "remainingCredits")):
                continue
            label = {"fiveHour": "5 h", "sevenDay": "7 d"}.get(key, key)
            details = [] if row.get("resetAt") else [{"label": "Início da janela", "value": "No primeiro pedido"}]
            windows.append(window(f"plan-{i}-{key}", label, name, used=row.get("usedCredits"),
                                  limit=row.get("limitCredits"), remaining=row.get("remainingCredits"),
                                  reset=row.get("resetAt"), unit="créditos", details=details))
        for model, usage in (quota.get("usageByModel") or {}).items():
            if isinstance(usage, dict) and number(usage.get("chargedCredits")) is not None:
                facts.append({"label": f"{name} · {model} · créditos debitados", "value": usage["chargedCredits"]})
        if plan.get("currentPeriodEnd"):
            facts.append({"label": f"{name} · fim do período", "value": stamp(plan["currentPeriodEnd"]) or "Não indicado"})
    if windows:
        facts.append({"label": "Unidade do plano", "value": "Créditos Flash-equivalentes; não USD"})
    return {"windows": windows, "facts": facts, "plan": " / ".join(names) or None,
            "source": "deepseekv4pro.com · api/quota/me"}


def fetch_deepseek(token):
    try:
        payload = get_json("https://deepseekv4pro.com/api/quota/me", {"Authorization": f"Bearer {token}"})
    except QuotaError as exc:
        if exc.status in (401, 403):
            raise QuotaError("A quota requer sessão iniciada no site deepseekv4pro.com; a API key do Hermes não dá acesso a estes dados. Consulte «Abrir no fornecedor». Nenhuma quota foi estimada.", status=exc.status) from None
        raise
    return normalize_deepseek(payload)


def _signature(home):
    # Hash stays server-side, isolates cache on credential/config change.
    digest = hashlib.sha256()
    for name in ("config.yaml", "auth.json", ".env", ".anthropic_oauth.json"):
        path = home / name
        if path.is_file():
            digest.update(path.read_bytes())
    from agent.secret_scope import current_secret_scope
    digest.update(json.dumps(dict(current_secret_scope() or {}), sort_keys=True).encode())
    return digest.hexdigest()


def cached_provider(provider, scope):
    key = (scope, provider["id"])
    with _guard:
        lock = _locks.setdefault(key, threading.Lock())
    with lock:
        now = time.monotonic()
        old = _cache.get(key)
        if old and now - old["attempt"] < TTL:
            return copy.deepcopy(old["value"])
        base = {"id": provider["id"], "name": NAMES[provider["id"]], "url": LINKS[provider["id"]],
                "status": "ok", "windows": [], "facts": [], "plan": None, "source": None,
                "fetched_at": None, "error": None}
        try:
            data = fetch_provider(provider)
            base.update(data)
            base["fetched_at"] = datetime.now(timezone.utc).isoformat()
            if not base["windows"] and not base["facts"]:
                raise QuotaError("O fornecedor não devolveu limites ou saldos para esta conta.")
        except Exception as exc:
            if old and old["value"].get("fetched_at"):
                base = copy.deepcopy(old["value"])
                base["status"] = "stale"
            else:
                base["status"] = "unavailable"
            base["error"] = str(exc) if isinstance(exc, QuotaError) else "Não foi possível obter a utilização com as credenciais deste perfil. Verifique o fornecedor no Hermes."
        _cache[key] = {"attempt": time.monotonic(), "value": base}
        # Bound old profile/config generations; no quota snapshots persisted to disk.
        if len(_cache) > 64:
            with _guard:
                obsolete = sorted(_cache, key=lambda k: _cache[k]["attempt"])[:-32]
                for k in obsolete:
                    _cache.pop(k, None)
                    _locks.pop(k, None)
        return copy.deepcopy(base)


@router.get("/quota")
async def quota(profile: str | None = Query(default=None, max_length=100)):
    from hermes_cli.web_server_profiles import _config_profile_scope
    from hermes_constants import get_hermes_home
    with _config_profile_scope(profile):
        home = get_hermes_home()
        try:
            providers = await asyncio.to_thread(discover)
            scope = (str(home.resolve()), await asyncio.to_thread(_signature, home))
            rows = await asyncio.gather(*(asyncio.to_thread(cached_provider, p, scope) for p in providers))
        except QuotaError as exc:
            return {"providers": [], "error": str(exc), "profile": profile or "current", "refresh_seconds": TTL}
        return {"providers": rows, "profile": profile or "current", "refresh_seconds": TTL,
                "checked_at": datetime.now(timezone.utc).isoformat(), "error": None}


@router.get('/history')
async def history(
    provider: Literal['openai-codex', 'anthropic', 'deepseekv4pro', 'zai'],
    profile: str | None = Query(default=None, max_length=100),
    q: str = Query(default='', max_length=200),
    model: str = Query(default='', max_length=200),
    sort: Literal['tokens', 'recent'] = 'tokens',
    offset: int = Query(default=0, ge=0, le=1_000_000),
    limit: int = Query(default=25, ge=1, le=100),
):
    from hermes_cli.web_server_profiles import _config_profile_scope
    from hermes_constants import get_hermes_home
    with _config_profile_scope(profile):
        if provider not in {p['id'] for p in await asyncio.to_thread(discover)}:
            raise HTTPException(status_code=404, detail='Fornecedor não ativo neste perfil.')
        result = await asyncio.to_thread(_history.load_history, get_hermes_home() / 'state.db', provider,
                                         query=q, model=model, sort=sort, offset=offset, limit=limit)
        return {**result, 'profile': profile or 'current', 'checked_at': datetime.now(timezone.utc).isoformat()}
