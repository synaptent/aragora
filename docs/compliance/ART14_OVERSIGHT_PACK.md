# Article 14 Human-Oversight Evidence Pack

**Issue:** #8230 (ODR-6) · **Modules:** `aragora/gauntlet/attestation.py`,
`aragora/compliance/oversight_pack.py` · **CLI:** `aragora compliance oversight-pack`

Regulators increasingly require *proof of effective human oversight of
agentic systems*. Aragora operates a credential-separated human gate in its
own development flow (the `aragora/human-settlement` commit status, Tier-4
preapprovals — see `docs/specs/TAMPER_EVIDENT_TRAIL.md`), and this pack
converts that operating practice into a generatable, audit-ready artifact
for the EU AI Act (Regulation (EU) 2024/1689) **Article 14** and the
NIST AI RMF.

## The attestation block

Every decision receipt exported as an Open Decision Receipt (ODR) carries an
`attestation` block with an explicit disposition — **absence is recorded,
never implied**:

```jsonc
// Autonomous decision (the honest default — no human oversaw it)
{ "disposition": "autonomous" }

// Human-settled decision
{
  "disposition": "human_attested",
  "attestor": { "id": "scarmani", "role": "oversight" },      // WHO accepted the risk
  "execution_identity": { "id": "an0mium" },                   // distinct, enforced
  "attested_at": "2026-07-17T12:00:00+00:00",                  // WHEN
  "observed": {                                                // WHAT they saw
    "head_sha": "…",
    "evidence_digest": "sha256:…"
  },
  "mechanism": {                                               // VIA WHAT
    "type": "settlement_status",
    "context": "aragora/human-settlement",
    "ref": "https://api.github.com/repos/…/statuses/…"
  }
}
```

Builders live in `aragora.gauntlet.attestation`:

- `attestation_from_settlement_status(status, head_sha=…)` — from the
  head-bound `aragora/human-settlement` commit status (creator login =
  oversight identity; the status description embeds the settlement receipt's
  SHA-256, giving the evidence digest).
- `attestation_from_preapproval_comment(comment, …)` — from a Tier-4
  preapproval comment.
- `build_oversight_attestation(…)` — explicit construction.

**Identity separation is enforced at construction**: an attestation whose
oversight identity equals the execution identity raises — self-attestation
is refused fail-closed, and the decision stays honestly `autonomous`.

## Generating the pack

```bash
# 30-day window over the repo trail (docs/receipts) + local receipt store
aragora compliance oversight-pack --window 30d \
  --output oversight-pack.json --markdown oversight-pack.md

# Explicit sources and externally built attestations
aragora compliance oversight-pack --window 12w \
  --receipts-dir docs/receipts --receipts-dir /path/to/odr/exports \
  --attestations attestations.json

# Auto-fetch human-settlement attestations from the GitHub trail
# (walks merged PRs' aragora/human-settlement commit statuses via gh)
aragora compliance oversight-pack --window 30d --fetch-settlements \
  --repo owner/name   # --repo optional; resolved from cwd via gh
```

### Auto-fetched settlement attestations (`--fetch-settlements`)

`aragora/compliance/oversight_fetch.py` automates the `--attestations`
input from the trail itself: it lists merged PRs in the window, reads each
head's commit statuses, and converts every successful head-bound
`aragora/human-settlement` status into an attestation via
`attestation_from_settlement_status` (status `creator.login` = oversight
identity, PR author = execution identity). The same honesty rules apply
end-to-end:

- **Self-settled PRs are refused** — a settlement whose status creator
  equals the PR's executing author fails the builder's identity-separation
  check and lands in the pack's `settlement_fetch.skipped` list with the
  reason, never silently kept *or* dropped.
- **Windowing is double-checked** — both the PR merge time and the status
  `created_at` must fall inside the window.
- **Completeness is persisted** — a scan that fills the PR limit is flagged
  `truncated`, and per-PR fetch failures are recorded in `skipped`; both
  live in the pack's `settlement_fetch` section (and the Markdown report),
  not just console output.
- Trail settlements are aggregated in the pack's `settlement_attestations`
  section and count toward the identity-dependent clauses (14(1), 14(3),
  14(4)(d)) as *mechanism-operating* evidence; alone (unmatched to windowed
  receipts) they cap those clauses at `partial`, never `satisfied`.

The pack contains: per-receipt entries (id, timestamp, verdict, disposition,
attestor, mechanism, observed evidence), summary counts, the clause mapping
below with **computed** statuses, NIST cross-references, and a
tamper-evidence digest (SHA-256 over the RFC 8785/JCS canonical payload —
the same basis as ODR content digests).

Honesty rules: receipts without attestations count as `autonomous`;
receipts without parseable timestamps are excluded *and counted as
excluded*; clause statuses degrade to `partial` when the window lacks the
evidence, they are never asserted unconditionally.

## Article 14 clause mapping

| Clause | Requirement (abridged) | Evidence in the pack | Status rule |
|---|---|---|---|
| 14(1) | System designed for effective oversight by natural persons | Oversight identity layer; per-decision dispositions | `satisfied` iff ≥1 human-attested receipt in window |
| 14(2) | Oversight prevents/minimises risks | Adversarial review verdicts, confidence, preserved dissent | `satisfied` when receipts present |
| 14(3) | Oversight measures built-in or identified | Settlement mechanism cited per attestation (status context / preapproval ref) | `satisfied` iff ≥1 human-attested receipt in window |
| 14(4)(a) | Understand capacities/limitations, monitor operation | Agent responses, confidence, dissent, provenance chains per receipt | `satisfied` when receipts present |
| 14(4)(b) | Awareness of automation bias | Heterogeneous-model dissent preserved verbatim; hollow-consensus detection | `satisfied` when receipts present |
| 14(4)(c) | Correctly interpret output | Verdict reasoning, explainability, exact evidence digest seen | `satisfied` when receipts present |
| 14(4)(d) | Can disregard/override/reverse output | Human settlement is the act gate; withheld attestation withholds action | `satisfied` iff ≥1 human-attested receipt in window |
| 14(4)(e) | Can intervene or interrupt (stop) | Kill-switches / halt files are procedural, not per-receipt | at most `partial` from receipts alone (by design) |

The 14(4)(e) ceiling is deliberate: this pack only claims what receipts can
evidence. Interruption capability should be evidenced separately (runbooks,
kill-switch drill records) in a fuller conformity bundle
(`aragora compliance eu-ai-act generate`).

## NIST AI RMF cross-references

| Function | Mapping |
|---|---|
| GOVERN 3.2 | Oversight roles/responsibilities → oversight identity layer + attestor records |
| MANAGE 2.4 | Mechanisms to supersede/disengage → human settlement gate |
| MEASURE 2.10 | Human-AI configuration / automation bias → preserved dissent + confidence |

## Relationship to other artifacts

- `aragora compliance eu-ai-act generate` — full per-receipt Article 9/12/13/14/15
  bundle; its `Article14Artifact` documents the oversight *design*. This pack
  documents oversight *practice over a window*, across many receipts.
- ODR export (`aragora/gauntlet/odr_export.py`) — carries the attestation
  block per receipt; this pack aggregates them.
- `docs/specs/TAMPER_EVIDENT_TRAIL.md` — the identity layers and the
  settlement-creator pin (H2) this evidence chain builds on.
