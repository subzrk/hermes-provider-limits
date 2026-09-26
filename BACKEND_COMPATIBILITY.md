# Backend compatibility gate

The unified package requires **Hermes 0.21.3 or later**. The Desktop SDK alone
is not the compatibility boundary: discovery imports `config_effective`, both
routes import `web_server_profiles`, and provider resolution uses
`credential_pool`, `auth`, `secret_scope`, `config_providers`,
and `runtime_provider`.

The runtime guard in `dashboard/plugin_api.py` rejects older Hermes before
registering a router or importing profile/credential modules. This is needed
because older loaders ignore `requires_hermes`; changing the manifest alone
would still allow a broken backend to mount.

## Pinned release evidence

| Hermes | Release tag | Commit | Result |
| --- | --- | --- | --- |
| 0.20.3 | v2026.8.16.2 | `7339f5f160db5c96657a3bab60151227cc61f66c` | Original discovery fails: missing `hermes_cli.config_effective`; fixed backend rejects import with upgrade guidance. |
| 0.21.2 | v2026.9.11 | `939e45c91d751fadd94dcd1b873ac3cb44846213` | Same original discovery failure; fixed backend rejects import. |
| 0.21.3 | v2026.9.14 | `345cd2b057a452236de401d3534b8502a7465e8d` | Discovery, all directly imported backend symbols, current/named-profile routes, and Codex 401 handling pass. |

**An import-only check would miss another incompatibility:** the released
0.21.3 `_resolve_codex_usage_credentials` has no `force_refresh` keyword. The
prerequisite fixed this by retaining the original 401 when unsupported. This
candidate replaces that general resolver with an owned-OAuth adapter using
`CredentialPool.try_refresh_matching(api_key_hint=..., credential_id=...)`,
which the real 0.21.3 release supports. It never falls back to the general
resolver. The regression still requires the original 401 when refresh is
unavailable or transiently fails, and no reactive refresh after 403.

`probe_owned_oauth.py` now exercises actual released pool loading, selection,
refresh locking, exact-row refresh, and persistence for Codex singleton and
Claude manual Hermes PKCE credentials. Only provider HTTP boundaries are
substituted. It verifies proactive refresh, one 401 recovery, 403 preservation,
and unrecoverable-401 propagation. Additional unit tests cover ownership,
account changes, refresh failures, and bounded cache behavior.

The minimum-release probe checks the added SDK exports (`atom`, `Switch`,
`Popover*`, `STATUSBAR_AREAS`) and verifies that its React Query core version
matches the pinned `5.101.2` used by the real QueryObserver tests. Those tests
exercise shared-cache revocation using `QueryFunctionContext.client` after
authentication or profile/contract rejection, including a subsequent soft error.

## Reproduce

Use Python 3.11.8+ (or 3.12+) and `uv`. From the plugin checkout, choose a
scratch directory outside any live Hermes installation/profile:

```sh
export COMPAT_ROOT=/path/to/scratch/provider-limits-compat
mkdir -p "$COMPAT_ROOT"
git clone https://github.com/NousResearch/hermes-agent.git "$COMPAT_ROOT/hermes-source"
export HERMES_SOURCE_REPO="$COMPAT_ROOT/hermes-source"
git -C "$HERMES_SOURCE_REPO" worktree add --detach "$COMPAT_ROOT/hermes-0.21.3" 345cd2b057a452236de401d3534b8502a7465e8d
uv sync --frozen --extra dev --project "$COMPAT_ROOT/hermes-0.21.3"
export PYTHON="$COMPAT_ROOT/hermes-0.21.3/.venv/bin/python"
"$PYTHON" -m pytest tests -q
"$PYTHON" -m pytest tests/test_backend_compatibility.py -q -s
"$PYTHON" -m compileall -q dashboard __init__.py tests
node --check desktop/plugin.js
mkdir -p "$COMPAT_ROOT/validation-home"
env -i PATH="$PATH" HOME="$COMPAT_ROOT/validation-home" \
  HERMES_HOME="$COMPAT_ROOT/validation-home/.hermes" \
  "$COMPAT_ROOT/hermes-0.21.3/.venv/bin/hermes" plugins validate . --json
```

See README for this branch's Desktop/component/browser commands.
`HERMES_SOURCE_REPO` is mandatory for the Python suite: unavailable real-release
coverage **fails**, never skips. The source clone must contain all three pinned
commits. Release source is extracted afresh with `git archive` for every probe.
The subprocess uses `-I -S`, explicitly selected third-party wheel paths, a
fresh HOME/HERMES_HOME, an allowlisted environment, and no outbound network.
No editable-install `.pth` hooks run. Every loaded `hermes_cli`, `agent.*`, and
`hermes_constants` module is checked to originate inside that release tree.

The supported-release probe executes real `discover()`, real FastAPI route
handlers (`/quota` 200, inactive `/history` 404, active `/history` 200), and named
profile scoping/restoration with synthetic local configs. It imports every
Hermes symbol found by AST inspection of all backend files and exercises the
owned-OAuth adapter with actual released credential pools and temporary stores
(only provider HTTP boundaries substituted). No real credentials or live quota requests
are used. The full Python suite also runs against the oldest supported release
and its frozen dependency lock, not the developer's current Hermes.

## Negative controls

Before the fix, both older-release probes failed with the original missing
module, and the 0.21.3 probe failed on the unexpected `force_refresh` keyword.
The old manifest also failed the revised floor test. Reverting each corresponding
production fix makes its regression fail again. PR1 additionally keeps three
in-memory history-request mutations: `/history` changed to `/quota`, removed
`provider`, and removed `q`. All three must be rejected by the same assertions
used for the real request.

These are local compatibility gates, not claims of live OAuth/provider-service
validation, complete packaged Electron execution, or GitHub Actions coverage.
The candidate starts on upstream main after both prerequisite UI PRs merged;
their runtime floor, theme matrix, and history-request mutations remain.
