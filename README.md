# Hermes Provider Limits

A unified [Hermes Desktop](https://hermes-agent.nousresearch.com/docs/user-guide/desktop) plugin that shows live provider quotas and local Hermes usage in one native page.

[Install in Hermes](hermes://plugin/install?repo=JaimeMarques/hermes-provider-limits&enable=1)

## What it shows

- Only providers configured and enabled in the selected Hermes profile.
- **OpenAI Codex:** every window returned by `wham/usage`, including additional model limits such as Spark, code-review limits, credits, and resets.
- **Claude:** every OAuth subscription window, model-specific windows, and extra-usage allowance when enabled.
- **GLM / Z.ai:** all token and tool/MCP windows returned by the Coding Plan quota API.
- **deepseekv4pro.com:** account quota when the dashboard endpoint accepts the available credential. Its current dashboard uses a separate website session, so a normal inference API key may only produce an explicit “unavailable” state.
- **Hermes history:** per-session, per-model, and per-task calls, tokens, cache, reasoning, and recorded USD cost from the selected profile’s local `state.db`.

Unknown values stay unknown. The plugin does not turn percentages into invented token ceilings, combine incompatible windows, or infer credits from tokens.

## Install

### Hermes Desktop

Open the install link above, review the repository and selected components, then confirm installation. In **Capabilities → Plugins**, enable the Desktop half if it is not already enabled.

### CLI

```bash
hermes plugins install JaimeMarques/hermes-provider-limits --enable
hermes gateway restart
```

Then open Hermes Desktop, go to **Capabilities → Plugins**, run **Rescan** if needed, and enable **Utilização e limites**. The plugin adds:

- **Utilização** in the sidebar;
- **Abrir utilização e limites** in the command palette.

Python routes mount when the Hermes backend starts, so a gateway/Desktop restart is required after the first install or a backend update. The JavaScript UI itself hot-reloads.

## Update

```bash
hermes plugins update provider-limits
hermes gateway restart
```

Run **Rescan** in **Capabilities → Plugins** to refresh the Desktop half.

## Security model

- Read-only: no inference calls, purchases, quota changes, or reset redemption.
- Provider credentials are resolved by Hermes in the Python backend and never returned to the renderer.
- Outbound quota requests are HTTPS-only, restricted to exact provider hosts, size-limited, time-bounded, and forbidden from following redirects.
- Error responses do not expose provider bodies, tokens, account identifiers, or emails.
- Local history opens `state.db` read-only and selects accounting columns only; it does not read prompts or messages.
- The 60-second in-memory cache is isolated by profile and by a server-side configuration/credential signature.

Third-party plugins execute inside Hermes. Review the source before enabling it.

## Package layout

```text
provider-limits/
├── plugin.yaml
├── __init__.py
├── dashboard/
│   ├── manifest.json
│   ├── plugin_api.py
│   └── history.py
└── desktop/
    └── plugin.js
```

The Desktop UI calls its backend through the plugin-scoped `ctx.rest` namespace. No build step is required.

## Development

Requirements:

- Hermes `0.20.3` or newer (the `v2026.8.16.2` release), the first version that
  satisfies the complete packaged-plugin contract: unified Desktop discovery,
  `ctx.os`, and `host.state.connectionId`; declared as
  `requires_hermes: ">=0.20.3"` in `plugin.yaml`, which newer builds enforce.
  Releases before `v2026.8.31` lack the `--dt-primary-solid*` theme tokens, so the
  highlighted-option rule falls back to opaque Nous blue (`#0053fd`) with
  `#fcfcfc` text. This pair stays at 5.599:1 across the older theme matrix; the
  SDK's translucent `--dt-accent*` pair falls below AA in Everforest light and
  Solarized dark;
- Python dependencies supplied by Hermes (`fastapi`, `PyYAML` for discovery tests);
- Node.js/npm for the ESM/component checks and the pinned Playwright browser gate.

```bash
python -m pytest tests -q
python -m py_compile dashboard/plugin_api.py dashboard/history.py
node --check desktop/plugin.js
npm ci
npm run install:chromium
npm test
```

`tests/test_select_styles.cjs` renders the plugin's CSS in Chromium against the
resolved ThemeProvider/SDK tokens captured at exact tags `v2026.8.27` (before
`--dt-primary-solid*`) and `v2026.8.31` (the first token generation). It asserts
all 11 built-in themes in light and dark mode stay visible and WCAG AA legible,
and proves the fixture reproduces the reported Everforest/Solarized failures.
Missing Playwright or Chromium is a hard failure rather than a green run with
skipped browser coverage.

Tests use synthetic protocol fixtures and do not require real provider credentials or network access.

## Limitations

Provider quota endpoints are not standardized and may change independently of Hermes. The plugin fails closed: it displays an unavailable/stale state rather than fabricating data. `deepseekv4pro.com` currently separates its website session from inference API keys, so authenticated quota retrieval may not be available to Hermes.

## License

[MIT](LICENSE)
