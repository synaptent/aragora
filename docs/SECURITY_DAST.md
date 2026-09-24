# Dynamic application security testing (DAST)

## Scan lanes

The M4 DAST workflow uses an isolated demo backend, without production credentials:

| Lane | Scan | Budget and policy |
| --- | --- | --- |
| Non-draft server/API PR | ZAP baseline spider (`-m 1 -I`), then passive OpenAPI scan (`-S -I -T 3`) | Small curated GET surface; warn-only findings |
| Nightly | Full canonical OpenAPI spec, active scan | 30-minute job cap; warn-only findings |

Draft PRs skip these scans; marking a PR ready triggers the lane. The small smoke
lane also runs nightly alongside the full scan. ZAP actions disable issue writing
and failing on findings (`allow_issue_writing: false`, `fail_action: false`), retain separate
HTML/JSON reports, and use `-c rules.tsv` in both lanes. Spec-regeneration drift
is a job failure, not a tolerated finding. See [CI lanes](CI_LANES.md).
Do not run the full active scan against production or as a local PR smoke test.

## Reproducible scan input

`docs/api/openapi.json` remains the canonical spec used by SDK generation and
route validation. The committed `docs/api/openapi-dast.json` is a separate scan
input, not a replacement. Consumers must name their spec explicitly, not discover
JSON files by a wildcard.

From the repository root, regenerate the committed file with:

```bash
python3 scripts/ci/trim_openapi.py \
  --input docs/api/openapi.json \
  --paths scripts/ci/zap_api_paths.txt \
  --output docs/api/openapi-dast.json \
  --server http://localhost:8080
git diff --exit-code -- docs/api/openapi-dast.json
```

The trimmer preserves `openapi`, `info`, and all `components`, includes only the
listed paths' GET operations, and replaces `servers`. It accepts blank lines and
`#` comments, deduplicates paths, rejects path parameters and missing paths/GETs,
and emits recursively sorted JSON with a final newline. Exit codes: **0** success
or help, **1** invalid input or file I/O error, **2** invalid CLI usage.
`python3 scripts/ci/trim_openapi.py --help` lists the arguments.

The 38 paths in `scripts/ci/zap_api_paths.txt` include health, debates, agents,
OAuth provider discovery, A2A discovery, analytics and accounting. These are
public-facing endpoints, not an authentication bypass. The canonical CI target
is `http://localhost:8080`. Local Docker scans override it with
`-O http://host.docker.internal:3110`, without regenerating the committed file.

## Tolerated baseline rules

`.zap/rules.tsv` uses exactly three TAB-separated fields: rule id, action, note.
The following existing demo findings are tolerated, not declared safe for
production. Remove each exception when the corresponding hardening is verified.

| Rule id | What it detects | Why tolerated on this target |
| --- | --- | --- |
| [10036](https://www.zaproxy.org/docs/alerts/10036/) | HTTP Server Response Header, including server fingerprint/version disclosure | The local Python demo server identifies itself. Production server/edge header hardening is separate from this scan-input change. |
| [10049](https://www.zaproxy.org/docs/alerts/10049/) | Content Cacheability, including cache-control directives that need review | This anonymous demo has no production customer data. Production authenticated responses still need a route-specific cache review; this exception does not endorse caching them. |
| [10055](https://www.zaproxy.org/docs/alerts/10055/) | Content Security Policy (CSP) issues, such as wildcard or missing fallback directives | The existing demo policy is not being redesigned here. Browser-facing production pages still require a restrictive, tested CSP. |
| [10063](https://www.zaproxy.org/docs/alerts/10063/) | Permissions Policy Header Not Set | The demo API does not configure browser feature permissions. Browser/edge policy hardening is deferred, not applied by this mission. |
| [90004](https://www.zaproxy.org/docs/alerts/90004/) | Insufficient Site Isolation Against Spectre | The demo lacks cross-origin isolation headers. Enforcing them needs compatibility checks for embedded and cross-origin clients. |
| 100000 | Server Error, including 5xx responses | **WARN, never IGNORE.** Documented accounting `503 not_configured` responses are expected; actual 500s and `handler_no_result` are regressions and must stay visible. |

The first five rules are `IGNORE` in the demo rule file. Other rules keep their
default policy; `-I` makes warnings non-fatal, not invisible. A green scan alone
does not prove that every request succeeded. Inspect the reports and backend log.

## Accounting response expectations

`rules.tsv` is **per-rule-id, not per-path**. It cannot exempt one endpoint's
503 while preserving the same rule on another endpoint. Expected per-path
responses are therefore documented here and annotated beside each accounting
path in `scripts/ci/zap_api_paths.txt`. Rule 100000 stays WARN globally.

All paths below are relative to `/api/v1/accounting`:

| Paths | Anonymous demo response |
| --- | --- |
| `/ap/discounts`, `/ap/forecast`, `/ap/invoices`, `/ar/aging`, `/ar/collections`, `/ar/invoices` | **401**, RBAC-protected. Demo mode has no auth bypass. |
| `/callback`, `/connect`, `/customers`, `/reports`, `/status`, `/transactions` | **503** with top-level `code: "not_configured"`, accounting integration unavailable. |
| `/gusto/callback`, `/gusto/connect`, `/gusto/employees`, `/gusto/payrolls`, `/gusto/status` | **503** with top-level `code: "not_configured"`, Gusto integration unavailable. |
| `/expenses`, `/expenses/export`, `/expenses/pending`, `/expenses/stats`, `/invoices`, `/invoices/overdue`, `/invoices/pending`, `/invoices/stats`, `/invoices/status`, `/payments/scheduled` | **401**, authentication required. |

The seven key regression paths are the six AP/AR paths (401) and `/connect`
(503 `not_configured`). None may return **500** or **`handler_no_result`**.
Only the listed integration paths may produce the expected 503s. Record any
rule-100000 instances and inspect status/body, rather than ignoring the whole
rule. A 401 is not a server-error instance (`100000-2`). Current ZAP images may
include 400/401 responses as informational client-error instances (`100000-1`)
under the same plugin id 100000 in JSON reports. Enumerate both variants, but do
not confuse the client-error entries with 5xx server errors.

Scanner-generated query values may be rejected before integration dispatch.
For example, `/gusto/employees?active=true` and
`/gusto/payrolls?start_date=start_date&end_date=end_date&processed=true` return
400 rather than the plain-GET 503 above. Timestamp-disclosure rule 10096 can flag
these responses (and `/api/v1/agents?include_stats=false`). The value it reports,
`1780272000`, is not a runtime error timestamp: it is the deliberately public
`Deprecation: @1780272000` header on these v1 responses, the Unix epoch of the
announced v1 sunset date 2026-06-01T00:00:00Z (`V1_DEPRECATION_TIMESTAMP` in
`aragora/server/versioning/constants.py`, emitted by
`aragora/server/middleware/deprecation.py`; the 400 is sent before handler
dispatch, so it carries this form rather than `Deprecation: true`). The separate
`Sunset` header carries the same date as an HTTP-date. The finding remains
visible as WARN, not suppressed.

## Run locally with Docker

Prerequisites: the installed Python development environment, Docker running, and
`ghcr.io/zaproxy/zaproxy:stable`. Run from the repository root. Use an isolated demo
instance and unoccupied ports. Binding `0.0.0.0` lets Docker reach the host;
do this only on a trusted local network, never with production data or credentials.
On Linux, the Docker commands' host-gateway mapping provides the host alias too.

In one terminal, run the demo backend in the foreground:

```bash
ARAGORA_CONTROL_PLANE_WS_PORT=3112 \
ARAGORA_NOMIC_LOOP_WS_PORT=3113 \
ARAGORA_CANVAS_WS_PORT=3114 \
  .venv/bin/aragora serve --demo --host 0.0.0.0 --api-port 3110 --ws-port 3111
```

In another terminal, check readiness, prepare a work directory, then scan:

```bash
curl --fail --max-time 10 http://127.0.0.1:3110/healthz
mkdir -p .zap/work
cp .zap/rules.tsv .zap/work/rules.tsv
cp docs/api/openapi-dast.json .zap/work/openapi-dast.json

timeout 300 docker run --rm --name zap-val-baseline \
  --add-host=host.docker.internal:host-gateway \
  -v "$PWD/.zap/work:/zap/wrk:rw" ghcr.io/zaproxy/zaproxy:stable \
  zap-baseline.py -t http://host.docker.internal:3110 \
  -m 1 -I -c rules.tsv -r baseline.html -J baseline.json

timeout 240 docker run --rm --name zap-val-api \
  --add-host=host.docker.internal:host-gateway \
  -v "$PWD/.zap/work:/zap/wrk:rw" ghcr.io/zaproxy/zaproxy:stable \
  zap-api-scan.py -t /zap/wrk/openapi-dast.json -f openapi \
  -O http://host.docker.internal:3110 -S -I -T 3 -c rules.tsv \
  -r api.html -J api.json
```

Retain `.zap/work/` reports locally for inspection, do not commit them. Expect
exit 0 and `FAIL-NEW: 0`; confirm no HTTP 500 or `handler_no_result` in responses
and the backend log. `/api/v1/agents` may return 400 for scanner-generated query
parameters even when a plain GET returns 200.

Stop the backend with Ctrl-C. If a scan times out, remove only its named container
with `docker rm -f zap-val-baseline` or `docker rm -f zap-val-api`. Do not use host
networking. If Docker is unavailable, report live scans as **blocked**, not passed.
