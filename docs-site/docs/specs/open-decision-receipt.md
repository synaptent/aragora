---
title: Open Decision Receipt (ODR) — Content Profile v0.1
description: Open Decision Receipt (ODR) — Content Profile v0.1
---

# Open Decision Receipt (ODR) — Content Profile v0.1

**Status:** Draft v0.1 — Tier 2, issue [#8224](https://github.com/synaptent/aragora/issues/8224),
part of the ODR spine ([#8223](https://github.com/synaptent/aragora/issues/8223)).
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

These additions preserve the meaning and required-ness of every v0.1 member; every row below is optional in a v0.2 document. Inside the five `object` rows (`quorum.verdicts[]`, `quorum.rule`, `quorum.dissent.findings[]`, `adjudication`, `reasoning.observations[]`) a `?` suffix (or the word optional) marks a sub-member an emitter may omit, and a conforming emitter writes every other listed sub-member whenever it writes that object (§8, rule 5). This revision's schema and verifiers do not yet enforce that completeness: an object lacking such a sub-member, or an `adjudication` carrying a `status` member, is schema-valid here and neither verifier rejects it; `required` arrays for those five shapes (`adjudication`: `kind`, `verdict`, `reason`, no `status`) and the matching verifier checks follow in the next revision of this staged rollout (§9.5).

| Member | Parent | Type | Meaning |
|---|---|---|---|
| `quorum.verdicts[]` | `quorum` | object | Per-reviewer `issuer`, `role?`, `verdict`, `model_family`, `model_id`, `head_sha?`, `posted_at?`, `grounded?`, `counted?`, `severity_max?`, `blocking?`; undisclosed model ids use `"undisclosed"`. |
| `quorum.rule` | `quorum` | object | Gate rule: `required_signals` (integer), `requires_western_frontier` and `western_only_counted` (booleans), `counted_families` (string array). |
| `quorum.dissent.findings[]` | `quorum.dissent` | object | Findings from all reviewers: `issuer`, `severity` (P0..P3), `blocking` (P0/P1 true), `location?`, `text`. |
| `quorum.dissent.severity_max` | `quorum.dissent` | string | Most severe finding, ordered P0 > P1 > P2 > P3. |
| `quorum.dissent.blocking` | `quorum.dissent` | boolean | True iff any finding is P0/P1. |
| `adjudication` | top-level | object | Omitted when absent; `kind: "review_adjudication.v1"`, `verdict` (settle/block/escalate/not_applicable), `reason`; optional policy and assessment/finding arrays record the adjudicator's decision. |
| `attestation.mechanism.{policy_version,tier,tiered_gate,severity_gated,action,action_reason,record_ref}` | `attestation.mechanism` | integer, integer, boolean, boolean, string, string, string | Policy version, risk tier, gate modes, action and reason, optional settlement-record reference. |
| `subject.repository` | `subject` | string | Repository owning the reviewed PR. |
| `subject.pr_number` | `subject` | integer | Reviewed pull-request number. |
| `subject.head_sha` | `subject` | string | Exact reviewed head. |
| `subject.base_sha` | `subject` | string | Recorded base, when available. |
| `reasoning.observations[]` | `reasoning` | object | `kind` (timeout/failure/rerun), `family`, `detail`; only alongside a real source reasoning summary, never an absent marker. |

Gate-level dissent (`present`/`dissenting_agents`/`verdicts[].blocking`) and severity-level findings (`findings`/`severity_max`/`dissent.blocking`) are independent notions, never derived from each other.
An emitter MUST NOT write any of these members into a v0.1 document (§8, rule 5).
The schema and the verifiers of this revision do not yet reject them on a v0.1 document; version-scoped rejection (failing check `schema_conformance`, detail `<path>: not in profile 0.1`) follows in the next revision of this staged rollout (§9.5).

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
  detached payload, or place Ed25519 signatures in the reserved
  `signatures[]` array (schema shape: `alg`, `key_id`, `signature`,
  `signed_at`). Implementation is issue **#8225** and is out of scope for
  v0.1 — emitters MUST emit `signatures: []`.
- **in-toto:** the ODR document can serve as the predicate of an attestation
  whose subject duplicates `subject.digest`.

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

## 7. Compliance mapping — EU AI Act Art. 14 / NIST AI 600-1

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

## 8. Conformance

An emitter conforms to ODR v0.1 or v0.2 iff:

1. its output validates against `aragora/gauntlet/odr_schema.json`;
2. every value is sourced from a real record (rule 1) and every unsupplied
   field carries an absent marker (rule 2) — fabricating a value that should
   be absent is non-conformant even if schema-valid;
3. hashing and signing use the JCS basis of §5;
4. `signatures` is `[]` and `routing.status` is `"reserved"`.
5. it writes no §4.10 member into a v0.1 document, no member outside §2 and §4.10 into a v0.2 document, and every non-`?` sub-member of each §4.10 `object` row it writes — non-conformant even if schema-valid in this revision (verifier-side rejection follows, §4.10).

A verifier conforms iff it validates the schema, recomputes `odr_digest` from
JCS bytes, and treats `"undisclosed"`/absent markers as *weakening* rather
than failing the receipt (policy thresholds are the verifier's choice).

A verifier SHOULD additionally cross-check internal consistency: every name
in `quorum.supporting_agents` and `quorum.dissent.dissenting_agents` should
appear among `quorum.participants[].agent`. A mismatch is a malformed-receipt
signal (emitter bug or tampering), not a mere weakening.

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

ODR v0.2 is a **staged rollout**, not one coordinated release. The schemas and
both in-repo verifiers accept v0.2 first; the emitter defaults to 0.1 and emits
0.2 **on request** (`odr_version="0.2"` in the library; `--odr-version 0.2` on
the CLIs once the bridge lands) until `aragora-verify` **0.2.0** is published
on PyPI. The default flips afterwards, for release 2.11.0.
Published `aragora-verify` 0.1.1 fails a v0.2 document at `schema_conformance`
(`odr_version: must be '0.1'`); use either in-repo verifier for opt-in v0.2
until 0.2.0 publishes. Every v0.1 document keeps verifying unchanged with every
verifier throughout. This remains the **stability contract that v1.0 will honour**.

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
