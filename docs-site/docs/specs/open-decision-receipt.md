---
title: Open Decision Receipt (ODR) — Content Profile v0.2
description: Open Decision Receipt (ODR) — Content Profile v0.2
---

# Open Decision Receipt (ODR) — Content Profile v0.2

**Status:** Draft v0.2

Tier 2, issue [#8224](https://github.com/synaptent/aragora/issues/8224), part of
the ODR spine ([#8223](https://github.com/synaptent/aragora/issues/8223)).
**Artifacts:** this spec, `aragora/gauntlet/odr_schema.json` (JSON Schema draft 2020-12),
`aragora/gauntlet/odr_export.py` (reference emitter), `aragora receipt export --format odr`.
**Related:** [`docs/specs/TAMPER_EVIDENT_TRAIL.md`](./tamper-evident-trail) (trail
*integrity*; this profile supplies the decision *semantics* that ride on it),
issue #8225 (Ed25519 detached signing).

---

## 1. Why a content profile

Trail-integrity standards — IETF SCITT, in-toto/SLSA attestations, Microsoft
agent action receipts — standardize **that** something happened and **that the
record was not rewritten**. They explicitly exclude decision **quality**: what
was claimed, who adversarially examined it, with what model diversity, who
dissented, how confident the system was, and whether a human accepted the
risk.

ODR is a versioned, vendor-neutral **content profile** for exactly that
payload. It deliberately does **not** define an envelope, transport, or
registry: an ODR payload is designed to be carried as the signed statement
inside standard envelopes (SCITT signed statements, COSE detached signatures,
in-toto attestation predicates). One profile, hashed identically everywhere —
"SLSA for decisions."

### Design rules

1. **Lossless where the source has data.** Every field maps from a real field
   of the emitting system (for Aragora: `aragora.gauntlet.receipt_models.DecisionReceipt`).
2. **Honest where it does not.** A field the emitter cannot supply MUST carry
   an explicit absent marker (§3). Emitters MUST NOT fabricate values.
3. **Deterministic bytes.** The hashing basis is RFC 8785 (JCS)
   canonicalization (§5). The same receipt hashes identically on every
   platform and language.
4. **Envelope-agnostic.** `signatures[]` is reserved for detached signatures
   (§6); nothing in the profile depends on a particular envelope.

## 2. Top-level structure

An ODR document is a single JSON object. All thirteen members below are
REQUIRED (the schema enforces this); blocks that the emitter cannot populate
carry absent markers rather than being omitted, so a verifier can distinguish
"not supplied" from "not part of the profile."

| Member | Type | Content |
|---|---|---|
| `odr_version` | string | Profile version, "0.1" or "0.2". |
| `profile` | string | `https://aragora.ai/specs/open-decision-receipt/v0.1` or `https://aragora.ai/specs/open-decision-receipt/v0.2`. |
| `receipt_id` | string | Unique id of this receipt. |
| `issued_at` | string \| null | ISO-8601 timestamp from the source receipt; `null` if the source recorded none. |
| `subject` | object | Binding to the decided thing (§4.1). |
| `claim` | object | What is asserted about the subject (§4.2). |
| `reasoning` | object | Reasoning summary or absent marker (§4.3). |
| `quorum` | object | Adversarial-quorum verdict or absent marker (§4.4). |
| `confidence` | object | Calibrated-confidence block or absent marker (§4.5). |
| `cruxes` | object | Crux set or absent marker (§4.6). |
| `attestation` | object | Human-attestation block or explicit `autonomous` disposition (§4.7). |
| `routing` | object | Reserved (§4.8). |
| `signatures` | array | Reserved for detached signatures, empty in v0.1 (§6). |
| `source` | object | Optional provenance link to the native emitting record (§4.9). |

## 3. Absent markers

```json
{ "status": "absent", "reason": "source receipt has no verdict_reasoning" }
```

An absent marker is an object with exactly `status: "absent"` and a non-empty
human-readable `reason`. Its evidentiary meaning: *the emitter looked and the
source record genuinely does not contain this information.* This is a
first-class honesty signal — a receipt full of absent markers is a weak
receipt, visibly, rather than a strong-looking fabricated one. Blocks that are
populated use `status: "present"` (where the schema requires the
discriminator).

## 4. Field semantics and evidentiary meaning

### 4.1 `subject` — what was decided about

| Field | Meaning |
|---|---|
| `identifier` | Stable id of the subject: a git SHA, an action id, a debate/gauntlet id. Binds the decision to one specific thing. |
| `digest` | Content digest of the decision input (`alg` + `value`, e.g. `sha-256`), or absent. With a digest, a verifier can confirm the decision was about *these exact bytes*. |
| `summary` | Optional human-readable description of the subject. |

*Aragora mapping:* `gauntlet_id` → `identifier`, `input_hash` → `digest.value`
(SHA-256), `input_summary` → `summary`.

### 4.2 `claim` — what is asserted

| Field | Meaning |
|---|---|
| `verdict` | The asserted outcome (`PASS`, `CONDITIONAL`, `FAIL`, or emitter-specific). The single load-bearing assertion of the receipt. |
| `statement` | The claim/input under examination, or absent. |

*Aragora mapping:* `verdict` → `verdict`, `input_summary` → `statement`.

### 4.3 `reasoning` — why

`{ "status": "present", "summary": "<text>" }` or absent. The summary is the
emitting system's recorded justification, not a post-hoc rationalization: it
must be the reasoning that was stored with the decision at decision time.

*Aragora mapping:* `verdict_reasoning`.

### 4.4 `quorum` — adversarial-quorum verdict

The core differentiator versus action receipts: **who examined the claim, how
independent they were, and who disagreed.**

| Field | Evidentiary meaning |
|---|---|
| `method` | Consensus mechanism (e.g. `majority`, `adversarial_validation`, `prover_estimator`). |
| `reached` | Whether the quorum converged. |
| `supporting_agents` | Agents endorsing the verdict. |
| `participants[]` | Per-agent `model_family` and `model_id`. The literal `"undisclosed"` means the source recorded no metadata — never a guess. |
| `independence` | `disclosed` (was model diversity recorded at all), `distinct_model_families`, `model_families[]`. Heterogeneous-family review is the substance behind "adversarial"; a quorum of one family is disclosed as such. |
| `dissent` | `present`, `dissenting_agents[]`, `views[]`. Dissent is preserved verbatim — its presence *raises* the evidentiary value of the receipt (the disagreement survived to the record). |

*Aragora mapping:* `consensus_proof` (method/reached/supporting/dissenting),
`agent_responses[].provider`/`.model` (participants and independence),
`dissenting_views` (dissent views). Absent when the source has no
`consensus_proof`.

### 4.5 `confidence` — calibrated confidence

| Field | Meaning |
|---|---|
| `value` | Confidence in `[0, 1]` (`scale: "unit_interval"`). |
| `calibration` | Provenance of calibration: `{ "status": "present", "provenance_ref": {...} }` pointing at the calibration/settlement record, or absent. |

A confidence number without calibration provenance is an *uncalibrated score*
and the profile says so explicitly: emitters MUST mark `calibration` absent
unless a real calibration record exists.

*Aragora mapping:* `confidence` → `value`; `settlement_metadata` (when
populated) → `calibration.provenance_ref` of type
`aragora.settlement_metadata`; otherwise calibration is absent.

### 4.6 `cruxes` — load-bearing disagreement

`{ "status": "present", "items": [...] }` or absent. Crux items identify the
specific claims on which the verdict actually turns (cf. Aragora's
`CruxReceipt`). The native `DecisionReceipt` does not carry a crux set, so the
Aragora emitter marks this absent unless a crux set is supplied explicitly
(`decision_receipt_to_odr(..., crux_set=...)`).

### 4.7 `attestation` — human accountability

| Field | Meaning |
|---|---|
| `disposition` | `"human_attested"` or `"autonomous"`. REQUIRED. |
| `attestor` | Who accepted the risk (REQUIRED when `human_attested`). |
| `attested_at`, `method` | When and how (e.g. `signed_approval`, `settlement_status`). |

`autonomous` is an explicit, first-class disposition — not a missing field.
A consumer can therefore mechanically filter "decisions no human ever looked
at," which is precisely what EU AI Act Article 14 oversight tooling needs.

*Aragora mapping:* the emitter defaults to `autonomous` because
`DecisionReceipt` does not record human sign-off; callers with a real
human-approval record pass it via `attestation=`.

### 4.8 `routing` — reserved

`{ "status": "reserved" }` in v0.1. Reserved for downstream delivery/routing
metadata (channels, jurisdictional residency) in a later minor version.

### 4.9 `source` — native-record provenance

Links the neutral profile back to the emitting system's native record
(`system`, `schema`, `schema_version`, `receipt_id`, `artifact_hash`) so an
auditor can pull the full-fidelity original. Aragora populates it with the
`DecisionReceipt` id and its `artifact_hash`.

**Honest-linkage note:** `DecisionReceipt.artifact_hash` is computed over a
six-field subset of the native record (`receipt_id`, `gauntlet_id`,
`input_hash`, `risk_summary`, `verdict`, `confidence`; see
`DecisionReceipt._calculate_hash`). Fields such as `verdict_reasoning`,
`dissenting_views`, and `agent_responses` can change without changing it.
Consumers MUST treat `source.artifact_hash` as a stable locator plus an
integrity check on those six fields, not as a content digest of the full
original. Full-payload integrity for the *neutral* artifact is exactly what
`odr_digest` (§5) provides; widening the native hash's coverage would re-hash
every stored receipt and is out of scope for v0.1.

### 4.10 v0.2 optional members

These additions preserve the meaning and required-ness of every v0.1 member; every row below is optional in a v0.2 document. Inside the five `object` rows (`quorum.verdicts[]`, `quorum.rule`, `quorum.dissent.findings[]`, `adjudication`, `reasoning.observations[]`) a `?` suffix (or the word optional) marks a sub-member an emitter may omit, and a conforming emitter writes every other listed sub-member whenever it writes that object (§8, rule 5). Both verifiers reject an object lacking a non-`?` sub-member (failing check `schema_conformance`, detail `<path>: missing required member: <name>`) and an `adjudication` carrying `status` (same check, detail `adjudication.status: unknown member`).

| Member | Parent | Type | Meaning |
|---|---|---|---|
| `quorum.verdicts[]` | `quorum` | object | Per-reviewer `issuer`, `role?`, `verdict`, `model_family`, `model_id`, `head_sha?`, `posted_at?`, `grounded?`, `counted?`, `severity_max?`, `blocking?`; undisclosed model ids use `"undisclosed"`. |
| `quorum.rule` | `quorum` | object | Gate rule: `required_signals` (integer), `requires_western_frontier` and `western_only_counted` (booleans), `counted_families` (string array). |
| `quorum.dissent.findings[]` | `quorum.dissent` | object | Findings from all reviewers: `issuer`, `severity` (P0..P3), `blocking` (P0/P1 true), `location?`, `text`. |
| `quorum.dissent.severity_max` | `quorum.dissent` | string | Most severe finding, ordered P0 > P1 > P2 > P3. |
| `quorum.dissent.blocking` | `quorum.dissent` | boolean | True iff any finding is P0/P1. |
| `adjudication` | top-level | object | Omitted when absent; `kind: "review_adjudication.v1"`, `verdict` (settle/block/escalate/not_applicable), `reason`, `groundedness_bar?` (number), `advisory_severity_policy?` (cap_at_advisory/promote_grounded_to_block); optional `policy` and assessment/finding arrays record the adjudicator's decision. |
| `attestation.mechanism.{policy_version,tier,tiered_gate,severity_gated,action,action_reason,record_ref}` | `attestation.mechanism` | integer, integer, boolean, boolean, string, string, string | Policy version, risk tier, gate modes, action and reason, optional settlement-record reference. |
| `subject.repository` | `subject` | string | Repository owning the reviewed PR. |
| `subject.pr_number` | `subject` | integer | Reviewed pull-request number. |
| `subject.head_sha` | `subject` | string | Exact reviewed head. |
| `subject.base_sha` | `subject` | string | Recorded base, when available. |
| `reasoning.observations[]` | `reasoning` | object | `kind` (timeout/failure/rerun), `family`, `detail`; only alongside a real source reasoning summary, never an absent marker. |
| `signatures[].{issuer,role,signed_at,expires_at}` | signature items | string | Signature metadata on 0.2 documents, signer-committed by the §6 construction: issuer, role (emitter/reviewer/attestor/notary), signing time and optional expiry (RFC 3339 UTC). |

Gate-level dissent (`present`/`dissenting_agents`/`verdicts[].blocking`) and severity-level findings (`findings`/`severity_max`/`dissent.blocking`) are independent notions, never derived from each other.
An emitter MUST NOT write any of these members into a v0.1 document (§8, rule 5).
Both verifiers reject any of these members on a v0.1 document (failing check `schema_conformance`, detail `<path>: not in profile 0.1`), with one exception: the `signatures[]` metadata members are syntactically legal on every version (the schema is one file for both), so on a v0.1 document both verifiers verify the entry under the 0.1 construction and report those members in `warnings[]` as `unauthenticated signature metadata` (§6) instead of rejecting them; the reference signer refuses to write them into a v0.1 document.

## 5. Canonicalization and hashing — RFC 8785 (JCS)

The hashing basis of an ODR document is its **RFC 8785 (JSON Canonicalization
Scheme)** serialization:

- UTF-8 output, no insignificant whitespace;
- object members sorted by UTF-16 code units;
- strings minimally escaped per JSON with lowercase `\u00xx` for controls;
- numbers serialized with the ECMAScript `Number::toString` shortest
  round-trip algorithm; `NaN`/`Infinity` are forbidden.

ODR payloads are I-JSON-safe (no numbers needing more than IEEE-754 double
precision), so any conforming JCS implementation produces identical bytes.
The reference implementation is `aragora.gauntlet.odr_export.jcs_canonicalize`
(dependency-free, byte-stability tested against the RFC 8785 number and
sorting examples).

**Content digest:**

```
odr_digest = SHA-256( JCS( odr_document minus the "signatures" member ) )
```

The `signatures` array is excluded so attaching detached signatures never
changes the digest they cover. `aragora.gauntlet.odr_export.odr_content_digest`
implements this.

## 6. Envelopes: ride SCITT/COSE, don't reinvent

ODR intentionally defines **no envelope**. Deployment guidance:

- **SCITT:** the JCS bytes of the ODR document are the signed statement
  payload (`application/json`); registration on a transparency service yields
  the append-only/inclusion properties — exactly the integrity layer that
  [`TAMPER_EVIDENT_TRAIL.md`](./tamper-evident-trail) builds for this
  repository's own loop. TET answers *"was the record rewritten?"*; ODR
  answers *"what did the decision actually consist of?"*. They compose.
- **COSE / detached signature:** sign `odr_digest` (§5) as a COSE_Sign1
  detached payload, or place Ed25519 detached signatures in the
  `signatures[]` array (issue **#8225**; shape: `alg`, `key_id`, `signature`,
  plus the signer-committed `issuer`, `role`, `signed_at`, `expires_at` of
  §4.10 on v0.2 documents). An emitter without a key emits `signatures: []`.
- **in-toto:** the ODR document can serve as the predicate of an attestation
  whose subject duplicates `subject.digest`.
- **ACTA signed receipts (`draft-farley-acta-signed-receipts-02`):** status —
  interop profile, tracks individual IETF drafts. A projection carries the
  whole document as `payload.odr` inside a signed `{payload, signature}`
  envelope (`aragora.gauntlet.odr_acta_projection`, mirrored verbatim in
  `aragora_verify.acta`; `receipt export --acta` emits one beside a v0.2
  document and `aragora-verify --acta` checks it), and §11 maps it member by
  member. `payload_digest` includes `signatures`; `odr_digest` (§5) excludes
  them, so the two agree only for a document carrying no `signatures` member
  at all. The projection assumes single custody: the envelope signature and
  the document's own `signatures[]` are expected to come from the same key
  custody, so a relay issuer that re-signs another emitter's document is out
  of scope for this revision, and lifting that assumption would take a future
  `--acta-pubkey` flag supplying the transport issuer's key.

**Signed-message construction (binding on signers and both verifiers).** The
document's `odr_version` selects the message an Ed25519 signature covers —
never the entry shape — and a verifier never falls back to the other
construction:

- `"0.1"`: `message = bytes.fromhex(odr_digest)`, the 32 raw bytes of the
  digest, with the three-member entry `{alg, key_id, signature}`. Metadata on
  a 0.1 document is unauthenticated: for any `issuer`, `role` or `expires_at`
  both verifiers still verify under this construction and add a `warnings[]`
  entry containing `unauthenticated signature metadata` (`signed_at` alone
  produces no warning).
- `"0.2"`: `protected` = the entry minus `signature`, and
  `message = JCS({"odr_digest": <hex>, "odr_signature_input": "0.2", "protected": protected})`
  under the §5 canonicalizer; `odr_signature_input` domain-separates the two
  messages. The verifier rebuilds `protected` from the entry under check, so
  any changed or stripped member (`key_id` included) fails `signature` while
  `canonical_digest` still passes. Signers write `issuer` (required), `role`
  (`emitter` for the reference producer), `signed_at` (RFC 3339, UTC offset
  only) and `expires_at` only when supplied (later than `signed_at`); the
  reference signer refuses to sign a 0.2 document without them. Both verifiers
  warn when `expires_at` has passed, or fail with `strict_expiry=True`.
  The package CLI exposes `--strict-expiry` and `--now <iso>` for that policy.
  Its `--require-issuer <name>` requires a verifying v0.2 signature with that
  signer-committed issuer; a v0.1 issuer claim never satisfies the requirement.
- In both, `signature` is base64 (or hex) of the 64 raw Ed25519 bytes,
  `key_id` is `ed25519-` + the first 16 hex digits of SHA-256 over the raw
  public key, and only entries whose `key_id` matches the supplied key count.

**Published custody record:** Receipt-First mission key `ed25519-44c316618e9a0f58`,
generated 2026-09-03 for validation (not a production trust anchor), is published as
[`aragora-odr-signing-ed25519-44c316618e9a0f58.pub.pem`](https://github.com/synaptent/aragora/blob/main/docs/specs/keys/aragora-odr-signing-ed25519-44c316618e9a0f58.pub.pem).
The operator holds its private half in `~/.aragora/odr-signing/mission-ed25519.pem`
(0600); CI and deployment configuration do not provision it. It is distinct from
`examples/example-signed.pubkey.pem` and the public deterministic test seed.
A server explicitly configured with the matching private key serves its public half at
`/.well-known/aragora-odr-signing-key` and `/api/v2/receipts/signing-key`.
Pin through a trusted channel, not the key routes alone. This record makes no
validity-period guarantee: offline verification does not discover revocation.
On compromise, the operator must revoke the key in a reviewed update here and notify
consumers to remove their pins; rotation publishes a replacement record and updates
consumer pins through that same trusted channel before signing resumes.
Unusable configured file custody fails closed: producers exit 1 without output,
both key routes return 404, and readiness remains independent (200).
On POSIX, the loader rejects a key file writable by group or other and warns on
one readable by group or other (strict mode rejects it).

## 7. Compliance crosswalk — EU AI Act Art. 14 / NIST AI 600-1

ODR fields are designed to be the machine-readable evidence behind human
oversight and GenAI risk-management controls:

| ODR field | EU AI Act Art. 14 (Human oversight) | NIST AI 600-1 (GenAI profile) |
|---|---|---|
| `subject` (binding + digest) | 14(4)(a) — enables the overseer to "duly monitor" exactly which input the decision concerns | GV-1.2 / MP-2: documented system context and provenance of inputs |
| `claim.verdict` | 14(4)(c) — output the human must be able to correctly interpret | MS-2.5: traceable system outputs |
| `reasoning.summary` | 14(4)(c)/(d) — interpretation aids; basis for deciding "not to use" the output | MS-2.8: documented rationale supporting explanation |
| `quorum.participants` + `independence` | 14(4)(b) — awareness of automation bias is operationalized by disclosing model-family homogeneity | GV-6.1 / MP-5.1: third-party/model diversity and provenance disclosure |
| `quorum.dissent` | 14(4)(d) — preserved dissent gives the overseer concrete grounds to disregard the output | MS-3.3: capture of disagreement/uncertainty in evaluation |
| `confidence` + `calibration` | 14(4)(b)/(c) — calibrated (or honestly uncalibrated) confidence counters over-reliance | MS-2.3 / MS-4: measured, documented confidence with provenance |
| `cruxes` | 14(4)(d) — identifies the load-bearing points a human should probe before overriding or accepting | MP-2.3: identification of decision-critical assumptions |
| `attestation` | 14(4)(e) — records whether a human exercised the ability to intervene; `autonomous` makes non-intervention auditable | GV-3.2: human oversight roles and responsibilities are recorded per decision |
| `signatures` / JCS digest (§5–6) | 14(1) — effective oversight presupposes the record itself is trustworthy | MS-2.7: integrity/verifiability of AI system records |
| `source` | 14(4)(a) — path back to full-fidelity native record for deeper monitoring | GV-1.5: auditability via linked provenance |

This table maps *evidence availability*, not legal conformity: ODR makes the
facts inspectable; conformity assessment remains the deployer's process (see
`docs/compliance/EU_AI_ACT_GUIDE.md`).

**Instrument and dates.** Article 14 is read here under the application dates
set by Regulation (EU) 2026/1744 (the "Digital Omnibus on AI", OJ L 2026/1744,
published 2026-07-24, in force 2026-07-27), which restates Article 113 of
Regulation (EU) 2024/1689 without changing Article 14 itself:

- Article 6(2) / `Annex III` high-risk systems: Chapter III applies from 2027-12-02.
- Article 6(1) / `Annex I` product-embedded high-risk systems: from 2028-08-02.

A receipt emitted today is therefore evidence gathered ahead of the obligation
it supports, not evidence of an obligation already in force.

## 8. Conformance

An emitter conforms to ODR v0.1 or v0.2 iff:

1. its output validates against `aragora/gauntlet/odr_schema.json`;
2. every value is sourced from a real record (rule 1) and every unsupplied
   field carries an absent marker (rule 2) — fabricating a value that should
   be absent is non-conformant even if schema-valid;
3. hashing and signing use the JCS basis of §5;
4. `signatures` is `[]` and `routing.status` is `"reserved"`.
5. it writes no §4.10 member into a v0.1 document, no member outside §2 and §4.10 into a v0.2 document, and every non-`?` sub-member of each §4.10 `object` row it writes.

A verifier conforms iff it validates the schema, recomputes `odr_digest` from
JCS bytes, and treats `"undisclosed"`/absent markers as *weakening* rather
than failing the receipt (policy thresholds are the verifier's choice).

A verifier SHOULD additionally cross-check internal consistency: every name
in `quorum.supporting_agents` and `quorum.dissent.dissenting_agents` should
appear among `quorum.participants[].agent`. A mismatch is a malformed-receipt
signal (emitter bug or tampering), not a mere weakening.

Both bundled verifiers report that cross-check as `quorum_consistency`, and on
a v0.2 document they add two more: `verdicts_consistency`, that every
`quorum.verdicts[].issuer` is a participant, and `dissent_consistency`, that
`quorum.dissent.severity_max` and `quorum.dissent.blocking` follow from
`quorum.dissent.findings[]` and that each `findings[].blocking` matches its own
severity, with the offending index named in the failure detail. A fourth check,
`quorum_rule`, compares `quorum.reached` against the recorded `quorum.rule` and
warns rather than fails, because the gate it re-derives also requires the
evidence to have been posted.

## 9. Versioning and Stability

`odr_version` follows semver-minor semantics: additive optional fields bump
the minor version; any change to canonicalization, required members, or
absent-marker semantics is a new major profile with a new `profile` URI.

### 9.1 Field-stability tiers

Every member of the content profile carries one of three stability tiers.
The tier governs what a future `odr_version` may do to it:

| Tier | Meaning | Change policy |
|---|---|---|
| **stable** | Load-bearing for verification or evidentiary meaning. | May not be removed, renamed, or have its type/semantics changed without a **major** profile bump (new `profile` URI). |
| **provisional** | Present and emitted, but its shape may still settle. | May be tightened or extended in a **minor** bump; removal requires a major bump and a deprecation cycle (§9.3). |
| **reserved** | Declared, not yet meaningful (e.g. `routing.status: "reserved"`). | May be defined in a **minor** bump without notice; carries no compatibility promise until it leaves reserved. |

Tier assignment for v0.1 → the v1.0 GA target:

- **stable:** `odr_version`, `profile`, `receipt_id`, `subject`, `claim`,
  `quorum`, the JCS canonicalization basis (§5), the absent-marker contract
  (§3), and `signatures`.
- **provisional:** `reasoning`, `confidence`, `cruxes`, `attestation`,
  `source`, `issued_at`.
- **reserved:** `routing`.

### 9.2 Compatibility guarantees (v1.0 GA)

When this profile reaches v1.0 GA, it commits to:

1. **Backward compatibility within a major:** a verifier for `1.x` MUST verify
   any receipt emitted at `1.y` for `y ≤ x`; unknown additive optional members
   are ignored, never fatal.
2. **Forward tolerance:** a `1.x` receipt presented to a `1.y` verifier with
   `y < x` MUST still verify on the stable core (schema of stable members, JCS
   digest, signatures, quorum consistency); provisional additions it does not
   recognize degrade to weakening signals, never hard failures.
3. **Conformance authority:** `aragora-verify` is the normative conformance
   checker. A change that would make a previously-verifying stable-core receipt
   fail is by definition a **major** bump requiring a new published verifier.

### 9.3 Deprecation policy

A provisional member slated for removal is marked deprecated in a minor bump,
continues to be emitted and accepted for at least one subsequent minor
release, and is removed only at the next major bump. Deprecations are recorded
in the verifier's `CHANGELOG.md` and surfaced as a verifier *warning*, never a
failure, during the deprecation window.

### 9.4 Native `DecisionReceipt` ↔ `odr_version` relationship

The on-wire `odr_version` is **independent** of the native
`DecisionReceipt.schema_version`. The native record may rev (e.g. `1.1 → 1.2`)
without changing `odr_version`; the export layer
(`aragora/gauntlet/odr_export.py`) absorbs the difference and records the
source record's version under `source.schema_version`. The full field-by-field
mapping is normative and lives in
[`odr-native-mapping.md`](./odr-native-mapping); that mapping is covered by
a drift-guard test so it cannot silently fall out of sync with the emitter.

### 9.5 Path to v1.0 GA (current status)

ODR v0.2 was a **staged rollout**, not one coordinated release. The schemas and
both in-repo verifiers accepted v0.2 first, and the emitter emitted 0.2 only on
request until `aragora-verify` **0.2.0** was published on PyPI. As of release
2.11.0 the emitter **defaults to 0.2**; 0.1 is still emitted **on request**
(`odr_version="0.1"` in the library; `--odr-version 0.1` on the CLIs;
`ARAGORA_ODR_PROFILE_VERSION=0.1`; `?odr_version=0.1` on the export endpoint).
Published `aragora-verify` 0.1.1 fails a v0.2 document at `schema_conformance`
(`odr_version: must be '0.1'`); verify v0.2 with `aragora-verify` 0.2.0 or later,
or request 0.1 for a 0.1.x verifier. Every v0.1 document keeps verifying
unchanged with every verifier. This remains the **stability contract that v1.0
will honour**.

### 9.6 Changelog — what 0.2 adds

0.2 is an additive minor over 0.1: no v0.1 member changes meaning, encoding or
required-ness, and every v0.1 document keeps verifying unchanged (§9.2). The
new members are all optional and defined in §4.10; the evidentiary ones come
first.

- `quorum.verdicts[]` — one recorded verdict per reviewing issuer, with its
  model family, model id and the head it reviewed, instead of a single
  aggregate outcome.
- `quorum.dissent.findings[]` — dissent kept per finding, each with a
  `severity` (P0..P3) and its own `blocking` flag, alongside the aggregates
  `severity_max` and `blocking`.
- `adjudication` — who settled a blocked review, under what rule, and on what
  stated reason.
- Supporting members: `quorum.rule`, `subject.repository`, `subject.pr_number`,
  `subject.head_sha`, `subject.base_sha`, `reasoning.observations[]`,
  `attestation.mechanism` and the signer-committed `signatures[]` metadata of
  §6.

Rollout: 0.2 is the default as of release 2.11.0, now that `aragora-verify` 0.2.0 is published; 0.1 is emitted on request (`--odr-version 0.1`) (§9.5).

## 10. Reference emitter

```bash
aragora receipt export --format odr <receipt-id-or-path> [-o out.odr.json]
```

emits a schema-valid, JCS-canonical ODR document for any stored or on-disk
`DecisionReceipt`. Programmatic use:

```python
from aragora.gauntlet.odr_export import (
    decision_receipt_to_odr, jcs_canonicalize, odr_content_digest,
)

odr = decision_receipt_to_odr(receipt)            # never fabricates
payload = jcs_canonicalize(odr)                   # RFC 8785 bytes
digest = odr_content_digest(odr)                  # SHA-256, signatures-excluded
```

## 11. IETF Draft Mapping

This section maps the profile against the two receipt drafts it tracks:
`draft-farley-acta-signed-receipts-02` (ACTA, 2026-06-28) and
`draft-marques-asqav-compliance-receipts-08` (ASQAV, 2026-08-31, an additive
overlay on ACTA). The mapping carries the status of the §6 projection: it
follows published draft revisions and changes with them.

Every row carries exactly one label:

- **conformant** — ODR, or its ACTA projection (§6), satisfies the draft member
  as written;
- **divergent** — a counterpart exists but differs in shape, scope or encoding,
  or ODR deliberately does not emit a member the draft defines;
- **extension** — the draft has no counterpart at all, so ODR defines the
  member itself.

Read the `extension` rows first. Per-issuer verdicts, dissent that keeps its
severity, the adjudication record and model-family independence are evidence
neither draft can express today, and they are the reason this profile exists.
Two honest summaries follow from the table. The ACTA projection is conformant
on the members it emits and adds one member the draft does not define,
`chain_scope`, which names the digest scope of `previousReceiptHash` because
ASQAV reuses that member name with a narrower scope. An ODR document is **not**
an ASQAV Compliance Receipt: it emits no `anchors`, no resolvable
`policy_digest` and no RFC 7638 `key_thumbprint`, so the profile's MUST clauses
are unmet and the table says so member by member.

| Member | Profile | Label | Reason | Reference |
|---|---|---|---|---|
| `odr_version` | ODR 0.1 | extension | Neither draft versions its payload; ACTA distinguishes shapes through the namespaced `type` alone. | ACTA §2.2 |
| `profile` | ODR 0.1 | extension | The profile URI names the content rules in force; ACTA identifies a receipt only by its `type` namespace. | ACTA §2.2 |
| `receipt_id` | ODR 0.1 | extension | The common ACTA payload carries no receipt identifier; ids appear only inside individual receipt types. | ACTA §2.2 |
| `issued_at` | ODR 0.1 | divergent | Same name and RFC 3339 form, but ODR allows `null` when the source recorded no time, where ACTA requires a value. | ACTA §2.2 |
| `subject` | ODR 0.1 | divergent | ACTA binds input bytes with `payload_digest` and correlates through `action_ref`; ODR binds an identifier plus digest in one object. | ACTA §2.2 |
| `claim` | ODR 0.1 | divergent | ACTA's `decision` is a closed policy outcome; ODR's verdict is deliberative and carries the statement examined. | ACTA §3.1.1 |
| `reasoning` | ODR 0.1 | divergent | ACTA's `reason` is a short machine code; ODR stores the justification recorded at decision time. | ACTA §3.1.1 |
| `quorum` | ODR 0.1 | extension | No ACTA member records who examined a claim; its debate type reports two scalar winners with no participant list. | ACTA §3.6 |
| `quorum.independence` | ODR 0.1 | extension | Model-family independence is recorded nowhere in either draft; a single-family panel is disclosed as such rather than hidden. | ACTA §2.2 |
| `confidence` | ODR 0.1 | extension | No draft member carries a calibrated score, and ASQAV's no-float rule would force it to a string inside an ASQAV receipt. | ASQAV §4 |
| `cruxes` | ODR 0.1 | extension | The load-bearing points a verdict turns on have no counterpart member in either draft. | ACTA §2.2 |
| `attestation` | ODR 0.1 | divergent | ASQAV names one producer-asserted approver on a risk-acceptance receipt; ODR states the disposition on every receipt, `autonomous` included. | ASQAV §5.11 |
| `routing` | ODR 0.1 | extension | Declared and reserved; neither draft has a delivery or residency member. | ACTA §2.2 |
| `signatures` | ODR 0.1 | divergent | The ACTA envelope holds exactly one `signature` object; ODR holds an array of detached entries and the projection signs with one of them. | ACTA §2.1.1 |
| `source` | ODR 0.1 | divergent | ASQAV resolves originals through the Audit Pack manifest; ODR links the native record inline. | ASQAV §9 |
| `quorum.verdicts` | ODR 0.2 | extension | Per-issuer verdicts inside one receipt; the ACTA envelope has a single signer and no per-reviewer record. | ACTA §2.1.1 |
| `quorum.rule` | ODR 0.2 | extension | ASQAV records only that a quorum control fired, behind an opaque hash; ODR states the gate rule that was applied. | ASQAV §5.10 |
| `dissent.findings` | ODR 0.2 | extension | Neither draft has dissent vocabulary; ASQAV's added-field rule is what allows carrying it without colliding with reserved names. | ASQAV §5.6 |
| `dissent.severity_max` | ODR 0.2 | extension | Objection severity has no counterpart; ASQAV's `risk_class` grades the action, not a reviewer's objection. | ASQAV §5.6 |
| `dissent.blocking` | ODR 0.2 | extension | ACTA's `decision` can block an action, but no draft member records that a reviewer's objection blocks the decision under review. | ACTA §3.1.1 |
| `adjudication` | ODR 0.2 | extension | ASQAV's risk-acceptance approver is producer-asserted with no authority check; ODR records who settled a blocked review and under what rule. | ASQAV §5.11 |
| `subject.repository` | ODR 0.2 | divergent | ASQAV carries `repo_ref` only on a code-authorship receipt; ODR binds the repository on the decision itself. | ASQAV §5.12 |
| `subject.pr_number` | ODR 0.2 | divergent | ASQAV's nearest member is `change_ref` on a code-authorship receipt; ODR records the reviewed pull-request number on the subject. | ASQAV §5.12 |
| `subject.head_sha` | ODR 0.2 | divergent | ASQAV's `commit_sha` and `base_sha` sit on a code-authorship receipt; ODR binds the exact reviewed head to the decision. | ASQAV §5.12 |
| `signatures[].issuer` | ODR 0.2 | divergent | ACTA carries `issuer_id` in the payload bound to `kid`; ODR's issuer is signer-committed on 0.2 documents by the §6 message. | ACTA §2.2 |
| `signatures[].role` | ODR 0.2 | extension | No draft member names the signer's role; it is signer-committed on 0.2 documents. | ACTA §2.1.1 |
| `signatures[].signed_at` | ODR 0.2 | divergent | ACTA's `issued_at` times the payload, not the signature; the signing time is signer-committed on 0.2 documents. | ACTA §2.2 |
| `signatures[].expires_at` | ODR 0.2 | divergent | ASQAV's `expires_at` declares payload validity; ODR's sits on one signature entry, is signer-committed on 0.2 documents and is enforced under `--strict-expiry`. | ASQAV §5.8 |
| `reasoning.observations` | ODR 0.2 | extension | Reviewer timeouts, failures and reruns have no draft counterpart; they qualify the reasoning they accompany. | ACTA §2.2 |
| `attestation.mechanism` | ODR 0.2 | divergent | ASQAV's `controls_evaluated` records which controls ran; ODR records the policy version, the risk tier and the action the gate took. | ASQAV §5.10 |
| `type` | ACTA-02 | conformant | The projection emits the namespaced type `aragora:decision`, which the draft's convention allows. | ACTA §2.2 |
| `issued_at` | ACTA-02 | conformant | Emitted on the projection payload as RFC 3339 with a timezone designator. | ACTA §2.2 |
| `issuer_id` | ACTA-02 | conformant | Emitted and equal to `signature.kid`, as the draft requires. | ACTA §2.2 |
| `payload_digest` | ACTA-02 | conformant | `{hash, size, preview}` over the JCS bytes of the whole ODR document, `signatures` included. | ACTA §2.2 |
| `action_ref` | ACTA-02 | divergent | Not emitted: there is no cross-engine action to correlate, and `subject` already binds the decided input. | ACTA §2.2 |
| `iteration_id` | ACTA-02 | divergent | Not emitted: debate rounds are summarised inside the ODR document rather than grouped by a transport-level id. | ACTA §2.2 |
| `verifier_sigil` | ACTA-02 | divergent | Not emitted: the sigil is produced at verification time, and `aragora-verify` reports named checks instead. | ACTA §2.2 |
| `sandbox_state` | ACTA-02 | divergent | Not emitted: an ODR receipt describes a decision, not the containment state of a tool call. | ACTA §2.2 |
| `hook_latency_ms` | ACTA-02 | divergent | Not emitted: no policy-evaluation hook runs on the projection path. | ACTA §2.2 |
| `tool_duration_ms` | ACTA-02 | divergent | Not emitted: there is no post-execution tool invocation to time. | ACTA §2.2 |
| `previousReceiptHash` | ACTA-02 | conformant | SHA-256 over the JCS bytes of the whole signed predecessor envelope, with 64 zeros at the head of a chain. | ACTA §5.7 |
| `chain_scope` | ACTA-02 | extension | Not a draft member: the projection states the digest scope of `previousReceiptHash` in the payload, because ASQAV reuses that name with a narrower scope. | ACTA §5.7 |
| `committed_fields_root` | ACTA-02 | divergent | Commitment Mode is not projected: ODR discloses the whole document, so there is nothing to withhold behind a Merkle root. | ACTA §5.1 |
| `signature.alg` | ACTA-02 | conformant | The JOSE name `EdDSA`, the draft's mandatory-to-implement algorithm. | ACTA §2.1.1 |
| `signature.kid` | ACTA-02 | divergent | The key id is `ed25519-` plus 16 hex digits of SHA-256 over the raw public key, not the recommended `sb:issuer:<base58>` form. | ACTA §2.1.1 |
| `signature.sig` | ACTA-02 | conformant | Lowercase hex Ed25519 over the JCS bytes of the payload member, with no intermediate hash. | ACTA §2.1.1 |
| `anchors` | ASQAV-08 | divergent | The profile requires a cryptographic timestamp anchor over the envelope; the projection emits none. | ASQAV §5.4 |
| `key_thumbprint` | ASQAV-08 | divergent | ODR's `key_id` is SHA-256 over the raw public key, not the RFC 7638 JWK thumbprint the profile asks for. | ASQAV §5.1.8 |
| `policy_digest` | ASQAV-08 | divergent | No policy artefact is retained or digested; the gate that applied is recorded as `quorum.rule` instead. | ASQAV §5.2.2 |
| `expires_at` | ASQAV-08 | divergent | The profile declares payload validity; ODR's expiry sits on a signature entry and is checked by both verifiers. | ASQAV §5.8 |
| `counterparty_binding` | ASQAV-08 | divergent | Cross-agent acknowledgement is not projected; reviewers are bound inside one document by `quorum.verdicts`. | ASQAV §5.7 |
| `controls_evaluated` | ASQAV-08 | divergent | ODR records the gate rule and the action taken rather than the profile's closed set of control keys. | ASQAV §5.10 |
| `witness_policy` | ASQAV-08 | divergent | ODR has no anchoring witnesses; its quorum is over reviewers, not over timestamp authorities. | ASQAV §5.4 |
| `unsigned_gap` | ASQAV-08 | divergent | ODR does not tally decisions lost to a signer outage; `reasoning.observations` records reviewer failures only. | ASQAV §5.5 |
| `risk_class` | ASQAV-08 | divergent | ODR grades the reviewer's objection through `dissent.severity_max`, never the risk of the action. | ASQAV §5.6 |
| `incident_class` | ASQAV-08 | divergent | No incident taxonomy: an ODR receipt describes a decision, not an incident. | ASQAV §5.6 |
| `result_digest` | ASQAV-08 | divergent | ODR digests the decided input through `subject.digest`; downstream result bytes are out of scope. | ASQAV §5.8 |
| `decision` | ASQAV-08 | divergent | The closed `allow`/`deny`/`rate_limit`/`observation` set cannot carry a deliberative verdict, so ODR keeps `claim.verdict`. | ASQAV §5.2 |
| `reason` | ASQAV-08 | divergent | The profile requires a vocabulary code on a denial; ODR carries prose in `reasoning.summary` and the stated ground in `adjudication`. | ASQAV §5.2.1 |
