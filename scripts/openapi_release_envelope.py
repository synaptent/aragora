#!/usr/bin/env python3
"""Read-only OpenAPI release-envelope builder and verifier (FIX-RT-017).

Expiring, fixed-name Actions artifacts are not durable contract evidence. The
``envelope`` job in ``.github/workflows/openapi.yml`` binds the exact
run-level payload bytes of the run/SHA-bound (attempt-free)
``openapi-spec-<run_id>-<head_sha>`` artifact into an immutable GitHub
release at the exact-SHA tag ``openapi-envelope-<head_sha>``, attests the
exact assets with the pinned ``actions/attest`` signer, and verifies the
whole chain with this helper.

This module never mutates remote state. ``build`` writes deterministic
envelope bytes (canonical compact sorted-key JSON manifest plus an
``sha256sum --check --strict``-compatible checksums file) to a local
directory; ``preflight`` proves everything that must hold before the
irreversible publication (local bytes, attestations, unused tag, capability,
main still at the bound head — movement is a free restart here); ``verify``
re-authenticates a published envelope release, its assets, its attestations
(``--signer-workflow`` + ``--source-digest``), and the passing rule-suite
record for the bound head, re-querying workflow/run/artifact/main before and
after with restart-on-movement semantics (main-only movement after
publication is recorded as supersession, never a strand); ``dry-run`` proves
deterministic byte construction from checked-in fixture bytes with no
network access. Admin-gated reads (rule suites, the immutability setting)
degrade under ``--admin-reads report`` on a true HTTP 403 capability gap
and on the admin-gated HTTP 404 mapping (the workflow's GITHUB_TOKEN sees a
hidden settings surface, indistinguishable in-run from a disabled setting);
every readable answer keeps full fail-closed semantics, and the operator's
``required`` mode enforces the reads outright.

Exit codes (CDG status vocabulary): 0 pass, 1 fail (verification
contradiction), 2 blocked (publication/attestation/rule-suite not yet
visible), 3 movement (selection moved; restart verification). Retries are
bounded, deterministic, and blocked-class only: ``preflight`` retries its
read-only pre-publish attestation checks on the 5/10/20s ladder before
concluding blocked, and only blocked post-publication verification may be
retried in place, with the same original identity and envelope. Fail,
movement, and unexpected errors are terminal; build, attestation (signing),
publication, and every other phase stay outside any retry.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

WORKFLOW_PATH = ".github/workflows/openapi.yml"
ENVELOPE_SCHEMA = "aragora/openapi-release-envelope@v1"
TAG_PREFIX = "openapi-envelope-"
MANIFEST_NAME = "manifest.json"
CHECKSUMS_NAME = "checksums.txt"
ARTIFACT_PREFIX = "openapi-spec-"
API_VERSION_HEADER = "X-GitHub-Api-Version: 2022-11-28"

EXIT_PASS = 0
EXIT_FAIL = 1
EXIT_BLOCKED = 2
EXIT_MOVEMENT = 3

# The stderr shapes `_checked_verification` keys blocked-vs-fail on (see
# `_is_absent_attestation_stderr`). cmd_preflight validates them against the
# live runner gh (blocked-marker probe) so the detection and the runner's
# actual error shape can never drift apart silently.
NO_ATTESTATIONS_MARKER = "no attestations"
ATTESTATIONS_API_PATH_MARKER = "/attestations/sha256:"
BLOCKED_MARKER_PROBE_NAME = "blocked-marker-probe.bin"
# Transient transport shapes for `_probe_transient_class` (observed live on
# gh 2.96.0, 2026-08-18): after verifier initialization a dead network
# surfaces as Go net dial/lookup text on the attestations-API read, so a
# connectivity retry genuinely clears this class. Message-only
# classification; never an exit-class input.
PROBE_NETWORK_STDERR_MARKERS = (
    "dial tcp",
    "proxyconnect",
    "no such host",
    "connection refused",
    "connection reset",
    "i/o timeout",
    "tls handshake",
    "context deadline exceeded",
    "temporary failure in name resolution",
)
# A dead Sigstore verifier initialization, pinned live 2026-08-19 with the
# byte-exact production argv (gh 2.96.0): gh swallows the underlying cause,
# so unreachable TUF surfaces, TLS interception toward them, and a stale or
# corrupt local TUF cache (`~/.cache/gh/.sigstore`) all emit this same bare
# line. The corrupt-cache case reproduces it even with full connectivity
# (gh never re-bootstraps the cache), so unlike the network class this
# wording must never promise that a connectivity retry clears it.
PROBE_VERIFIER_INIT_STDERR_MARKERS = ("no valid sigstore verifiers could be initialized",)
# Corporate-MITM trust failures on the attestations-API read, pinned live
# 2026-08-18 with the byte-exact production argv (gh 2.96.0). The crypto/tls
# umbrella prefix is load-bearing: an untrusted interceptor reports unknown
# authority even when its certificate is expired, so a `certificate has
# expired` literal can never be pinned against a MITM; the umbrella covers
# that trusted-but-expired shape instead. Kept separate from the network
# markers because a trust failure is a persistent runner configuration
# state, so its wording must not promise that a retry clears it.
PROBE_TLS_TRUST_STDERR_MARKERS = (
    "tls: failed to verify certificate",
    "x509: certificate signed by unknown authority",
)
# Pre-publish attestation lag ladder; mirrors the workflow's post-publish
# retry step (4 attempts, 5/10/20s waits), blocked class only.
PREPUBLISH_RETRY_DELAYS = (5, 10, 20)

_sleep = time.sleep

_FULL_SHA = re.compile(r"^[0-9a-f]{40}$")
_REPOSITORY = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
_ASSET_NAME = re.compile(r"^[A-Za-z0-9._-]+$")

# Post-verification re-query rule (VAL-CDG-012): if any of these move between
# the opening and closing snapshots, the whole selection restarts.
# `run_attempt`/`conclusion` describe the BOUND attempt's immutable record;
# `latest_run_attempt` tracks the run-level object so a re-run landing DURING
# a verification window restarts it, while a re-run that settled before the
# window leaves the bound attempt verifiable (no permanent wedge).
SELECTION_KEYS = (
    "main_sha",
    "workflow_id",
    "run_id",
    "run_attempt",
    "latest_run_attempt",
    "conclusion",
    "artifact_id",
    "artifact_size",
)


class Blocked(RuntimeError):
    """Publication, attestation, or rule-suite record is not visible yet."""


class Forbidden(Blocked):
    """The token cannot read an admin-gated surface (rule suites, release
    immutability setting); verification is blocked, not contradicted."""


class Movement(RuntimeError):
    """The bound selection moved during verification; restart required."""


def sha256_hexdigest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def canonical_json_bytes(value: Any) -> bytes:
    """Compact, sorted-key, ASCII JSON with one trailing newline: the only
    manifest serialization the envelope accepts, so identical content can
    never produce distinct release bytes."""
    return (
        json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":")) + "\n"
    ).encode("ascii")


def make_identity(
    *,
    repository: str,
    head_sha: str,
    run_id: int,
    run_attempt: int,
    artifact_name: str,
) -> dict[str, Any]:
    """Validate and freeze the execution identity every envelope operation is
    bound to. The artifact name must be exactly run- and SHA-bound; a fixed or
    foreign name is rejected before any bytes are touched. The attempt is
    deliberately NOT part of the name (re-running only a failed dependent job
    increments the run attempt while the artifact keeps its original name);
    attempt binding lives in the manifest and the movement plane instead."""
    if not isinstance(repository, str) or not _REPOSITORY.fullmatch(repository):
        raise ValueError(f"repository {repository!r} is not owner/name")
    if not isinstance(head_sha, str) or not _FULL_SHA.fullmatch(head_sha):
        raise ValueError("head SHA must be a full lowercase 40-hex commit SHA")
    for label, value in (("run id", run_id), ("run attempt", run_attempt)):
        if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
            raise ValueError(f"{label} must be a positive integer")
    expected_name = f"{ARTIFACT_PREFIX}{run_id}-{head_sha}"
    if artifact_name != expected_name:
        raise ValueError(
            f"artifact name {artifact_name!r} is not run/SHA-bound (expected {expected_name!r})"
        )
    return {
        "repository": repository,
        "head_sha": head_sha,
        "run_id": run_id,
        "run_attempt": run_attempt,
        "artifact_name": artifact_name,
        "tag": TAG_PREFIX + head_sha,
    }


def _checksum_bytes(digests: dict[str, str]) -> bytes:
    lines = [f"{digest}  {name}\n" for name, digest in sorted(digests.items())]
    return "".join(lines).encode("ascii")


def build_envelope(payload_files: dict[str, bytes], identity: dict[str, Any]) -> dict[str, bytes]:
    """Deterministically derive the complete release asset set (payload bytes
    passed through untouched, plus manifest.json and checksums.txt) from the
    exact run-level payload bytes and the execution identity."""
    if not payload_files:
        raise ValueError("release envelope requires at least one payload file")
    entries: list[dict[str, Any]] = []
    payload_by_name: dict[str, bytes] = {}
    for rel_path in sorted(payload_files):
        pure = Path(rel_path)
        if pure.is_absolute() or ".." in pure.parts:
            raise ValueError(f"payload path {rel_path!r} escapes the payload root")
        name = pure.name
        if not _ASSET_NAME.fullmatch(name):
            raise ValueError(f"payload file name {name!r} is not release-asset safe")
        if name in (MANIFEST_NAME, CHECKSUMS_NAME):
            raise ValueError(f"payload file name {name!r} collides with an envelope asset")
        if name in payload_by_name:
            raise ValueError(f"duplicate payload basename {name!r}")
        data = payload_files[rel_path]
        if not data:
            raise ValueError(f"payload file {rel_path!r} is empty")
        payload_by_name[name] = data
        entries.append(
            {
                "byte_length": len(data),
                "name": name,
                "path": Path(rel_path).as_posix(),
                "sha256": sha256_hexdigest(data),
            }
        )
    manifest = {
        "artifact_name": identity["artifact_name"],
        "head_sha": identity["head_sha"],
        "payload_assets": entries,
        "repository": identity["repository"],
        "run_attempt": identity["run_attempt"],
        "schema": ENVELOPE_SCHEMA,
        "tag": identity["tag"],
        "workflow_path": WORKFLOW_PATH,
        "workflow_run_id": identity["run_id"],
    }
    manifest_bytes = canonical_json_bytes(manifest)
    digests = {entry["name"]: entry["sha256"] for entry in entries}
    digests[MANIFEST_NAME] = sha256_hexdigest(manifest_bytes)
    assets = dict(payload_by_name)
    assets[MANIFEST_NAME] = manifest_bytes
    assets[CHECKSUMS_NAME] = _checksum_bytes(digests)
    return assets


def verify_envelope_assets(assets: dict[str, bytes], identity: dict[str, Any]) -> dict[str, Any]:
    """Fail-closed verification of exact downloaded asset bytes against the
    execution identity: canonical manifest bytes, identity binding, exact
    asset set, per-asset digests, and the checksums file itself."""
    for required in (MANIFEST_NAME, CHECKSUMS_NAME):
        if required not in assets:
            raise ValueError(f"envelope asset {required!r} is missing")
    manifest_bytes = assets[MANIFEST_NAME]
    try:
        manifest = json.loads(manifest_bytes.decode("ascii"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"manifest bytes are not parseable canonical JSON: {exc}") from exc
    if not isinstance(manifest, dict):
        raise ValueError("manifest is not a JSON object")
    if canonical_json_bytes(manifest) != manifest_bytes:
        raise ValueError("manifest bytes are not in canonical form")
    bindings = {
        "schema": ENVELOPE_SCHEMA,
        "repository": identity["repository"],
        "head_sha": identity["head_sha"],
        "workflow_run_id": identity["run_id"],
        "run_attempt": identity["run_attempt"],
        "artifact_name": identity["artifact_name"],
        "tag": identity["tag"],
        "workflow_path": WORKFLOW_PATH,
    }
    for field, expected in bindings.items():
        if manifest.get(field) != expected:
            raise ValueError(
                f"manifest field {field!r} is {manifest.get(field)!r}, not the bound {expected!r}"
            )
    entries = manifest.get("payload_assets")
    if not isinstance(entries, list) or not entries:
        raise ValueError("manifest lists no payload assets")
    digests: dict[str, str] = {}
    for entry in entries:
        if not isinstance(entry, dict):
            raise ValueError("manifest payload asset entry is not an object")
        name = entry.get("name")
        if not isinstance(name, str) or name in digests or name in (MANIFEST_NAME, CHECKSUMS_NAME):
            raise ValueError(f"manifest payload asset name {name!r} is invalid or duplicated")
        if name not in assets:
            raise ValueError(f"payload asset {name!r} is missing from the release")
        data = assets[name]
        size = entry.get("byte_length")
        if isinstance(size, bool) or not isinstance(size, int) or size <= 0 or size != len(data):
            raise ValueError(f"payload asset {name!r} byte length contradicts its exact bytes")
        digest = entry.get("sha256")
        if digest != sha256_hexdigest(data):
            raise ValueError(f"payload asset {name!r} bytes contradict the manifest digest")
        digests[name] = str(digest)
    expected_assets = set(digests) | {MANIFEST_NAME, CHECKSUMS_NAME}
    if set(assets) != expected_assets:
        raise ValueError(
            f"release asset set {sorted(assets)} does not equal the manifest set {sorted(expected_assets)}"
        )
    digests[MANIFEST_NAME] = sha256_hexdigest(manifest_bytes)
    if assets[CHECKSUMS_NAME] != _checksum_bytes(digests):
        raise ValueError("checksums.txt contradicts the recomputed asset digests")
    return manifest


def release_digest_set(assets: dict[str, bytes]) -> set[str]:
    """SHA-256 digests of every published asset's exact bytes: the
    ``release_digests`` plane a run-level artifact payload must bind into."""
    return {sha256_hexdigest(data) for data in assets.values()}


def selection_is_stable(before: dict[str, Any], after: dict[str, Any]) -> bool:
    for key in SELECTION_KEYS:
        if key not in before or key not in after:
            raise ValueError(f"selection snapshot is missing {key!r}")
        if before[key] != after[key]:
            return False
    return True


def movement_disposition(before: dict[str, Any], after: dict[str, Any]) -> str:
    """Classify movement between two selection snapshots.

    ``restart``: the bound execution's own provenance moved (workflow, run,
    attempt, conclusion, or artifact) — verification must restart.
    ``superseded``: only main advanced past the bound head. A published
    immutable capsule stays byte-valid for its exact SHA; failing here after
    publication would strand it, so callers record supersession instead
    (before publication a restart is still free and callers restart).
    ``stable``: nothing moved.
    """
    if selection_is_stable(before, after):
        return "stable"
    moved = {key for key in SELECTION_KEYS if before[key] != after[key]}
    if moved == {"main_sha"}:
        return "superseded"
    return "restart"


def attestation_verify_argv(
    asset_path: str, *, repository: str, head_sha: str, signer_workflow: str
) -> list[str]:
    return [
        "gh",
        "attestation",
        "verify",
        asset_path,
        "-R",
        repository,
        "--signer-workflow",
        signer_workflow,
        "--source-digest",
        head_sha,
        "--format",
        "json",
    ]


def release_verify_argv(tag: str, *, repository: str) -> list[str]:
    return ["gh", "release", "verify", tag, "-R", repository, "--format", "json"]


def release_verify_asset_argv(tag: str, asset_path: str, *, repository: str) -> list[str]:
    return ["gh", "release", "verify-asset", tag, asset_path, "-R", repository, "--format", "json"]


_READ_ONLY_GH_ACTIONS = {
    ("api",),
    ("attestation", "verify"),
    ("release", "download"),
    ("release", "verify"),
    ("release", "verify-asset"),
    ("release", "view"),
    ("run", "list"),
    ("run", "view"),
}
_GH_API_WRITE_FLAGS = {"-f", "-F", "--field", "--raw-field", "--input"}


def require_read_only_argv(argv: list[str]) -> None:
    """Reject any subprocess invocation that could mutate remote state. The
    helper's contract is read-only verification; publication belongs to the
    workflow's own reviewed steps."""
    if not argv or Path(argv[0]).name != "gh":
        raise ValueError(f"only read-only gh invocations are allowed, not {argv!r}")
    if len(argv) < 2:
        raise ValueError("gh invocation names no subcommand")
    group = argv[1]
    if group == "api":
        index = 2
        while index < len(argv):
            item = argv[index]
            if item in {"-X", "--method"}:
                if index + 1 >= len(argv) or argv[index + 1].upper() != "GET":
                    raise ValueError("gh api may only issue GET requests")
                index += 2
                continue
            # pflag also accepts attached shorthand (-XPOST, -fk=v, -Fk=v),
            # so prefix forms must be screened, not just separated flags.
            if item.startswith("-X") and item != "-X":
                if item[2:].upper() != "GET":
                    raise ValueError("gh api may only issue GET requests")
                index += 1
                continue
            if item.startswith("--method=") and item.split("=", 1)[1].upper() != "GET":
                raise ValueError("gh api may only issue GET requests")
            if (
                item in _GH_API_WRITE_FLAGS
                or item.startswith("--field=")
                or item.startswith("--raw-field=")
                or item.startswith("--input=")
                or (item.startswith("-f") and item != "-f")
                or (item.startswith("-F") and item != "-F")
            ):
                raise ValueError("gh api write-shaped flags are rejected")
            index += 1
        return
    action = (group, argv[2] if len(argv) > 2 else "")
    if action not in _READ_ONLY_GH_ACTIONS:
        raise ValueError(f"mutating or unsupported gh action rejected: {' '.join(action)}")


def _run_gh(argv: list[str]) -> subprocess.CompletedProcess[bytes]:
    require_read_only_argv(argv)
    # The Tier-4 authority-closure scanner forbids dynamic subprocess
    # commands, so the executed command is rebuilt around the literal program
    # name. That is only byte-identical to the caller's argv when argv[0] is
    # exactly "gh"; path forms (accepted by the basename guard above) would
    # silently execute a different program token and are rejected instead.
    if argv[0] != "gh":
        raise ValueError(f"gh must be invoked by bare program name, not {argv[0]!r}")
    return subprocess.run(["gh", *argv[1:]], capture_output=True, check=False)


def _gh_api_json(endpoint: str, *, paginate: bool = False, admin_gated: bool = False) -> Any:
    argv = ["gh", "api", "-H", API_VERSION_HEADER, endpoint]
    if paginate:
        argv += ["--paginate", "--slurp"]
    completed = _run_gh(argv)
    if completed.returncode != 0:
        stderr = completed.stderr.decode("utf-8", "replace").strip()
        if "HTTP 404" in stderr:
            if admin_gated:
                # Admin-gated settings surfaces exist for every repository
                # and GitHub hides them behind 404 (not 403) from tokens
                # without Administration:read, so 404 here is a capability
                # gap, not an absent resource.
                raise Forbidden(f"{endpoint} is hidden from this token: {stderr}")
            raise Blocked(f"{endpoint} is not visible: {stderr}")
        if "HTTP 403" in stderr:
            raise Forbidden(f"{endpoint} is not readable by this token: {stderr}")
        raise RuntimeError(f"gh api {endpoint} failed: {stderr}")
    return json.loads(completed.stdout)


def _is_absent_attestation_stderr(stderr: str, marker: str) -> bool:
    """Both shapes gh uses for an absent (or not-yet-propagated) attestation:
    the textual marker family, and the raw attestations-API HTTP 404 that
    newer gh emits instead (2.96.0, observed live 2026-08-18). The 404 is
    scoped to the attestations endpoint so a missing release or any other
    404 stays a readable contradiction."""
    lowered = stderr.lower()
    if marker in lowered:
        return True
    return "http 404" in lowered and ATTESTATIONS_API_PATH_MARKER in lowered


def _probe_transient_class(stderr: str) -> str | None:
    """Message-only hint for a probe stderr that matched no absent-attestation
    shape: an HTTP 403 answer, a TLS certificate-verification failure, a dead
    Sigstore verifier initialization, or a network transport death never
    carried a verification verdict, so attributing it to marker drift would
    misdirect the operator. Anything unrecognized is genuine drift, and the
    caller's fail-closed blocked exit is identical for every class."""
    lowered = stderr.lower()
    if "http 403" in lowered:
        return "http-403"
    if any(marker in lowered for marker in PROBE_TLS_TRUST_STDERR_MARKERS):
        return "tls-trust"
    # Before the network markers: gh currently swallows the verifier-init
    # cause, but a gh that starts appending it (dial/TLS text) must keep the
    # no-transience classification instead of degrading to the network
    # class's retry-on-connectivity promise.
    if any(marker in lowered for marker in PROBE_VERIFIER_INIT_STDERR_MARKERS):
        return "verifier-init"
    if any(marker in lowered for marker in PROBE_NETWORK_STDERR_MARKERS):
        return "network"
    return None


def _checked_verification(argv: list[str], *, kind: str, blocked_marker: str = "") -> None:
    completed = _run_gh(argv)
    if completed.returncode == 0:
        return
    stderr = completed.stderr.decode("utf-8", "replace").strip()
    if blocked_marker and _is_absent_attestation_stderr(stderr, blocked_marker):
        raise Blocked(f"{kind} is not attested yet: {stderr}")
    raise RuntimeError(f"{kind} verification failed: {stderr}")


def _verification_with_lag_retry(
    argv: list[str], *, kind: str, delays: tuple[int, ...] = PREPUBLISH_RETRY_DELAYS
) -> None:
    """Bounded deterministic retry for the blocked class only. Attestation
    data written by actions/attest propagates to the verification data plane
    asynchronously, so a pre-publish read can lag the signing step inside
    the same run; a readable contradiction (RuntimeError) is terminal on the
    first read and never retried."""
    for delay in delays:
        try:
            _checked_verification(argv, kind=kind, blocked_marker=NO_ATTESTATIONS_MARKER)
            return
        except Blocked:
            _sleep(delay)
    _checked_verification(argv, kind=kind, blocked_marker=NO_ATTESTATIONS_MARKER)


def live_selection_snapshot(identity: dict[str, Any]) -> dict[str, Any]:
    """Requery main, workflow, the bound attempt, and the run-level artifact;
    the caller compares two snapshots and restarts on any movement.

    The run-level object reports only the LATEST attempt, so binding to it
    would permanently wedge verification of a correctly published capsule
    after any later re-run. The bound attempt's own immutable record carries
    the head/conclusion binding instead, and the latest attempt number joins
    the movement plane so a re-run landing DURING a verification window still
    restarts it."""
    repository = identity["repository"]
    main_ref = _gh_api_json(f"repos/{repository}/git/ref/heads/main")
    workflow = _gh_api_json(f"repos/{repository}/actions/workflows/{Path(WORKFLOW_PATH).name}")
    if workflow.get("path") != WORKFLOW_PATH or workflow.get("state") != "active":
        raise RuntimeError(
            f"live workflow moved: {workflow.get('path')!r} {workflow.get('state')!r}"
        )
    run = _gh_api_json(f"repos/{repository}/actions/runs/{identity['run_id']}")
    if run.get("path") != WORKFLOW_PATH:
        raise RuntimeError("bound run does not belong to the OpenAPI workflow")
    if run.get("head_sha") != identity["head_sha"]:
        raise RuntimeError("bound run head SHA contradicts the envelope identity")
    attempt = _gh_api_json(
        f"repos/{repository}/actions/runs/{identity['run_id']}/attempts/{identity['run_attempt']}"
    )
    if attempt.get("run_attempt") != identity["run_attempt"]:
        raise RuntimeError("attempt record contradicts the bound run attempt")
    if attempt.get("head_sha") != identity["head_sha"]:
        raise RuntimeError("bound attempt head SHA contradicts the envelope identity")
    pages = _gh_api_json(
        f"repos/{repository}/actions/runs/{identity['run_id']}/artifacts?per_page=100",
        paginate=True,
    )
    artifacts: list[dict[str, Any]] = []
    for page in pages if isinstance(pages, list) else [pages]:
        artifacts.extend(page.get("artifacts", []))
    matching = [item for item in artifacts if item.get("name") == identity["artifact_name"]]
    if len(matching) != 1:
        raise RuntimeError(
            f"run-level artifact {identity['artifact_name']!r} is not uniquely present "
            f"({len(matching)} matches)"
        )
    artifact = matching[0]
    size = artifact.get("size_in_bytes")
    if isinstance(size, bool) or not isinstance(size, int) or size <= 0:
        raise RuntimeError("run-level artifact lacks a nonempty payload")
    return {
        "main_sha": main_ref.get("object", {}).get("sha"),
        "workflow_id": workflow.get("id"),
        "run_id": run.get("id"),
        "run_attempt": attempt.get("run_attempt"),
        "latest_run_attempt": run.get("run_attempt"),
        "conclusion": attempt.get("conclusion"),
        "artifact_id": artifact.get("id"),
        "artifact_size": size,
    }


def _resolve_tag_commit(repository: str, tag: str) -> str:
    ref = _gh_api_json(f"repos/{repository}/git/ref/tags/{tag}")
    obj = ref.get("object", {})
    if obj.get("type") == "tag":
        obj = _gh_api_json(f"repos/{repository}/git/tags/{obj.get('sha')}").get("object", {})
    return str(obj.get("sha"))


def _passing_rule_suite(repository: str, head_sha: str) -> dict[str, Any]:
    pages = _gh_api_json(
        f"repos/{repository}/rulesets/rule-suites"
        f"?ref=refs/heads/main&time_period=month&per_page=100",
        paginate=True,
        admin_gated=True,
    )
    suites: list[dict[str, Any]] = []
    for page in pages if isinstance(pages, list) else [pages]:
        suites.extend(page if isinstance(page, list) else [page])
    matching = [item for item in suites if item.get("after_sha") == head_sha]
    if not matching:
        raise Blocked(
            f"no rule-suite record for {head_sha} on refs/heads/main within the month window"
        )
    newest = max(matching, key=lambda item: item.get("id") or 0)
    if newest.get("result") != "pass":
        raise RuntimeError(
            f"rule suite {newest.get('id')} for {head_sha} concluded {newest.get('result')!r}"
        )
    return {"id": newest.get("id"), "result": "pass"}


def _emit(report: dict[str, Any]) -> None:
    sys.stdout.write(json.dumps(report, sort_keys=True) + "\n")


def cmd_build(args: argparse.Namespace) -> int:
    identity = make_identity(
        repository=args.repository,
        head_sha=args.head_sha,
        run_id=args.run_id,
        run_attempt=args.run_attempt,
        artifact_name=args.artifact_name,
    )
    payload_root = Path(args.payload_dir)
    payload_files = {
        path.relative_to(payload_root).as_posix(): path.read_bytes()
        for path in sorted(payload_root.rglob("*"))
        if path.is_file()
    }
    assets = build_envelope(payload_files, identity)
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    if any(output_dir.iterdir()):
        raise RuntimeError(f"output dir {output_dir} must be empty for a deterministic build")
    for name, data in sorted(assets.items()):
        (output_dir / name).write_bytes(data)
    _emit(
        {
            "status": "pass",
            "tag": identity["tag"],
            "asset_names": sorted(assets),
            "manifest_sha256": sha256_hexdigest(assets[MANIFEST_NAME]),
        }
    )
    return EXIT_PASS


def _immutability_state(repository: str, *, admin_reads: str) -> str:
    """Read the repo immutable-releases setting; under a token without
    Administration read (the workflow's GITHUB_TOKEN) the surface is
    recorded as unreadable in ``report`` mode instead of blocking, and the
    release object's own ``immutable`` field carries the durability proof.
    Only a true capability gap (HTTP 403) may degrade: any readable answer
    keeps full semantics in both modes, so a readable ``enabled: false``
    always fails."""
    try:
        immutability = _gh_api_json(f"repos/{repository}/immutable-releases", admin_gated=True)
    except Forbidden as exc:
        if admin_reads == "required":
            raise
        return f"unreadable ({exc})"
    if immutability.get("enabled") is not True:
        raise RuntimeError("release immutability is not enabled; the envelope is not durable")
    return "enabled"


def _rule_suite_binding(repository: str, head_sha: str, *, admin_reads: str) -> dict[str, Any]:
    """Only a 403 capability gap may degrade in ``report`` mode. A readable
    rule-suite surface with no matching record stays ``Blocked`` and a
    readable non-pass result stays a failure, in both modes: degradation
    never substitutes for a missing binding the token could have seen."""
    try:
        return _passing_rule_suite(repository, head_sha)
    except Forbidden as exc:
        if admin_reads == "required":
            raise
        return {"state": "unverified", "reason": str(exc)}


def _admin_gated_notes(report: dict[str, Any]) -> list[str]:
    # `_append_step_summary` dedupes on the exact bytes of the rendered
    # block, so these note strings must stay static for a given report
    # state; rewording them would make blocked-class retries append a
    # duplicate block instead of deduping.
    notes: list[str] = []
    setting = report.get("immutability_setting")
    if isinstance(setting, str) and setting.startswith("unreadable"):
        notes.append("immutable-releases setting: unreadable (Administration:read gated)")
    suite = report.get("rule_suite")
    if isinstance(suite, dict) and suite.get("state") == "unverified":
        notes.append("rule-suite binding: unverified (Administration:read gated)")
    return notes


def _append_step_summary(report: dict[str, Any]) -> None:
    """Surface admin-read-gated degradation distinctly in the job summary.

    The in-job token soft-reports these surfaces by design (``--admin-reads
    report``); the summary makes the degraded state visible to the operator
    without hard-failing non-admin tokens. Blocked-class retries re-invoke
    this process against the same summary file, so an identical block that
    already landed is not appended again. Summary IO is cosmetic and must
    never flip a verification outcome."""
    path = os.environ.get("GITHUB_STEP_SUMMARY")
    if not path:
        return
    notes = _admin_gated_notes(report)
    if not notes:
        return
    lines = [
        f"### OpenAPI envelope {report.get('phase', 'run')}: admin-read-gated reads degraded",
        *[f"- {note}" for note in notes],
        "- authoritative for these surfaces: the external `verify --admin-reads required` run",
        "",
    ]
    block = "\n".join(lines) + "\n"
    # The summary file is shared with every other step in the job and may
    # hold arbitrary non-UTF-8 bytes; dedupe on raw bytes so no decode error
    # can escape the finally-block append and flip a verification exit.
    try:
        with open(path, "rb") as stream:
            if block.encode("utf-8") in stream.read():
                return
    except OSError:
        pass
    try:
        with open(path, "a", encoding="utf-8") as stream:
            stream.write(block)
    except OSError:
        return


def cmd_verify(args: argparse.Namespace) -> int:
    identity = make_identity(
        repository=args.repository,
        head_sha=args.head_sha,
        run_id=args.run_id,
        run_attempt=args.run_attempt,
        artifact_name=args.artifact_name,
    )
    repository = identity["repository"]
    tag = identity["tag"]
    signer_workflow = args.signer_workflow or f"{repository}/{WORKFLOW_PATH}"
    report: dict[str, Any] = {"tag": tag, "head_sha": identity["head_sha"], "phase": "verify"}
    try:
        report["immutability_setting"] = _immutability_state(
            repository, admin_reads=args.admin_reads
        )
        before = live_selection_snapshot(identity)
        try:
            release = _gh_api_json(f"repos/{repository}/releases/tags/{tag}")
        except Blocked as exc:
            raise Blocked(f"release {tag} is not published yet") from exc
        if release.get("draft"):
            raise Blocked(f"release {tag} is still an unpublished draft")
        report["release_api_id"] = release.get("id")
        # The release object's own immutable flag is readable with plain
        # contents access and proves durability without Administration read.
        if release.get("immutable") is False:
            raise RuntimeError(f"release {tag} is not immutable")
        report["release_immutable"] = (
            release["immutable"] if isinstance(release.get("immutable"), bool) else "unreported"
        )
        if (
            args.admin_reads == "required"
            and release.get("immutable") is not True
            and report["immutability_setting"] != "enabled"
        ):
            raise RuntimeError(f"no surface proves release {tag} is immutable")
        tag_commit = _resolve_tag_commit(repository, tag)
        if tag_commit != identity["head_sha"]:
            raise RuntimeError(
                f"tag {tag} resolves to {tag_commit}, not the bound head {identity['head_sha']}"
            )
        hosted = {
            str(asset.get("name")): asset
            for asset in release.get("assets", [])
            if isinstance(asset, dict) and isinstance(asset.get("name"), str)
        }
        with tempfile.TemporaryDirectory() as scratch:
            download = _run_gh(
                ["gh", "release", "download", tag, "--repo", repository, "--dir", scratch]
            )
            if download.returncode != 0:
                raise RuntimeError(
                    "release asset download failed: "
                    + download.stderr.decode("utf-8", "replace").strip()
                )
            files = {
                path.name: path.read_bytes()
                for path in sorted(Path(scratch).iterdir())
                if path.is_file()
            }
            manifest = verify_envelope_assets(files, identity)
            if set(hosted) != set(files):
                raise RuntimeError(
                    f"hosted asset listing {sorted(hosted)} contradicts downloaded assets {sorted(files)}"
                )
            for name, data in files.items():
                if hosted[name].get("size") != len(data):
                    raise RuntimeError(f"hosted size for {name!r} contradicts its exact bytes")
            # release verify/verify-asset read the same Sigstore data plane
            # as attestation verify; right after publication that data can
            # lag, which is a blocked retry state, not a contradiction.
            _checked_verification(
                release_verify_argv(tag, repository=repository),
                kind=f"release {tag}",
                blocked_marker=NO_ATTESTATIONS_MARKER,
            )
            for name in sorted(files):
                asset_path = str(Path(scratch) / name)
                _checked_verification(
                    release_verify_asset_argv(tag, asset_path, repository=repository),
                    kind=f"release asset {name}",
                    blocked_marker=NO_ATTESTATIONS_MARKER,
                )
                _checked_verification(
                    attestation_verify_argv(
                        asset_path,
                        repository=repository,
                        head_sha=identity["head_sha"],
                        signer_workflow=signer_workflow,
                    ),
                    kind=f"attestation for {name}",
                    blocked_marker=NO_ATTESTATIONS_MARKER,
                )
        report["payload_assets"] = [entry["name"] for entry in manifest["payload_assets"]]
        report["rule_suite"] = _rule_suite_binding(
            repository, identity["head_sha"], admin_reads=args.admin_reads
        )
        after = live_selection_snapshot(identity)
        disposition = movement_disposition(before, after)
        if disposition == "restart":
            raise Movement("workflow/run/artifact selection moved during verification")
        # Main-only movement after publication cannot strand the published
        # capsule: it stays byte-valid for its exact SHA and is recorded as
        # superseded for the validator's newest-execution selection.
        report["main_moved_during_verification"] = disposition == "superseded"
        report["superseded_by_newer_main"] = after["main_sha"] != identity["head_sha"]
        report["status"] = "pass"
        _emit(report)
        return EXIT_PASS
    except Blocked as exc:
        _emit({**report, "status": "blocked", "reason": str(exc)})
        return EXIT_BLOCKED
    except Movement as exc:
        _emit({**report, "status": "movement", "reason": str(exc)})
        return EXIT_MOVEMENT
    except (RuntimeError, ValueError) as exc:
        _emit({**report, "status": "fail", "reason": str(exc)})
        return EXIT_FAIL
    finally:
        _append_step_summary(report)


def cmd_preflight(args: argparse.Namespace) -> int:
    """Everything that must hold BEFORE the irreversible `gh release create`:
    local envelope bytes verify, every asset already has a valid attestation,
    the tag is unused, admin-read capability is probed, and main still points
    at the bound head (a restart is free at this point, so any movement exits
    3 instead of stranding a half-published capsule later)."""
    identity = make_identity(
        repository=args.repository,
        head_sha=args.head_sha,
        run_id=args.run_id,
        run_attempt=args.run_attempt,
        artifact_name=args.artifact_name,
    )
    repository = identity["repository"]
    tag = identity["tag"]
    signer_workflow = args.signer_workflow or f"{repository}/{WORKFLOW_PATH}"
    report: dict[str, Any] = {"tag": tag, "head_sha": identity["head_sha"], "phase": "preflight"}
    try:
        assets_dir = Path(args.assets_dir)
        files = {
            path.name: path.read_bytes() for path in sorted(assets_dir.iterdir()) if path.is_file()
        }
        manifest = verify_envelope_assets(files, identity)
        report["payload_assets"] = [entry["name"] for entry in manifest["payload_assets"]]
        # `gh release verify`/`verify-asset` arrived in gh 2.96; probing the
        # subcommands AND every flag of the exact post-publish argv (built by
        # the same builders the post-publish steps run) keeps a runner-gh
        # mismatch from surfacing only after the irreversible publication.
        sample_asset = str(assets_dir / MANIFEST_NAME)
        for capability, probe_argv in (
            (("release", "verify"), release_verify_argv(tag, repository=repository)),
            (
                ("release", "verify-asset"),
                release_verify_asset_argv(tag, sample_asset, repository=repository),
            ),
            (
                ("attestation", "verify"),
                attestation_verify_argv(
                    sample_asset,
                    repository=repository,
                    head_sha=identity["head_sha"],
                    signer_workflow=signer_workflow,
                ),
            ),
        ):
            helped = _run_gh(["gh", *capability, "--help"])
            if helped.returncode != 0:
                raise Blocked(
                    f"gh {' '.join(capability)} is unavailable on this runner; "
                    "post-publication verification would be impossible"
                )
            help_text = (helped.stdout + helped.stderr).decode("utf-8", "replace")
            missing = [
                flag
                for flag in sorted({token for token in probe_argv if token.startswith("-")})
                if flag not in help_text
            ]
            if missing:
                raise Blocked(
                    f"gh {' '.join(capability)} on this runner does not accept "
                    f"{', '.join(missing)}; the exact post-publish verification argv "
                    "would be rejected only after the irreversible publication"
                )
        report["gh_capabilities"] = [
            "attestation verify",
            "release verify",
            "release verify-asset",
        ]
        # `_checked_verification` distinguishes retryable lag from a readable
        # contradiction by `_is_absent_attestation_stderr`. Verifying a
        # per-identity scratch subject that provably has no attestation forces
        # the live runner gh to emit its no-attestation error NOW, so marker
        # drift blocks here instead of hard-failing after publication.
        with tempfile.TemporaryDirectory() as probe_dir:
            probe_path = Path(probe_dir) / BLOCKED_MARKER_PROBE_NAME
            probe_path.write_bytes(f"unattested probe subject for {tag}\n".encode())
            probe = _run_gh(
                attestation_verify_argv(
                    str(probe_path),
                    repository=repository,
                    head_sha=identity["head_sha"],
                    signer_workflow=signer_workflow,
                )
            )
        if probe.returncode == 0:
            raise Blocked(
                "blocked-marker probe unexpectedly verified an unattested scratch "
                "subject; this runner's gh verification verdicts cannot be trusted"
            )
        probe_stderr = probe.stderr.decode("utf-8", "replace").strip()
        if not _is_absent_attestation_stderr(probe_stderr, NO_ATTESTATIONS_MARKER):
            transient = _probe_transient_class(probe_stderr)
            if transient == "http-403":
                raise Blocked(
                    f"blocked-marker probe was answered with HTTP 403, so no "
                    f"live no-attestation error shape was observed; a "
                    f"rate-limited read clears on retry, but a token-permission "
                    f"403 persists until this token can read the attestations "
                    f"API; observed: {probe_stderr[:300]}"
                )
            if transient == "tls-trust":
                raise Blocked(
                    f"blocked-marker probe failed TLS certificate verification "
                    f"toward the attestations API before any verification "
                    f"verdict (corporate-proxy interception or an untrusted or "
                    f"expired chain); this persists until the runner trusts "
                    f"the presented chain, so repair the runner trust store or "
                    f"proxy configuration; observed: {probe_stderr[:300]}"
                )
            if transient == "verifier-init":
                raise Blocked(
                    f"blocked-marker probe could not initialize the Sigstore "
                    f"verifier; gh swallows the underlying cause, and a stale "
                    f"or corrupt local TUF cache reproduces this even with "
                    f"full connectivity, so clear or repair the runner's "
                    f"Sigstore TUF cache or restore its TUF reachability "
                    f"instead of waiting on a connectivity retry; "
                    f"observed: {probe_stderr[:300]}"
                )
            if transient == "network":
                raise Blocked(
                    f"blocked-marker probe died in the network/Sigstore transport "
                    f"(transient infrastructure class) before any verification "
                    f"verdict; retry when the runner has connectivity; "
                    f"observed: {probe_stderr[:300]}"
                )
            raise Blocked(
                f"runner gh reports a missing attestation with neither the "
                f"{NO_ATTESTATIONS_MARKER!r} marker nor the attestations-API "
                f"HTTP 404 shape, so post-publish propagation lag "
                f"would hard-fail instead of retrying; observed: {probe_stderr[:300]}"
            )
        report["blocked_marker_probe"] = "validated"
        for name in sorted(files):
            _verification_with_lag_retry(
                attestation_verify_argv(
                    str(assets_dir / name),
                    repository=repository,
                    head_sha=identity["head_sha"],
                    signer_workflow=signer_workflow,
                ),
                kind=f"pre-publish attestation for {name}",
            )
        # Forbidden subclasses Blocked: only a plain Blocked (404-class
        # invisibility) proves absence. A 403 rate-limit/permission answer
        # must stay blocked, or an existing tag could hide behind it and
        # the irreversible publish would proceed over it.
        try:
            _gh_api_json(f"repos/{repository}/releases/tags/{tag}")
        except Forbidden:
            raise
        except Blocked:
            pass
        else:
            raise RuntimeError(
                f"release tag {tag} already exists; refusing to publish over it "
                "(verify the existing capsule with its own run identity instead)"
            )
        # A bare git tag is just as disqualifying: `gh release create` would
        # attach to it and ignore --target, publishing at the wrong commit.
        try:
            _gh_api_json(f"repos/{repository}/git/ref/tags/{tag}")
        except Forbidden:
            raise
        except Blocked:
            pass
        else:
            raise RuntimeError(
                f"git tag {tag} already exists; publishing would bind the release "
                "to that tag's commit instead of the requested target"
            )
        report["immutability_setting"] = _immutability_state(
            repository, admin_reads=args.admin_reads
        )
        report["rule_suite"] = _rule_suite_binding(
            repository, identity["head_sha"], admin_reads=args.admin_reads
        )
        snapshot = live_selection_snapshot(identity)
        if snapshot["main_sha"] != identity["head_sha"]:
            raise Movement(
                f"main is at {snapshot['main_sha']}, no longer the bound head "
                f"{identity['head_sha']}; re-dispatch at the current head before publishing"
            )
        report["status"] = "pass"
        _emit(report)
        return EXIT_PASS
    except Blocked as exc:
        _emit({**report, "status": "blocked", "reason": str(exc)})
        return EXIT_BLOCKED
    except Movement as exc:
        _emit({**report, "status": "movement", "reason": str(exc)})
        return EXIT_MOVEMENT
    except (RuntimeError, ValueError) as exc:
        _emit({**report, "status": "fail", "reason": str(exc)})
        return EXIT_FAIL
    finally:
        _append_step_summary(report)


DRY_RUN_HEAD_SHA = "0123456789abcdef0123456789abcdef01234567"
DRY_RUN_PAYLOADS = {
    "docs/api/openapi_generated.json": (
        b'{"info":{"title":"aragora dry-run fixture","version":"0.0.0"},'
        b'"openapi":"3.1.0","paths":{}}\n'
    ),
    "docs/api/openapi_generated.yaml": (
        b"info:\n  title: aragora dry-run fixture\n  version: 0.0.0\nopenapi: 3.1.0\npaths: {}\n"
    ),
    "sdk/typescript/src/openapi-types.ts": b"export type DryRunFixture = never;\n",
}


def dry_run_report() -> dict[str, Any]:
    identity = make_identity(
        repository="synaptent/aragora",
        head_sha=DRY_RUN_HEAD_SHA,
        run_id=1,
        run_attempt=1,
        artifact_name=f"{ARTIFACT_PREFIX}1-{DRY_RUN_HEAD_SHA}",
    )
    first = build_envelope(DRY_RUN_PAYLOADS, identity)
    second = build_envelope(dict(DRY_RUN_PAYLOADS), identity)
    if first != second:
        raise RuntimeError("envelope bytes are not deterministic")
    verify_envelope_assets(first, identity)
    tampered = dict(first)
    tampered["openapi_generated.json"] = tampered["openapi_generated.json"] + b" "
    try:
        verify_envelope_assets(tampered, identity)
    except ValueError:
        pass
    else:
        raise RuntimeError("tampered payload bytes were not rejected")
    snapshot = {key: index for index, key in enumerate(SELECTION_KEYS)}
    if not selection_is_stable(snapshot, dict(snapshot)):
        raise RuntimeError("stable selection was misreported as movement")
    if selection_is_stable(snapshot, {**snapshot, "main_sha": "moved"}):
        raise RuntimeError("main movement was not detected")
    if movement_disposition(snapshot, {**snapshot, "main_sha": "moved"}) != "superseded":
        raise RuntimeError("main-only movement must classify as superseded")
    if movement_disposition(snapshot, {**snapshot, "run_attempt": 99}) != "restart":
        raise RuntimeError("execution movement must classify as restart")
    return {
        "status": "pass",
        "deterministic": True,
        "tag": identity["tag"],
        "asset_names": sorted(first),
        "manifest_sha256": sha256_hexdigest(first[MANIFEST_NAME]),
        "checksums_sha256": sha256_hexdigest(first[CHECKSUMS_NAME]),
        "release_digests": sorted(release_digest_set(first)),
    }


def cmd_dry_run(_args: argparse.Namespace) -> int:
    _emit(dry_run_report())
    return EXIT_PASS


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    def add_identity_args(sub: argparse.ArgumentParser) -> None:
        sub.add_argument("--repository", required=True)
        sub.add_argument("--head-sha", required=True)
        sub.add_argument("--run-id", type=int, required=True)
        sub.add_argument("--run-attempt", type=int, required=True)
        sub.add_argument("--artifact-name", required=True)

    build = subparsers.add_parser("build", help="write deterministic envelope bytes locally")
    add_identity_args(build)
    build.add_argument("--payload-dir", required=True)
    build.add_argument("--output-dir", required=True)
    build.set_defaults(func=cmd_build)

    verify = subparsers.add_parser("verify", help="verify a published envelope read-only")
    add_identity_args(verify)
    verify.add_argument("--signer-workflow", default="")
    verify.add_argument("--admin-reads", choices=("required", "report"), default="required")
    verify.set_defaults(func=cmd_verify)

    preflight = subparsers.add_parser(
        "preflight", help="verify everything that must hold before publication"
    )
    add_identity_args(preflight)
    preflight.add_argument("--assets-dir", required=True)
    preflight.add_argument("--signer-workflow", default="")
    preflight.add_argument("--admin-reads", choices=("required", "report"), default="report")
    preflight.set_defaults(func=cmd_preflight)

    dry_run = subparsers.add_parser("dry-run", help="offline deterministic self-check")
    dry_run.set_defaults(func=cmd_dry_run)

    args = parser.parse_args(argv)
    try:
        return int(args.func(args))
    except (RuntimeError, ValueError) as exc:
        _emit({"status": "fail", "reason": str(exc)})
        return EXIT_FAIL


if __name__ == "__main__":
    sys.exit(main())
