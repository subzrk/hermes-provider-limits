const assert = require('node:assert/strict')
const fs = require('node:fs')
const path = require('node:path')
const test = require('node:test')
const vm = require('node:vm')

const pluginPath = path.join(__dirname, '..', 'desktop', 'plugin.js')

function sdkComponent(name) {
  const component = () => null
  component.sdkName = name
  return component
}

function walk(value, output = []) {
  if (Array.isArray(value)) {
    for (const item of value) walk(item, output)
    return output
  }
  if (!value || typeof value !== 'object') return output
  if (value.type) output.push(value)
  walk(value.props?.children, output)
  return output
}

async function renderPage() {
  const stateUpdates = []
  let stateIndex = 0
  const host = {
    navigate() {},
    state: { connectionId: {}, profile: {} }
  }
  const components = Object.fromEntries([
    'Button', 'Codicon', 'Input', 'Select', 'SelectContent', 'SelectItem',
    'SelectTrigger', 'SelectValue', 'Tabs', 'TabsList', 'TabsTrigger'
  ].map(name => [name, sdkComponent(name)]))
  const jsx = (type, props = {}) => {
    if (typeof type === 'function') {
      if (type.sdkName) return { type: type.sdkName, props }
      return type(props)
    }
    return { type, props }
  }
  const useState = initial => {
    const index = stateIndex++
    return [initial, value => stateUpdates.push({ index, value: typeof value === 'function' ? value(initial) : value })]
  }
  const quota = {
    providers: [{ id: 'openai-codex', name: 'Codex', status: 'ok', plan: null, windows: [], facts: [], source: null, fetched_at: null, url: null }]
  }
  const history = {
    by_model: [],
    coverage: { legacy_sessions: 0, unattributed_main_tokens_in_profile: 0 },
    has_more: false,
    model_options: ['gpt-5', 'claude-sonnet', '__provider_limits_all_models__'],
    period: 'Histórico acumulado.',
    sessions: [],
    source: 'state.db',
    total_sessions: 0,
    totals: { total_tokens: 0 }
  }
  const useQuery = options => ({
    data: options.queryKey[0] === 'provider-limits-history' ? history : quota,
    error: null,
    isFetching: false,
    isPending: false,
    refetch() {}
  })
  const context = vm.createContext({
    Array, Date, Error, Intl, Map, Math, Number, Object, RegExp, Set, String,
    URLSearchParams, clearTimeout, console, encodeURIComponent, setTimeout
  })
  const jsxModule = new vm.SyntheticModule(['jsx', 'jsxs'], function () {
    this.setExport('jsx', jsx)
    this.setExport('jsxs', jsx)
  }, { context })
  const reactModule = new vm.SyntheticModule(['useEffect', 'useState'], function () {
    this.setExport('useEffect', () => {})
    this.setExport('useState', useState)
  }, { context })
  const sdkExports = {
    ...components,
    PALETTE_AREA: 'palette',
    ROUTES_AREA: 'routes',
    SIDEBAR_NAV_AREA: 'sidebar',
    host,
    useQuery,
    useQueryClient: () => ({ invalidateQueries() {} }),
    useValue: atom => atom === host.state.profile ? 'default' : 'local'
  }
  const sdkModule = new vm.SyntheticModule(Object.keys(sdkExports), function () {
    for (const [name, value] of Object.entries(sdkExports)) this.setExport(name, value)
  }, { context })
  const pluginModule = new vm.SourceTextModule(fs.readFileSync(pluginPath, 'utf8'), {
    context,
    identifier: pluginPath
  })
  await pluginModule.link(specifier => ({
    'react/jsx-runtime': jsxModule,
    react: reactModule,
    '@hermes/plugin-sdk': sdkModule
  })[specifier])
  await pluginModule.evaluate()

  const contributions = []
  const ctx = {
    os: { openExternal() {} },
    registerMany(items) { contributions.push(...items) },
    rest() { throw new Error('render test must not fetch directly') }
  }
  pluginModule.namespace.default.register(ctx)
  const route = contributions.find(item => item.area === 'routes')
  return { nodes: walk(route.render()), stateUpdates }
}

test('history filters use Hermes themed selects instead of native popups', async () => {
  const { nodes } = await renderPage()

  assert.equal(nodes.filter(node => node.type === 'Select').length, 2)
  assert.equal(nodes.filter(node => node.type === 'SelectTrigger').length, 2)
  assert.equal(nodes.filter(node => node.type === 'SelectContent').length, 2)
  assert.equal(nodes.filter(node => node.type === 'select').length, 0)
  assert.equal(nodes.filter(node => node.type === 'option').length, 0)
})

test('themed history selects preserve model and sort changes', async () => {
  const { nodes, stateUpdates } = await renderPage()
  const selects = nodes.filter(node => node.type === 'Select')
  const modelItems = walk(selects[0].props.children).filter(node => node.type === 'SelectItem')
  const gpt5 = modelItems.find(item => item.props.children === 'gpt-5')

  selects[0].props.onValueChange(gpt5.props.value)
  selects[1].props.onValueChange('recent')

  assert.deepEqual(stateUpdates.map(update => update.value), ['gpt-5', 0, 'recent', 0])
})

test('history selects stay compact and provide theme-safe control classes', async () => {
  const { nodes } = await renderPage()

  assert.equal(nodes.filter(node => node.type === 'div' && node.props.className === 'pl-select-wrap').length, 2)
  const triggers = nodes.filter(node => node.type === 'SelectTrigger')
  assert.equal(triggers.length, 2)
  assert.ok(triggers.every(trigger => trigger.props.className === 'pl-select-trigger'))
  const items = nodes.filter(node => node.type === 'SelectItem')
  assert.ok(items.length > 0)
  assert.ok(items.every(item => item.props.className === 'pl-select-item'))
})

test('all-models control value cannot collide with a literal model name', async () => {
  const { nodes, stateUpdates } = await renderPage()
  const modelSelect = nodes.find(node => node.type === 'Select')
  const items = walk(modelSelect.props.children).filter(node => node.type === 'SelectItem')
  const values = items.map(item => item.props.value)
  const literalSentinelModel = items.find(item => item.props.children === '__provider_limits_all_models__')
  const allModels = items.find(item => item.props.children === 'Todos os modelos')

  assert.equal(new Set(values).size, values.length)
  modelSelect.props.onValueChange(literalSentinelModel.props.value)
  modelSelect.props.onValueChange(allModels.props.value)
  assert.deepEqual(stateUpdates.map(update => update.value), ['__provider_limits_all_models__', 0, '', 0])
})
