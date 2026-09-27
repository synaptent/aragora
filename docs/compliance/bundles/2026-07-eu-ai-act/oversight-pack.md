# Human Oversight Evidence Pack (EU AI Act Article 14)

Generated: 2026-07-20T15:37:36.007105+00:00
Amended: 2026-07-22 — 14(4)(c) manually downgraded to **partial** (source
receipt's verdict reasoning is truncated at 2,000 characters, mid-sentence,
and unrecoverable); integrity digest recomputed over the amended pack.
Window: 30 days (2026-06-20T15:37:36.007105+00:00 → 2026-07-20T15:37:36.007105+00:00)
Integrity: `088e0e97992023fd379d738e7d5010754038c42a5cff86259d29fc3a5f132595` (sha256/jcs)

## Summary

- Receipts in window: **1**
- Human-attested: **0**
- Autonomous (explicitly recorded): **1**
- Attestor identities: scarmani
- Mechanisms: {"settlement_status": 1}
- Excluded (no timestamp): 0; out of window: 3

## Article 14 clause mapping

| Clause | Status | Basis |
|---|---|---|
| 14(1) | partial | 1 human-settlement attestation(s) demonstrate the oversight mechanism operating in the window, but no windowed receipt is itself human-attested |
| 14(2) | satisfied | all 1 windowed receipts carry verdict + confidence |
| 14(3) | partial | 1 human-settlement attestation(s) demonstrate the oversight mechanism operating in the window, but no windowed receipt is itself human-attested |
| 14(4)(a) | satisfied | all 1 windowed receipts carry agent responses / provenance |
| 14(4)(b) | satisfied | all 1 windowed receipts carry recorded dissent field |
| 14(4)(c) | partial | amended 2026-07-22: the 1 windowed receipt carries a verdict_reasoning field, but the recorded verdict_reasoning/final_answer are truncated mid-sentence at 2,000 characters by the receipt persistence path; the local receipt store copy carries the identical truncation, so the full synthesis text is not recoverable. Truncated reasoning only partially supports 'overseers can correctly interpret the system's output' |
| 14(4)(d) | partial | 1 human-settlement attestation(s) demonstrate the oversight mechanism operating in the window, but no windowed receipt is itself human-attested |
| 14(4)(e) | partial | interruption capability is procedural (kill-switches, halt files); not evidenced per-receipt by this pack |

## NIST AI RMF cross-references

| Function | Evidence basis |
|---|---|
| GOVERN 3.2 | Oversight identity layer and per-decision attestor records. |
| MANAGE 2.4 | Human settlement gate; withheld attestation withholds action. |
| MEASURE 2.10 | Preserved dissent and confidence in every windowed receipt. |

## Settlement fetch completeness

- Repo scanned: synaptent/aragora (424 merged PRs in window)
- Truncated scan: **no**
- Skipped (unverifiable oversight): 50
  - PR #9417: oversight identity must differ from execution identity (both are 'scarmani'); record the decision as 'autonomous' instead of self-attesting
  - PR #9413: oversight identity must differ from execution identity (both are 'scarmani'); record the decision as 'autonomous' instead of self-attesting
  - PR #9412: oversight identity must differ from execution identity (both are 'scarmani'); record the decision as 'autonomous' instead of self-attesting
  - PR #9406: oversight identity must differ from execution identity (both are 'scarmani'); record the decision as 'autonomous' instead of self-attesting
  - PR #9371: oversight identity must differ from execution identity (both are 'scarmani'); record the decision as 'autonomous' instead of self-attesting
  - PR #9370: oversight identity must differ from execution identity (both are 'scarmani'); record the decision as 'autonomous' instead of self-attesting
  - PR #9368: oversight identity must differ from execution identity (both are 'scarmani'); record the decision as 'autonomous' instead of self-attesting
  - PR #9367: oversight identity must differ from execution identity (both are 'scarmani'); record the decision as 'autonomous' instead of self-attesting
  - PR #9366: oversight identity must differ from execution identity (both are 'scarmani'); record the decision as 'autonomous' instead of self-attesting
  - PR #9365: oversight identity must differ from execution identity (both are 'scarmani'); record the decision as 'autonomous' instead of self-attesting
  - PR #9360: oversight identity must differ from execution identity (both are 'scarmani'); record the decision as 'autonomous' instead of self-attesting
  - PR #9358: oversight identity must differ from execution identity (both are 'scarmani'); record the decision as 'autonomous' instead of self-attesting
  - PR #9351: oversight identity must differ from execution identity (both are 'scarmani'); record the decision as 'autonomous' instead of self-attesting
  - PR #9346: oversight identity must differ from execution identity (both are 'scarmani'); record the decision as 'autonomous' instead of self-attesting
  - PR #9343: oversight identity must differ from execution identity (both are 'scarmani'); record the decision as 'autonomous' instead of self-attesting
  - PR #9320: oversight identity must differ from execution identity (both are 'scarmani'); record the decision as 'autonomous' instead of self-attesting
  - PR #9319: oversight identity must differ from execution identity (both are 'scarmani'); record the decision as 'autonomous' instead of self-attesting
  - PR #9316: oversight identity must differ from execution identity (both are 'scarmani'); record the decision as 'autonomous' instead of self-attesting
  - PR #9314: oversight identity must differ from execution identity (both are 'scarmani'); record the decision as 'autonomous' instead of self-attesting
  - PR #9312: oversight identity must differ from execution identity (both are 'scarmani'); record the decision as 'autonomous' instead of self-attesting
  - PR #9310: oversight identity must differ from execution identity (both are 'scarmani'); record the decision as 'autonomous' instead of self-attesting
  - PR #9307: oversight identity must differ from execution identity (both are 'scarmani'); record the decision as 'autonomous' instead of self-attesting
  - PR #9302: oversight identity must differ from execution identity (both are 'scarmani'); record the decision as 'autonomous' instead of self-attesting
  - PR #9284: oversight identity must differ from execution identity (both are 'scarmani'); record the decision as 'autonomous' instead of self-attesting
  - PR #9271: oversight identity must differ from execution identity (both are 'scarmani'); record the decision as 'autonomous' instead of self-attesting
  - PR #9238: oversight identity must differ from execution identity (both are 'an0mium'); record the decision as 'autonomous' instead of self-attesting
  - PR #9144: oversight identity must differ from execution identity (both are 'scarmani'); record the decision as 'autonomous' instead of self-attesting
  - PR #9123: oversight identity must differ from execution identity (both are 'an0mium'); record the decision as 'autonomous' instead of self-attesting
  - PR #9093: oversight identity must differ from execution identity (both are 'an0mium'); record the decision as 'autonomous' instead of self-attesting
  - PR #8950: oversight identity must differ from execution identity (both are 'an0mium'); record the decision as 'autonomous' instead of self-attesting
  - PR #8912: oversight identity must differ from execution identity (both are 'an0mium'); record the decision as 'autonomous' instead of self-attesting
  - PR #8892: oversight identity must differ from execution identity (both are 'an0mium'); record the decision as 'autonomous' instead of self-attesting
  - PR #8809: oversight identity must differ from execution identity (both are 'an0mium'); record the decision as 'autonomous' instead of self-attesting
  - PR #8750: oversight identity must differ from execution identity (both are 'scarmani'); record the decision as 'autonomous' instead of self-attesting
  - PR #8745: oversight identity must differ from execution identity (both are 'scarmani'); record the decision as 'autonomous' instead of self-attesting
  - PR #8741: oversight identity must differ from execution identity (both are 'scarmani'); record the decision as 'autonomous' instead of self-attesting
  - PR #8738: oversight identity must differ from execution identity (both are 'scarmani'); record the decision as 'autonomous' instead of self-attesting
  - PR #8729: oversight identity must differ from execution identity (both are 'scarmani'); record the decision as 'autonomous' instead of self-attesting
  - PR #8726: oversight identity must differ from execution identity (both are 'scarmani'); record the decision as 'autonomous' instead of self-attesting
  - PR #8701: oversight identity must differ from execution identity (both are 'scarmani'); record the decision as 'autonomous' instead of self-attesting
  - PR #8696: oversight identity must differ from execution identity (both are 'scarmani'); record the decision as 'autonomous' instead of self-attesting
  - PR #8695: oversight identity must differ from execution identity (both are 'scarmani'); record the decision as 'autonomous' instead of self-attesting
  - PR #8693: oversight identity must differ from execution identity (both are 'scarmani'); record the decision as 'autonomous' instead of self-attesting
  - PR #8673: oversight identity must differ from execution identity (both are 'scarmani'); record the decision as 'autonomous' instead of self-attesting
  - PR #8672: oversight identity must differ from execution identity (both are 'scarmani'); record the decision as 'autonomous' instead of self-attesting
  - PR #8638: oversight identity must differ from execution identity (both are 'scarmani'); record the decision as 'autonomous' instead of self-attesting
  - PR #8624: oversight identity must differ from execution identity (both are 'scarmani'); record the decision as 'autonomous' instead of self-attesting
  - PR #8568: oversight identity must differ from execution identity (both are 'scarmani'); record the decision as 'autonomous' instead of self-attesting
  - PR #8525: oversight identity must differ from execution identity (both are 'scarmani'); record the decision as 'autonomous' instead of self-attesting
  - PR #8507: oversight identity must differ from execution identity (both are 'scarmani'); record the decision as 'autonomous' instead of self-attesting

## Human-settlement attestations (repository trail)

| PR | Attestor | Attested at | Head SHA | Ref |
|---|---|---|---|---|
| #8533 | scarmani | 2026-06-23T02:54:44Z | `076a6f9068e8` | https://api.github.com/repos/synaptent/aragora/statuses/076a6f9068e82bda42a680e76d57d96fa02c9185 |

## Receipts

| Receipt | Timestamp | Verdict | Disposition | Attestor | Mechanism |
|---|---|---|---|---|---|
| `debate-9ea6b178-` | 2026-06-22T22:11:52Z | PASS | autonomous |  |  |

Clause requirement texts and evidence definitions: `docs/compliance/ART14_OVERSIGHT_PACK.md`.
