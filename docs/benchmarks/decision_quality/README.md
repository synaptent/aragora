# Outcome-Backed Decision Quality Benchmark

This benchmark tests the bounded claim that Aragora's fixed heterogeneous team
improves outcome-backed decision quality over its strongest constituent single
model. Truthful completion is valid whether the final result is `go`,
`conditional_go`, or `no_go`.

## Frozen Contract

`benchmark-manifest.json` binds eight construction tranches, the aggregate
24-case corpus and outcome-sidecar digests, the prompt, the exact model roster,
the scorer contract, the retry policy, and the paid-API budget. The canonical
JSON convention is Python `json.dumps` with sorted keys, compact separators,
UTF-8 output, `ensure_ascii=False`, and non-finite numbers rejected. It is a
documented benchmark convention, not a claim of RFC 8785 compatibility.

The outcome sidecars are never model-visible. `run` builds one isolated packet
per case and rejects a packet that contains outcome IDs, resolution text,
authoritative outcome-source IDs, or preregistered crux IDs. Any correction to
a tranche, prompt, roster, scorer contract, or answer key requires a new
benchmark revision and invalidates affected runs.

The fixed conditions are:

- `single_claude`
- `single_openai`
- `single_gemini`
- `aragora_team`, using the same three families, one adversarial round, and one
  declared synthesis

The frozen roster uses subscription-backed `vibeproxy-required` transport.
The runner must fail closed on a requested/resolved model mismatch and must not
substitute an incomplete family roster. Paid API fallback remains capped at
USD 25 per UTC day and is not enabled by this manifest.

## Available Command

```bash
python3 scripts/outcome_decision_quality_benchmark.py validate-corpus
```

This contract-first slice intentionally does not execute models or score
results. The later `run`, `score`, and `render` implementation must extend this
same CLI without changing the frozen corpus, prompt, roster, scorer contract,
retry policy, or budget. Before inference, that implementation must prove its
result records are bound to the manifest, case packet, split, repetition, and
implementation SHA.

The first holdout repetition creates a holdout lock that binds the corpus,
outcomes, prompt, roster, scorer contract, and implementation SHA. The second
repetition refuses to run if any bound field changed.

## Result Interpretation

Primary metrics are binary Brier score, directional accuracy, preregistered
crux recall, provenance completeness, team receipt verification, latency,
model calls, and cost. The target is an absolute holdout Brier improvement of
at least 0.05 over the best single condition. Reports include descriptive
ranges only; this 24-case corpus does not support a statistical-significance
claim.
