# Aragora documentation site

The public documentation at [docs.aragora.ai](https://docs.aragora.ai), built
with [Docusaurus](https://docusaurus.io/) 3.9. The pages under `docs/` are
generated from the repository's root `docs/` tree by `scripts/sync-docs.js`;
edit the source there, not the generated copy.

## Setup

Node 20 or newer and npm are required. Install the pinned dependencies from
`package-lock.json`:

```bash
cd docs-site
npm ci
```

`.npmrc` applies the repository-wide release cooldown (`min-release-age=3`), so
freshly published package versions are not installable for three days.

## Run

Regenerate the docs tree, then serve the site with hot reload. The port is
taken from `DOCS_PORT` so it never collides with other local services:

```bash
npm ci
node scripts/sync-docs.js
npm run start -- --port "${DOCS_PORT:-3130}" --no-open
```

Open `http://127.0.0.1:${DOCS_PORT:-3130}/` in a browser.

## Build

Produce the static site under `build/` and preview it:

```bash
node scripts/sync-docs.js
npm run build
npm run serve -- --port "${DOCS_PORT:-3130}" --no-open
```

`onBrokenLinks` stays at `warn`: the build reports broken links but still
succeeds, and the broken-link ratchet (not the build) enforces the count.

## Test

The Vitest suite in `tests/` checks that every sidebar doc id resolves to a
docs file, that `docusaurus.config.js` keeps a valid `url`/`baseUrl` and
`onBrokenLinks: 'warn'`, and that the PostHog plugin is only present when its
key is configured:

```bash
npm test
```

## Lint

```bash
npm run typecheck        # tsc --noEmit over config, sidebars, scripts, tests
npm run lint             # ESLint 9 flat config (eslint.config.mjs)
npm run format:check     # Prettier (npm run format rewrites)
npx knip                 # unused files, dependencies and exports
npm run lint:duplicates  # jscpd over src, scripts and tests (.jscpd.json)
```

From the repository root, `make readiness-lint-docs readiness-typecheck-docs
readiness-test-docs` runs the same checks plus the knip and file-size ratchets
(`scripts/baselines/docs-knip.json`, `scripts/baselines/docs-file-sizes.json`).

## Deploy

`.github/workflows/deploy-docs.yml` builds the site on every push to `main`
that touches `docs/**` or `docs-site/**` and publishes `build/` to GitHub Pages
at `https://docs.aragora.ai`. No manual step is involved.

The `deploy` and `deploy:preview` npm scripts and `DEPLOY.md` describe the
earlier Vercel flow. They are unused: GitHub Pages is the deploy target and the
`vercel` binary is not a dependency of this package.

## Configuration

| Variable          | Purpose                                                                                                                                         |
| ----------------- | ----------------------------------------------------------------------------------------------------------------------------------------------- |
| `POSTHOG_API_KEY` | Build-time analytics gate. When set, the build enables the PostHog plugin with this project key; when unset or empty, no analytics is embedded. |
| `DOCS_PORT`       | Local port for `npm run start` and `npm run serve` (see Run); defaults to 3130 in the examples above.                                           |

No `.env` file is read; set the variables in the shell that runs the build.
