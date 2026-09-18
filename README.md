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

Then open Hermes Desktop, go to **Capabilities → Plugins**, run **Rescan** if needed, and enable **Usage and limits**. The plugin adds:

- **Usage** in the sidebar;
- **Open usage and limits** in the command palette.

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

## Localization

English is the complete fallback and is currently the only registered bundle. UI copy lives in the `LOCALES` object in `desktop/plugin.js`. Add future translations only as sibling bundles for locale IDs supported by Hermes (`zh`, `zh-hant`, `ja`, `ar`, or `ru`); locale support is add-only, so do not replace or remove the English fallback or register unreachable locale IDs. Missing keys fall back to English.

Page content is reactive to locale changes. Sidebar and command-palette labels are activation-time snapshots: the current Hermes contribution schema accepts plain string labels, so those two labels update only when the plugin is activated again. The plugin does not modify Hermes core to simulate reactive contribution chrome.

Schema v2 adds locale-neutral display descriptors and stable problem codes; legacy presentation fields remain temporarily for v1 compatibility. Provider names, named upstream plans, model IDs, session titles, and other upstream values remain literal. Do not add translated prose to new API fields.

## Development

Requirements:

- a recent Hermes checkout/runtime with unified Desktop plugins;
- Python dependencies supplied by Hermes (`fastapi`, `PyYAML` for discovery tests);
- Node.js for the ESM syntax check.

```bash
python -m pytest tests -q
python -m py_compile dashboard/plugin_api.py dashboard/history.py
node --check desktop/plugin.js
node --experimental-vm-modules --test tests/test_desktop_i18n.mjs
```

Tests use synthetic protocol fixtures and do not require real provider credentials or network access.

## Limitations

Provider quota endpoints are not standardized and may change independently of Hermes. The plugin fails closed: it displays an unavailable/stale state rather than fabricating data. `deepseekv4pro.com` currently separates its website session from inference API keys, so authenticated quota retrieval may not be available to Hermes.

## License

[MIT](LICENSE)
