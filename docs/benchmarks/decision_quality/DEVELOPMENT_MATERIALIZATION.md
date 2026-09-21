# Outcome-Backed Development Materialization Proof

Generated from exact `origin/main` commit:
`5d2c20448ee9dec673073ddd6a264506044b5473`.

This proof covers only the 16 development cases. No holdout packet was
materialized, no model was called, and no benchmark budget was consumed.

VERDICT: MATERIALIZATION PROVEN at 5d2c20448ee9dec673073ddd6a264506044b5473

Development inference readiness remains **BLOCKED** because the canonical
direct Anthropic and OpenAI credentials are unavailable. Gemini is configured,
and the full USD 25 daily budget remains available.

## Reproduction

The locked environment was created and checked with:

```bash
uv run --locked --extra dev python -c \
  "from aragora.evaluation.outcome_backed_preflight import preflight_development_run; print('import-ok')"
```

Packets were materialized with:

```bash
uv run --locked --extra dev python \
  scripts/build_outcome_backed_source_packets.py \
  --split development --json
```

The command fetched 20 allowlisted sources and verified every source against
the SHA-256 pinned in the frozen corpus. It then wrote 16 outcome-blind packets
under the ignored local path
`.aragora/outcome_backed/source_packets/development/`.

Packet-set manifest:

- Schema: `outcome-backed-source-packet-set/1.0`
- Benchmark: `outcome-backed-decision-quality-v1`
- Split: `development`
- Packets: 16
- Sources: 20
- Packet-set SHA-256: `ab09fd09ff788593daf6a6bf25988799353c50193cbd2a07ab6dcb473a431088`

| Case | Packet SHA-256 |
| --- | --- |
| `biz-dev-adobe-figma-close` | `c726488202c8b1ec2ffbc12b1139ab7048e694104cb577aa7cf2e1d77139f37a` |
| `biz-dev-jetblue-spirit-close` | `a83192086da5e84ee9e990d0a09ce16eee01150a4f5de98b22b3440ff8aa6552` |
| `biz-dev-microsoft-activision-close` | `f7806db2a5e976eb5398666a0987efd95fa563e94af24766cd906900c6409cdc` |
| `biz-dev-twitter-merger-close` | `df49e9af8a0d961196bc524739569fea8449907692edb21fe28222026ea4a5e6` |
| `policy-dev-fda-food-traceability-2022` | `4f442ad2f4ddf73810eb13c83d64f81635a0fd5360cc580bd7f41df71a99c552` |
| `policy-dev-nist-csf2-july-2023` | `3bf9ede6abb0603ca829d48437c6efcdb40f31cf5f51166d404e6455ec4ed4f9` |
| `policy-dev-sec-climate-disclosure-2023` | `a50a7a73708dac5d9eb45d3a988dc4c4456b882ba26b548c970d3179299e7c59` |
| `policy-dev-sec-cyber-disclosure-2023` | `aee8f8a6d0a96ad54d4e0f64fdaf3f879bdf24d3497dba5214fc80324f4eea69` |
| `science-dev-atlantic-2023-storm-count` | `6f3bbf50c6860e331b7ac8ff6a162959bf319e8c157080b090d946ccb80ccb04` |
| `science-dev-dart-orbit-change` | `3af1f92ae586aa29bde6a1466c0f2868b70ffe8b58cb337c8b81b9d4eaf2ccc7` |
| `science-dev-psyche-2022-launch` | `665faa4e81c761f0a683822368bee7e2a59358b51ac643d1a6b2c7fa275ca39f` |
| `science-dev-starliner-cft-july-2023` | `ad1e224f2cf350af84b2c04ebe3e00449d88e65c0380a97f6ce30a24b9a90cd7` |
| `se-dev-k8s-dockershim-1-24` | `d1bdd8ecb4a7e1987bd8ca09f016fa901b57cf719646852c384283dd1803f98f` |
| `se-dev-node16-eol` | `963d18e4a6bfba6c7288abb9757ab74e34482e88879c84192a6f58f6f8f920e7` |
| `se-dev-pep703-acceptance` | `4ac82fc42336b639f4dc78bb4603f5750cb51a92775054d486d7096a5c36bc78` |
| `se-dev-python312-distutils-removal` | `66560c12fb35abe4f29c7d6e9e8a25412926d10051f3304cddad9b5c05d698ef` |

## Zero-Inference Preflight

The preflight was run with the exact implementation SHA:

```bash
uv run --locked --extra dev python \
  scripts/preflight_outcome_backed_development.py \
  --implementation-sha 5d2c20448ee9dec673073ddd6a264506044b5473 \
  --output .aragora/outcome_backed/preflight_report.json
```

It rendered 64 deterministic prompts across the four frozen conditions. The
corpus, roster, packet set, and prompt set remained hash-bound. The process
exited `1`, as designed for a truthful readiness blocker, and emitted:

```json
{
  "benchmark_id": "outcome-backed-decision-quality-v1",
  "blockers": [
    {
      "code": "missing_provider_credential",
      "message": "claude direct-api credential is unavailable"
    },
    {
      "code": "missing_provider_credential",
      "message": "openai direct-api credential is unavailable"
    }
  ],
  "budget": {
    "cap_usd": "25",
    "committed_usd": "0",
    "event_count": 0,
    "exceeded": false,
    "open_reservations": 0,
    "remaining_usd": "25",
    "reserved_usd": "0",
    "settled_usd": "0",
    "utc_date": "2026-08-31"
  },
  "case_count": 16,
  "condition_count": 4,
  "condition_ids": [
    "claude-single",
    "openai-single",
    "gemini-single",
    "aragora-team"
  ],
  "corpus_sha256": "ee5a809d88dddc1c17c326adaef3b619ac10fe936c70bcc559370509846809c5",
  "credential_readiness": [
    {
      "accepted_environment_variables": [
        "ANTHROPIC_API_KEY"
      ],
      "agent_type": "anthropic-api",
      "allow_fallback": false,
      "credential_available": false,
      "credential_source": "missing",
      "expected_resolved_model": "claude-opus-5",
      "family": "claude",
      "requested_model": "claude-opus-5",
      "transport": "direct-api"
    },
    {
      "accepted_environment_variables": [
        "OPENAI_API_KEY"
      ],
      "agent_type": "openai-api",
      "allow_fallback": false,
      "credential_available": false,
      "credential_source": "missing",
      "expected_resolved_model": "gpt-5.6-sol",
      "family": "openai",
      "requested_model": "gpt-5.6-sol",
      "transport": "direct-api"
    },
    {
      "accepted_environment_variables": [
        "GEMINI_API_KEY",
        "GOOGLE_API_KEY"
      ],
      "agent_type": "gemini",
      "allow_fallback": false,
      "credential_available": true,
      "credential_source": "env",
      "expected_resolved_model": "gemini-3.1-pro-preview",
      "family": "gemini",
      "requested_model": "gemini-3.1-pro-preview",
      "transport": "direct-api"
    }
  ],
  "development_case_ids": [
    "biz-dev-adobe-figma-close",
    "biz-dev-jetblue-spirit-close",
    "biz-dev-microsoft-activision-close",
    "biz-dev-twitter-merger-close",
    "policy-dev-fda-food-traceability-2022",
    "policy-dev-nist-csf2-july-2023",
    "policy-dev-sec-climate-disclosure-2023",
    "policy-dev-sec-cyber-disclosure-2023",
    "science-dev-atlantic-2023-storm-count",
    "science-dev-dart-orbit-change",
    "science-dev-psyche-2022-launch",
    "science-dev-starliner-cft-july-2023",
    "se-dev-k8s-dockershim-1-24",
    "se-dev-node16-eol",
    "se-dev-pep703-acceptance",
    "se-dev-python312-distutils-removal"
  ],
  "implementation_sha": "5d2c20448ee9dec673073ddd6a264506044b5473",
  "ok": false,
  "packet_set_sha256": "ab09fd09ff788593daf6a6bf25988799353c50193cbd2a07ab6dcb473a431088",
  "prompt_count": 64,
  "prompt_set_sha256": "0c8e71c2e3b197bede3f543fd3c131ea451ddf606373faf37d513cedd22e5768",
  "ready": false,
  "roster_sha256": "a9fd7b664ab0f86b7c13e172d6eb03ade3edb927edf9a49ff739b57de1b2542e",
  "schema_version": "outcome-backed-development-preflight/1.0"
}
```

## Validation

```bash
uv run --locked --extra dev pytest \
  tests/evaluation/test_outcome_backed_packets.py \
  tests/evaluation/test_outcome_backed_preflight.py \
  tests/scripts/test_preflight_outcome_backed_development.py -q
```

Result: `31 passed`.

No budget ledger was created or mutated by this proof. The next execution step
is credential provisioning, followed by a fresh preflight at the implementation
SHA that will actually run the development benchmark.
