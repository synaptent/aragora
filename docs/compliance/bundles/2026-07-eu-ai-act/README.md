# EU AI Act Compliance Bundle — July 2026 (W3)

**Status:** DRAFT — content-complete target **2026-07-27**, publish target **2026-07-30**
**Plan:** [`docs/plans/2026-07-09-thirty-day-external-proof-month.md`](../../../plans/2026-07-09-thirty-day-external-proof-month.md) (W3, Jul 23–30)
**Scope:** GPAI / Art. 50 transparency posture ahead of the **Aug 2, 2026** EU AI Act GPAI deadline, plus the Article 14 human-oversight evidence pack (#8230 / ODR-6).
**Assembled:** 2026-07-20
**Status checked:** 2026-07-27 against current main for the crux-cards section,
including generating and verifying artifact 11; the signed-receipt and Art.14
material was last verified 2026-07-24. All timestamps in this bundle are UTC.

Issue [#9391](https://github.com/synaptent/aragora/issues/9391) remains open and
production was re-probed directly on 2026-07-24
(`https://api.aragora.ai/health` returned no response), so Variant A stays
blocked and Variant B remains the shipping default. The crux-cards gap was
re-attributed on 2026-07-24 after direct testing and its status updated again on
2026-07-27 — see "Crux cards" below,
[#9581](https://github.com/synaptent/aragora/issues/9581) and
[#9644](https://github.com/synaptent/aragora/issues/9644).

This bundle packages what Aragora can already prove — signed, dissent-preserving
decision receipts with third-party offline verification — into one auditable
directory. Every artifact below is either present in this directory, or listed
with an honest pending status and the exact step that closes it.

## Bundle contents

| # | Artifact | File | Status |
|---|----------|------|--------|
| 1 | Bundle index (this file) | `README.md` | present |
| 2 | Art. 14 human-oversight evidence pack (JSON, canonical) | `oversight-pack.json` | present |
| 3 | Art. 14 human-oversight evidence pack (Markdown report) | `oversight-pack.md` | present |
| 4 | Source decision receipt (real 2026-06-22 debate, two contributing agents) | `receipts/2026-06-22-packaging-decision-8263.receipt.json` | present |
| 5 | Signed Open Decision Receipt — **Variant B, locally signed** | `packaging-8263.signed-local.odr.json` | present (local key — see contingency below) |
| 6 | Ed25519 public key for artifact 5 | `local-signing.pubkey.pem` | present (local key — see contingency below) |
| 7 | Receipt-verification walkthrough | `verification-walkthrough.md` | present |
| 8 | Rekor transparency-log note | `rekor-note.md` | present (log entry itself: **pending** — submission is an external publish, held for operator) |
| 9 | ODR-2 (#8225) closure comment draft | `odr2-closure-draft.md` | present (**pending-founder-review** — do not post until reviewed) |
| 10 | Signed **production** receipt — **Variant A** | — | **pending-prod** (blocked on AWS reinstatement, [#9391](https://github.com/synaptent/aragora/issues/9391)) |
| 11 | Crux-cards receipt (`cruxes` block populated, dissent attributed) | `receipts/2026-07-27-crux-cards-scoring-decision.receipt.json` | present — attribution sound, ranking provisional ([#9661](https://github.com/synaptent/aragora/issues/9661)) |
| 12 | Founder earned-claim review of the bundle | — | **pending-founder-review** (W3 exit criterion) |

## Remaining exit gates

| Gate | Class | Smallest completion action |
|---|---|---|
| Production-signed receipt | infrastructure/operator | Restore production access under #9391, then run the documented Variant A export and independent verification. |
| Rekor entry | external publish/operator | Review `rekor-note.md`, publish the digest once, and record the returned UUID. |
| Crux-cards receipt | **met 2026-07-27 for dissent attribution; ranking provisional** | Artifact 11 above. Edge construction fixed in [#9643](https://github.com/synaptent/aragora/pull/9643), dissent attribution in [#9652](https://github.com/synaptent/aragora/pull/9652). The KM-belief-sync configuration remains unfixed and is tracked as [#9649](https://github.com/synaptent/aragora/issues/9649); it does not affect this artifact, which was produced on the default path. The duplication defect is fixed ([#9665](https://github.com/synaptent/aragora/pull/9665)) and the artifact regenerated. Remaining disclosed characteristics — ordering is a pivotality ranking rather than a dissent ranking, and `input_hash` is not reproducible — are in "Crux cards" below. |
| Earned-claim and ODR-2 text | founder review | Review this bundle and `odr2-closure-draft.md`; publication and issue closure remain separate operator actions. |

The repository can prepare and validate these artifacts, but no gate is silently
treated as complete by this draft. Two gates are operator or infrastructure
actions, one is the founder's earned-claim review, and the crux-cards gate is
recorded as partially met rather than closed — see the section below for exactly
which part is sound.

## Signed-receipt contingency (Variant A / Variant B)

Production is down: the AWS account is suspended
([#9391](https://github.com/synaptent/aragora/issues/9391)), and the production
Ed25519 ODR signing key lives in AWS Secrets Manager
(`aragora/odr-signing-key`, loaded via `aragora/gauntlet/odr_signing.py` —
by design the key never transits an environment variable and has no local
copy). Until the account is reinstated, no production-signed receipt can be
produced. The bundle is built to ship either way:

### Variant A — production-signed receipt (preferred)

- **What:** the same ODR export signed with the production Ed25519 key from
  AWS Secrets Manager; public key published in-repo and at the
  `.well-known` endpoint.
- **Blocker:** AWS account suspension —
  [#9391](https://github.com/synaptent/aragora/issues/9391). Goodwill-credit
  case pending with AWS Billing/Finance as of 2026-07-17.
- **If reinstated before 2026-07-27:** regenerate artifact 5 with
  `ARAGORA_USE_SECRETS_MANAGER=true aragora receipt export <receipt> --format odr --output <out>`
  (signing is automatic when the secret is reachable), replace artifacts 5–6,
  and delete the gap statement below from the published copy.

### Variant B — locally-signed receipt + dated gap statement (shipping default)

- **What:** artifacts 5–6 in this directory. A real decision receipt (the
  issue #8263 packaging decision, 2026-06-22 — a **two-contributing-agent**
  debate: grok proposed, deepseek critiqued; mistral-api was invited
  (`agents_requested`) but recorded zero contributions, and the signed ODR
  lists only grok and deepseek as participants/supporters; consensus PASS at
  0.80 confidence with consensus proof) exported to the JCS-canonical ODR
  v0.1 profile and signed with a **locally generated** Ed25519 key
  (`key_id=ed25519-7be72c773c6db3a5`).
  The signature is real and verifies offline; what the local key does *not*
  provide is issuer authenticity — the key is not the pinned production
  identity.
- **Gap statement (dated 2026-07-20):** the production signing path is
  blocked by the AWS account suspension
  ([#9391](https://github.com/synaptent/aragora/issues/9391)); the production
  private key is held (inaccessible) in AWS Secrets Manager. This bundle
  therefore demonstrates the *mechanism* (sign → publish key → third-party
  offline verify) with a bundle-local key. **Upgrade path:** on AWS
  reinstatement, re-sign the same ODR bytes with the production key
  (Variant A above — the ODR content digest
  `a00f54fc75207b8b205254290739ebbc287a0b5d189facfe65c442517a922d2a` is
  unchanged by re-signing, since signatures are detached), publish the
  production public key, and anchor the digest in Rekor (`rekor-note.md`).
- **Verify it yourself** (no Aragora account, no API key):

  ```bash
  pip install 'aragora-verify==0.1.1'
  aragora-verify packaging-8263.signed-local.odr.json --pubkey local-signing.pubkey.pem
  ```

  Expected: `=> VERIFIED`, with the honest weakening signals
  `attestation: autonomous` and `confidence: present but uncalibrated`.
  Full walkthrough: `verification-walkthrough.md`.

## Art. 14 oversight pack — generation provenance

Generated 2026-07-20 by:

```bash
aragora compliance oversight-pack --window 30d --fetch-settlements \
  --receipts-dir docs/receipts \
  --receipts-dir docs/compliance/bundles/2026-07-eu-ai-act/receipts \
  --output oversight-pack.json --markdown oversight-pack.md
```

- Clause mapping reference: [`docs/compliance/ART14_OVERSIGHT_PACK.md`](../../ART14_OVERSIGHT_PACK.md) (#9417 / #8230).
- `--fetch-settlements` scanned 424 merged PRs in the window via the
  `aragora/human-settlement` commit status; **1 valid human-settlement
  attestation** was included and **50 were refused** because oversight
  identity equalled execution identity — self-attestation is rejected
  fail-closed and those decisions are recorded as `autonomous`. That refusal
  count is itself Art. 14 evidence that the identity-separation control is
  enforced, not decorative.
- Receipt curation note: the default local receipt store
  (`~/.aragora/receipts`) was found to contain test-run pollution
  (MagicMock artifacts from suite runs). The pack was generated from the
  repo trail (`docs/receipts`) plus this bundle's curated `receipts/`
  directory, which holds the one genuine in-window debate receipt. Curation
  rule: exclude receipts containing mock artifacts or mock-agent demo runs;
  include only receipts of real multi-agent debates.
- Honesty contract: 1 windowed receipt, 0 human-attested — the pack marks
  14(1)/14(3)/14(4)(d) as **partial**, not satisfied. Absence is recorded,
  never implied.
- **14(4)(c) amendment (2026-07-22):** the generated pack originally marked
  14(4)(c) satisfied on "verdict reasoning / explainability". The source
  receipt's `verdict_reasoning` / `final_answer` are in fact truncated
  mid-sentence at 2,000 characters by the receipt persistence path, and the
  local receipt store copy carries the identical truncation, so the full
  synthesis text is not recoverable. The pack was manually amended to mark
  14(4)(c) **partial** with the truncation recorded, and its integrity
  digest recomputed. The signed ODR's `reasoning.summary` reproduces the
  same truncated text; the ODR bytes and signature are unchanged.

## Crux cards (met for dissent attribution 2026-07-27; ranking provisional)

Crux cards (#9414, `DebateProtocol.enable_crux_cards`, default OFF) attach
load-bearing disagreements to receipts; the ODR `cruxes` block renders them
to verifiers. **No existing receipt in `docs/receipts/` or the local store
carries a populated `cruxes` block** (checked 2026-07-20).

**Gap re-attributed 2026-07-24 — the original attribution was wrong.** This
entry previously stated that no CLI flag exposed `enable_crux_cards` and that
generating a crux-bearing receipt therefore "requires a real (API-key) debate
run". Both halves are now false:

- A CLI flag does exist: `aragora ask --crux-cards`, shipped in #9506 (merged
  2026-07-23T02:43Z, after this bundle was assembled). All timestamps in this
  bundle are UTC, matching what GitHub records.
- Credentials are **not** the blocker. *(Assessment as of 2026-07-24; see the
  2026-07-27 status below, which supersedes the present tense here.)* Crux cards
  could not then be produced by *any* standard debate — see
  [#9581](https://github.com/synaptent/aragora/issues/9581).
  Both paths that build the `BeliefNetwork` for crux detection
  (`crux_cards._network_from_messages` and
  `winner_selector.analyze_belief_network`) add claims but never add the
  `SUPPORTS`/`CONTRADICTS` factor edges that
  `CruxDetector.compute_disagreement_scores()` requires, so
  `total_disagreements` was always `0` and no crux cleared any threshold.

Evidence for the re-attribution: two real provider-backed debates were run on
2026-07-24 (`aragora ask --agents claude,codex --crux-cards`, 2 and 3 rounds,
deliberately contested prompts). Both produced receipts with
`schema_version: 1.1` and no `cruxes` block.

### Status 2026-07-27 — met for dissent attribution; card ranking provisional

Both defects are fixed and the artifact exists. Artifact 11 above
(`receipts/2026-07-27-crux-cards-scoring-decision.receipt.json`) is a real
two-agent debate carrying a populated `cruxes` block with dissent attributed by
agent.

Two fixes landed today:

- [#9643](https://github.com/synaptent/aragora/pull/9643) — edge construction.
  `CruxDetector` scores a claim from the belief network's factor edges, and both
  network-building paths added claims without ever adding edges, so
  `total_disagreements` was always `0` and no crux cleared any threshold. Each
  `Critique` already records which agent contested whose proposal and how hard
  (`severity`), so those now become the `CONTRADICTS` edges.
- [#9652](https://github.com/synaptent/aragora/pull/9652) — dissent attribution.
  Attribution is now read from the direction and polarity of those edges: a
  `CONTRADICTS` factor from S to A *is* the recorded fact "S's author contests
  A". Previously it was derived from variance in belief values, measured after
  `propagate()` had already reconciled the disagreement being measured — so
  `contesting_agents` came back empty on every card.

**What the artifact shows.** The debate asks whether a critic's repeated
objections across rounds should accumulate or count once — a question genuinely
open in this repo, tracked as
[#9655](https://github.com/synaptent/aragora/issues/9655). The receipt records:

```
schema_version: 1.2
total_disagreements: 2
  author=codex   contested_by=[]          disagreement=0.00
  author=codex   contested_by=[]          disagreement=0.00
  author=claude  contested_by=['codex']   disagreement=0.30
  author=claude  contested_by=['codex']   disagreement=0.30
```

Both directions are correct: claude's positions are recorded as contested by
codex, and codex's critiques as contested by nobody — an agent is never listed
as contesting their own claim, and a critique nobody answered attracts no
dissent.

**Known characteristics of this receipt, disclosed rather than left to be found**
([#9661](https://github.com/synaptent/aragora/issues/9661),
[#9655](https://github.com/synaptent/aragora/issues/9655)):

1. **Duplication — FIXED, and this artifact was regenerated.** Every mid-debate
   response used to be recorded twice: `DebateContext.add_message` already
   appends to `result.messages` and five phases appended again. That inflated
   `agent_contributions` and put byte-identical duplicate claims into the crux
   top-k. Fixed in
   [#9665](https://github.com/synaptent/aragora/pull/9665) and this receipt was
   regenerated against it — `agent_responses` now holds 5 entries with **zero
   duplicates** (per-round 1/2/2, previously 1/4/4).

   Worth knowing why it survived so long: `MockDebateContext.add_message`
   appended to only one of the three lists the real method writes, so the mock
   cancelled the production bug out and a test asserting "exactly one message"
   passed. The mock now mirrors the real contract.

2. **Ranking leads with uncontested claims.** `crux_score` is a composite —
   influence, uncertainty, centrality and resolution impact, with disagreement
   weighted 0.3 — so a highly-connected claim nobody contested can outrank a
   contested one. In this artifact the top two entries carry
   `disagreement_score 0.00` and empty `contesting_agents`, while the two
   genuinely contested claims rank third and fourth:

   ```
   0.4707  disagreement=0.00  contested_by=[]         influence=1.00
   0.4707  disagreement=0.00  contested_by=[]         influence=1.00
   0.4219  disagreement=0.30  contested_by=['codex']  influence=0.63
   0.4217  disagreement=0.30  contested_by=['codex']  influence=0.63
   ```

   So read this block as *"the top-k most pivotal claims, with dissent
   attributed where it exists"* — **not** as "a ranked list of the
   disagreements". The attribution is exact; the ordering is a pivotality
   ranking in which disagreement is one input among four. Whether a crux should
   require disagreement at all is an open design question
   ([#9655](https://github.com/synaptent/aragora/issues/9655)).

3. **`input_hash` is not reproducible** from the recorded input, and the
   receipt records no generating commit. `input_hash` is sha256 of neither
   `task` nor `input_summary`; the pre-image is an upstream payload the receipt
   does not carry. `consensus_proof.evidence_hash` and the
   `provenance_chain` event's `evidence_hash` reuse that same pre-image, so an
   auditor probing either hits the same wall. No claim in this bundle rests on it — the
   verification chain below names the artifact-hash check, which passes — but an
   auditor who tries to recompute it will not match.

**Verify it yourself:**

```bash
cd docs/compliance/bundles/2026-07-eu-ai-act    # paths below are bundle-relative
aragora receipt verify receipts/2026-07-27-crux-cards-scoring-decision.receipt.json
```

Expected: `VALID (3/3 checks passed)` — artifact hash present, integrity
verified, required fields present.

**Provenance.** Regenerated on 2026-07-28 from `main` at `9807a69a3f` (the
#9665 merge commit, which fixed the duplication), so the artifact is
reproducible from shipped code rather than from a branch. **This claim rests on the author, not on the artifact:** the
receipt records no generating commit or code version — its `provenance_chain`
holds a single `verdict` event — so an auditor cannot confirm it from the file.
Recording the generating revision in the receipt is folded into #9661. Agents `claude` and `codex` via local CLI transports; no API keys
and no production dependency, so this artifact is unaffected by #9391.

**Remaining limitation, unchanged.** Under `enable_km_belief_sync` the debate
uses a KM-seeded `ctx.belief_network` whose claim ids are KM-derived, so
message-derived ids match nothing and crux cards are still unproducible for that
configuration — tracked as
[#9649](https://github.com/synaptent/aragora/issues/9649). This artifact was
produced on the default path, where the flag is off.

An earlier revision of this section stated as a hard condition that "two agents
cannot register a disagreement", and therefore that a 3+ agent debate was
required. #9652 removed that limitation along with the attribution defect: a
single cross-author `CONTRADICTS` edge with positive strength now registers a
contester, which is why a two-agent debate closes this gate.

**W3 plan line: "crux cards in ≥1 published receipt".** Artifact 11 satisfies it
literally — a published receipt carrying crux cards with dissent attributed by
agent — and that part is sound. The gate is deliberately **not** recorded as
fully closed: #9661 distorts `crux_score` ranking, so the *ordering* of the
cards is not yet trustworthy even though the attribution is. Marking a
compliance gate met on an artifact with a known systemic distortion would be the
kind of overclaim this bundle exists to avoid. It closes fully when #9661 is
fixed and the artifact is regenerated.

This was a product defect rather than a credentials or infrastructure gap, which
is why it could progress at all while #9391 remains open.

## Verification chain (what an auditor can check today)

1. **Receipt integrity** — `aragora receipt verify <receipt.json>` (native
   receipts; artifact-hash check).
2. **Signed ODR** — `aragora-verify <odr.json> --pubkey <pem>` (standalone
   PyPI package, no Aragora dependency): schema conformance, JCS-canonical
   digest, Ed25519 signature, quorum consistency, weakening signals.
3. **Oversight pack integrity** — the pack embeds a `sha256/jcs` integrity
   digest (`oversight-pack.json` → `integrity`).
4. **Transparency log** — pending; see `rekor-note.md` for the exact
   publish-and-verify procedure.

## Bundle PR hygiene

Compliance and evidence bundle PRs carry bundle files only. Generated surfaces
(`METRICS`, `STATUS`, `EXTENDED_README`, `CANONICAL_GOALS`, `ARCHITECTURE`,
`FEATURE_DISCOVERY`, and their docs-site mirrors) stay owned by main's generators;
including them guarantees repeated merge-context conflicts.

## Related documents

- [`docs/compliance/EU_AI_ACT_GUIDE.md`](../../EU_AI_ACT_GUIDE.md) — artifact generation guide (Articles 9/12/13/14/15)
- [`docs/compliance/ART14_OVERSIGHT_PACK.md`](../../ART14_OVERSIGHT_PACK.md) — attestation block + clause mapping
- [`docs/proof/2026-07-10-outsider-receipt-verification-runbook.md`](../../../proof/2026-07-10-outsider-receipt-verification-runbook.md) — outsider verification runbook + gap ledger (#8858)
- [`docs/specs/TAMPER_EVIDENT_TRAIL.md`](../../../specs/TAMPER_EVIDENT_TRAIL.md) — anchor / transparency-log design
- [`docs/security/POST_QUANTUM_CRYPTO_MIGRATION.md`](../../../security/POST_QUANTUM_CRYPTO_MIGRATION.md) — PQC groundwork cited by the ODR-2 closure draft
