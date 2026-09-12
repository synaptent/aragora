# Aragora Live

Next.js control plane for debates, agent activity and decision receipts.
Commands below run from `aragora/live` unless marked as repository-root commands.
Use Node `>=24.18.0 <25` and npm with `min-release-age` support (11.9 or newer).
The local `.npmrc` requires packages to be at least three days old.

## Run

```sh
npm ci
npm run dev -- --port 3120
```

Open <http://localhost:3120/landing/>. The backend is a separate service.
For a local backend on HTTP 3110 and WebSocket 3111, set
`NEXT_PUBLIC_API_URL=http://localhost:3110` and
`NEXT_PUBLIC_WS_URL=ws://localhost:3111/ws` in an untracked `.env.local`.
Use `NEXT_PUBLIC_CONTROL_PLANE_WS_URL=ws://localhost:3112/api/control-plane/stream`
and `NEXT_PUBLIC_NOMIC_LOOP_WS_URL=ws://localhost:3113/api/nomic/stream`
if those backend listeners are enabled.

`npm run setup` copies `.env.local.example` only when `.env.local` is absent.
Its backend port defaults differ from the example above; replace the Supabase
placeholders or omit those variables. Never commit credentials.

## Build

**The single build command measured by size-limit is `npm run build:local`.**
It uses webpack and `NEXT_OUTPUT=standalone`. Run:

```sh
npm run build:local
npx size-limit
```

`.size-limit.json` budgets all emitted `.next/static/**/*.js` and
`.next/static/**/*.css`, separately, using summed per-file Brotli sizes.
These are whole-client-build budgets, not one route's first-load size.
Each adoption limit is the measured bytes plus 10%, rounded up to a byte.
JavaScript measured 2,472,416 B (limit 2,719,658 B); CSS measured 31,608 B
(limit 34,769 B).
Embedded build timestamps and commit IDs can slightly change these measurements.
Re-measure with the same command and review budget changes; do not switch to
a different output mode to pass a budget.
From the repository root, `make readiness-heavy-live` runs both commands,
without opening a port. Heavy work is not part of the three readiness aggregates.

| Script                     | Output and behavior                                                                                                                                                                                |
| -------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `npm run build`            | Runs `prebuild` (environment validation and `.next` cleanup), then `build:runtime`. Runtime mode builds `.next/` with Turbopack and hosted API/WS URLs. Start with `npm run start -- --port 3120`. |
| `npm run build:runtime`    | Same runtime build, without the `prebuild` hook.                                                                                                                                                   |
| `npm run build:local`      | Webpack `.next/` plus `.next/standalone/`; preserves supplied API/WS settings. The size-limit reference build.                                                                                     |
| `npm run build:standalone` | Same standalone output, but bakes in hosted API/WS URLs.                                                                                                                                           |
| `npm run build:export`     | Webpack static `out/` directory with hosted URLs. No Next server, redirects or API rewrites; hosting must supply those.                                                                            |
| `npm run export`           | Static `out/` with the caller's API/WS settings.                                                                                                                                                   |
| `npm run build:ci`         | Cleans `.next`, validates env, then webpack builds `.next/` with the configured output mode.                                                                                                       |

The standalone build emits `.next/standalone/server.js` in this checkout.
Copy static assets beside it to serve the UI (Next does not copy these
automatically), then start on port 3120:

```sh
mkdir -p .next/standalone/.next
cp -R .next/static .next/standalone/.next/
cp -R public .next/standalone/
PORT=3120 node .next/standalone/server.js
```

Open <http://localhost:3120/healthz/> for the local liveness document.
If a different tracing root nests `server.js`, use that generated path and
copy the assets beside it instead.

Static-export verification currently stops at the existing
`/autonomous/bridge/[run_id]` page, which lacks `generateStaticParams()`.
`NEXT_OUTPUT=export npx next build --webpack` exits non-zero before writing
`out/healthz*`, so `/healthz/` is not part of static-export output today.
The health handler itself opts into static generation, but the export scripts
above remain blocked by that pre-existing page.

Public environment values are baked into the client build. Rebuild after
changing them. Output overrides (`NEXT_OUTPUT` or `ARAGORA_NEXT_OUTPUT`) also
apply to runtime/CI builds; clear them when requesting normal runtime output.

## Test

```sh
npx jest --ci --coverage --maxWorkers=4
```

Jest always collects coverage, including `npm test` and CI's `npx jest --ci`.
Tests are named `*.test.[jt]s?(x)` or live under `__tests__/`; E2E and build
directories are excluded. The adoption suite has 4,035 passing tests and 27
skipped tests (4,062 total). Global coverage measured 27.01% statements,
22.71% branches, 22.98% functions and 27.91% lines. Floors are one percentage
point below each measurement and should only rise.

Reports: ignored `coverage/` (LCOV, HTML and JSON summary) and `junit.xml`
(per-test timings). `npm run test:watch` watches unit tests;
`npm run test:e2e` runs the separate Playwright suite against
`PLAYWRIGHT_BASE_URL` (default `http://localhost:3000`, set it to your server).
From the repository root: `make readiness-test-live`.

## Lint

```sh
npm run typecheck
npm run lint
npm run format:check
```

From the repository root, `make readiness-lint-live` additionally checks knip
through the shared shrink-only baseline, jscpd at 6%, and source file sizes.
`make readiness-typecheck-live` runs TypeScript. `npm run format` formats code.
See [ratchet maintenance](../../docs/RATCHETS.md) for baseline regeneration and
ESLint suppression pruning. Plain `npx knip` still reports adopted debt.

The `frontend-lint` job in `.github/workflows/lint.yml` runs every live gate,
including Jest coverage/junit and standalone size-limit, on non-draft PRs
touching `aragora/live/**`. It skips draft PRs and re-evaluates on
`ready_for_review`. CI rejects a toolchain SKIP; local Make targets print
`SKIP live: <reason>` when their toolchain is absent.

## Env vars

All `NEXT_PUBLIC_*` values are public, build-time configuration, never secrets.
The list below covers app and Next config reads; localStorage/backend settings
can override some runtime connection and feature choices.

| Variable                                    | Default and purpose                                                                                                                                                                                                                                                                                                                                                                                |
| ------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `NEXT_PUBLIC_API_URL`                       | Unset. Local browser uses same-origin `/api`; SSR falls back to `http://localhost:8080`. Next rewrites use that backend in development and `https://api.aragora.ai` in production. Production browser config derives `https://api.<host>` (preserves an `api.` host). Some legacy direct consumers use localhost, the hosted API, or same-origin instead, so set this explicitly for self-hosting. |
| `NEXT_PUBLIC_WS_URL`                        | Unset. Central config uses `ws://localhost:8765/ws` locally or `wss://api.<host>/ws` in production. Some legacy viewers default to `wss://api.aragora.ai/ws`, the playground to `ws://localhost:8765`. Set explicitly in deployments.                                                                                                                                                              |
| `NEXT_PUBLIC_CONTROL_PLANE_WS_URL`          | `ws://localhost:8766/api/control-plane/stream` locally; `wss://api.<host>/api/control-plane/stream` in production.                                                                                                                                                                                                                                                                                 |
| `NEXT_PUBLIC_NOMIC_LOOP_WS_URL`             | `ws://localhost:8767/api/nomic/stream` locally; `wss://api.<host>/api/nomic/stream` in production.                                                                                                                                                                                                                                                                                                 |
| `NEXT_PUBLIC_SUPABASE_URL`                  | Empty; optional history persistence.                                                                                                                                                                                                                                                                                                                                                               |
| `NEXT_PUBLIC_SUPABASE_ANON_KEY`             | Empty; optional public Supabase anonymous key, not a service-role key.                                                                                                                                                                                                                                                                                                                             |
| `NEXT_PUBLIC_DEFAULT_AGENTS`                | `grok,anthropic-api,openai-api,deepseek,mistral,gemini,qwen,kimi`.                                                                                                                                                                                                                                                                                                                                 |
| `NEXT_PUBLIC_DEFAULT_ROUNDS`                | `9`.                                                                                                                                                                                                                                                                                                                                                                                               |
| `NEXT_PUBLIC_MAX_ROUNDS`                    | `12`.                                                                                                                                                                                                                                                                                                                                                                                              |
| `NEXT_PUBLIC_DEFAULT_CONSENSUS`             | `judge`.                                                                                                                                                                                                                                                                                                                                                                                           |
| `NEXT_PUBLIC_STREAMING_AGENTS`              | `grok,anthropic-api,openai-api,mistral`.                                                                                                                                                                                                                                                                                                                                                           |
| `NEXT_PUBLIC_API_TIMEOUT`                   | `30000` milliseconds.                                                                                                                                                                                                                                                                                                                                                                              |
| `NEXT_PUBLIC_WS_RECONNECT_DELAY`            | `3000` milliseconds.                                                                                                                                                                                                                                                                                                                                                                               |
| `NEXT_PUBLIC_WS_DEBATE_TIMEOUT`             | `180000` milliseconds.                                                                                                                                                                                                                                                                                                                                                                             |
| `NEXT_PUBLIC_WS_POLLING_INTERVAL`           | `3000` milliseconds.                                                                                                                                                                                                                                                                                                                                                                               |
| `NEXT_PUBLIC_ORACLE_FIRST_TOKEN_TIMEOUT_MS` | `15000` milliseconds.                                                                                                                                                                                                                                                                                                                                                                              |
| `NEXT_PUBLIC_ORACLE_ACTIVITY_TIMEOUT_MS`    | `20000` milliseconds.                                                                                                                                                                                                                                                                                                                                                                              |
| `NEXT_PUBLIC_DEFAULT_PAGE_SIZE`             | `20`.                                                                                                                                                                                                                                                                                                                                                                                              |
| `NEXT_PUBLIC_ENABLE_STREAMING`              | Enabled unless exactly `false`.                                                                                                                                                                                                                                                                                                                                                                    |
| `NEXT_PUBLIC_ENABLE_AUDIENCE`               | Enabled unless exactly `false`.                                                                                                                                                                                                                                                                                                                                                                    |
| `NEXT_PUBLIC_BUILD_SHA`                     | Git HEAD, or `unknown` outside Git; embedded by Next config.                                                                                                                                                                                                                                                                                                                                       |
| `NEXT_PUBLIC_BUILD_TIME`                    | Current ISO timestamp at config evaluation; embedded by Next config.                                                                                                                                                                                                                                                                                                                               |
| `LIVE_DEPLOY_MODE`                          | `runtime`; `static-export` selects export when no output override is set.                                                                                                                                                                                                                                                                                                                          |
| `ARAGORA_LIVE_DEPLOY_MODE`                  | Fallback alias when `LIVE_DEPLOY_MODE` is unset.                                                                                                                                                                                                                                                                                                                                                   |
| `NEXT_OUTPUT`                               | Unset; explicit Next output mode (`standalone` or `export`).                                                                                                                                                                                                                                                                                                                                       |
| `ARAGORA_NEXT_OUTPUT`                       | Fallback alias when `NEXT_OUTPUT` is unset.                                                                                                                                                                                                                                                                                                                                                        |
| `ANALYZE`                                   | Disabled unless exactly `true`; enables the bundle analyzer.                                                                                                                                                                                                                                                                                                                                       |
| `NODE_ENV`                                  | Set by Next (`development` for dev, `production` for build/start) or Jest (`test`); controls diagnostics, env validation and rewrite defaults.                                                                                                                                                                                                                                                     |
| `PORT`, `HOSTNAME`                          | Standalone launcher defaults: `3000`, `0.0.0.0`; override as in Build.                                                                                                                                                                                                                                                                                                                             |
| `ARAGORA_API_KEY`                           | No app runtime read: appears only in the developer landing page's displayed SDK example. A key for that separate SDK process has no default and must never be put in a public variable.                                                                                                                                                                                                            |

The legacy `src/lib/featureFlags.ts` helper dynamically reads the following
variables in a server environment. Unset values use these defaults; `true` or
`1` enables, any other supplied value disables. Next does not inline dynamic
`process.env[envKey]` access in browser bundles; browser testing uses
`localStorage.feature_<NAME>` instead (which takes precedence).

| Variable                                  | Default |
| ----------------------------------------- | ------- |
| `NEXT_PUBLIC_FEATURE_STANDARD_DEBATES`    | `true`  |
| `NEXT_PUBLIC_FEATURE_FORK_VISUALIZER`     | `true`  |
| `NEXT_PUBLIC_FEATURE_PLUGIN_MARKETPLACE`  | `true`  |
| `NEXT_PUBLIC_FEATURE_PULSE_SCHEDULER`     | `true`  |
| `NEXT_PUBLIC_FEATURE_AGENT_RECOMMENDER`   | `true`  |
| `NEXT_PUBLIC_FEATURE_BATCH_DEBATES`       | `true`  |
| `NEXT_PUBLIC_FEATURE_EVIDENCE_EXPLORER`   | `true`  |
| `NEXT_PUBLIC_FEATURE_GRAPH_DEBATES`       | `true`  |
| `NEXT_PUBLIC_FEATURE_MATRIX_DEBATES`      | `true`  |
| `NEXT_PUBLIC_FEATURE_FORMAL_VERIFICATION` | `true`  |
| `NEXT_PUBLIC_FEATURE_MEMORY_EXPLORER`     | `true`  |
| `NEXT_PUBLIC_FEATURE_TOURNAMENT_MODE`     | `true`  |
| `NEXT_PUBLIC_FEATURE_CLI_AGENTS`          | `false` |
| `NEXT_PUBLIC_FEATURE_AGENT_BRIDGE`        | `false` |

## Observability

M6 placeholder: env-gated Sentry, OpenTelemetry, PostHog and structured server
logging will be documented here when implemented. No telemetry keys are
required for the current quality gates.

## Health

`GET /healthz/` returns HTTP 200 with compact JSON and `Cache-Control: no-store`:

```json
{ "status": "ok", "app": "aragora-live", "version": "2.9.0", "commit": "unknown" }
```

`version` comes from this app's `package.json` at build time. `commit` is the
build-time `NEXT_PUBLIC_BUILD_SHA` (Next config defaults to Git HEAD, then
`unknown` outside Git). `/healthz` redirects with HTTP 308 to `/healthz/`
because `trailingSlash` is enabled.

This is a local Next route, not an `/api` proxy or backend readiness check.
It stays healthy with the backend stopped or `NEXT_PUBLIC_API_URL` pointing
at an unreachable host. Production builds pre-render the document with
`dynamic = 'force-static'`; it describes the frontend build, not live backend
dependencies.

```sh
curl -si http://localhost:3120/healthz/
curl -si http://localhost:3120/healthz
npx jest --ci --maxWorkers=4 --collectCoverageFrom=src/app/healthz/route.ts src/app/healthz/__tests__/route.test.ts
```
