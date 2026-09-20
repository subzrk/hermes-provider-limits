import assert from 'node:assert/strict'
import fs from 'node:fs/promises'
import test from 'node:test'
import vm from 'node:vm'

const ROOT = new URL('../', import.meta.url)
const PROFILE_ID = 'b'.repeat(64)
const provider = (id, name) => ({ id, name, status: 'ok', windows: [], facts: [] })
const quota = {
  schema_version: 3, profile: 'angel', profile_identity: { name: 'angel', id: PROFILE_ID },
  providers: [provider('zai', 'GLM / Z.ai'), provider('openai-codex', 'Codex'), provider('anthropic', 'Claude')]
}

async function loadPlugin(enabled = {}, queryResult = { data: quota, error: null, isPending: false, isFetching: false, refetch() {} }) {
  const source = await fs.readFile(new URL('desktop/plugin.js', ROOT), 'utf8')
  const state = { contributions: [], queries: [], restCalls: 0 }
  const context = vm.createContext({ console, URL, URLSearchParams, Intl, Date, Math, Map, Set, Number, String, Object, Array, Promise, Error, RegExp, JSON, encodeURIComponent, setTimeout, clearTimeout })
  const module = new vm.SourceTextModule(source, { context })
  const synthetic = (id, values) => new vm.SyntheticModule(Object.keys(values), function () {
    for (const [name, value] of Object.entries(values)) this.setExport(name, value)
  }, { context, identifier: id })
  const atom = initial => { let value = initial; return { get: () => value, set: next => { value = next } } }
  const sdkComponent = name => { const component = () => null; component.sdkName = name; return component }
  const jsx = (type, props = {}, key) => {
    if (typeof type === 'function') {
      if (type.sdkName) return { type: type.sdkName, props, key }
      return type(props)
    }
    return { type, props, key }
  }
  const host = { state: { profile: {}, connectionId: {} }, navigate() {} }
  const components = Object.fromEntries(['Button', 'Switch', 'Input', 'Codicon', 'Select', 'SelectContent', 'SelectItem', 'SelectTrigger', 'SelectValue', 'Tabs', 'TabsList', 'TabsTrigger', 'Popover', 'PopoverTrigger', 'PopoverContent'].map(name => [name, sdkComponent(name)]))
  const sdk = {
    ...components, atom, host,
    useValue: store => typeof store.get === 'function' ? store.get() : store === host.state.profile ? 'angel' : 'local',
    useQuery: options => { state.queries.push(options); return queryResult },
    useQueryClient: () => ({ invalidateQueries() {} }),
    usePluginI18n: () => key => key,
    useI18n: () => ({ locale: 'en' }),
    ROUTES_AREA: 'routes', SIDEBAR_NAV_AREA: 'sidebar', PALETTE_AREA: 'palette', STATUSBAR_AREAS: { right: 'status-right' }
  }
  await module.link(specifier => {
    if (specifier === 'react/jsx-runtime') return synthetic(specifier, { jsx, jsxs: jsx })
    if (specifier === 'react') return synthetic(specifier, { useState: value => [value, () => {}], useEffect: () => {}, useMemo: fn => fn() })
    return synthetic(specifier, sdk)
  })
  await module.evaluate()
  const scope = JSON.stringify(['local', 'angel'])
  const ctx = {
    i18n: { register() {}, t: key => key },
    registerMany(items) { state.contributions.push(...items) },
    storage: { get: () => ({ version: 1, scopes: { [scope]: enabled } }), set() {} },
    rest: async () => { state.restCalls += 1; return quota }
  }
  module.namespace.default.register(ctx)
  return { mod: module.namespace, state }
}

function walk(value, output = []) {
  if (Array.isArray(value)) { for (const item of value) walk(item, output); return output }
  if (!value || typeof value !== 'object') return output
  if (value.type) output.push(value)
  walk(value.props?.children, output)
  return output
}

const text = node => walk(node).flatMap(item => {
  const children = item.props?.children
  return typeof children === 'string' ? [children] : []
}).join(' ')

test('registers exactly one right status-bar contribution', async () => {
  const { state } = await loadPlugin()
  const status = state.contributions.filter(item => item.area === 'status-right')
  assert.equal(status.length, 1)
  assert.equal(status[0].id, 'status-gauges')
  assert.equal(status[0].order, 90)
})

test('default-off status root renders null with one disabled shared query', async () => {
  const { state } = await loadPlugin()
  const status = state.contributions.find(item => item.area === 'status-right')
  assert.equal(status.render(), null)
  assert.equal(state.queries.length, 1)
  assert.equal(state.queries[0].enabled, false)
  assert.deepEqual(Array.from(state.queries[0].queryKey), ['provider-limits', 3, 'local', 'angel'])
  assert.equal(state.restCalls, 0)
})

test('one or three enabled providers still use one quota query and stable chip order', async () => {
  for (const enabled of [
    { anthropic: true },
    { anthropic: true, 'openai-codex': true, zai: true }
  ]) {
    const { state } = await loadPlugin(enabled)
    const root = state.contributions.find(item => item.area === 'status-right').render()
    assert.equal(state.queries.length, 1)
    assert.equal(state.queries[0].enabled, true)
    const chips = walk(root).filter(node => node.props?.['data-provider-chip'])
    assert.deepEqual(chips.map(node => node.props['data-provider-chip']), Object.keys(enabled).filter(id => enabled[id]))
  }
})

test('canonical selectors reject missing and ambiguous weekly windows', async () => {
  const { mod } = await loadPlugin()
  const { selectProviderWindows } = mod
  const weekly = { id: 'seven_day', group: 'Claude', period_seconds: 604800, used_percent: 20 }
  const five = { id: 'five_hour', group: 'Claude', period_seconds: 18000, used_percent: 10 }
  let selected = selectProviderWindows({ id: 'anthropic', windows: [five, weekly] })
  assert.equal(selected.weekly.used_percent, 20)
  assert.deepEqual(JSON.parse(JSON.stringify(selected.relevant.map(item => item.id))), ['five_hour', 'seven_day'])
  assert.equal(selectProviderWindows({ id: 'anthropic', windows: [weekly, { ...weekly }] }).weekly, null)
  assert.equal(selectProviderWindows({ id: 'anthropic', windows: [five] }).weekly, null)

  selected = selectProviderWindows({ id: 'openai-codex', windows: [
    { group: 'Code review', period_seconds: 604800 },
    { group: 'Codex', period_seconds: 604800, used_percent: 30 }
  ] })
  assert.equal(selected.weekly.used_percent, 30)
  assert.equal(selectProviderWindows({ id: 'openai-codex', windows: [
    { group: 'Codex', period_seconds: 604800 }, { group: 'Codex', period_seconds: 604800 }
  ] }).weekly, null)

  selected = selectProviderWindows({ id: 'zai', windows: [
    { unit_code: 'credit', period_seconds: 604800 },
    { unit_code: 'token', period_seconds: 604800, used_percent: 40 }
  ] })
  assert.equal(selected.weekly.used_percent, 40)
})

test('pace math honors the start threshold, stale and rolling suppression, and uncapped projection', async () => {
  const { mod } = await loadPlugin()
  const { quotaPaceState, paceSegments } = mod
  const now = Date.parse('2026-09-20T00:00:00Z')
  const make = (used, elapsed, extra = {}) => ({
    used_percent: used,
    period_seconds: 100000,
    reset_at: new Date(now + (1 - elapsed) * 100000 * 1000).toISOString(),
    ...extra
  })
  assert.equal(quotaPaceState(make(1, 0), 'ok', now).allowance, null)
  assert.equal(quotaPaceState(make(1, 0.02), 'ok', now).allowance, null)
  const over = quotaPaceState(make(60, 0.4), 'ok', now)
  assert.equal(over.allowance, 40)
  assert.equal(over.projection, 150)
  assert.equal(over.level, 'critical')
  assert.equal(quotaPaceState(make(20, 0.4, { rolling: true }), 'ok', now).allowance, null)
  assert.equal(quotaPaceState(make(20, 0.4), 'stale', now).allowance, null)
  assert.deepEqual(JSON.parse(JSON.stringify(paceSegments(60, 40))), { used: 40, paceRoom: 0, overPace: 20, remaining: 40 })
  assert.deepEqual(JSON.parse(JSON.stringify(paceSegments(20, 40))), { used: 20, paceRoom: 20, overPace: 0, remaining: 60 })
})

test('provider chips are semantic buttons inside native popovers without hover tooltips', async () => {
  const reset = new Date(Date.now() + 4 * 86400000).toISOString()
  const providers = quota.providers.map(item => ({ ...item, windows: item.id === 'anthropic'
    ? [{ id: 'five_hour', group: 'Claude', period_seconds: 18000, used_percent: 5, reset_at: reset }, { id: 'seven_day', group: 'Claude', period_seconds: 604800, used_percent: 20, reset_at: reset }]
    : item.id === 'openai-codex'
      ? [{ id: 'weekly', group: 'Codex', period_seconds: 604800, used_percent: 30, reset_at: reset }]
      : [{ id: 'weekly', unit_code: 'token', period_seconds: 604800, used_percent: 40, reset_at: reset }]
  }))
  const result = { data: { ...quota, providers }, error: null, isPending: false, isFetching: false, refetch() {} }
  const { state } = await loadPlugin({ anthropic: true, 'openai-codex': true, zai: true }, result)
  const root = state.contributions.find(item => item.area === 'status-right').render()
  const nodes = walk(root)
  assert.equal(nodes.filter(node => node.type === 'Popover').length, 3)
  const triggers = nodes.filter(node => node.type === 'PopoverTrigger')
  assert.equal(triggers.length, 3)
  assert.ok(triggers.every(trigger => trigger.props.asChild === true))
  const buttons = nodes.filter(node => node.type === 'button' && node.props['data-provider-chip'])
  assert.deepEqual(buttons.map(node => node.props['data-provider-chip']), ['anthropic', 'openai-codex', 'zai'])
  assert.ok(buttons.every(button => button.props.type === 'button' && button.props.title === undefined))
  assert.ok(buttons.every(button => /chrome-action-hover/.test(button.props.className)))
  assert.equal(nodes.filter(node => node.type === 'Tip').length, 0)
  const contents = nodes.filter(node => node.type === 'PopoverContent')
  assert.equal(contents.length, 3)
  assert.ok(contents.every(content => content.props.side === 'top' && content.props.align === 'end'))
})

test('backend 404 renders the scoped unavailable state instead of provider data', async () => {
  const result = { data: undefined, error: new Error('404 not found'), isPending: false, isFetching: false, refetch() {} }
  const { state } = await loadPlugin({ anthropic: true }, result)
  const root = state.contributions.find(item => item.area === 'status-right').render()
  assert.match(text(root), /statusBar\.backendUnavailable/)
  assert.equal(walk(root).filter(node => node.props?.['data-provider-chip']).length, 0)
})
