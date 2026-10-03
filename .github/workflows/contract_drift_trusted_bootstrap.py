"""Base-owned admission for the first Contract Drift accepted authority."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import stat
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

BOOTSTRAP_PATH = ".github/workflows/contract_drift_trusted_bootstrap.py"
WORKFLOW_PATH = ".github/workflows/contract-drift-trusted-bootstrap.yml"
LAUNCHER_PATH = ".github/workflows/contract_drift_trusted_launcher.py"
MANIFEST_PATH = ".github/workflows/contract-drift-trusted-bootstrap-manifest.json"
BASELINE_PATH = "scripts/baselines/contract_drift_inventory.json"
TRUSTED_SURFACE_FILES = (WORKFLOW_PATH, BOOTSTRAP_PATH, LAUNCHER_PATH)
ANALYZER_FILES = (
    "scripts/check_contract_drift_ratchet.py",
    "scripts/generate_contract_drift_inventory.py",
    "scripts/baselines/contract_drift_program.json",
)
ANALYZER_DIGESTS = (
    "716d360c5fd4bd5dc1b423005b5dcc4c7f2000e3d6f099a9bc0a314bd1fca4e1",
    "1528c5cda481d83e157b973be610e820e4750d5d4a5fa59924484137877a2bb4",
    "0328ec88fa524d8ff4259f6bf1dbeb0fd1514de18d2ac472914e39e4e688921c",
)
# Immutable source of the serial PR #9645 analyzer bundle. The prerequisite
# intentionally authenticates these future candidate bytes, not the older
# analyzer versions on its own base.
ANALYZER_SOURCE_SHA = "1722a6145c0c23a2c1c0d20be5ed1329bb01d666"
ANALYZER_FLAGS = ("-I", "-S", "-B")
ACCEPTED_CATEGORIES = (
    "python_sdk_drift",
    "routes_missing_in_spec",
    "routes_orphaned_in_spec",
    "sdk_missing_from_both",
    "typescript_sdk_drift",
)
AUTHORITY_FIELDS = frozenset(
    "active_inventory active_inventory_sha256 analyzer_bundle canonical_artifact_bindings "
    "canonical_artifacts categories manifest_sha256 publication schema transition".split()
)
EXPECTED_HISTORICAL_NONCONFORMING = [
    {
        "actor": "scarmani",
        "head_sha": "83a7c59169ea238e0439a27fbb80d3cb3ce7e916",
        "merge_sha": "14d1ef53e23c5466c0491ed93f72752944c78cd4",
        "merged_at": "2026-07-16T18:30:08Z",
        "pr": 9346,
    },
    {
        "actor": "scarmani",
        "head_sha": "aba6b14c94eca3a9c825b1a303ea67684d5f8daa",
        "merge_sha": "0b28f68b9f4d204ae14814169093723ea84c1364",
        "merged_at": "2026-07-16T20:00:49Z",
        "pr": 9320,
    },
]
SHA_RE = re.compile(r"[0-9a-f]{40}")
HERMETIC_LAUNCHER = (
    b"import hashlib,os,runpy,sys;p=__file__;assert "
    b"hashlib.sha256(open(p,'rb').read()).hexdigest()=="
    b"os.environ['CDG_EXECUTED_LAUNCHER_SHA256'];sys.path.insert(0,sys.argv.pop(1));"
    b"runpy.run_path(sys.argv.pop(1),run_name='__main__')"
)
EXPECTED_WORKFLOW_REF = (
    "synaptent/aragora/.github/workflows/contract-drift-trusted-bootstrap.yml@refs/heads/main"
)


class BootstrapError(ValueError): ...


@dataclass(frozen=True)
class ArtifactBinding:
    path: str
    schema: str
    sha256: str
    byte_length: int


@dataclass(frozen=True)
class RunProvenance:
    event_name: str
    repository: str
    run_attempt: int
    run_id: int
    workflow_ref: str


@dataclass(frozen=True)
class BootstrapPolicy:
    analyzer_digests: tuple[str, ...] = ANALYZER_DIGESTS
    analyzer_source_sha: str = ANALYZER_SOURCE_SHA
    artifact_bindings: tuple[ArtifactBinding, ...] = (
        ArtifactBinding(
            path="library/contract-drift-original-cohort-v1.json",
            schema="contract-drift-original-cohort-v1",
            sha256="565cd84a9a5d266f61b66bd7965e0a036e4817ef5fed32edb8c41a2dea6cc208",
            byte_length=1692125,
        ),
        ArtifactBinding(
            path="library/contract-drift-sdk-provenance-v1.json",
            schema="contract-drift-sdk-provenance-v1",
            sha256="21ae1c30200cda6df51dbca7053bbbbde6241ab78a73347b0fe5e4d2ed79f07f",
            byte_length=898099,
        ),
    )
    expected_head_sha: str | None = None
    transition_base_sha: str = "d5c9df5cea5719404b54c34fdb62a89daf65a92f"


def _sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _canonical(value: Any, terminal_lf: bool = True) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        + ("\n" if terminal_lf else "")
    ).encode()


def _duplicate_key_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise BootstrapError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _strict_json(raw: bytes, label: str) -> dict[str, Any]:
    try:
        value = json.loads(raw, object_pairs_hook=_duplicate_key_object)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise BootstrapError(f"{label} is not strict UTF-8 JSON") from exc
    if not isinstance(value, dict):
        raise BootstrapError(f"{label} must be a JSON object")
    return value


def _validate_run_provenance(provenance: RunProvenance) -> dict[str, Any]:
    if (
        provenance.event_name != "pull_request_target"
        or provenance.repository != "synaptent/aragora"
        or isinstance(provenance.run_id, bool)
        or not isinstance(provenance.run_id, int)
        or provenance.run_id <= 0
        or isinstance(provenance.run_attempt, bool)
        or not isinstance(provenance.run_attempt, int)
        or provenance.run_attempt <= 0
        or provenance.workflow_ref != EXPECTED_WORKFLOW_REF
    ):
        raise BootstrapError("workflow run provenance is not the trusted base workflow")
    return {
        "event_name": provenance.event_name,
        "repository": provenance.repository,
        "run_attempt": provenance.run_attempt,
        "run_id": provenance.run_id,
        "workflow_ref": provenance.workflow_ref,
    }


def _git(repo: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess[bytes]:
    proc = subprocess.run(
        ["git", "-C", str(repo), *args],
        check=False,
        capture_output=True,
    )
    if check and proc.returncode:
        message = proc.stderr.decode(errors="replace").strip()
        raise BootstrapError(f"git {' '.join(args)} failed: {message}")
    return proc


def _git_blob(repo: Path, sha: str, path: str) -> bytes:
    return _git(repo, "show", f"{sha}:{path}").stdout


def _resolve_pair(
    repo: Path,
    event_path: Path,
    base_sha: str,
    head_sha: str,
    policy: BootstrapPolicy,
) -> str:
    if not SHA_RE.fullmatch(base_sha) or not SHA_RE.fullmatch(head_sha) or base_sha == head_sha:
        raise BootstrapError("base and head must be distinct immutable 40-character SHAs")
    for label, sha in (("base", base_sha), ("head", head_sha)):
        resolved = _git(repo, "rev-parse", "--verify", f"{sha}^{{commit}}").stdout.decode().strip()
        if resolved != sha:
            raise BootstrapError(f"{label} SHA did not resolve exactly")
    event = _strict_json(event_path.read_bytes(), "event")
    pull = event.get("pull_request")
    repository = event.get("repository")
    if not isinstance(pull, dict) or not isinstance(repository, dict):
        raise BootstrapError("event is not a pull request")
    base = pull.get("base")
    head = pull.get("head")
    if not isinstance(base, dict) or not isinstance(head, dict):
        raise BootstrapError("event pull request refs are incomplete")
    repo_name = repository.get("full_name")
    base_repo = base.get("repo")
    head_repo = head.get("repo")
    if (
        base.get("sha") != base_sha
        or head.get("sha") != head_sha
        or base.get("ref") != "main"
        or not isinstance(repo_name, str)
        or not isinstance(base_repo, dict)
        or not isinstance(head_repo, dict)
        or base_repo.get("full_name") != repo_name
        or head_repo.get("full_name") != repo_name
    ):
        raise BootstrapError("event base/head repository or immutable refs do not match")
    if policy.expected_head_sha is not None and policy.expected_head_sha != head_sha:
        raise BootstrapError("event head does not match the admitted candidate head")
    return _git(repo, "rev-parse", f"{head_sha}^{{tree}}").stdout.decode().strip()


def _verify_trusted_surface(
    repo: Path,
    base_sha: str,
    head_sha: str,
    executed_bootstrap: Path,
    executed_analyzer_launcher: Path,
) -> dict[str, str]:
    manifest_raw = _git_blob(repo, base_sha, MANIFEST_PATH)
    manifest = _strict_json(manifest_raw, f"{base_sha}:{MANIFEST_PATH}")
    if manifest_raw != _canonical(manifest):
        raise BootstrapError("trusted bootstrap manifest is not canonical JSON")
    files = manifest.get("files")
    if (
        set(manifest) != {"files", "schema"}
        or manifest.get("schema") != "contract-drift-trusted-bootstrap-manifest-v1"
        or not isinstance(files, list)
        or [item.get("path") for item in files if isinstance(item, dict)]
        != list(TRUSTED_SURFACE_FILES)
    ):
        raise BootstrapError("trusted bootstrap manifest is not an exact closed surface")

    result: dict[str, str] = {}
    for item, path in zip(files, TRUSTED_SURFACE_FILES, strict=True):
        if not isinstance(item, dict) or set(item) != {"byte_length", "path", "sha256"}:
            raise BootstrapError(f"trusted bootstrap manifest binding is malformed: {path}")
        base_raw = _git_blob(repo, base_sha, path)
        if item.get("byte_length") != len(base_raw) or item.get("sha256") != _sha256(base_raw):
            raise BootstrapError(f"trusted bootstrap manifest digest mismatch: {path}")
        proposed = _git(repo, "show", f"{head_sha}:{path}", check=False)
        if proposed.returncode != 0 or proposed.stdout != base_raw:
            raise BootstrapError(f"proposed tree overrides trusted surface: {path}")
        result[path] = _sha256(base_raw)
        if path == BOOTSTRAP_PATH and executed_bootstrap.read_bytes() != base_raw:
            raise BootstrapError("executed trusted bootstrap differs from resolved base")
        if path == LAUNCHER_PATH and (
            base_raw != HERMETIC_LAUNCHER or executed_analyzer_launcher.read_bytes() != base_raw
        ):
            raise BootstrapError("executed trusted analyzer launcher bytes are not accepted")
    proposed_manifest = _git(repo, "show", f"{head_sha}:{MANIFEST_PATH}", check=False)
    if proposed_manifest.returncode != 0 or proposed_manifest.stdout != manifest_raw:
        raise BootstrapError(f"proposed tree overrides trusted surface: {MANIFEST_PATH}")
    result[MANIFEST_PATH] = _sha256(manifest_raw)
    return result


def _authority(repo: Path, sha: str) -> dict[str, Any] | None:
    baseline = _strict_json(_git_blob(repo, sha, BASELINE_PATH), f"{sha}:{BASELINE_PATH}")
    authority = baseline.get("accepted_authority")
    if authority is None:
        return None
    if not isinstance(authority, dict):
        raise BootstrapError("accepted authority must be an object")
    return authority


def _binding_dict(binding: ArtifactBinding) -> dict[str, Any]:
    return {
        "byte_length": binding.byte_length,
        "path": binding.path,
        "sha256": binding.sha256,
    }


def _validate_first_authority(
    repo: Path,
    head_sha: str,
    authority: dict[str, Any],
    policy: BootstrapPolicy,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    if set(authority) != AUTHORITY_FIELDS:
        raise BootstrapError("accepted authority fields are not exact")
    manifest = {key: value for key, value in authority.items() if key != "manifest_sha256"}
    if authority.get("manifest_sha256") != _sha256(_canonical(manifest, terminal_lf=False)):
        raise BootstrapError("accepted authority manifest digest mismatch")
    if authority.get("schema") != "contract-drift-accepted-authority-v1" or authority.get(
        "categories"
    ) != list(ACCEPTED_CATEGORIES):
        raise BootstrapError("accepted authority schema or categories mismatch")
    publication = authority.get("publication")
    transition = authority.get("transition")
    if publication != {
        "authority": "future-immutable-github-release-capsule",
        "status": "pending-merge",
    }:
        raise BootstrapError("first authority publication is not pending external acceptance")
    if (
        not isinstance(transition, dict)
        or set(transition)
        != {
            "accepted_transition_head",
            "base_sha",
            "historical_nonconforming",
            "kind",
        }
        or transition.get("kind") != "authority_transition"
        or transition.get("base_sha") != policy.transition_base_sha
        or transition.get("historical_nonconforming") != EXPECTED_HISTORICAL_NONCONFORMING
        or transition.get("accepted_transition_head") != "bound-by-release-capsule"
    ):
        if (
            isinstance(transition, dict)
            and transition.get("base_sha") != policy.transition_base_sha
        ):
            raise BootstrapError("first authority transition base mismatch")
        raise BootstrapError("first authority transition attempts self-authorization")
    active_inventory = authority.get("active_inventory")
    if not isinstance(active_inventory, list) or authority.get(
        "active_inventory_sha256"
    ) != _sha256(_canonical(active_inventory, terminal_lf=False)):
        raise BootstrapError("accepted authority active inventory digest mismatch")

    expected_bindings = [_binding_dict(binding) for binding in policy.artifact_bindings]
    if authority.get("canonical_artifact_bindings") != expected_bindings:
        raise BootstrapError("canonical artifact bindings differ from base-owned descriptors")
    artifacts = authority.get("canonical_artifacts")
    if not isinstance(artifacts, dict) or set(artifacts) != {"original_cohort", "sdk_provenance"}:
        raise BootstrapError("canonical comparison artifact set is not exact")
    comparison: list[dict[str, Any]] = []
    for key, binding in zip(
        ("original_cohort", "sdk_provenance"), policy.artifact_bindings, strict=True
    ):
        artifact = artifacts[key]
        if not isinstance(artifact, dict):
            raise BootstrapError(f"canonical comparison artifact missing: {binding.schema}")
        raw = _canonical(artifact)
        if len(raw) != binding.byte_length or _sha256(raw) != binding.sha256:
            raise BootstrapError(f"canonical comparison artifact mismatch: {binding.schema}")
        comparison.append(_binding_dict(binding) | {"schema": binding.schema})

    bundle = authority.get("analyzer_bundle")
    if not isinstance(bundle, dict) or set(bundle) != {
        "dependencies",
        "files",
        "interpreter_flags",
        "launcher_sha256",
        "schema",
    }:
        raise BootstrapError("accepted analyzer bundle contract is not exact")
    if (
        bundle.get("schema") != "contract-drift-analyzer-bundle-v1"
        or bundle.get("dependencies") != []
        or bundle.get("interpreter_flags") != list(ANALYZER_FLAGS)
        or bundle.get("launcher_sha256") != _sha256(HERMETIC_LAUNCHER)
    ):
        raise BootstrapError("accepted analyzer launcher or dependency contract mismatch")
    files = bundle.get("files")
    if (
        not isinstance(files, list)
        or len(files) != len(ANALYZER_FILES)
        or [item.get("path") for item in files if isinstance(item, dict)] != list(ANALYZER_FILES)
    ):
        raise BootstrapError("accepted analyzer bundle file set is not exact")
    if not SHA_RE.fullmatch(policy.analyzer_source_sha):
        raise BootstrapError("base-owned analyzer source ref is not immutable")
    resolved_source = (
        _git(repo, "rev-parse", "--verify", f"{policy.analyzer_source_sha}^{{commit}}")
        .stdout.decode()
        .strip()
    )
    if resolved_source != policy.analyzer_source_sha:
        raise BootstrapError("base-owned analyzer source ref did not resolve exactly")
    for item, path, digest in zip(files, ANALYZER_FILES, policy.analyzer_digests, strict=True):
        if (
            not isinstance(item, dict)
            or set(item) != {"path", "sha256"}
            or item.get("sha256") != digest
            or _sha256(_git_blob(repo, policy.analyzer_source_sha, path)) != digest
            or _sha256(_git_blob(repo, head_sha, path)) != digest
        ):
            raise BootstrapError(f"candidate analyzer digest mismatch: {path}")
    return bundle, comparison


def _write_comparison_signal(
    output_dir: Path,
    base_sha: str,
    head_sha: str,
    proposed_tree_sha: str,
    trusted_surface: dict[str, str],
    authority: dict[str, Any],
    bundle: dict[str, Any],
    comparison: list[dict[str, Any]],
    workflow_run: dict[str, Any],
) -> Path:
    payload = {
        "accepted_authority_sha256": _sha256(_canonical(authority)),
        "analyzer_bundle_sha256": _sha256(_canonical(bundle, terminal_lf=False)),
        "candidate_head_sha": head_sha,
        "canonical_comparison": comparison,
        "proposed_tree_sha": proposed_tree_sha,
        "schema": "contract-drift-first-transition-comparison-v1",
        "status": "authenticated",
        "trusted_base_sha": base_sha,
        "trusted_surface": trusted_surface,
        "workflow_run": workflow_run,
    }
    envelope = {
        "payload": payload,
        "signal_sha256": _sha256(_canonical(payload)),
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / "first-transition-comparison.json"
    path.write_bytes(_canonical(envelope))
    return path


def _authenticate_comparison_signal(
    path: Path,
    *,
    base_sha: str,
    head_sha: str,
    workflow_run: dict[str, Any],
) -> str:
    if not path.is_file():
        raise BootstrapError("authenticated comparison signal is missing")
    envelope = _strict_json(path.read_bytes(), "comparison signal")
    payload = envelope.get("payload")
    signal_sha = envelope.get("signal_sha256")
    if (
        not isinstance(payload, dict)
        or not isinstance(signal_sha, str)
        or signal_sha != _sha256(_canonical(payload))
        or payload.get("candidate_head_sha") != head_sha
        or payload.get("trusted_base_sha") != base_sha
        or payload.get("workflow_run") != workflow_run
        or payload.get("status") != "authenticated"
    ):
        raise BootstrapError("authenticated comparison signal is invalid")
    return signal_sha


def _materialize_bundle(repo: Path, head_sha: str, destination: Path) -> Path:
    for relative in ANALYZER_FILES:
        target = destination / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(_git_blob(repo, head_sha, relative))
        target.chmod(stat.S_IRUSR | stat.S_IRGRP | stat.S_IROTH)
    return destination / ANALYZER_FILES[0]


def _execute_candidate(
    repo: Path,
    base_sha: str,
    head_sha: str,
    bundle: dict[str, Any],
    signal_path: Path,
    temporary_root: Path,
    trusted_launcher: Path,
    workflow_run: dict[str, Any],
) -> tuple[int, dict[str, Any], str]:
    signal_sha = _authenticate_comparison_signal(
        signal_path,
        base_sha=base_sha,
        head_sha=head_sha,
        workflow_run=workflow_run,
    )
    _materialize_bundle(repo, head_sha, temporary_root)
    launcher_target = temporary_root / LAUNCHER_PATH
    launcher_target.parent.mkdir(parents=True, exist_ok=True)
    launcher_target.write_bytes(trusted_launcher.read_bytes())
    launcher_target.chmod(stat.S_IRUSR | stat.S_IRGRP | stat.S_IROTH)
    bundle_sha = _sha256(_canonical(bundle, terminal_lf=False))
    env = {
        "CDG_AUTHORITY_ROOT": str(temporary_root),
        "CDG_EXECUTED_LAUNCHER_SHA256": bundle["launcher_sha256"],
        "CDG_FIRST_TRANSITION_COMPARISON_SHA256": signal_sha,
        "CDG_TRUSTED_BUNDLE": bundle_sha,
        "HOME": str(temporary_root),
        "PATH": "/usr/bin:/bin",
    }
    command = [
        sys.executable,
        *ANALYZER_FLAGS,
        LAUNCHER_PATH,
        str(temporary_root),
        "scripts/check_contract_drift_ratchet.py",
        "--mode",
        "pr",
        "--trusted-bundle",
        bundle_sha,
        "--base-ref",
        base_sha,
        "--head-ref",
        head_sha,
        "--repo-root",
        str(repo),
        "--inventory",
        BASELINE_PATH,
        "--json",
    ]
    proc = subprocess.run(
        command,
        cwd=temporary_root,
        env=env,
        capture_output=True,
        text=True,
    )
    if proc.returncode not in {0, 1}:
        raise BootstrapError(f"candidate analyzer execution failed: {proc.stderr.strip()}")
    try:
        result = json.loads(proc.stdout)
    except json.JSONDecodeError as exc:
        raise BootstrapError("candidate analyzer did not emit JSON") from exc
    if not isinstance(result, dict):
        raise BootstrapError("candidate analyzer result must be an object")
    return proc.returncode, result, signal_sha


def _write_admission_receipt(
    output_dir: Path,
    *,
    analysis: dict[str, Any],
    base_sha: str,
    head_sha: str,
    returncode: int,
    signal_sha: str,
    workflow_run: dict[str, Any],
) -> Path:
    analysis_path = output_dir / "trusted-bootstrap-analysis.json"
    analysis_path.write_bytes(_canonical(analysis))
    payload = {
        "analysis_path": analysis_path.name,
        "analysis_sha256": _sha256(analysis_path.read_bytes()),
        "candidate_head_sha": head_sha,
        "comparison_signal_sha256": signal_sha,
        "schema": "contract-drift-trusted-bootstrap-admission-v1",
        "status": "pass" if returncode == 0 else "analyzer-rejected",
        "trusted_base_sha": base_sha,
        "workflow_run": workflow_run,
    }
    envelope = {
        "payload": payload,
        "receipt_sha256": _sha256(_canonical(payload)),
    }
    path = output_dir / "trusted-bootstrap-admission.json"
    path.write_bytes(_canonical(envelope))
    return path


def _write_not_first_receipt(
    output_dir: Path,
    *,
    base_sha: str,
    head_sha: str,
    workflow_run: dict[str, Any],
) -> Path:
    payload = {
        "candidate_head_sha": head_sha,
        "schema": "contract-drift-trusted-bootstrap-admission-v1",
        "status": "not-first-transition",
        "trusted_base_sha": base_sha,
        "workflow_run": workflow_run,
    }
    envelope = {
        "payload": payload,
        "receipt_sha256": _sha256(_canonical(payload)),
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / "trusted-bootstrap-admission.json"
    path.write_bytes(_canonical(envelope))
    return path


def _write_no_authority_receipt(
    output_dir: Path,
    *,
    base_sha: str,
    head_sha: str,
    workflow_run: dict[str, Any],
) -> Path:
    payload = {
        "candidate_head_sha": head_sha,
        "schema": "contract-drift-trusted-bootstrap-admission-v1",
        "status": "no-authority-proposed",
        "trusted_base_sha": base_sha,
        "workflow_run": workflow_run,
    }
    envelope = {
        "payload": payload,
        "receipt_sha256": _sha256(_canonical(payload)),
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / "trusted-bootstrap-admission.json"
    path.write_bytes(_canonical(envelope))
    return path


def run_bootstrap(
    *,
    repo: Path,
    event_path: Path,
    base_sha: str,
    head_sha: str,
    output_dir: Path,
    policy: BootstrapPolicy = BootstrapPolicy(),
    executed_launcher: Path | None = None,
    run_provenance: RunProvenance | None = None,
) -> dict[str, Any]:
    if sys.version_info < (3, 11):
        raise BootstrapError("trusted bootstrap requires Python 3.11 or newer")
    repo = repo.resolve()
    if run_provenance is None:
        raise BootstrapError("workflow run provenance is required")
    workflow_run = _validate_run_provenance(run_provenance)
    proposed_tree_sha = _resolve_pair(repo, event_path, base_sha, head_sha, policy)
    bootstrap_path = (executed_launcher or Path(__file__)).resolve()
    analyzer_launcher = bootstrap_path.with_name(Path(LAUNCHER_PATH).name)
    trusted_surface = _verify_trusted_surface(
        repo,
        base_sha,
        head_sha,
        bootstrap_path,
        analyzer_launcher,
    )
    if _authority(repo, base_sha) is not None:
        _write_not_first_receipt(
            output_dir,
            base_sha=base_sha,
            head_sha=head_sha,
            workflow_run=workflow_run,
        )
        return {
            "candidate_head_sha": head_sha,
            "status": "not-first-transition",
            "trusted_base_sha": base_sha,
        }
    authority = _authority(repo, head_sha)
    if authority is None:
        _write_no_authority_receipt(
            output_dir,
            base_sha=base_sha,
            head_sha=head_sha,
            workflow_run=workflow_run,
        )
        return {
            "candidate_head_sha": head_sha,
            "status": "no-authority-proposed",
            "trusted_base_sha": base_sha,
        }
    bundle, comparison = _validate_first_authority(repo, head_sha, authority, policy)
    signal_path = _write_comparison_signal(
        output_dir,
        base_sha,
        head_sha,
        proposed_tree_sha,
        trusted_surface,
        authority,
        bundle,
        comparison,
        workflow_run,
    )
    with tempfile.TemporaryDirectory(prefix="cdg-bootstrap-") as raw:
        returncode, analysis, signal_sha = _execute_candidate(
            repo,
            base_sha,
            head_sha,
            bundle,
            signal_path,
            Path(raw),
            analyzer_launcher,
            workflow_run,
        )
    _write_admission_receipt(
        output_dir,
        analysis=analysis,
        base_sha=base_sha,
        head_sha=head_sha,
        returncode=returncode,
        signal_sha=signal_sha,
        workflow_run=workflow_run,
    )
    return {
        "analysis": analysis,
        "candidate_head_sha": head_sha,
        "comparison_signal_sha256": signal_sha,
        "status": "pass" if returncode == 0 else "analyzer-rejected",
        "trusted_base_sha": base_sha,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, required=True)
    parser.add_argument("--event", type=Path, required=True)
    parser.add_argument("--base-sha", required=True)
    parser.add_argument("--head-sha", required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--event-name", required=True)
    parser.add_argument("--repository", required=True)
    parser.add_argument("--run-attempt", type=int, required=True)
    parser.add_argument("--run-id", type=int, required=True)
    parser.add_argument("--workflow-ref", required=True)
    args = parser.parse_args()
    try:
        result = run_bootstrap(
            repo=args.repo,
            event_path=args.event,
            base_sha=args.base_sha,
            head_sha=args.head_sha,
            output_dir=args.output_dir,
            run_provenance=RunProvenance(
                event_name=args.event_name,
                repository=args.repository,
                run_attempt=args.run_attempt,
                run_id=args.run_id,
                workflow_ref=args.workflow_ref,
            ),
        )
    except (BootstrapError, OSError) as exc:
        print(f"::error::{exc}", file=sys.stderr)  # noqa: T201
        return 2
    print(json.dumps(result, indent=2, sort_keys=True))  # noqa: T201
    return 0 if result["status"] in {"pass", "not-first-transition", "no-authority-proposed"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
