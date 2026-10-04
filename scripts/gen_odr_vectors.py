#!/usr/bin/env python3
"""Write the committed ODR test vectors under ``tests/verify/vectors/``.

Deterministic by construction: pinned receipt ids, pinned timestamps and the
committed non-secret seed from ``tests/gauntlet/odr_test_keys.py``, so two
consecutive runs leave the tree unchanged. Only the public half of the signing
key is written out.

Each vector gets ``<name>.odr.json``, a ``<name>.expected.json`` oracle and,
where the vector is a projection or a chain, a ``<name>.acta.json`` (plus
``chain_three.chain.json``). The expected outcome of every vector is pinned
here as ``exit_code``; the generator refuses to write an oracle that disagrees
with it, so a verifier regression cannot quietly rewrite the fixtures.

Usage: ``python3 scripts/gen_odr_vectors.py``
"""

from __future__ import annotations

import base64
import copy
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "aragora-verify" / "src"))

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey  # noqa: E402

from aragora.gauntlet.odr_acta_projection import (  # noqa: E402
    acta_envelope_hash,
    project_to_acta,
    verify_acta_projection,
)
from aragora.gauntlet.odr_export import decision_receipt_to_odr  # noqa: E402
from aragora.gauntlet.odr_jcs import jcs_canonicalize  # noqa: E402
from aragora.gauntlet.odr_signing import (  # noqa: E402
    compute_key_id,
    public_key_pem,
    sign_odr_receipt,
)
from aragora.gauntlet.odr_verify import FAIL, verify_odr_document  # noqa: E402
from aragora.gauntlet.receipt_models import DecisionReceipt  # noqa: E402
from aragora_verify import verify  # noqa: E402
from tests.gauntlet.odr_test_keys import odr_test_key  # noqa: E402

VECTORS = ROOT / "tests" / "verify" / "vectors"

#: One vector: its ODR document, its ACTA projection (when it has one), the exit
#: code its oracle must pin, and the human-readable reason.
VectorSpec = tuple[dict[str, Any], dict[str, Any] | None, int, str]

ISSUED_AT = "2026-01-15T12:00:00+00:00"
SIGNED_AT = "2026-01-15T12:05:00+00:00"
EXPIRES_AT = "2026-01-16T12:00:00+00:00"
ACTA_ISSUED_AT = "2026-01-15T12:10:00+00:00"
ISSUER = "aragora"
IMPOSTOR = "impostor"
HEAD_SHA = "7f9c2ba4e88f827d616045507605853ed73b8093"
BASE_SHA = "4b825dc642cb6eb9a060e54bf8d69288fbee4904"
REPOSITORY = "synaptent/aragora"
PR_NUMBER = 10110

#: A second committed test seed, used only so ``wrong_key`` carries a signature
#: that is valid under a key which is NOT ``pubkey.pem``. Test material, like
#: ``tests/gauntlet/odr_test_keys.py``; never a production key.
FOREIGN_KEY_SEED = bytes(range(32, 64))

AGENTS = (
    ("claude", "claude", "claude-opus-5"),
    ("codex", "openai", "gpt-4.1-codex"),
    ("gemini", "gemini", "gemini-3.1-pro-preview"),
)
ALL_AGENTS = [agent for agent, _, _ in AGENTS]
RULE = {
    "required_signals": 2,
    "requires_western_frontier": True,
    "western_only_counted": False,
    "counted_families": ["claude", "openai"],
}

#: Ordering for ``severity_max``. Ranking by label rather than by string order
#: keeps an unexpected label loud instead of silently sorting into the wrong
#: place.
SEVERITY_RANK = {"P0": 0, "P1": 1, "P2": 2, "P3": 3}


def verdicts(decisions: dict[str, str], blocking: tuple[str, ...] = ()) -> list[dict[str, Any]]:
    return [
        {
            "issuer": agent,
            "role": "reviewer",
            "verdict": decisions.get(agent, "approve"),
            "model_family": family,
            "model_id": model,
            "posted_at": ISSUED_AT,
            "grounded": True,
            "counted": True,
            "blocking": agent in blocking,
        }
        for agent, family, model in AGENTS
    ]


def finding(issuer: str, severity: str, text: str) -> dict[str, Any]:
    return {
        "issuer": issuer,
        "severity": severity,
        "blocking": severity in ("P0", "P1"),
        "text": text,
    }


def dissent_block(findings: list[dict[str, Any]]) -> dict[str, Any]:
    severities = [item["severity"] for item in findings]
    return {
        "findings": findings,
        "severity_max": min(severities, key=SEVERITY_RANK.__getitem__),
        "blocking": any(item["blocking"] for item in findings),
    }


def receipt(
    receipt_id: str,
    *,
    summary: str,
    reasoning: str,
    verdict: str,
    reached: bool,
    supporting: list[str],
    dissenting: tuple[str, ...] = (),
    views: tuple[str, ...] = (),
    odr: dict[str, Any] | None = None,
) -> DecisionReceipt:
    return DecisionReceipt.from_dict(
        {
            "receipt_id": receipt_id,
            "gauntlet_id": f"{receipt_id}-gauntlet",
            "timestamp": ISSUED_AT,
            "input_summary": summary,
            "input_hash": hashlib.sha256(summary.encode("utf-8")).hexdigest(),
            "verdict": verdict,
            "confidence": 0.86,
            "verdict_reasoning": reasoning,
            "dissenting_views": list(views),
            "consensus_proof": {
                "reached": reached,
                "confidence": 0.86,
                "method": "merge-quorum",
                "supporting_agents": list(supporting),
                "dissenting_agents": list(dissenting),
            },
            "agent_responses": [
                {"agent": agent, "response": "reviewed", "provider": family, "model": model}
                for agent, family, model in AGENTS
            ],
            "settlement_metadata": {
                "repo": REPOSITORY,
                "pr": PR_NUMBER,
                "head_sha": HEAD_SHA,
                "base_sha": BASE_SHA,
                "odr": odr or {},
            },
        }
    )


def document(receipt_id: str, *, odr_version: str, **fields: Any) -> dict[str, Any]:
    """Emit one ODR document at an EXPLICIT profile version (ruling 4).

    The vectors must stay stable across a change of the emitter's default, so
    the version is always passed, never inherited.
    """
    return decision_receipt_to_odr(receipt(receipt_id, **fields), odr_version=odr_version)


def signed(doc: dict[str, Any], key: Any, **extra: Any) -> dict[str, Any]:
    """Sign a v0.2 document: the entry's metadata is signer-committed."""
    return sign_odr_receipt(doc, key, issuer=ISSUER, role="emitter", signed_at=SIGNED_AT, **extra)


def tamper_signature(doc: dict[str, Any]) -> dict[str, Any]:
    doc = copy.deepcopy(doc)
    entry = doc["signatures"][0]
    raw = bytearray(base64.b64decode(entry["signature"]))
    raw[-1] ^= 0x01
    entry["signature"] = base64.b64encode(bytes(raw)).decode("ascii")
    return doc


def tamper_member(doc: dict[str, Any], path: tuple[Any, ...], value: Any) -> dict[str, Any]:
    doc = copy.deepcopy(doc)
    target = doc
    for member in path[:-1]:
        target = target[member]
    target[path[-1]] = value
    return doc


def project(
    doc: dict[str, Any], key: Any, previous: dict[str, Any] | None = None
) -> dict[str, Any]:
    return project_to_acta(
        doc,
        private_key=key,
        kid=compute_key_id(key.public_key()),
        previous_receipt_hash=None if previous is None else acta_envelope_hash(previous),
        issued_at=ACTA_ISSUED_AT,
    )


def break_binding(envelope: dict[str, Any], key: Any) -> dict[str, Any]:
    """Move only the declared payload digest, then re-sign.

    The envelope stays well-formed and its signature stays valid, so the
    projection fails on ``acta_binding`` alone rather than on the shape or the
    signature.
    """
    envelope = copy.deepcopy(envelope)
    digest = envelope["payload"]["payload_digest"]
    digest["hash"] = digest["hash"][:-1] + ("0" if digest["hash"][-1] != "0" else "1")
    envelope["signature"]["sig"] = key.sign(jcs_canonicalize(envelope["payload"])).hex()
    return envelope


MERGE = {
    "summary": f"Merge {REPOSITORY} PR {PR_NUMBER}: bound the ingest worker retry budget",
    "reasoning": (
        "Three model families reviewed the diff against the retry-budget "
        "contract; none found a blocking defect."
    ),
    "verdict": "PASS",
    "reached": True,
    "supporting": ALL_AGENTS,
    "odr": {"verdicts": verdicts({}), "rule": RULE},
}


def build_vectors(key: Any, foreign_key: Any) -> dict[str, dict[str, Any]]:
    """Return ``{name: {doc, acta, chain, description, exit_code}}``."""
    base = signed(document("odr-vector-merge-quorum", odr_version="0.2", **MERGE), key)
    blocking_finding = finding(
        "gemini", "P1", "Retry budget is still unbounded when the upstream returns 429."
    )
    advisory_finding = finding(
        "gemini", "P2", "The retry cap would read better as a named constant."
    )
    style_finding = finding("codex", "P3", "Docstring does not mention the new cap.")

    dissent_p1 = document(
        "odr-vector-dissent-p1",
        odr_version="0.2",
        summary=f"Merge {REPOSITORY} PR {PR_NUMBER}: bound the ingest worker retry budget",
        reasoning="One family found a grounded blocking defect, so the gate did not open.",
        verdict="CONDITIONAL",
        reached=False,
        supporting=["claude", "codex"],
        dissenting=("gemini",),
        views=("gemini: the retry budget is unbounded on 429 responses.",),
        odr={
            "verdicts": verdicts({"gemini": "request_changes"}, blocking=("gemini",)),
            "rule": RULE,
            "dissent": dissent_block([blocking_finding]),
        },
    )
    dissent_p2 = document(
        "odr-vector-dissent-p2",
        odr_version="0.2",
        summary=f"Merge {REPOSITORY} PR {PR_NUMBER}: name the ingest retry cap",
        reasoning="The only dissent is advisory, so the gate opened with the finding recorded.",
        verdict="PASS",
        reached=True,
        supporting=ALL_AGENTS,
        dissenting=("gemini",),
        views=("gemini: prefer a named constant for the cap.",),
        # No `rule` here: the recorded rule treats any dissent as a closed gate,
        # which would contradict this receipt's advisory-only outcome.
        odr={"verdicts": verdicts({}), "dissent": dissent_block([advisory_finding])},
    )
    escalate = document(
        "odr-vector-adjudicated-escalate",
        odr_version="0.2",
        summary=f"Merge {REPOSITORY} PR {PR_NUMBER}: rework the ingest retry ladder",
        reasoning="The blocking finding is grounded but disputed, so a human was asked to rule.",
        verdict="CONDITIONAL",
        reached=False,
        supporting=["claude"],
        dissenting=("codex", "gemini"),
        views=(
            "codex: the ladder still retries non-idempotent writes.",
            "gemini: prefer a named constant for the cap.",
        ),
        odr={
            "verdicts": verdicts(
                {"codex": "request_changes", "gemini": "comment"}, blocking=("codex",)
            ),
            "rule": RULE,
            "dissent": dissent_block(
                [
                    finding("codex", "P1", "The ladder still retries non-idempotent writes."),
                    advisory_finding,
                ]
            ),
            "adjudication": {
                "kind": "review_adjudication.v1",
                "verdict": "escalate",
                "reason": "the blocking finding is grounded but disputed by the author",
                "escalated_findings": ["retry-ladder-non-idempotent"],
            },
        },
    )
    settle = document(
        "odr-vector-adjudicated-settle",
        odr_version="0.2",
        summary=f"Merge {REPOSITORY} PR {PR_NUMBER}: document the ingest retry cap",
        reasoning="Both findings are advisory; the adjudicator settled them and the gate opened.",
        verdict="PASS",
        reached=True,
        supporting=ALL_AGENTS,
        odr={
            "verdicts": verdicts({"codex": "comment"}),
            "rule": RULE,
            "dissent": dissent_block([advisory_finding, style_finding]),
            "adjudication": {
                "kind": "review_adjudication.v1",
                "verdict": "settle",
                "reason": "both findings are advisory and were addressed in the same push",
                "advisory_severity_policy": "cap_at_advisory",
                "settled_findings": ["retry-cap-constant", "retry-cap-docstring"],
            },
        },
    )
    v01 = {
        "summary": f"Merge {REPOSITORY} PR {PR_NUMBER}: bound the ingest worker retry budget",
        "reasoning": "A v0.1 receipt records the same decision without the v0.2 members.",
        "verdict": "PASS",
        "reached": True,
        "supporting": ALL_AGENTS,
    }
    chain_docs = [
        signed(
            document(
                f"odr-vector-chain-{link}",
                odr_version="0.2",
                summary=f"Merge {REPOSITORY} PR {PR_NUMBER}: ingest hardening step {link}",
                reasoning="Chain link recorded by the same emitter under the same key.",
                verdict="PASS",
                reached=True,
                supporting=ALL_AGENTS,
                odr={"verdicts": verdicts({}), "rule": RULE},
            ),
            key,
        )
        for link in (1, 2, 3)
    ]
    chain: list[dict[str, Any]] = []
    for doc in chain_docs:
        chain.append(project(doc, key, chain[-1] if chain else None))

    projection = project(base, key)
    vectors: dict[str, VectorSpec] = {
        "pass_clean": (
            base,
            None,
            0,
            "A signed v0.2 receipt with a reached quorum and no dissent.",
        ),
        "dissent_p1_blocking": (
            signed(dissent_p1, key),
            None,
            0,
            "Blocking dissent: severity_max P1 and dissent.blocking true; the receipt still verifies.",
        ),
        "dissent_p2_advisory": (
            signed(dissent_p2, key),
            None,
            0,
            "Advisory dissent: severity_max P2 and dissent.blocking false.",
        ),
        "adjudicated_escalate": (
            signed(escalate, key),
            None,
            0,
            "A blocking finding escalated to a human: adjudication.verdict is escalate.",
        ),
        "adjudicated_settle": (
            signed(settle, key),
            None,
            0,
            "Advisory findings settled by the adjudicator: adjudication.verdict is settle.",
        ),
        "tampered_body": (
            tamper_member(base, ("claim", "verdict"), "FAIL"),
            None,
            1,
            "pass_clean with claim.verdict rewritten after signing: signature FAIL, "
            "canonical_digest still PASS.",
        ),
        "tampered_signature": (
            tamper_signature(base),
            None,
            1,
            "pass_clean with one flipped signature byte: signature FAIL (INVALID).",
        ),
        "tampered_metadata": (
            tamper_member(base, ("signatures", 0, "issuer"), IMPOSTOR),
            None,
            1,
            "pass_clean with signatures[0].issuer relabelled after signing: signature FAIL, "
            "canonical_digest still PASS, because the v0.2 construction commits the entry's "
            "metadata.",
        ),
        "wrong_key": (
            signed(document("odr-vector-merge-quorum", odr_version="0.2", **MERGE), foreign_key),
            None,
            1,
            "The same decision signed by a foreign key: no signature verifies with pubkey.pem.",
        ),
        "expired_signature": (
            signed(
                document("odr-vector-merge-quorum", odr_version="0.2", **MERGE),
                key,
                expires_at=EXPIRES_AT,
            ),
            None,
            0,
            "A valid signature whose expires_at has passed: a warning by default, a failure "
            "under --strict-expiry.",
        ),
        "v01_compat_unsigned": (
            document("odr-vector-v01-unsigned", odr_version="0.1", **v01),
            None,
            0,
            "An unsigned v0.1 receipt: schema and digest verify and the signature check is "
            "skipped rather than failed, so the recorded verdict is ok. The packaged CLI "
            "additionally reports exit 3 (authenticity never established) when a key is "
            "supplied and the receipt carries nothing to check.",
        ),
        "v01_compat_signed": (
            sign_odr_receipt(document("odr-vector-v01-signed", odr_version="0.1", **v01), key),
            None,
            0,
            "A v0.1 receipt signed over the 32-byte v0.1 message with the three-member entry, "
            "so no unauthenticated-metadata warning is raised.",
        ),
        "chain_three": (
            chain_docs[-1],
            chain[-1],
            0,
            "Head of a three-link ACTA-02 chain, verified with --acta chain_three.acta.json; "
            "chain_three.chain.json carries all three envelopes, genesis first, for link-by-link "
            "hash recomputation. It is not an input to --chain, which reads the legacy JSONL "
            "hash ledger.",
        ),
        "projection_pass": (
            base,
            projection,
            0,
            "pass_clean projected into a genesis ACTA-02 envelope that carries it verbatim.",
        ),
        "projection_binding_broken": (
            base,
            break_binding(projection, key),
            1,
            "The same projection with only payload_digest.hash moved and re-signed: "
            "acta_binding FAIL.",
        ),
    }
    built: dict[str, dict[str, Any]] = {
        name: {
            "doc": doc,
            "acta": acta,
            "chain": None,
            "description": description,
            "exit_code": exit_code,
        }
        for name, (doc, acta, exit_code, description) in vectors.items()
    }
    built["chain_three"]["chain"] = chain
    return built


def failing(checks: Any) -> list[str]:
    return sorted({check.name for check in checks if check.status == FAIL})


def expected_entry(name: str, vector: dict[str, Any], public_key: Any) -> dict[str, Any]:
    """Run both verifiers over one vector and pin the result.

    The in-repo engine takes no envelope, so the projection vectors are checked
    with ``verify_acta_projection`` beside it — the same two library calls the
    CLI makes in one pass.
    """
    doc, acta = vector["doc"], vector["acta"]
    entry: dict[str, Any] = {}
    in_repo = verify_odr_document(doc, public_key=public_key)
    ok, reasons = in_repo.ok, failing(in_repo.checks)
    if acta is not None:
        projection = verify_acta_projection(acta, public_key)
        ok, reasons = ok and projection.ok, sorted({*reasons, *failing(projection.checks)})
    entry["verifier"] = {"verified": ok, "exit_code": 0 if ok else 1, "reasons": reasons}
    for member, strict in (("aragora_verify", False), ("aragora_verify_strict_expiry", True)):
        if strict and name != "expired_signature":
            continue
        result = verify(doc, public_key=public_key, acta=acta, strict_expiry=strict)
        entry[member] = {
            "ok": result.ok,
            "exit_code": 0 if result.ok else 1,
            "reasons": failing(result.checks),
        }
    entry["description"] = vector["description"]
    pinned = vector["exit_code"]
    measured = {entry["verifier"]["exit_code"], entry["aragora_verify"]["exit_code"]}
    if measured != {pinned}:
        raise SystemExit(f"{name}: expected exit {pinned}, verifiers report {sorted(measured)}")
    if pinned and not entry["aragora_verify"]["reasons"]:
        raise SystemExit(f"{name}: a failing vector must name its failing check")
    return entry


def write_json(path: Path, payload: Any) -> None:
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def main() -> int:
    key = odr_test_key()
    foreign_key = Ed25519PrivateKey.from_private_bytes(FOREIGN_KEY_SEED)
    VECTORS.mkdir(parents=True, exist_ok=True)
    (VECTORS / "pubkey.pem").write_text(public_key_pem(key), encoding="utf-8")
    vectors = build_vectors(key, foreign_key)
    for name, vector in vectors.items():
        write_json(VECTORS / f"{name}.odr.json", vector["doc"])
        if vector["acta"] is not None:
            write_json(VECTORS / f"{name}.acta.json", vector["acta"])
        if vector["chain"] is not None:
            write_json(VECTORS / f"{name}.chain.json", vector["chain"])
        write_json(
            VECTORS / f"{name}.expected.json", expected_entry(name, vector, key.public_key())
        )
    print(f"wrote {len(vectors)} vectors to {VECTORS.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
