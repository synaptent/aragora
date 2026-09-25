# Verifying an Aragora Decision Receipt — Auditor Walkthrough

**Audience:** a compliance officer, auditor, or regulator who has never seen
this repository and needs to independently verify that an Aragora decision
receipt is genuine, untampered, and understand what it evidences.
**Time required:** under five minutes, on any machine with Python 3.10+.
**You do not need** an Aragora installation, an Aragora account, API keys, or
network access to Aragora — verification is fully offline.

This document is executable: every command below was run against the
checked-in sample receipt in [`fixtures/`](fixtures/) and the outputs shown
are real. The sample is an ODR v0.2 receipt, the emitter's default output from
release 2.11.0; the output below was captured on 2026-09-25 with the published
`aragora-verify` 0.2.0 installed from PyPI into a clean venv (Python 3.11).
The earlier v0.1 sample was verified on 2026-07-02 with `aragora-verify` 0.1.0
and re-verified on 2026-07-04 with 0.1.1.

---

## 1. What a decision receipt is

When Aragora vets a decision, the outcome is recorded as a **decision
receipt**: a signed, machine-verifiable record of *what was decided, about
which exact input, by which AI models, with what independence and dissent, at
what confidence, and whether a human accepted the risk*.

For exchange with outside parties the receipt is exported to the **Open
Decision Receipt (ODR v0.2)** profile — a vendor-neutral JSON document
normatively specified in
[`docs/specs/OPEN_DECISION_RECEIPT.md`](../specs/OPEN_DECISION_RECEIPT.md).
The members an auditor will inspect:

| Field | What it records |
|---|---|
| `receipt_id`, `issued_at` | Unique identifier and timestamp of this decision record. |
| `subject` | What was decided about: a stable identifier plus a SHA-256 digest of the exact input, so the decision is bound to *these bytes*, not a paraphrase. |
| `claim.verdict` | The load-bearing assertion: `PASS`, `CONDITIONAL`, `FAIL` (or emitter-specific). |
| `reasoning` | The justification recorded *at decision time* (never a post-hoc rationalization). |
| `quorum` | Who examined the claim: participating agents with their model families (`anthropic`, `openai`, ...), whether model diversity was disclosed, who supported the verdict, and — preserved verbatim — who dissented and why. |
| `confidence` | Confidence in [0, 1], with an explicit statement of whether it is calibrated (backed by a calibration record) or an uncalibrated raw score. |
| `cruxes` | The specific claims the verdict actually turns on, when recorded. |
| `attestation` | `human_attested` (with attestor identity) or the explicit `autonomous` disposition — "no human looked at this" is a first-class, auditable fact, not a missing field. |
| `signatures` | Detached Ed25519 signatures over the canonical content digest (§3 below). |
| `source` | Link back to the full-fidelity native record inside the emitting Aragora deployment. |

A design rule worth knowing before you read one: **the profile never
fabricates**. Anything the decision record genuinely does not contain appears
as `{"status": "absent", "reason": ...}`. Absent markers and `"undisclosed"`
model families make a weak receipt *visibly* weak — they are reported by the
verifier as warnings, and it is your policy (not the tool's) whether to accept
such a receipt.

## 2. Verify the sample receipt (three commands)

The [`fixtures/`](fixtures/) directory contains a sample signed receipt and
the public key that verifies it. The only tool needed is **`aragora-verify`**,
a free, standalone, MIT-licensed verifier published on PyPI whose only
dependency is the `cryptography` package.

> PyPI release verified: `pip install -U 'aragora-verify>=0.2.0'` from a clean
> venv (real PyPI, no local wheel) installed `aragora-verify-0.2.0` and verified
> this fixture with all checks PASS on 2026-09-25 (verify the release live:
> https://pypi.org/pypi/aragora-verify/json). Version 0.2.0 is the first
> release that accepts ODR v0.2 receipts such as this one; 0.1.x rejects them
> at `schema_conformance`. Since 0.1.1 the verifier binds each signature's
> recorded `key_id` to the supplied key, so a relabeled signer fails as
> tampering. CI additionally smoke-tests the CLI against a wheel built from the
> in-repo [`aragora-verify/`](../../aragora-verify/) source.

```bash
# 1. Install the standalone verifier into a clean environment
python3 -m venv odr-env && . odr-env/bin/activate
pip install -U 'aragora-verify>=0.2.0'

# 2. Fetch the two fixture files (or copy them from a repo checkout)
#    docs/compliance/fixtures/sample_decision_receipt.odr.json
#    docs/compliance/fixtures/odr_sample_signing_public_key.pem

# 3. Verify — fully offline
aragora-verify sample_decision_receipt.odr.json --pubkey odr_sample_signing_public_key.pem
```

> Building from source instead of PyPI: `pip install ./aragora-verify` from a
> checkout of this repository installs the identical package.

Expected output (exit code `0`):

```text
Open Decision Receipt — VERIFIED
  receipt_id: receipt-walkthrough-0001
  odr_digest: sha-256:<64 hex digits>

  checks:
    [PASS] schema_conformance: conforms to ODR v0.2 profile
    [PASS] quorum_consistency: supporting/dissenting agents all appear in participants
    [PASS] canonical_digest: sha-256:<64 hex digits>
    [PASS] signature: Ed25519 signature verified — sig[0] (key_id=ed25519-…): verified
    [----] chain_link: no --chain supplied

  weakening signals (do not fail verification):
    ! attestation: autonomous — no human accepted the risk for this decision
    ! confidence: present but uncalibrated (no calibration provenance)

Dissent trail
(no dissent recorded)
  => VERIFIED (key_id=ed25519-…)
```

The `Dissent trail` section lists per-finding dissent
(`quorum.dissent.findings[]`, which merge-quorum review receipts carry). This
sample records its dissent as `quorum.dissent.views` instead, so the section
reads `(no dissent recorded)`; the dissenting agent and its view are still in
the signed receipt.

Add `--json` for a machine-readable result suitable for archiving in an audit
file.

### Verifying a receipt from a live Aragora deployment

The procedure is identical; only the key source changes: obtain the
deployment's ODR signing **public** key once, through a channel you trust
(the deployment operator; a planned discovery endpoint
`GET /.well-known/aragora-odr-signing-key` is tracked in issue #8804), then
verify any number of that deployment's receipts offline. Note that as of this
writing, receipts exported by `aragora receipt export --format odr` are
emitted **unsigned** (`signatures: []`). The verifier surfaces this as WARN
in the signature check, and when you supply `--pubkey` expecting authenticity
the overall verdict is **UNVERIFIED** (exit 3) — an unsigned receipt is never
presented as authenticated. Wiring the Ed25519 signer into the
production export path is tracked in issues #8544 and #8546. The fixture key
here is a demonstration key generated only for this walkthrough — see
[`fixtures/README.md`](fixtures/README.md).

## 3. What each check proves

| Check | What a PASS proves |
|---|---|
| `schema_conformance` | The document is a structurally well-formed ODR receipt of the version it declares (v0.1 or v0.2): all thirteen required members present, absent markers well-formed, no smuggled or malformed blocks. |
| `canonical_digest` | The receipt's canonical content digest was recomputed deterministically: `SHA-256(JCS(document minus signatures))` per RFC 8785. This digest is the exact value the signature covers and is reproducible byte-for-byte by any independent implementation. |
| `signature` | At least one Ed25519 detached signature over that digest verifies against the public key **you** supplied, **and** (0.1.1+) that signature's recorded `key_id` matches the id recomputed from your key — a relabeled `key_id` on an otherwise-valid signature FAILs as signer-label tampering. Together with `canonical_digest`, this proves the receipt was signed by the holder of the corresponding private key and that **no field outside `signatures` has been altered since signing** — verdict, reasoning, participants, dissent, confidence, timestamps, all of it. The `signatures` array itself is outside the signed digest; the `key_id` binding is what closes the signer-label spoofing gap there. |
| `quorum_consistency` | Every agent named as supporting or dissenting is a disclosed participant. A mismatch is a malformed-receipt or tampering signal (spec §8), not a style issue. |
| `chain_link` | Only when you pass `--chain <file.jsonl>`: the receipt's content digest is anchored in the supplied hash chain and declared links are self-consistent. Reported as WARN (not PASS) when links are present, because entry hashes are not independently recomputed — treat the chain as corroborating evidence, not a standalone proof. |

**Exit codes** (script these in your audit tooling):

| Code | Meaning |
|---|---|
| `0` | VERIFIED — no check failed and every present signature was cryptographically checked. |
| `1` | FAILED — at least one check failed (e.g. tampered content, invalid signature). |
| `2` | Usage/input error (unreadable file, malformed JSON or key). |
| `3` | UNVERIFIED — structurally sound, but authenticity was not established: the receipt carries signatures you did not check (no `--pubkey`), or you supplied a key and the receipt carries no signatures at all. Deliberately not `0`: **authenticity has not been established.** |

### Prove to yourself that tampering is detected

Flip the verdict in a copy of the receipt and re-verify:

```bash
python3 - <<'EOF'
import json
d = json.load(open("sample_decision_receipt.odr.json"))
d["claim"]["verdict"] = "PASS"          # attacker upgrades CONDITIONAL to PASS
json.dump(d, open("tampered.odr.json", "w"), indent=2)
EOF

aragora-verify tampered.odr.json --pubkey odr_sample_signing_public_key.pem
echo "exit=$?"
```

Result: `signature: ... INVALID`, verdict `FAILED`, `exit=1`. Any single-byte
change to any covered field — verdict, a dissenting view, a confidence value,
a participant's model family — fails the same way.

### Weakening signals are not failures

`VERIFIED` answers *"is this record authentic and intact?"* — it does not
answer *"is this decision well-supported?"*. The verifier separately reports
**weakening signals**: autonomous (un-attested) decisions, uncalibrated
confidence, undisclosed model families, absent reasoning. The sample receipt
deliberately carries two, so you can see how an honest-but-weaker receipt
presents. Thresholds ("require human attestation", "require ≥2 model
families") are organizational policy, applied on top of verification.

## 4. Receipt fields → EU AI Act Articles 12 and 13

The table maps receipt content to the record-keeping (Art. 12) and
transparency (Art. 13) obligations for high-risk AI systems. It maps
**evidence availability, not legal conformity** — the receipt makes the facts
independently inspectable; conformity assessment remains the deployer's
process. For Aragora's overall EU AI Act programme (role determination, Annex
IV technical documentation, retention policies, generated artifact bundles)
see [`EU_AI_ACT_GUIDE.md`](EU_AI_ACT_GUIDE.md); for the Article 14 (human
oversight) mapping see the profile spec
[§7](../specs/OPEN_DECISION_RECEIPT.md#7-compliance-crosswalk--eu-ai-act-art-14--nist-ai-600-1).

| Receipt field | Art. 12 — Record-keeping | Art. 13 — Transparency to deployers |
|---|---|---|
| `receipt_id` + `issued_at` | 12(1): each decision event is automatically recorded as a uniquely identified, timestamped log entry. | — |
| `subject.identifier` + `subject.digest` | 12(2): traceability of system functioning — the record is cryptographically bound (SHA-256) to the exact input examined, supporting post-market monitoring of *which* inputs produced *which* outcomes. | 13(3)(b)(vi), input-data relevance: the deployer can identify precisely what the decision concerned. |
| `claim.verdict` | 12(2): the system's output for the logged event. | 13(1): the output the deployer must be able to interpret and use appropriately. |
| `reasoning.summary` | 12(1): the decision-time justification is part of the automatic record, not reconstructed later. | 13(3)(b)(iv): information enabling interpretation of the output. |
| `quorum.participants[]` (model families/IDs) + `quorum.independence` | 12(2): identifies which model systems participated in producing each logged decision. | 13(3)(a)-(b): system identity and characteristics — including honest disclosure when diversity is `"undisclosed"` or single-family. |
| `quorum.dissent` (agents + verbatim views) | 12(1): disagreement is retained in the record rather than overwritten by the consensus. | 13(3)(b)(iii): known limitations and circumstances affecting reliability — preserved dissent tells the deployer exactly where the models disagreed. |
| `confidence.value` + `confidence.calibration` | 12(2): recorded confidence for each event. | 13(3)(b)(ii): accuracy characteristics — with an explicit, machine-readable statement of whether the figure is calibrated or a raw score. |
| `cruxes` | — | 13(3)(b)(iv): the load-bearing points a deployer should probe before relying on the output. |
| `attestation` | 12(1)/(2): whether a human reviewed the event is itself part of the record (see also Art. 14 mapping in spec §7). | 13(3)(d): information on human oversight measures as exercised for this decision. |
| `signatures` + canonical digest (spec §5–6) | 12(1) presupposes trustworthy logs: the Ed25519 signature over the RFC 8785 canonical digest makes every retained record independently tamper-evident, offline, by any party. | — |
| `source` (native-record link) | 12(1): locator from the portable artifact back to the full-fidelity internal record and its provenance chain, over the lifetime of the system. | 13(3)(e): path to fuller documentation held by the provider. |

The native `DecisionReceipt` additionally carries a per-event `provenance_chain`
(every probe, attack, and verdict, timestamped and hashed) that backs the
Art. 12 rows above; the ODR `source` block is the pointer to it. Aragora can
also generate Article-12/13 artifact bundles directly — see
[`EU_AI_ACT_GUIDE.md`](EU_AI_ACT_GUIDE.md) ("Full Artifact Bundles").

## 5. How the sample was produced (reproducibility)

The fixture is generated entirely by in-tree tooling — no model API keys, no
network, no AWS access:

```bash
# from a checkout of this repository
python scripts/generate_odr_fixture.py --output-dir docs/compliance/fixtures
```

The script builds a representative native `DecisionReceipt`, exports it with
the reference emitter (`aragora.gauntlet.odr_export.decision_receipt_to_odr` —
the same code behind `aragora receipt export --format odr`), signs it with a
freshly generated Ed25519 demonstration key
(`aragora.gauntlet.odr_signing.sign_odr_receipt`), self-verifies, and writes
the receipt plus the public key. The private key is discarded; re-running
changes only the key and signature, never the receipt content.

In production the flow is the same with two differences: receipts come from
real debates (`aragora receipt export --format odr <receipt-id>`), and signing
uses the deployment key held in AWS Secrets Manager (only its public half is
ever distributed to verifiers). Signed export and public-key discovery for
live deployments are tracked in issues #8544, #8546, and #8804.

## 6. Reference

- Profile spec (normative): [`docs/specs/OPEN_DECISION_RECEIPT.md`](../specs/OPEN_DECISION_RECEIPT.md)
- Field-by-field native mapping: [`docs/specs/odr-native-mapping.md`](../specs/odr-native-mapping.md)
- Standalone verifier source: [`aragora-verify/`](../../aragora-verify/) (PyPI: `aragora-verify`)
- EU AI Act programme guide: [`EU_AI_ACT_GUIDE.md`](EU_AI_ACT_GUIDE.md)
- Sample artifacts: [`fixtures/`](fixtures/)
