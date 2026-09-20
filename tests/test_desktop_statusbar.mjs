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

test('backend 404 renders the scoped unavailable state instead of provider data', async () => {
  const result = { data: undefined, error: new Error('404 not found'), isPending: false, isFetching: false, refetch() {} }
  const { state } = await loadPlugin({ anthropic: true }, result)
  const root = state.contributions.find(item => item.area === 'status-right').render()
  assert.match(text(root), /statusBar\.backendUnavailable/)
  assert.equal(walk(root).filter(node => node.props?.['data-provider-chip']).length, 0)
})
