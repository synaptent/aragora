# VibeProxy Local Transport

Aragora can use a locally running VibeProxy for developer and operator model
calls when an operator opts in. VibeProxy remains a transport: provider family
and requested model identity do not change, and it does not create an
additional review signal.

## Current Scope

- Supported now: bounded Fable/Claude advisory consults and Claude-family
  merge-quorum review collection through the Anthropic Messages protocol, plus
  exact-model, non-streaming OpenAI Chat Completions. The transport client
  also contract-tests exact-model OpenAI Responses for callers that already
  use that protocol. Each path remains direct unless VibeProxy is explicitly
  selected.
- Direct by default: normal agents, CI, production servers, credential checks,
  public gateways, every unconfigured merge-quorum evidence collection, OpenAI
  web search and tools, OpenAI streaming, and custom `OPENAI_BASE_URL`
  gateways.
- Deferred until contract-tested: web search, tools, embeddings, image, audio,
  and other media capabilities.

The local implementation uses `http://127.0.0.1:8318/v1`. This is VibeProxy's
loopback-bound core endpoint and is provisional. Port `8317` is not selected:
the tested macOS application listened on all interfaces there, and Aragora
rejects it even when explicitly configured.

## Configuration

```bash
export ARAGORA_MODEL_TRANSPORT=vibeproxy-prefer
export ARAGORA_VIBEPROXY_BASE_URL=http://127.0.0.1:8318
```

Modes:

- `direct`: retain existing behavior. This is the project and advisory-consult
  default.
- `vibeproxy-prefer`: try the exact catalog model through VibeProxy, then use
  the existing backend order if the proxy is unavailable.
- `vibeproxy-required`: fail closed if VibeProxy cannot serve the exact model.

Optional settings are `ARAGORA_VIBEPROXY_API_KEY`,
`ARAGORA_VIBEPROXY_CATALOG_TTL_SECONDS`, and
`ARAGORA_VIBEPROXY_MODEL_MAP`. Model mappings are explicit JSON; no semantic
substitution occurs by default.

Plaintext endpoints must use a literal loopback IP. Remote endpoints require
HTTPS and an explicit key. Credentials are never included in diagnostics.
Requests ignore ambient HTTP proxy settings and reject redirects so prompts
and authorization headers cannot escape the resolved endpoint.
Loopback prevents network exposure but does not authenticate the local server.
Opting in therefore trusts the process bound to the configured endpoint with
the full consult prompt. Use `direct` on a shared or untrusted host; broader
rollout requires a separate server-authentication or endpoint-pinning design.

## Readiness Diagnostic

Check the configured endpoint without sending a prompt or making any inference
request:

```bash
python3 scripts/check_vibeproxy.py
python3 scripts/check_vibeproxy.py --json
```

The command always performs a fresh `GET /v1/models`. If that required catalog
request succeeds, it may also perform `GET /` to read advertised routes and an
allowlisted version header. It never calls `/messages`, `/chat/completions`,
`/completions`, or another prompt-bearing route. Exit code `0` means the live
catalog was non-empty and well formed. Configuration, availability, timeout,
redirect, and malformed-response failures exit nonzero; `--json` still emits
exactly one schema-versioned object.

Schema version `1` contains:

- `endpoint`: the normalized URL and literal-loopback classification. Unsafe
  input is rejected before this field is populated, so userinfo and query data
  are never echoed.
- `version`: an allowlisted HTTP-header value and its exact source, or
  `{ "value": null, "source": "unknown" }`. The diagnostic does not guess a
  version from model names or make remote use depend on a local app bundle. A
  value containing the request credential is omitted with source `redacted`.
- `protocols.advertised`: sanitized method/path pairs reported by `GET /`.
  `verified_no_inference` separately lists only `GET /v1/models`, which this
  run actually exercised. `aragora_implemented_not_probed` records the
  Anthropic Messages and OpenAI Chat/Responses routes implemented by Aragora
  without claiming the diagnostic verified them. `advertised_redacted_count`
  reports routes omitted because they echoed the request credential.
- `model_inventory`: a sorted model-ID list and server count. IDs containing
  the request credential or terminal-unsafe characters are omitted from the
  list and counted in `redacted_count`.
- `catalog_freshness`: the age and configured TTL of the forced live catalog
  observation. Age and freshness are process-local monotonic-clock values, not
  server timestamps. With a zero TTL, the observation is intentionally not
  cache-fresh even though the request succeeded.
- `latency_ms`: catalog, optional metadata, and total wall-clock timings. One
  total budget covers both GETs; metadata cannot reset it. Set the budget with
  `--timeout-seconds` or
  `ARAGORA_VIBEPROXY_DIAGNOSTIC_TIMEOUT_SECONDS`.
- `error`: `null` on readiness, otherwise a stable sanitized category and
  message. Response bodies, redirect locations, authorization headers, API
  keys, prompts, and token-bearing URL data are never included.

The diagnostic preserves the same trust boundary as transport requests:
plaintext is literal-loopback-only, remote endpoints require HTTPS and an
explicit API key, port `8317` is prohibited, ambient proxies are disabled,
redirects are denied, and response size plus wall-clock reads are bounded.
Catalog readiness is not proof that a prompt-bearing protocol works or that the
local process is trustworthy.

## Verify

```bash
python3 scripts/consult_claude.py --json "Reply with exactly DIRECT"
ARAGORA_MODEL_TRANSPORT=vibeproxy-prefer \
  python3 scripts/consult_claude.py --json "Reply with exactly PREFER_PROXY"
ARAGORA_MODEL_TRANSPORT=vibeproxy-required \
  python3 scripts/consult_claude.py --json "Reply with exactly PROXY_ONLY"
```

For an exact-head Claude quorum dry-run, select the transport explicitly:

```bash
ARAGORA_MODEL_TRANSPORT=vibeproxy-required \
  python3 scripts/collect_quorum_evidence.py \
    --repo synaptent/aragora --pr <PR> --reviewers claude --json
```

The resulting evidence still identifies the logical family as Claude and
discloses the VibeProxy Anthropic Messages harness. Transport selection does
not grant evidence-posting, settlement, or merge authority. The normal
exact-head lint, dissent, tier, and human-settlement gates remain unchanged.
`ARAGORA_COLLECT_EVIDENCE_VIBEPROXY_TIMEOUT_SECONDS` bounds the proxy leg;
prefer mode also reserves half of the reviewer timeout for the direct fallback.

## Fallback Rules

`vibeproxy-prefer` tries the requested exact model through VibeProxy before
using the existing direct backend, and only before any output begins.
`vibeproxy-required` fails closed when an eligible exact model cannot be served.
In `vibeproxy-prefer`, capabilities outside the supported slices above (web
search, tools, custom endpoints, streaming) stay direct. In
`vibeproxy-required` the policy is an egress boundary: those requests raise
instead of silently reaching a direct provider endpoint.
One timeout budget covers catalog resolution and each eligible proxy request;
catalog discovery is additionally capped at a few seconds so an unresponsive
proxy cannot delay `vibeproxy-prefer` fallback.

## Prepare-Only Audited Claude Code Runner

`scripts/prepare_claude_code_vibeproxy_review.py` is a separate, opt-in diagnostic,
not a quorum backend. Every output has `non_countable=true` and
`would_count=false`; there is no posting or apply option. Existing single-shot
caps, family requirements, dissent handling, and attempt budgets are unchanged.

Run the no-inference preflight against a clean disposable checkout, using full
base/head SHAs and a new output directory outside that checkout:

```bash
python3 scripts/prepare_claude_code_vibeproxy_review.py \
  --checkout /path/to/clean-checkout --base FULL_BASE_SHA --head FULL_HEAD_SHA \
  --output /private/tmp/claude-review-diagnostic-unique
```

Only after separate authorization and reviewer-capacity coordination, repeat with
a **new** output directory, `--execute --timeout 180`, and
`ARAGORA_MODEL_TRANSPORT=vibeproxy-required`. The existing
`ARAGORA_VIBEPROXY_BASE_URL` must select the literal `127.0.0.1` HTTP gateway;
no remote gateway, direct fallback, model mapping, or saved Claude login is used.
Execution currently requires macOS `sandbox-exec` and Claude Code `2.1.263`.
Unsupported containment or CLI versions fail closed.

The host materializes exact Git blobs into a read-only sandbox. Only bounded
Read operations are permitted. It verifies returned line ranges against those
blobs and checks that the same results reach subsequent model requests. Every
changed file must be covered before the diagnostic is complete; partial reads,
missing history, model substitution, truncation, and failed tools are terminal.
Deleted, renamed, empty, binary, symlink, and submodule surfaces are unsupported
in this first version. Streams are bounded and buffered per response so tool
instructions can be checked before execution. Hard deadlines kill the owned CLI
process group; a failed diagnostic must not be retried implicitly.

`diagnostic.json` records coverage, artifact hashes, harness/binary identity,
gateway, requested/response-declared model, and termination. Upstream model
attestation remains explicitly `UNMEASURED`. Artifacts include source content and
are local diagnostics, not PR evidence comments; keep the private output directory
secure. Exit `0` means preflight/preparation succeeded, not that the code is sound
or countable. Exit `2` is a failed diagnostic. Production counting integration and
any real-PR pilot require separate Tier-4 authorization.
