// Real computed-style verification of the themed-select highlight.
//
// The string assertions in test_desktop_selects.cjs prove the CSS text contains a
// fallback; they cannot prove a browser RESOLVES it to a visible highlight. This
// renders the plugin's own CSS in Chromium against the token declarations Hermes
// actually ships, for both token generations:
//
//   pre-v2026.8.31 (e.g. v2026.7.20, v2026.8.27): --dt-accent* defined,
//                                                 --dt-primary-solid* absent
//   v2026.8.31+:                                  --dt-primary-solid* defined
//
// Token values below are copied verbatim from apps/desktop/src/styles.css at the
// corresponding tags. Skips cleanly when Playwright is unavailable.
const assert = require('node:assert/strict')
const fs = require('node:fs')
const path = require('node:path')
const test = require('node:test')

let chromium = null
try {
  ({ chromium } = require('playwright'))
} catch {
  try {
    ({ chromium } = require('/home/subzrk/.hermes/hermes-agent/node_modules/playwright'))
  } catch { /* stays null; tests skip */ }
}

const source = fs.readFileSync(path.join(__dirname, '..', 'desktop', 'plugin.js'), 'utf8')
const cssMatch = source.match(/export const CSS = `([\s\S]*?)`\n/)
assert.ok(cssMatch, 'could not extract CSS from desktop/plugin.js')
const PLUGIN_CSS = cssMatch[1]

// Verbatim from apps/desktop/src/styles.css :root at each tag.
const SHARED_TOKENS = `
  color-scheme: light;
  --theme-primary: #0053fd;
  --theme-foreground: #111111;
  --theme-accent-soft: color-mix(in srgb, #0053fd 10%, #ffffff);
  --ui-accent: #0053fd;
  --theme-fill-secondary-accent-mix: 6%;
  --theme-fill-quaternary-accent-mix: 4%;
  --ui-base: var(--theme-foreground);
  --ui-bg-secondary: color-mix(in srgb, var(--ui-accent) var(--theme-fill-secondary-accent-mix), color-mix(in srgb, var(--ui-base) 7%, transparent));
  --ui-bg-quaternary: color-mix(in srgb, var(--ui-accent) var(--theme-fill-quaternary-accent-mix), color-mix(in srgb, var(--ui-base) 4%, transparent));
  --ui-text-primary: color-mix(in srgb, var(--ui-base) 94%, transparent);
  --ui-stroke-tertiary: color-mix(in srgb, var(--ui-base) 12%, transparent);
`

const GENERATIONS = {
  'pre-v2026.8.31': `${SHARED_TOKENS}
    --dt-accent: var(--theme-accent-soft);
    --dt-accent-foreground: var(--ui-text-primary);`,
  'v2026.8.31+': `${SHARED_TOKENS}
    --dt-accent: var(--theme-accent-soft);
    --dt-accent-foreground: var(--ui-text-primary);
    --dt-primary-solid: var(--theme-primary);
    --dt-primary-solid-foreground: #fcfcfc;`
}

// The SDK's own SelectItem classes (apps/desktop/src/components/ui/select.tsx),
// which a broken custom override is supposed to fall back to.
const SDK_FOCUS_RULE = `
  .sdk-native{outline:none;background:transparent;color:var(--ui-text-primary)}
  .sdk-native[data-highlighted]{background:var(--dt-accent);color:var(--dt-accent-foreground)}
`

function page(css, tokens) {
  return `<!doctype html><html><head><meta charset="utf-8"><style>
    :root{${tokens}}
    body{margin:0;background:var(--ui-bg-secondary)}
    .surface{background:var(--ui-bg-quaternary);padding:8px}
    .pl-select-item{outline:none;background:transparent;color:var(--ui-text-primary)}
    ${SDK_FOCUS_RULE}
    ${css}
  </style></head><body><div class="surface">
    <div class="pl-select-item" id="plain">gpt-5</div>
    <div class="pl-select-item" id="hot" data-highlighted>claude-opus-4</div>
    <div class="sdk-native" id="sdk" data-highlighted>sdk reference</div>
  </div></body></html>`
}

const srgb = c => (c <= 0.04045 ? c / 12.92 : Math.pow((c + 0.055) / 1.055, 2.4))
const luminance = ([r, g, b]) => {
  const [lr, lg, lb] = [r, g, b].map(v => srgb(v / 255))
  return 0.2126 * lr + 0.7152 * lg + 0.0722 * lb
}
const contrast = (fg, bg) => {
  const [a, b] = [luminance(fg), luminance(bg)]
  return (Math.max(a, b) + 0.05) / (Math.min(a, b) + 0.05)
}

async function measure(browser, css, tokens) {
  const tab = await browser.newPage()
  await tab.setContent(page(css, tokens))
  const result = await tab.evaluate(() => {
    // Computed colors come back as color-mix()/oklch() strings, so rasterize to
    // real sRGB bytes, compositing alpha over the surface the user actually sees.
    const canvas = document.createElement('canvas')
    canvas.width = canvas.height = 1
    const ctx = canvas.getContext('2d', { willReadFrequently: true })
    const surface = getComputedStyle(document.querySelector('.surface')).backgroundColor
    const raster = (color, under) => {
      ctx.clearRect(0, 0, 1, 1)
      ctx.fillStyle = under
      ctx.fillRect(0, 0, 1, 1)
      ctx.fillStyle = color
      ctx.fillRect(0, 0, 1, 1)
      return Array.from(ctx.getImageData(0, 0, 1, 1).data).slice(0, 3)
    }
    const read = id => {
      const s = getComputedStyle(document.getElementById(id))
      const bg = raster(s.backgroundColor, surface)
      return { bg, fg: raster(s.color, `rgb(${bg.join(',')})`) }
    }
    return { plain: read('plain'), hot: read('hot'), sdk: read('sdk') }
  })
  await tab.close()
  return result
}

for (const [generation, tokens] of Object.entries(GENERATIONS)) {
  test(`highlighted option is visible and AA-legible on ${generation}`, { skip: chromium ? false : 'playwright not installed' }, async () => {
    const browser = await chromium.launch()
    try {
      const m = await measure(browser, PLUGIN_CSS, tokens)

      assert.notDeepEqual(m.hot.bg, m.plain.bg,
        `highlighted option is indistinguishable from an unhighlighted one on ${generation}`)

      const ratio = contrast(m.hot.fg, m.hot.bg)
      assert.ok(ratio >= 4.5,
        `highlighted text contrast ${ratio.toFixed(3)}:1 is below WCAG AA on ${generation}`)
    } finally {
      await browser.close()
    }
  })
}

test('without the fallback the highlight disappears on pre-v2026.8.31 builds', { skip: chromium ? false : 'playwright not installed' }, async () => {
  const broken = PLUGIN_CSS.replace(
    'background:var(--dt-primary-solid,var(--dt-accent));color:var(--dt-primary-solid-foreground,var(--dt-accent-foreground))',
    'background:var(--dt-primary-solid);color:var(--dt-primary-solid-foreground)')
  assert.notEqual(broken, PLUGIN_CSS, 'fallback rule not found; update this test')

  const browser = await chromium.launch()
  try {
    const m = await measure(browser, broken, GENERATIONS['pre-v2026.8.31'])
    // This is the regression the fallback exists to prevent.
    assert.deepEqual(m.hot.bg, m.plain.bg,
      'expected the unresolved custom property to erase the highlight')
  } finally {
    await browser.close()
  }
})

test('the fallback highlight matches the SDK native focus appearance', { skip: chromium ? false : 'playwright not installed' }, async () => {
  const browser = await chromium.launch()
  try {
    const m = await measure(browser, PLUGIN_CSS, GENERATIONS['pre-v2026.8.31'])
    assert.deepEqual(m.hot.bg, m.sdk.bg,
      'fallback should reproduce the SDK focus:bg-accent background exactly')
    assert.deepEqual(m.hot.fg, m.sdk.fg,
      'fallback should reproduce the SDK focus:text-accent-foreground exactly')
  } finally {
    await browser.close()
  }
})
