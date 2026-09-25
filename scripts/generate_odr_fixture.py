#!/usr/bin/env python3
"""Generate the sample signed Open Decision Receipt fixture for the compliance walkthrough.

Produces the three artifacts checked in under ``docs/compliance/fixtures/`` and
referenced by ``docs/compliance/ODR_VERIFICATION_WALKTHROUGH.md``:

* ``sample_decision_receipt.json``      -- the native ``DecisionReceipt`` record
* ``sample_decision_receipt.odr.json``  -- the vendor-neutral ODR v0.2 export,
                                           carrying one Ed25519 detached signature
* ``odr_sample_signing_public_key.pem`` -- the public key that verifies it

The receipt *content* is fixed (deterministic IDs and timestamps) so diffs stay
reviewable; the signing key is generated fresh on every run and its private
half is **never written anywhere** -- only the public key is emitted. The key is
a demonstration key for the walkthrough, not Aragora's production ODR signing
key (which lives in AWS Secrets Manager; see ``aragora/gauntlet/odr_signing.py``).

Requires no provider API keys, no network, and no AWS access:

    python scripts/generate_odr_fixture.py --output-dir docs/compliance/fixtures

The script self-checks its own output with the in-repo verification engine
(``aragora.gauntlet.odr_verify.verify_odr_document``) before writing, so a
fixture that would not verify is never emitted.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from aragora.gauntlet.odr_export import (  # noqa: E402
    decision_receipt_to_odr,
    odr_content_digest,
)
from aragora.gauntlet.odr_signing import (  # noqa: E402
    DEFAULT_SIGNING_ISSUER,
    generate_signing_key,
    public_key_pem,
    sign_odr_receipt,
)
from aragora.gauntlet.odr_verify import load_public_key, verify_odr_document  # noqa: E402
from aragora.gauntlet.receipt_models import (  # noqa: E402
    AgentResponseRecord,
    ConsensusProof,
    DecisionReceipt,
    ProvenanceRecord,
)

#: Fixed content so re-runs only change the signature block, keeping diffs small.
RECEIPT_ID = "receipt-walkthrough-0001"
GAUNTLET_ID = "gauntlet-walkthrough-0001"
TIMESTAMP = "2026-07-02T12:00:00+00:00"
INPUT_SUMMARY = (
    "Proposal: enable automated invoice approval for amounts under EUR 5,000 "
    "when the supplier is on the approved-vendor list"
)
# SHA-256 of the canonical proposal text above (recomputed below, never hardcoded stale).


def build_sample_receipt() -> DecisionReceipt:
    """A representative, fully-populated DecisionReceipt.

    Includes the evidentiary features the walkthrough teaches an auditor to
    look for: heterogeneous model families, an explicit dissenting agent with a
    preserved dissenting view, consensus proof, verdict reasoning, and a
    provenance chain.
    """
    import hashlib

    input_hash = hashlib.sha256(INPUT_SUMMARY.encode("utf-8")).hexdigest()

    consensus = ConsensusProof(
        reached=True,
        confidence=0.82,
        supporting_agents=["claude", "gpt5"],
        dissenting_agents=["gemini"],
        method="majority",
        evidence_hash=hashlib.sha256(b"walkthrough-consensus-evidence").hexdigest(),
    )

    agent_responses = [
        AgentResponseRecord(
            agent="claude",
            response=(
                "Support with conditions: the EUR 5,000 threshold is reasonable, "
                "but the approved-vendor list must be re-validated quarterly."
            ),
            role="proposer",
            round=2,
            provider="anthropic",
            model="claude-opus-4",
        ),
        AgentResponseRecord(
            agent="gpt5",
            response=(
                "Support: exposure is bounded by the threshold and vendor "
                "allow-list; recommend sampling 5% of auto-approved invoices "
                "for retrospective human review."
            ),
            role="critic",
            round=2,
            provider="openai",
            model="gpt-5",
        ),
        AgentResponseRecord(
            agent="gemini",
            response=(
                "Dissent: duplicate-invoice detection is not yet in place; "
                "automated approval should wait until it ships."
            ),
            role="critic",
            round=2,
            provider="google",
            model="gemini-2.5-pro",
        ),
    ]

    provenance = [
        ProvenanceRecord(
            timestamp="2026-07-02T11:45:00+00:00",
            event_type="probe",
            agent="gpt5",
            description="Adversarial probe: split-invoice evasion of the EUR 5,000 threshold",
            evidence_hash=hashlib.sha256(b"walkthrough-probe-1").hexdigest(),
        ),
        ProvenanceRecord(
            timestamp="2026-07-02T11:52:00+00:00",
            event_type="attack",
            agent="gemini",
            description="Attack scenario: supplier impersonation via look-alike vendor name",
            evidence_hash=hashlib.sha256(b"walkthrough-attack-1").hexdigest(),
        ),
        ProvenanceRecord(
            timestamp="2026-07-02T11:59:00+00:00",
            event_type="verdict",
            description="Majority verdict recorded with one dissent preserved",
            evidence_hash=hashlib.sha256(b"walkthrough-verdict").hexdigest(),
        ),
    ]

    return DecisionReceipt(
        receipt_id=RECEIPT_ID,
        gauntlet_id=GAUNTLET_ID,
        timestamp=TIMESTAMP,
        input_summary=INPUT_SUMMARY,
        input_hash=input_hash,
        risk_summary={"critical": 0, "high": 1, "medium": 2, "low": 1},
        attacks_attempted=4,
        attacks_successful=1,
        probes_run=6,
        vulnerabilities_found=1,
        verdict="CONDITIONAL",
        confidence=0.82,
        robustness_score=0.75,
        vulnerability_details=[
            {
                "severity": "high",
                "description": (
                    "Split-invoice evasion: two invoices under the threshold from "
                    "the same vendor on the same day bypass the intended cap"
                ),
                "mitigation": "Aggregate same-vendor daily totals before auto-approval",
            }
        ],
        verdict_reasoning=(
            "Majority (2 of 3) support automated approval under EUR 5,000 with "
            "quarterly vendor-list revalidation and 5% retrospective sampling. "
            "Conditional rather than pass: the split-invoice finding must be "
            "mitigated, and gemini's dissent on duplicate-invoice detection is "
            "preserved as an open risk."
        ),
        dissenting_views=[
            "gemini: duplicate-invoice detection is not yet in place; automated "
            "approval should wait until it ships."
        ],
        consensus_proof=consensus,
        provenance_chain=provenance,
        agent_responses=agent_responses,
    )


def export_receipt_to_odr(receipt: DecisionReceipt) -> dict:
    """The exact (unsigned) export call used to produce the checked-in fixture.

    Deliberately passes **no** ``calibration_provenance``: the walkthrough
    fixture demonstrates the honest ``absent`` calibration marker, and
    consulting the ambient calibration store would make regeneration depend on
    whichever ELO/calibration records happen to exist on the generating
    machine — breaking the "re-running changes only the key and signature"
    guarantee. The regression tests in
    ``tests/gauntlet/test_odr_walkthrough_fixture.py`` call this same function
    so the fixture is always compared against the generator's actual export
    path.
    """
    return decision_receipt_to_odr(receipt)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--output-dir",
        default=str(REPO_ROOT / "docs" / "compliance" / "fixtures"),
        help="Directory to write the fixture files into (default: docs/compliance/fixtures)",
    )
    args = parser.parse_args()
    out_dir = Path(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    receipt = build_sample_receipt()

    # Native -> neutral ODR profile (never fabricates; absent markers are honest).
    odr = export_receipt_to_odr(receipt)

    # Sign with a fresh demonstration key. The private half exists only in this
    # process; solely the public key is written out.
    private_key = generate_signing_key()
    signed_odr = sign_odr_receipt(odr, private_key, issuer=DEFAULT_SIGNING_ISSUER)
    pubkey = public_key_pem(private_key)

    # Self-check: never emit a fixture that does not verify.
    result = verify_odr_document(signed_odr, public_key=load_public_key(pubkey.encode("utf-8")))
    failed = [c for c in result.checks if c.status == "fail"]
    if failed or not result.ok:
        for check in result.checks:
            print(f"  [{check.status}] {check.name}: {check.detail}", file=sys.stderr)
        print("error: generated fixture failed self-verification; nothing written", file=sys.stderr)
        return 1

    native_path = out_dir / "sample_decision_receipt.json"
    odr_path = out_dir / "sample_decision_receipt.odr.json"
    pubkey_path = out_dir / "odr_sample_signing_public_key.pem"

    native_path.write_text(json.dumps(receipt.to_dict(), indent=2, sort_keys=True) + "\n")
    odr_path.write_text(json.dumps(signed_odr, indent=2, sort_keys=True) + "\n")
    pubkey_path.write_text(pubkey)

    digest = odr_content_digest(signed_odr)
    print(f"wrote {native_path}")
    print(f"wrote {odr_path}")
    print(f"wrote {pubkey_path}")
    print(f"odr_digest: sha-256:{digest}")
    print(f"key_id:     {signed_odr['signatures'][0]['key_id']}")
    print("self-verification: ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
