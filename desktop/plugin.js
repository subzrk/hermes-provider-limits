import { jsx as h, jsxs } from 'react/jsx-runtime'
import { useState, useEffect } from 'react'
import { host, useValue, useQuery, useQueryClient, Button, Input, Codicon, Select, SelectContent, SelectItem, SelectTrigger, SelectValue, Tabs, TabsList, TabsTrigger, ROUTES_AREA, SIDEBAR_NAV_AREA, PALETTE_AREA } from '@hermes/plugin-sdk'

const PATH = '/provider-limits'
const ALL_MODELS = '__provider_limits_all_models__'
const MODEL_VALUE_PREFIX = 'model:'
const nf = new Intl.NumberFormat('pt-PT', { maximumFractionDigits: 2 })
const pf = new Intl.NumberFormat('pt-PT', { maximumFractionDigits: 1 })
const dtf = new Intl.DateTimeFormat('pt-PT', { day: '2-digit', month: 'short', hour: '2-digit', minute: '2-digit' })
const isNumber = value => typeof value === 'number' && Number.isFinite(value)
const pct = value => isNumber(value) ? `${pf.format(value)}%` : '—'
const amount = (value, unit) => isNumber(value) ? `${nf.format(value)}${unit && unit !== '%' ? ` ${unit}` : ''}` : '—'

export function resetText(value, now = Date.now()) {
  const end = value ? new Date(value).getTime() : NaN
  if (!Number.isFinite(end)) return 'Renovação não indicada'
  const minutes = Math.ceil((end - now) / 60000)
  if (minutes <= 0) return 'Renovação prevista atingida · aguarda atualização'
  const days = Math.floor(minutes / 1440)
  const hours = Math.floor((minutes % 1440) / 60)
  const mins = minutes % 60
  return `Renova em ${days ? `${days} d ${hours} h` : hours ? `${hours} h ${mins} min` : `${mins} min`}`
}

export const CSS = `
.pl-page{height:100%;overflow:auto;container-type:inline-size;color:var(--ui-text-primary);font:inherit;scrollbar-color:var(--ui-stroke-primary) transparent}
.pl-content{padding:clamp(20px,4vw,48px);max-width:1160px;margin:0 auto}
.pl-header{display:flex;align-items:center;justify-content:space-between;gap:20px;flex-wrap:wrap;margin-bottom:18px}
.pl-header h1{font-size:clamp(24px,3vw,32px);font-weight:650;letter-spacing:-.025em;line-height:1.18;margin:0 0 9px}
.pl-description{color:var(--ui-text-secondary);font-size:13px;line-height:1.6;margin:0;max-width:65ch}
.pl-meta{display:flex;flex-wrap:wrap;gap:8px 18px;align-items:center;font-size:12px;color:var(--ui-text-secondary);padding-bottom:28px}
.pl-profile{display:inline-flex;align-items:center;gap:7px;color:var(--ui-text-primary)}
.pl-section{border-top:1px solid var(--ui-stroke-tertiary);padding:28px 0 30px}
.pl-section-head{display:flex;align-items:center;justify-content:space-between;gap:16px;margin-bottom:24px}
.pl-identity{display:flex;align-items:center;gap:12px;min-width:0}
.pl-identity h2{font-size:19px;font-weight:600;letter-spacing:-.015em;margin:0}
.pl-mark{font-weight:650;letter-spacing:-.05em;font-size:20px;color:var(--ui-text-secondary);width:34px;flex-shrink:0}
.pl-plan{font-size:12px;color:var(--ui-text-secondary);margin-top:5px}
.pl-status{display:flex;align-items:center;gap:6px;font-size:12px;color:var(--ui-text-secondary)}
.pl-status-dot{width:6px;height:6px;border-radius:50%;background:var(--ui-accent)}
.pl-group+.pl-group{margin-top:28px}
.pl-group-title{display:flex;align-items:center;gap:7px;font-size:13px;font-weight:600;color:var(--ui-text-secondary);margin:0 0 14px}
.pl-windows{display:grid;grid-template-columns:repeat(auto-fit,minmax(min(100%,260px),1fr));gap:22px 36px}
.pl-window{min-width:0}
.pl-window-top{display:flex;justify-content:space-between;align-items:baseline;gap:12px;margin-bottom:12px}
.pl-window-label{font-size:14px;font-weight:550}
.pl-rest{font-size:20px;letter-spacing:-.035em;font-weight:600;font-variant-numeric:tabular-nums;white-space:nowrap}
.pl-rest small{font-size:11px;letter-spacing:normal;font-weight:400;color:var(--ui-text-secondary);margin-left:5px}
.pl-track{height:7px;background:var(--ui-bg-quaternary);border-radius:4px;overflow:hidden;position:relative}
.pl-fill{height:100%;width:100%;transform-origin:left;border-radius:4px;background:var(--ui-accent);transition:transform .5s cubic-bezier(.16,1,.3,1)}
.pl-window[data-severity=warn] .pl-fill{background:var(--ui-warning,var(--ui-accent))}
.pl-window[data-severity=danger] .pl-fill{background:var(--destructive,var(--ui-accent))}
.pl-track[data-unknown=true]{background:repeating-linear-gradient(110deg,var(--ui-bg-quaternary) 0 8px,transparent 8px 12px);border:1px solid var(--ui-stroke-tertiary)}
.pl-measure{display:flex;justify-content:space-between;gap:14px;margin-top:10px;font-size:12px;color:var(--ui-text-secondary);font-variant-numeric:tabular-nums}
.pl-renewal{font-size:12px;margin-top:16px;line-height:1.65;color:var(--ui-text-secondary)}
.pl-renewal time{display:block;color:var(--ui-text-tertiary);font-size:11px;font-variant-numeric:tabular-nums}
.pl-note{margin:10px 0 0;font-size:11px;color:var(--ui-text-tertiary);line-height:1.6}
.pl-facts{display:flex;flex-wrap:wrap;gap:14px 32px;margin:22px 0 0;font-size:12px}
.pl-fact dt{color:var(--ui-text-secondary);margin-bottom:5px}.pl-fact dd{margin:0;font-weight:550;font-variant-numeric:tabular-nums}
.pl-source{font-size:11px;color:var(--ui-text-tertiary);margin-top:20px;display:flex;flex-wrap:wrap;gap:6px 18px;overflow-wrap:anywhere}
.pl-alert{display:flex;gap:10px;align-items:flex-start;padding:14px 16px;background:var(--ui-bg-quaternary);border-radius:6px;font-size:13px;line-height:1.65;margin:0 0 20px;color:var(--ui-text-secondary)}
.pl-alert strong{display:block;color:var(--ui-text-primary);font-weight:550}
.pl-empty{padding:46px 0;max-width:65ch}.pl-empty h2{font-size:20px;font-weight:550;margin:14px 0 10px}
.pl-empty p{font-size:13px;line-height:1.7;color:var(--ui-text-secondary)}
.pl-loading{padding:32px 0;color:var(--ui-text-secondary);font-size:13px}
.pl-loading-lines{display:grid;gap:18px;margin-top:24px}.pl-loading-lines span{display:block;height:8px;background:var(--ui-bg-quaternary);border-radius:3px;width:100%}
.pl-footer{border-top:1px solid var(--ui-stroke-tertiary);padding-top:20px;font-size:11px;line-height:1.7;color:var(--ui-text-tertiary);max-width:75ch}
.pl-details{margin-top:12px;color:var(--ui-text-secondary);font-size:12px}.pl-details summary{cursor:pointer;padding:4px 0;list-style-position:inside}.pl-details dl{margin:8px 0;display:grid;gap:9px}.pl-details .pl-fact{display:flex;gap:16px;justify-content:space-between}.pl-details dt{margin:0}
.pl-page :focus-visible{outline:2px solid var(--ui-accent);outline-offset:4px;border-radius:3px}
.pl-page ::selection{background:var(--ui-accent);color:var(--ui-bg-primary)}
.pl-tabs-list{margin-bottom:8px;max-width:100%;overflow-x:auto}
.pl-history{border-top:1px solid var(--ui-stroke-tertiary);padding:26px 0 28px}
.pl-history h2{font-size:19px;font-weight:600;letter-spacing:-.015em;margin:0 0 8px}
.pl-history-top{display:flex;align-items:flex-start;justify-content:space-between;gap:16px}
.pl-stat-strip{display:flex;flex-wrap:wrap;gap:20px 36px;margin:24px 0}
.pl-stat-strip dt{font-size:12px;color:var(--ui-text-secondary);margin-bottom:8px}.pl-stat-strip dd{font-size:22px;font-weight:550;font-variant-numeric:tabular-nums;margin:0;letter-spacing:-.025em}
.pl-history-tools{display:flex;align-items:center;flex-wrap:wrap;gap:10px;margin:24px 0 16px}
.pl-search{flex:1;min-width:180px}.pl-select-wrap{flex:0 1 170px;min-width:0;max-width:100%}.pl-select-trigger{font-size:12px;overflow:hidden}.pl-select-trigger [data-slot=select-value]{display:block;flex:1 1 auto;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;text-align:left}
/* --dt-primary-solid* only exist from Hermes v2026.8.31. The older SDK's accent
   pair falls below AA in Everforest light and Solarized dark, so the compatibility
   path uses the opaque Nous-blue pair whose 5.599:1 text contrast is independent of
   the active palette. New hosts still use their contrast-guarded theme tokens. */
.pl-select-item:focus,.pl-select-item[data-highlighted]{background:var(--dt-primary-solid,#0053fd);color:var(--dt-primary-solid-foreground,#fcfcfc)}
.pl-table-wrap{max-width:100%;overflow:auto;scrollbar-color:var(--ui-stroke-primary) transparent}
.pl-table{width:100%;min-width:740px;border-collapse:collapse;text-align:left;font-size:12px;line-height:1.6}
.pl-table th{font-weight:500;color:var(--ui-text-secondary);padding:9px 12px;border-bottom:1px solid var(--ui-stroke-tertiary);white-space:nowrap}
.pl-table td{padding:14px 12px;vertical-align:top;border-bottom:1px solid var(--ui-stroke-tertiary)}
.pl-table th:first-child,.pl-table td:first-child{padding-left:0}.pl-table th:last-child,.pl-table td:last-child{padding-right:0}
.pl-table tbody tr:hover{background:var(--chrome-action-hover)}
.pl-session-title{font-size:13px;font-weight:550;max-width:360px;overflow-wrap:anywhere;color:var(--ui-text-primary)}
.pl-session-id{font-size:11px;color:var(--ui-text-tertiary);font-variant-numeric:tabular-nums;overflow-wrap:anywhere}
.pl-session-models{display:flex;flex-wrap:wrap;gap:3px 9px;margin-top:5px;font-size:11px;color:var(--ui-text-secondary);max-width:360px;overflow-wrap:anywhere}
.pl-numeric{font-variant-numeric:tabular-nums;white-space:nowrap;font-weight:550}.pl-submeasure{font-size:11px;font-weight:400;color:var(--ui-text-secondary);margin-top:4px;white-space:normal}
.pl-model-details summary{cursor:pointer;color:var(--ui-text-secondary);margin-top:10px;font-size:12px;list-style-position:inside}
.pl-model-details .pl-table{font-size:11px;margin-top:10px;min-width:600px}.pl-model-details .pl-table td{padding-top:8px;padding-bottom:8px}
.pl-detail-row td{padding-top:0}.pl-task{font-weight:400;font-size:11px;color:var(--ui-text-secondary)}
.pl-pagination{display:flex;justify-content:space-between;align-items:center;gap:12px;margin-top:16px;flex-wrap:wrap;font-size:12px;color:var(--ui-text-secondary)}
.pl-pagination-actions{display:flex;gap:8px}.pl-model-summary{margin:20px 0}
.pl-history-warning{font-size:12px;color:var(--ui-text-secondary);padding:12px 0;line-height:1.7}
@container (max-width:550px){.pl-content{padding:22px 20px}.pl-meta{padding-bottom:16px}.pl-section-head{align-items:flex-start}.pl-section{padding-top:24px}.pl-windows{grid-template-columns:1fr;gap:26px}.pl-status{font-size:11px}.pl-rest{font-size:21px}}
@media(prefers-reduced-motion:reduce){.pl-fill{transition:none}}
`

function Fact({ fact }) {
  return jsxs('div', { className: 'pl-fact', children: [h('dt', { children: fact.label }), h('dd', { children: isNumber(fact.value) ? nf.format(fact.value) : String(fact.value ?? '—') })] })
}

function Meter({ value }) {
  const w = value
  const known = isNumber(w.used_percent)
  const severity = known && w.used_percent >= 95 ? 'danger' : known && w.used_percent >= 80 ? 'warn' : 'normal'
  const absolute = isNumber(w.limit) || isNumber(w.used) || isNumber(w.remaining)
  return jsxs('div', { className: 'pl-window', 'data-severity': severity, children: [
    jsxs('div', { className: 'pl-window-top', children: [h('span', { className: 'pl-window-label', children: w.label }), jsxs('span', { className: 'pl-rest', children: [w.unlimited ? 'Sem limite' : pct(w.remaining_percent), !w.unlimited && h('small', { children: 'restante' })] })] }),
    h('div', { className: 'pl-track', 'data-unknown': !known, role: known ? 'progressbar' : undefined, 'aria-label': `${w.group} · ${w.label} · utilizado`, 'aria-valuemin': known ? 0 : undefined, 'aria-valuemax': known ? 100 : undefined, 'aria-valuenow': known ? Math.max(0, Math.min(100, w.used_percent)) : undefined, 'aria-valuetext': known ? `${pct(w.used_percent)} utilizado; ${pct(w.remaining_percent)} restante` : undefined, children: known && h('div', { className: 'pl-fill', style: { transform: `scaleX(${Math.min(100, Math.max(0, w.used_percent)) / 100})` } }) }),
    jsxs('div', { className: 'pl-measure', children: [h('span', { children: known ? `${pct(w.used_percent)} utilizado` : 'Utilização não indicada' }), h('span', { children: absolute ? `${amount(w.used, '')} / ${amount(w.limit, w.unit)}` : 'Quota da subscrição' })] }),
    absolute && isNumber(w.remaining) && h('p', { className: 'pl-note', children: `Disponível: ${amount(w.remaining, w.unit)}` }),
    jsxs('div', { className: 'pl-renewal', children: [resetText(w.reset_at), w.reset_at && h('time', { dateTime: w.reset_at, children: dtf.format(new Date(w.reset_at)) })] }),
    w.details?.length > 0 && jsxs('details', { className: 'pl-details', children: [h('summary', { children: 'Detalhe de utilização' }), h('dl', { children: w.details.map((fact, i) => h(Fact, { fact }, i)) })] })
  ] })
}

function Provider({ provider, ctx }) {
  const p = provider
  const groups = new Map()
  for (const w of p.windows) {
    if (!groups.has(w.group)) groups.set(w.group, [])
    groups.get(w.group).push(w)
  }
  const status = { ok: 'Atualizado', stale: 'Dados anteriores', unavailable: 'Indisponível' }[p.status] || p.status
  return jsxs('section', { className: 'pl-section', 'aria-labelledby': `pl-${p.id}`, children: [
    jsxs('div', { className: 'pl-section-head', children: [
      jsxs('div', { className: 'pl-identity', children: [h('span', { className: 'pl-mark', 'aria-hidden': true, children: { 'openai-codex': '>_', anthropic: 'Cl', deepseekv4pro: 'ds', zai: 'Z' }[p.id] }), jsxs('div', { children: [h('h2', { id: `pl-${p.id}`, children: p.name }), h('div', { className: 'pl-plan', children: p.plan ? `Plano ${p.plan}` : { 'openai-codex': 'Subscrição ChatGPT', anthropic: 'Subscrição Claude', deepseekv4pro: 'deepseekv4pro.com', zai: 'Coding Plan' }[p.id] })] })] }),
      jsxs('div', { className: 'pl-status', children: [p.status === 'ok' && h('span', { className: 'pl-status-dot' }), status] })
    ] }),
    p.error && jsxs('div', { className: 'pl-alert', role: 'status', children: [h(Codicon, { name: 'warning' }), jsxs('div', { children: [p.status === 'stale' && h('strong', { children: 'A atualização falhou. Os valores abaixo são anteriores.' }), p.error] })] }),
    ...Array.from(groups, ([group, windows]) => jsxs('div', { className: 'pl-group', children: [h('h3', { className: 'pl-group-title', children: group }), h('div', { className: 'pl-windows', children: windows.map(w => h(Meter, { value: w }, w.id)) })] }, group)),
    p.facts?.length > 0 && h('dl', { className: 'pl-facts', children: p.facts.map((fact, i) => h(Fact, { fact }, i)) }),
    jsxs('div', { className: 'pl-source', children: [p.source && h('span', { children: `Fonte: ${p.source}` }), p.fetched_at && h('time', { dateTime: p.fetched_at, children: `Consultado ${dtf.format(new Date(p.fetched_at))}` }), p.url && ctx.os?.openExternal && h(Button, { variant: 'link', size: 'inline', onClick: () => ctx.os.openExternal(p.url), children: 'Abrir no fornecedor' })] })
  ] })
}

const usd = new Intl.NumberFormat('pt-PT', { style: 'currency', currency: 'USD', maximumFractionDigits: 4 })
const taskLabels = { main: 'Conversa', approval: 'Aprovações', title_generation: 'Título', vision: 'Visão', compression: 'Compressão', goal_judge: 'Avaliação', background_review: 'Revisão' }
function costText(row) {
  if (row.cost_state === 'included') return 'Incluído no plano'
  const parts = []
  if (isNumber(row.actual_cost_usd)) parts.push(usd.format(row.actual_cost_usd))
  if (isNumber(row.estimated_cost_usd)) parts.push(`≈ ${usd.format(row.estimated_cost_usd)}`)
  return parts.length ? `${parts.join(' + ')}${row.cost_state === 'mixed' ? ' (parcial)' : ''}` : 'Não registado'
}
function ModelTable({ rows, tasks = false }) {
  const headings = [tasks ? 'Modelo / tarefa' : 'Modelo', 'Entrada¹', 'Saída', 'Cache lida', 'Cache escrita', 'Raciocínio²', 'Total', 'Custo USD']
  return h('div', { className: 'pl-table-wrap', tabIndex: 0, role: 'region', 'aria-label': tasks ? 'Utilização por modelo e tarefa' : 'Resumo por modelo', children: jsxs('table', { className: 'pl-table', children: [
    h('thead', { children: h('tr', { children: headings.map(label => h('th', { scope: 'col', children: label }, label)) }) }),
    h('tbody', { children: rows.map((r, index) => jsxs('tr', { children: [jsxs('td', { children: [r.model, tasks && h('div', { className: 'pl-task', children: taskLabels[r.task] || r.task }), r.attribution === 'session_summary' && h('div', { className: 'pl-task', children: 'Resumo antigo da sessão' })] }), ...['input_tokens', 'output_tokens', 'cache_read_tokens', 'cache_write_tokens', 'reasoning_tokens', 'total_tokens'].map(k => h('td', { className: 'pl-numeric', children: nf.format(r[k]) }, k)), h('td', { children: costText(r) })] }, `${r.model}-${index}`)) })
  ] }) })
}
function SessionRows({ session: s }) {
  const [open, setOpen] = useState(false)
  const row = s.summary
  return [jsxs('tr', { children: [
    jsxs('td', { children: [h('div', { className: 'pl-session-title', children: s.title }), h('div', { className: 'pl-session-id', children: `${s.session_id} · ${s.source}` }), h('div', { className: 'pl-session-models', children: [...new Set(s.models.map(m => m.model))].map(name => h('span', { children: name }, name)) }), h(Button, { variant: 'link', size: 'inline', 'aria-expanded': open, 'aria-controls': `pl-detail-${s.session_id}`, onClick: () => setOpen(v => !v), children: open ? 'Ocultar detalhe' : 'Modelos e tarefas' })] }),
    jsxs('td', { className: 'pl-numeric', children: [nf.format(row.total_tokens), h('div', { className: 'pl-submeasure', children: `${nf.format(row.input_tokens + row.cache_read_tokens + row.cache_write_tokens)} entrada · ${nf.format(row.output_tokens)} saída` })] }),
    h('td', { className: 'pl-numeric', children: nf.format(row.api_call_count) }),
    h('td', { children: costText(row) }),
    h('td', { title: 'Créditos por sessão não registados pelo Hermes', children: '—' })
  ] }, s.session_id), open && h('tr', { className: 'pl-detail-row', id: `pl-detail-${s.session_id}`, children: jsxs('td', { colSpan: 5, children: [h(ModelTable, { rows: s.models, tasks: true }), h('p', { className: 'pl-note', children: '¹ Entrada sem cache; o total inclui cache lida e escrita. ² Raciocínio já incluído na saída, não volta a ser somado.' })] }) }, `${s.session_id}-details`)]
}
function UsageHistory({ ctx, provider, profile, connection }) {
  const [search, setSearch] = useState('')
  const [needle, setNeedle] = useState('')
  const [model, setModel] = useState('')
  const [sort, setSort] = useState('tokens')
  const [offset, setOffset] = useState(0)
  useEffect(() => { const timer = setTimeout(() => { setNeedle(search); setOffset(0) }, 300); return () => clearTimeout(timer) }, [search])
  const query = useQuery({
    queryKey: ['provider-limits-history', connection, profile, provider, needle, model, sort, offset],
    queryFn: () => ctx.rest(`/history?${new URLSearchParams({ provider, profile, q: needle, model, sort, offset: String(offset), limit: '25' })}`, { method: 'GET', timeoutMs: 15000 }),
    staleTime: 10000, refetchInterval: q => q.state.error ? false : 60000, refetchIntervalInBackground: false, retry: false
  })
  const d = query.data
  const problem = query.error || d?.error
  return jsxs('section', { className: 'pl-history', 'aria-label': 'Consumo registado no Hermes', children: [
    jsxs('div', { className: 'pl-history-top', children: [jsxs('div', { children: [h('h2', { children: 'Consumo no Hermes' }), h('p', { className: 'pl-description', children: 'O que cada sessão e modelo consumiu, incluindo tarefas auxiliares.' })] }), h(Button, { variant: 'ghost', size: 'sm', disabled: query.isFetching, onClick: () => query.refetch(), children: 'Atualizar histórico' })] }),
    jsxs('div', { className: 'pl-history-tools', children: [h('div', { className: 'pl-search', children: h(Input, { 'aria-label': 'Procurar sessão ou modelo', placeholder: 'Procurar sessão, ID ou modelo…', value: search, onChange: e => setSearch(e.target.value) }) }),
      h('div', { className: 'pl-select-wrap', children: h(Select, { value: model ? `${MODEL_VALUE_PREFIX}${model}` : ALL_MODELS, onValueChange: value => { setModel(value === ALL_MODELS ? '' : value.slice(MODEL_VALUE_PREFIX.length)); setOffset(0) }, children: [h(SelectTrigger, { className: 'pl-select-trigger', 'aria-label': 'Filtrar modelo', children: h(SelectValue, {}) }), h(SelectContent, { children: [h(SelectItem, { className: 'pl-select-item', value: ALL_MODELS, children: 'Todos os modelos' }), ...(d?.model_options || (model ? [model] : [])).map(name => h(SelectItem, { className: 'pl-select-item', value: `${MODEL_VALUE_PREFIX}${name}`, children: name }, name))] })] }) }),
      h('div', { className: 'pl-select-wrap', children: h(Select, { value: sort, onValueChange: value => { setSort(value); setOffset(0) }, children: [h(SelectTrigger, { className: 'pl-select-trigger', 'aria-label': 'Ordenar sessões', children: h(SelectValue, {}) }), h(SelectContent, { children: [h(SelectItem, { className: 'pl-select-item', value: 'tokens', children: 'Mais tokens' }), h(SelectItem, { className: 'pl-select-item', value: 'recent', children: 'Atividade recente' })] })] }) })] }),
    query.isPending && h('p', { className: 'pl-loading', role: 'status', children: 'A ler o registo do Hermes…' }),
    problem && h('div', { className: 'pl-alert', role: 'alert', children: d?.error || 'O histórico não está disponível neste backend. Se acabou de atualizar o plugin, reabra o Hermes Desktop depois das conversas em curso.' }),
    d && !problem && jsxs('div', { children: [
      h('dl', { className: 'pl-stat-strip', children: [{ label: 'Tokens registados', value: nf.format(d.totals.total_tokens) }, { label: 'Sessões', value: nf.format(d.total_sessions) }, { label: 'Modelos', value: nf.format(d.by_model.length) }, { label: 'Créditos por sessão', value: 'Não registados' }].map(f => h(Fact, { fact: f }, f.label)) }),
      h('p', { className: 'pl-note', children: `${d.period} Custos em USD: ≈ estimado; «Incluído» não significa zero créditos. O Hermes não guarda os créditos debitados por sessão.` }),
      d.coverage.unattributed_main_tokens_in_profile > 0 && h('p', { className: 'pl-history-warning', children: `No perfil existem ${nf.format(d.coverage.unattributed_main_tokens_in_profile)} tokens de resumos sem atribuição segura a modelo/fornecedor. Não foram imputados a estes totais.` }),
      d.coverage.legacy_sessions > 0 && h('p', { className: 'pl-note', children: `${nf.format(d.coverage.legacy_sessions)} sessões antigas usam o modelo registado no resumo; eventuais trocas de modelo não podem ser reconstruídas.` }),
      d.by_model.length > 0 && jsxs('details', { className: 'pl-model-details pl-model-summary', children: [h('summary', { children: `Resumo por modelo (${d.by_model.length})` }), h(ModelTable, { rows: d.by_model })] }),
      d.sessions.length > 0 ? h('div', { className: 'pl-table-wrap', tabIndex: 0, role: 'region', 'aria-label': 'Sessões e consumo', children: jsxs('table', { className: 'pl-table', children: [h('thead', { children: h('tr', { children: ['Sessão / modelos', 'Tokens', 'Chamadas', 'Custo USD', 'Créditos'].map(t => h('th', { scope: 'col', children: t }, t)) }) }), h('tbody', { children: d.sessions.map(s => h(SessionRows, { session: s }, s.session_id)) })] }) }) : h('p', { className: 'pl-empty', children: needle || model ? 'Nenhuma sessão corresponde aos filtros.' : 'Ainda não existem consumos registados para este fornecedor neste perfil.' }),
      jsxs('div', { className: 'pl-pagination', children: [h('span', { children: d.total_sessions ? `${offset + 1}–${Math.min(offset + d.sessions.length, d.total_sessions)} de ${d.total_sessions} sessões` : '0 sessões' }), jsxs('div', { className: 'pl-pagination-actions', children: [h(Button, { variant: 'secondary', size: 'sm', disabled: offset === 0 || query.isFetching, onClick: () => setOffset(Math.max(0, offset - 25)), children: 'Anterior' }), h(Button, { variant: 'secondary', size: 'sm', disabled: !d.has_more || query.isFetching, onClick: () => setOffset(offset + 25), children: 'Seguinte' })] })] }),
      h('p', { className: 'pl-source', children: `${d.source} · Só este perfil · Conversas, delegações e auxiliares discriminados` })
    ] })
  ] })
}

export function QuotaPage({ ctx }) {
  const profile = useValue(host.state.profile) || 'default'
  // Hosts predating requires_hermes enforcement can still evaluate a copied
  // plugin.js. Keep the hook shape stable and never call useValue(undefined).
  const hasConnectionState = Boolean(host.state.connectionId)
  const connectionValue = useValue(host.state.connectionId || host.state.profile)
  const connection = hasConnectionState ? connectionValue : null
  const client = useQueryClient()
  const [preferred, setPreferred] = useState('')
  const query = useQuery({
    queryKey: ['provider-limits', connection, profile],
    queryFn: async () => {
      const data = await ctx.rest(`/quota?profile=${encodeURIComponent(profile)}`, { method: 'GET', timeoutMs: 55000 })
      if (!data || !Array.isArray(data.providers)) throw new Error('INVALID_RESPONSE')
      return data
    },
    staleTime: 60000, refetchInterval: q => q.state.error ? false : 60000,
    refetchIntervalInBackground: false, refetchOnWindowFocus: true, retry: false
  })
  const providers = query.data?.providers || []
  const selected = providers.some(p => p.id === preferred) ? preferred : providers[0]?.id || ''
  const count = providers.reduce((n, p) => n + p.windows.length, 0)
  const backendMissing = query.error && /404|not found/i.test(String(query.error))
  return jsxs('div', { className: 'pl-page', children: [h('style', { children: CSS }), jsxs('div', { className: 'pl-content', children: [
    jsxs('header', { className: 'pl-header', children: [jsxs('div', { children: [h('h1', { children: 'Utilização e limites' }), h('p', { className: 'pl-description', children: 'Quotas da conta e consumo do Hermes, sessão a sessão.' })] }), jsxs(Button, { variant: 'secondary', size: 'sm', disabled: query.isFetching, onClick: () => { query.refetch(); client.invalidateQueries({ queryKey: ['provider-limits-history', connection, profile] }) }, children: [h(Codicon, { name: 'refresh' }), query.isFetching ? 'A atualizar…' : 'Atualizar'] })] }),
    jsxs('div', { className: 'pl-meta', children: [jsxs('span', { className: 'pl-profile', children: [h(Codicon, { name: 'account' }), `Perfil ${profile}`] }), query.data && h('span', { children: `${providers.length} ${providers.length === 1 ? 'fornecedor ativo' : 'fornecedores ativos'} · ${count} ${count === 1 ? 'limite' : 'limites'}` }), h('span', { children: 'Consulta automática · 1 min' })] }),
    query.isPending && h('div', { className: 'pl-loading', role: 'status', 'aria-live': 'polite', children: jsxs('div', { children: ['A consultar os fornecedores ativos neste perfil…', h('div', { className: 'pl-loading-lines', 'aria-hidden': true, children: [h('span', {}), h('span', {}), h('span', {})] })] }) }),
    (query.error || query.data?.error) && jsxs('div', { className: 'pl-alert', role: 'alert', children: [h(Codicon, { name: 'info' }), jsxs('div', { children: [h('strong', { children: backendMissing ? 'O backend ainda não carregou o plugin' : 'Não foi possível atualizar' }), backendMissing ? 'O plugin já está instalado. Quando as conversas terminarem, feche e volte a abrir o Hermes Desktop para carregar o backend. Não é necessário voltar a configurar as contas.' : query.data?.error || 'Verifique a ligação ao Hermes e tente Atualizar. Não estamos a apresentar valores inventados.'] })] }),
    !query.isPending && !query.error && !query.data?.error && providers.length === 0 && jsxs('div', { className: 'pl-empty', children: [h(Codicon, { name: 'plug' }), h('h2', { children: 'Nenhum destes fornecedores está ativo' }), h('p', { children: 'Ative Codex, Claude, deepseekv4pro.com ou Z.ai nas definições de modelos deste perfil. O painel usa as credenciais do Hermes, sem pedir outras chaves.' })] }),
    providers.length > 0 && jsxs(Tabs, { value: selected, onValueChange: setPreferred, children: [
      h(TabsList, { className: 'pl-tabs-list', 'aria-label': 'Fornecedores ativos', children: providers.map(p => h(TabsTrigger, { value: p.id, id: `pl-tab-${p.id}`, 'aria-controls': `pl-panel-${p.id}`, children: p.name }, p.id)) }),
      ...providers.filter(p => p.id === selected).map(p => jsxs('div', { role: 'tabpanel', id: `pl-panel-${p.id}`, 'aria-labelledby': `pl-tab-${p.id}`, tabIndex: 0, children: [h(Provider, { provider: query.error ? { ...p, status: 'stale', error: 'A atualização falhou; estes valores são anteriores.' } : p, ctx }), h(UsageHistory, { ctx, provider: p.id, profile, connection }, `${connection}:${profile}:${p.id}`)] }, p.id))
    ] }),
    h('footer', { className: 'pl-footer', children: 'Apenas fornecedores configurados e ativos neste perfil. Os limites vêm de cada API; uma percentagem não permite deduzir um teto de tokens. Janelas e modelos diferentes não são somados. As chaves permanecem no backend. Atualizar respeita a cache de 60 segundos.' })
  ] })] })
}

export default {
  id: 'provider-limits',
  name: 'Utilização e limites',
  description: 'Consumo, restante e renovações dos fornecedores ativos no Hermes.',
  register(ctx) {
    ctx.registerMany([
      { id: 'page', area: ROUTES_AREA, data: { path: PATH }, render: () => h(QuotaPage, { ctx }) },
      { id: 'nav', area: SIDEBAR_NAV_AREA, order: 75, data: { path: PATH, label: 'Utilização', codicon: 'graph' } },
      { id: 'open', area: PALETTE_AREA, data: { id: 'provider-limits.open', label: 'Abrir utilização e limites', keywords: ['quota', 'codex', 'spark', 'claude', 'deepseek', 'glm', 'zai'], run: () => host.navigate(PATH) } }
    ])
  }
}
