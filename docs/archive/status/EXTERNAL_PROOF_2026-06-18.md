# External Proof Run — 2026-06-18

**Purpose.** A self-contained, reproducible record of Aragora capabilities verified by
*executing existing artifacts* against real data — not by adding new substrate. This run
honors the substrate-freeze directive: run an existing benchmark/verifier, publish one
artifact, exit.

**Repo state.** Run from a worktree off `origin/main` at the merge of `#8388` (the offline
ODR receipt verifier), `#8511`, `#8512`. No production code was modified to produce this
report.

**Honesty note.** Every number below is from a command re-runnable by the reader. Where a
path could not be exercised in this environment (live multi-model debate latency), that is
stated plainly rather than substituted with mock output.

---

## Proof 1 — Decision-receipt integrity verifier (`aragora-verify`, #8388)

The offline verifier is the product "moat": anyone can validate an Open Decision Receipt
(ODR) with no Aragora install or account. Demonstrated here on both the **valid** and the
**tampered** path.

```bash
# from aragora-verify/ ; builds a signed ODR receipt from the package's own fixtures
PYTHONPATH=src:tests python -c "
import json
from cryptography.hazmat.primitives import serialization
from _fixtures import make_keypair, sign_odr, valid_odr
priv, pub = make_keypair()
pem = pub.public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo)
json.dump(sign_odr(valid_odr(), priv), open('/tmp/sample.odr.json','w'))
open('/tmp/sample.pub.pem','wb').write(pem)"

# A) valid signed receipt
PYTHONPATH=src python -m aragora_verify /tmp/sample.odr.json --pubkey /tmp/sample.pub.pem --json

# B) tamper the claim, re-verify (must report ok=false)
python -c "import json;d=json.load(open('/tmp/sample.odr.json'));d['claim']='TAMPERED'+str(d.get('claim'));json.dump(d,open('/tmp/tampered.odr.json','w'))"
PYTHONPATH=src python -m aragora_verify /tmp/tampered.odr.json --pubkey /tmp/sample.pub.pem --json

# (positive + negative paths together) re-run the package's own suite
python -m pytest -q   # 49 passed
```

| Case | `ok` | Checks |
|------|------|--------|
| **Valid signed ODR receipt** | `True` | schema_conformance ✅ · canonical_digest ✅ · signature ✅ (Ed25519) · quorum_consistency ✅ · chain_link ⏭ skip |
| **Tampered claim** | `False` | schema/digest mismatch detected ❌ |

**Result:** the verifier accepts a conformant signed receipt and detects tampering. Backed by
the package's own suite — **49 passed** (`PYTHONPATH=src:tests python -m pytest -q`, shown above).

---

## Proof 2 — Autonomy-tier classifier benchmark (terminal-truth fixtures)

The swarm's terminal-state classifier (`classify_from_metrics`) decides whether an
autonomous run produced a deliverable, was correctly blocked, or needs rescue. Scored against
50 recorded terminal-truth examples across 14 fixtures — fully offline, deterministic.

```bash
python scripts/score_benchmark.py
```

| Metric | Value |
|--------|-------|
| Fixture files | 14 |
| Examples | 50 |
| **Pass** | **50 / 50 (100%)** |
| Fail | 0 |
| Exit code | 0 |

**Result:** every recorded terminal state is classified correctly (auth-failure /
decomposition-limit / no-runner / sanitation / validation-target / branch-pushed /
pr-created / already-resolved / rescue-timeout / worker-crash / verification-failed, etc.).

---

## Proof 3 — Live heterogeneous debate (end-to-end product path)

A genuinely **heterogeneous** debate — three different frontier models, all routed through a
single OpenRouter key — run end-to-end through the real `aragora ask` pipeline (not the
onboarding quickstart), producing a persisted, verifiable decision-integrity receipt.

```bash
aragora ask "Should an early-stage SaaS startup adopt a multi-cloud architecture from day \
one, or start single-cloud and migrate later?" \
  --agents "openrouter|anthropic/claude-opus-4.8||analyst,openrouter|openai/gpt-5.5||critic,openrouter|deepseek/deepseek-v4-pro||synthesizer" \
  --rounds 1 --decision-integrity
```

| Field | Value |
|-------|-------|
| Agents | `openrouter_analyst` (Claude Opus 4.8) · `openrouter_critic` (GPT-5.5) · `openrouter_synthesizer` (DeepSeek V4 Pro) |
| Mode | **live** (not simulated) |
| Verdict | **PASS** |
| Confidence | **0.80** |
| Consensus reached | **True** |
| Debate duration | 212.6s (round 1: 110.3s; critique phase: 71.4s) |
| Agent responses | 5 |
| Receipt | `debate-00d6a36d-…` (schema 1.1), persisted to the receipt store |
| Post-consensus quality | verdict=good, score=10.0, practicality=7.75 |

The pipeline produced a full decision-integrity package: a phased implementation plan, file
scope, test plan, gate criteria, and a rollback plan — then path-grounded the plan against the
(empty) target repo (`grounded=23%`, correctly flagging the plan's files as not-yet-existing).

**Receipt verification** (`aragora receipt verify`):

```
Result: VALID (3/3 checks passed)
  [PASS] artifact_hash present: a484ecd98cb04839…
  [PASS] integrity verified
  [PASS] required fields present (receipt_id, verdict, timestamp, confidence)
```

**Honest caveats.**
- The first attempt via the onboarding **quickstart** path (single provider, 120s internal
  cap) **timed out and fell back to demo/simulated mode**; that mock receipt is *not* reported
  as proof. The result above is the longer-budget, real, 3-model `aragora ask` run.
- Two non-fatal degradations were logged and did not affect the verdict: semantic search used
  the hash-based embedding fallback (no embedding key in this env), and the optional "Claude
  knowledge" research fallback skipped on auth (no direct Anthropic key — debate agents ran via
  OpenRouter). Trending-context enrichment timed out at its 5s soft cap.
- The live receipt is platform schema v1.1, validated by the platform verifier above. The
  standalone ODR-format verifier in Proof 1 targets the portable ODR v0.1 export profile.

---

## Reproducibility

- Verifier (Proof 1): `aragora-verify/`, `PYTHONPATH=src python -m aragora_verify <receipt> --pubkey <pem> --json`
- Classifier benchmark (Proof 2): `python scripts/score_benchmark.py`
- Live debate (Proof 3): `aragora ask "<question>" --agents "openrouter|<model>||<role>,..." --rounds 1 --decision-integrity` (requires `OPENROUTER_API_KEY`)

All commands run with no AWS credentials and no paid API spend beyond the optional live
debate (Proof 3, OpenRouter usage only).
