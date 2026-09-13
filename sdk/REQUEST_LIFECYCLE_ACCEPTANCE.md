# Installed HTTP consumer acceptance

These SDK-local runners test installed artifacts, not an editable/source checkout.
Use a clean worktree at one recorded commit for **both** packages and test inputs.
They are local tests, not release publication, live inference, receipt verification,
or a claim that unrelated repository checks pass.

## Build and run

From the repository root, with Python 3.10+ and Node 20+ available:

```sh
set -eu
source_root="$(pwd)"
git diff --exit-code
git diff --cached --exit-code
git rev-parse HEAD
consumer="$(mktemp -d)"
python3 -m venv "$consumer/build-tools"
"$consumer/build-tools/bin/python" -m pip install build
"$consumer/build-tools/bin/python" -m build --wheel --outdir "$consumer/packages" sdk/python
python3 -m venv "$consumer/python"
"$consumer/python/bin/python" -m pip install "$consumer"/packages/*.whl pytest pytest-asyncio
"$consumer/python/bin/python" -I "$source_root/sdk/python/acceptance/http_lifecycle.py"

(cd sdk/typescript && npm ci --ignore-scripts && npm run typecheck && npm run build)
(cd sdk/typescript && npm pack --ignore-scripts --pack-destination "$consumer/packages")
mkdir "$consumer/typescript"
(cd "$consumer/typescript" && npm init -y && npm install --ignore-scripts "$consumer"/packages/*.tgz)
node "$source_root/sdk/typescript/acceptance/http-lifecycle.cjs" "$consumer/typescript"
shasum -a 256 "$consumer"/packages/*
"$consumer/python/bin/python" -m pip freeze
node --version
```

Run the final Node command on both the minimum supported major (20) and the
current development runtime. Keep the commit, package SHA-256 values, resolved
dependency versions, runtime versions, commands, stdout/stderr and exit codes.
Retain the temporary consumer directory for inspection; remove it only when its
artifacts are no longer needed. No package/version/release configuration is changed.

## Contracts

| Surface | Acceptance |
| --- | --- |
| Python sync and async | Existing full request/transport lifecycle parameter matrices run against the wheel: integer/date/malformed hints, preserved zero, automatic-wait boundary, diagnostic fields, attempt counts, typed errors/causes, cancellation in requests/backoff and owned-client closure. |
| Python loopback and examples | Debate/review/receipt HTTP routes are exercised through a real local server; both documented error-handler examples execute using deterministic HTTPX transports. |
| Native TypeScript CJS and ESM | Actual require/import export conditions, namespace routes, malformed JSON/body failures without replay, JSON/text/empty results and a prior 503 attempt. |
| TypeScript deadlines | Successful/error bodies, pre-header timeout, per-request overrides, cleanup before backoff, concurrent requests, completion/abort ordering and both documented handlers. |
| Real Fetch | Loopback successful/invalid POSTs and stalled headers/bodies at HTTP 200/400/503; the configured deadline must beat a failure watchdog. |

Python copies only the two focused lifecycle test modules into a temporary directory,
excludes their source-inserting conftest and repository pytest configuration, and
checks installed module origins before and after pytest. Deselection, skips/xfails,
zero collection or collection-only execution fail acceptance; every collected case
must pass. TypeScript verifies bundle paths beneath the consumer's
node_modules and loads ESM through a generated native package-import probe.

The runners print installed-file hashes. This is provenance, not cryptographic
receipt authenticity. Compare mutation runs with a passing unchanged control:
restored raw header conversion, lost zero hints, generic transport exceptions,
successful-response replay, early timer clearing, missing timer cleanup and swallowed
body aborts must each fail. Mutate disposable artifact copies, never the reviewed tree.

Synthetic failures test SDK contracts, not the incidence of real network failures.
Loopback responses are minimal HTTP fixtures, not an Aragora server or signed receipts.
Examples use their committed source; no real service, credentials or paid provider
is contacted. Existing source-level suites and repository gates remain required.
