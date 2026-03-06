"""CLI commands for context file signing and verification (G1)."""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

logger = logging.getLogger(__name__)

_DEFAULT_MANIFEST = Path(".aragora/context_manifest.json")
_DEFAULT_PATHS = ["CLAUDE.md", "memory/"]


def add_signing_parser(subparsers: argparse._SubParsersAction) -> None:
    """Register the 'signing' subcommand."""
    parser = subparsers.add_parser(
        "signing",
        help="Sign and verify context files for Nomic Loop provenance (G1)",
        description=(
            "Cryptographic provenance for Nomic Loop context files.\n\n"
            "Commands:\n"
            "  sign    Sign files and write .aragora/context_manifest.json\n"
            "  verify  Verify files against the manifest (exits 0 = ok, 1 = violations)\n"
            "  show    Print current manifest contents\n"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    sub = parser.add_subparsers(dest="signing_command")

    sign_p = sub.add_parser("sign", help="Sign context files")
    sign_p.add_argument(
        "paths",
        nargs="*",
        default=_DEFAULT_PATHS,
        help=f"Files to sign (default: {' '.join(_DEFAULT_PATHS)})",
    )
    sign_p.add_argument(
        "--manifest",
        default=str(_DEFAULT_MANIFEST),
        help=f"Manifest output path (default: {_DEFAULT_MANIFEST})",
    )

    verify_p = sub.add_parser("verify", help="Verify files against the manifest")
    verify_p.add_argument(
        "--manifest",
        default=str(_DEFAULT_MANIFEST),
        help=f"Manifest path (default: {_DEFAULT_MANIFEST})",
    )

    show_p = sub.add_parser("show", help="Print manifest contents")
    show_p.add_argument(
        "--manifest",
        default=str(_DEFAULT_MANIFEST),
        help=f"Manifest path (default: {_DEFAULT_MANIFEST})",
    )

    parser.set_defaults(func=cmd_signing)


def cmd_signing(args: argparse.Namespace) -> None:
    """Dispatch signing subcommands."""
    command = getattr(args, "signing_command", None)
    if command == "sign":
        manifest_path = Path(getattr(args, "manifest", str(_DEFAULT_MANIFEST)))
        paths = args.paths if hasattr(args, "paths") else _DEFAULT_PATHS
        cmd_signing_sign(list(paths), manifest_path=manifest_path)
    elif command == "verify":
        manifest_path = Path(getattr(args, "manifest", str(_DEFAULT_MANIFEST)))
        exit_code = cmd_signing_verify(manifest_path=manifest_path)
        sys.exit(exit_code)
    elif command == "show":
        manifest_path = Path(getattr(args, "manifest", str(_DEFAULT_MANIFEST)))
        cmd_signing_show(manifest_path=manifest_path)
    else:
        print("Usage: aragora signing {sign,verify,show}")
        sys.exit(1)


def cmd_signing_sign(paths: list[str], manifest_path: Path = _DEFAULT_MANIFEST) -> None:
    """Sign files and write manifest."""
    from aragora.security.context_signing import create_manifest, get_signing_key

    key = get_signing_key()
    resolved = [Path(p) for p in paths if Path(p).is_file()]
    if not resolved:
        print(f"No files found to sign from: {paths}", file=sys.stderr)
        sys.exit(1)

    create_manifest(resolved, key=key, manifest_path=manifest_path)
    mode = "HMAC-SHA256" if key else "SHA-256 (hash-only)"
    print(f"Signed {len(resolved)} file(s) [{mode}] → {manifest_path}")
    for p in resolved:
        print(f"  {p}")


def cmd_signing_verify(manifest_path: Path = _DEFAULT_MANIFEST) -> int:
    """Verify files against manifest. Returns 0 on success, 1 on violations."""
    from aragora.security.context_signing import get_signing_key, verify_manifest

    result = verify_manifest(manifest_path, key=get_signing_key())

    if result.manifest_missing:
        print(f"No manifest at {manifest_path} — run 'aragora signing sign' first")
        return 1

    if result.ok:
        print(f"OK — {len(result.verified_files)} file(s) verified clean")
        return 0

    print(f"VIOLATIONS ({len(result.violations)}):")
    for v in result.violations:
        print(f"  {v}")
    if result.missing_files:
        print(f"MISSING FILES: {result.missing_files}")
    return 1


def cmd_signing_show(manifest_path: Path = _DEFAULT_MANIFEST) -> None:
    """Print manifest contents."""
    manifest_path = Path(manifest_path)
    if not manifest_path.exists():
        print(f"No manifest at {manifest_path}")
        return
    data = json.loads(manifest_path.read_text())
    print(f"Manifest: {manifest_path}")
    print(f"Created:  {data.get('created_at', 'unknown')}")
    print(f"Signed:   {data.get('signed', False)}")
    print(f"Entries:  {len(data.get('entries', []))}")
    print()
    for entry in data.get("entries", []):
        hmac_str = entry.get("hmac_sha256") or "—"
        print(f"  {entry['path']}")
        print(f"    sha256:  {entry['sha256'][:16]}...")
        print(f"    hmac:    {hmac_str[:16] if hmac_str != '—' else '—'}")
        print(f"    signed:  {entry.get('signed_at', 'unknown')}")
