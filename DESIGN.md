# Provider Limits — visual contract

Inherited from Hermes Desktop `apps/desktop/DESIGN.md`; this plugin adds a page, not a separate brand.

- Route `/provider-limits`; sidebar **Utilização**, codicon `graph`; palette entry points to the same route.
- Native Tabs/TabsList/TabsTrigger, one labelled tab per active provider and only one panel mounted. Session history lives below that provider’s quota section; unavailable remote quota never hides local Hermes history.
- Local usage: flat totals strip, debounced search, model filter, token/recent sorting,25-row pagination. Expand a session to see every model/task and canonical token bucket. The per-model summary covers all filtered sessions, not only the current page.
- Accounting tables are horizontally scrollable labelled regions at narrow widths. Long titles/model IDs wrap; token counters use tabular numerals. Credits are explicitly «Não registados»; unknown USD zeros are never presented as invoices.
- Flat, theme-adaptive provider sections, separated by a single token hairline and whitespace. No card-in-card layout.
- Native Hermes font and SDK Button/Codicon. Provider wordmarks are typographic identifiers, not downloaded third-party artwork.
- `--ui-text-primary/secondary/tertiary`, `--ui-accent`, `--ui-bg-quaternary`, `--ui-stroke-tertiary`; destructive state uses theme token. Never hardcode a separate production palette.
- 24–32px page heading,19px provider headings,14px window labels,20px tabular remaining percentages,12px supporting measures. Information precedence: provider → model group → period → remaining/used → renewal.
- Filled bars represent **used**, explicitly labelled below; the leading percentage is **remaining**, explicitly labelled beside it. Usage is clamped only for bar geometry, not the numerical overage.
- Single-column small containers; responsive auto-fit at260px per quota window. Codex weekly takes full width; Spark5h/7d shares a two-column group when room permits.
- Reduced-motion disables transform animation. Numbers remain visible throughout refresh.
- Loading, empty, unavailable, stale and missing-backend states have distinct copy; no silent zeros or indefinite missing-backend polling.
- External-provider link and refresh are keyboard accessible. Bars expose labelled ARIA ranges and value text.
- No shipping raster assets. Screenshots are test evidence from live-snapshot data and a test SDK host, not product assets.

## Verification scope

Playwright at1100px dark/light and420px dark: no horizontal overflow or JS exceptions; refresh and provider link function; empty and missing-backend states pass. Actual native app: SDK import/render, persisted Desktop activation, sidebar entry and backend-not-yet-mounted guidance verified. Live API via fresh Hermes server TestClient:401 without session token,200 with token, real Codex windows. The existing running Desktop backend still requires restart to mount Python routes; active conversations were not interrupted.
