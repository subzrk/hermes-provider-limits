// Real computed-style verification of the themed Select highlight.
//
// The fixture was captured by Chromium through the real Hermes ThemeProvider
// and SDK Select at exact release tags:
//   - v2026.8.27 / hermes 0.20.6: every built-in light/dark palette before
//     --dt-primary-solid* existed;
//   - v2026.8.31 / hermes 0.21.0: every built-in light/dark palette in the
//     first primary-solid generation.
//
// Source-string checks cannot prove CSS variables resolve, contrast survives
// alpha compositing, or a highlighted option differs from its surface. These
// tests render the plugin's own CSS in Chromium and measure rasterized pixels.
const assert = require('node:assert/strict')
const fs = require('node:fs')
const path = require('node:path')
const test = require('node:test')
const { chromium } = require('playwright')

const source = fs.readFileSync(path.join(__dirname, '..', 'desktop', 'plugin.js'), 'utf8')
const cssMatch = source.match(/export const CSS = `([\s\S]*?)`\n/)
assert.ok(cssMatch, 'could not extract CSS from desktop/plugin.js')
const PLUGIN_CSS = cssMatch[1]

const fixturePath = path.join(__dirname, 'fixtures', 'hermes-theme-matrix.json')
const fixture = JSON.parse(fs.readFileSync(fixturePath, 'utf8'))
const FALLBACK_DECLARATIONS =
  'background:var(--dt-primary-solid,#0053fd);color:var(--dt-primary-solid-foreground,#fcfcfc)'

const srgb = value => (value <= 0.04045 ? value / 12.92 : Math.pow((value + 0.055) / 1.055, 2.4))
const luminance = ([r, g, b]) => {
  const [lr, lg, lb] = [r, g, b].map(value => srgb(value / 255))
  return 0.2126 * lr + 0.7152 * lg + 0.0722 * lb
}
const contrast = (first, second) => {
  const [a, b] = [luminance(first), luminance(second)]
  return (Math.max(a, b) + 0.05) / (Math.min(a, b) + 0.05)
}

function tokenDeclarations(entry) {
  const values = {
    '--dt-popover': entry.popover,
    '--dt-popover-foreground': entry.popoverForeground,
    '--dt-accent': entry.accent,
    '--dt-accent-foreground': entry.accentForeground,
    '--dt-primary-solid': entry.primarySolid,
    '--dt-primary-solid-foreground': entry.primarySolidForeground
  }
  return Object.entries(values)
    .filter(([, value]) => value)
    .map(([name, value]) => `${name}:${value}`)
    .join(';')
}

function documentFor(css, entry) {
  return `<!doctype html><html><head><meta charset="utf-8"><style>
    :root{${tokenDeclarations(entry)}}
    body{margin:0;background:${entry.bodyBackground}}
    .surface{background:var(--dt-popover);color:var(--dt-popover-foreground);padding:8px}
    .pl-select-item{outline:none;background:transparent;color:var(--dt-popover-foreground)}
    ${css}
  </style></head><body><div class="surface">
    <div class="pl-select-item" id="plain">gpt-5</div>
    <div class="pl-select-item" id="hot" data-highlighted>claude-opus-4</div>
  </div></body></html>`
}

async function measure(tab, css, entry) {
  await tab.setContent(documentFor(css, entry))
  return tab.evaluate(() => {
    const canvas = document.createElement('canvas')
    canvas.width = canvas.height = 1
    const context = canvas.getContext('2d', { willReadFrequently: true })
    const body = getComputedStyle(document.body).backgroundColor
    const surface = getComputedStyle(document.querySelector('.surface')).backgroundColor

    // Composites every alpha-bearing layer exactly as the browser paints it,
    // then returns real sRGB bytes regardless of the computed color syntax.
    const raster = layers => {
      context.clearRect(0, 0, 1, 1)
      for (const color of layers) {
        context.fillStyle = color
        context.fillRect(0, 0, 1, 1)
      }
      return Array.from(context.getImageData(0, 0, 1, 1).data).slice(0, 3)
    }
    const read = id => {
      const style = getComputedStyle(document.getElementById(id))
      const background = raster([body, surface, style.backgroundColor])
      const foreground = raster([body, surface, style.backgroundColor, style.color])
      return { background, foreground }
    }
    return { plain: read('plain'), hot: read('hot') }
  })
}

const EXPECTED_THEMES = [
  'catppuccin', 'cyberpunk', 'ember', 'everforest', 'github', 'midnight',
  'mono', 'nous', 'nous-alt', 'slate', 'solarized'
]

for (const release of fixture.releases) {
  test(`${release.sourceTag}: all built-in light/dark palettes keep the highlight visible and AA-legible`, async t => {
    assert.equal(release.entries.length, 22, 'expected 11 themes × 2 modes')
    assert.deepEqual([...new Set(release.entries.map(entry => entry.name))].sort(), EXPECTED_THEMES)
    assert.deepEqual([...new Set(release.entries.map(entry => entry.mode))].sort(), ['dark', 'light'])

    const browser = await chromium.launch()
    const tab = await browser.newPage()
    let minimumText = { ratio: Infinity, label: '' }
    let minimumIndicator = { ratio: Infinity, label: '' }
    try {
      for (const entry of release.entries) {
        const label = `${entry.name}/${entry.mode}`
        await t.test(label, async () => {
          const measured = await measure(tab, PLUGIN_CSS, entry)
          const textRatio = contrast(measured.hot.foreground, measured.hot.background)
          const indicatorRatio = contrast(measured.hot.background, measured.plain.background)

          if (textRatio < minimumText.ratio) minimumText = { ratio: textRatio, label }
          if (indicatorRatio < minimumIndicator.ratio) minimumIndicator = { ratio: indicatorRatio, label }

          assert.ok(textRatio >= 4.5,
            `${label} highlighted text contrast ${textRatio.toFixed(3)}:1 is below WCAG AA`)
          assert.notDeepEqual(measured.hot.background, measured.plain.background,
            `${label} highlighted option is indistinguishable from an unhighlighted one`)
        })
      }
    } finally {
      await tab.close()
      await browser.close()
    }
    console.log(`${release.sourceTag}: min text ${minimumText.ratio.toFixed(3)}:1 at ${minimumText.label}; ` +
      `min highlight/surface ${minimumIndicator.ratio.toFixed(3)}:1 at ${minimumIndicator.label}`)
  })
}

test('fixture reproduces the reviewer-reported legacy accent failures', async () => {
  const accentCss = PLUGIN_CSS.replace(
    FALLBACK_DECLARATIONS,
    'background:var(--dt-primary-solid,var(--dt-accent));color:var(--dt-primary-solid-foreground,var(--dt-accent-foreground))')
  assert.notEqual(accentCss, PLUGIN_CSS, 'fallback declarations not found; update this test')

  const legacy = fixture.releases.find(release => release.sourceTag === 'v2026.8.27')
  const browser = await chromium.launch()
  const tab = await browser.newPage()
  const failures = []
  try {
    for (const entry of legacy.entries) {
      const measured = await measure(tab, accentCss, entry)
      const ratio = contrast(measured.hot.foreground, measured.hot.background)
      if (ratio < 4.5) failures.push({ label: `${entry.name}/${entry.mode}`, ratio })
    }
  } finally {
    await tab.close()
    await browser.close()
  }

  const labels = failures.map(failure => failure.label)
  console.log('legacy accent failures: ' + failures
    .map(failure => `${failure.label} ${failure.ratio.toFixed(3)}:1`).join(', '))
  assert.ok(labels.includes('everforest/light'), `missing Everforest reproduction: ${labels}`)
  assert.ok(labels.includes('solarized/dark'), `missing Solarized reproduction: ${labels}`)
})

test('removing every fallback reproduces the invisible pre-v2026.8.31 highlight', async () => {
  const brokenCss = PLUGIN_CSS.replace(
    FALLBACK_DECLARATIONS,
    'background:var(--dt-primary-solid);color:var(--dt-primary-solid-foreground)')
  assert.notEqual(brokenCss, PLUGIN_CSS, 'fallback declarations not found; update this test')

  const entry = fixture.releases
    .find(release => release.sourceTag === 'v2026.8.27').entries
    .find(candidate => candidate.name === 'nous' && candidate.mode === 'light')
  const browser = await chromium.launch()
  const tab = await browser.newPage()
  try {
    const measured = await measure(tab, brokenCss, entry)
    assert.deepEqual(measured.hot.background, measured.plain.background,
      'expected unresolved variables to erase the highlight')
  } finally {
    await tab.close()
    await browser.close()
  }
})
