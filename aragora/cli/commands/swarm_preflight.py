"""``aragora swarm preflight`` subcommand.

``aragora.cli.commands.swarm`` dispatches ``swarm preflight`` here and re-exports
``_run_preflight_action``. The preflight functions are imported when the command
runs, so tests patch them on ``aragora.swarm.preflight``.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any

JsonDict = dict[str, Any]


def _run_preflight_action(
    args: argparse.Namespace,
    *,
    target_branch: str,
    skip_publication: bool,
    as_json: bool,
) -> None:
    """Handle ``aragora swarm preflight``; exits with status 2 when the preflight is blocked."""

    from aragora.swarm.credential_envelope import CredentialEnvelope
    from aragora.swarm.preflight import (
        evaluate_preflight_receipt_gate,
        run_contract_preflight_receipt,
        run_preflight,
    )
    from aragora.worktree.fleet import resolve_repo_root

    payload: JsonDict

    repo_root = resolve_repo_root(Path.cwd())
    contract_arg = getattr(args, "contract", None)
    if contract_arg:
        contract_path = Path(str(contract_arg)).expanduser()
        envelope = CredentialEnvelope.from_environment(os.environ)
        receipt = run_contract_preflight_receipt(
            repo_root=repo_root,
            agent=str(getattr(args, "worker_model", "claude") or "claude"),
            base_ref=str(target_branch or "main"),
            skip_publication=skip_publication,
            contract_path=contract_path,
            envelope=envelope,
        )
        expected_contract_checksum = str(
            receipt.artifacts.get("expected_contract_checksum", "") or ""
        ).strip()
        admission_gate = evaluate_preflight_receipt_gate(
            receipt,
            repo_root=repo_root,
            envelope=envelope,
            check_type="scratch" if skip_publication else "remote_publish",
            base_ref=str(target_branch or "main"),
            expected_contract_checksum=expected_contract_checksum,
        )
        failure_terminal_class = receipt.failure_terminal_class
        payload = {
            "mode": "swarm-preflight",
            "receipt": receipt.to_dict(),
            "admission_gate": admission_gate.to_dict(),
            "failure_terminal_class": (
                failure_terminal_class.value if failure_terminal_class is not None else None
            ),
        }
    else:
        preflight_result = run_preflight(
            repo_root=repo_root,
            agent=str(getattr(args, "worker_model", "claude") or "claude"),
            base_ref=str(target_branch or "main"),
            skip_publication=skip_publication,
            contract_path=None,
        )
        payload = {"mode": "swarm-preflight", **preflight_result.to_dict()}
    if as_json:
        print(json.dumps(payload, indent=2))
    else:
        if contract_arg:
            receipt_payload = dict(payload.get("receipt", {}) or {})
            gate_payload = dict(payload.get("admission_gate", {}) or {})
            print(f"swarm preflight: {gate_payload.get('verdict', 'blocked')}")
            print(f"receipt_id={receipt_payload.get('receipt_id', '')}")
            print(f"check_type={receipt_payload.get('check_type', '')}")
            print(f"passed={receipt_payload.get('passed', False)}")
            print(f"expires_at={receipt_payload.get('expires_at', '')}")
            failure_terminal_text = str(payload.get("failure_terminal_class", "") or "").strip()
            if failure_terminal_text:
                print(f"failure_terminal_class={failure_terminal_text}")
        else:
            preflight_passed = bool(payload.get("passed", False))
            print(f"swarm preflight: {'ok' if preflight_passed else 'blocked'}")
            print(f"repo_root={payload['repo_root']}")
            print(f"agent={payload['agent']}")
            print(f"base_ref={payload['base_ref']}")
            print(f"branch={payload['branch']}")
            worker = payload.get("worker", {})
            checksum = str(worker.get("worker_contract_checksum", "")).strip()
            if checksum:
                print(f"worker_contract_checksum={checksum}")
    if contract_arg and payload["admission_gate"]["verdict"] != "pass":
        raise SystemExit(2)
    if not contract_arg and not bool(payload.get("passed", False)):
        raise SystemExit(2)
    return
