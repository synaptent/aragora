#!/usr/bin/env python3
"""
Constitution signing tool for Aragora nomic loop.

This tool manages Ed25519 key pairs and signs the Constitution file.
The private key should be stored securely and never committed to the repository.

Usage:
    # Generate a new key pair
    python scripts/sign_constitution.py generate-key

    # Sign the constitution
    python scripts/sign_constitution.py sign

    # Verify the signature
    python scripts/sign_constitution.py verify

    # Create default constitution
    python scripts/sign_constitution.py create-default

Environment Variables:
    ARAGORA_CONSTITUTION_KEY: Base64-encoded Ed25519 private key
    ARAGORA_CONSTITUTION_PUBLIC_KEY: Base64-encoded Ed25519 public key
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import sys
from datetime import datetime
from pathlib import Path

# Add parent to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from scripts.nomic.safety.constitution import (
    Constitution,
    ConstitutionVerifier,
    create_default_constitution,
    save_constitution,
    DEFAULT_CONSTITUTION_PATH,
)


def generate_key_pair() -> tuple[bytes, bytes]:
    """Generate a new Ed25519 key pair.

    Returns:
        (private_key, public_key) as raw bytes
    """
    try:
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    except ImportError:
        print("Error: cryptography library not installed")
        print("Install with: pip install cryptography")
        sys.exit(1)

    private_key = Ed25519PrivateKey.generate()
    public_key = private_key.public_key()

    private_bytes = private_key.private_bytes_raw()
    public_bytes = public_key.public_bytes_raw()

    return private_bytes, public_bytes


def sign_constitution(constitution: Constitution, private_key_bytes: bytes) -> str:
    """Sign the Constitution content.

    Args:
        constitution: The Constitution to sign
        private_key_bytes: Raw Ed25519 private key bytes

    Returns:
        Base64-encoded signature
    """
    try:
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    except ImportError:
        print("Error: cryptography library not installed")
        sys.exit(1)

    private_key = Ed25519PrivateKey.from_private_bytes(private_key_bytes)
    content = constitution.get_signable_content()
    signature = private_key.sign(content)

    return base64.b64encode(signature).decode("ascii")


def cmd_generate_key(args: argparse.Namespace) -> int:
    """Generate a new key pair."""
    private_bytes, public_bytes = generate_key_pair()

    private_b64 = base64.b64encode(private_bytes).decode("ascii")
    public_b64 = base64.b64encode(public_bytes).decode("ascii")

    print("=" * 60)
    print("Ed25519 Key Pair Generated")
    print("=" * 60)
    print()
    print("PRIVATE KEY (keep secret, add to .env):")
    print(f"ARAGORA_CONSTITUTION_KEY={private_b64}")
    print()
    print("PUBLIC KEY (can be shared, add to environment or code):")
    print(f"ARAGORA_CONSTITUTION_PUBLIC_KEY={public_b64}")
    print()

    # Optionally save to file
    if args.output:
        key_file = Path(args.output)
        key_data = {
            "private_key": private_b64,
            "public_key": public_b64,
            "created_at": datetime.now().isoformat(),
        }
        key_file.write_text(json.dumps(key_data, indent=2))
        print(f"Keys saved to {key_file}")
        print("WARNING: Protect this file! It contains your private key.")

    return 0


def cmd_sign(args: argparse.Namespace) -> int:
    """Sign the Constitution file."""
    constitution_path = Path(args.constitution or DEFAULT_CONSTITUTION_PATH)

    if not constitution_path.exists():
        print(f"Error: Constitution not found at {constitution_path}")
        print("Run 'python scripts/sign_constitution.py create-default' first")
        return 1

    # Load private key
    private_key_b64 = os.environ.get("ARAGORA_CONSTITUTION_KEY")
    if not private_key_b64 and args.key_file:
        key_data = json.loads(Path(args.key_file).read_text())
        private_key_b64 = key_data["private_key"]

    if not private_key_b64:
        print("Error: No private key found")
        print("Set ARAGORA_CONSTITUTION_KEY environment variable or use --key-file")
        return 1

    private_key_bytes = base64.b64decode(private_key_b64)

    # Load constitution
    with open(constitution_path) as f:
        data = json.load(f)
    constitution = Constitution.from_dict(data)

    # Sign it
    signature = sign_constitution(constitution, private_key_bytes)
    constitution.signature = signature
    constitution.signed_at = datetime.now().isoformat()

    # Save back
    save_constitution(constitution, constitution_path)

    print("Constitution signed successfully")
    print(f"  Version: {constitution.version}")
    print(f"  Rules: {len(constitution.rules)}")
    print(f"  Signed at: {constitution.signed_at}")
    print(f"  Signature: {signature[:32]}...")

    return 0


def cmd_verify(args: argparse.Namespace) -> int:
    """Verify the Constitution signature."""
    constitution_path = Path(args.constitution or DEFAULT_CONSTITUTION_PATH)

    # Load public key
    public_key_b64 = os.environ.get("ARAGORA_CONSTITUTION_PUBLIC_KEY")
    if not public_key_b64 and args.key_file:
        key_data = json.loads(Path(args.key_file).read_text())
        public_key_b64 = key_data["public_key"]

    public_key = base64.b64decode(public_key_b64) if public_key_b64 else None

    verifier = ConstitutionVerifier(constitution_path, public_key)

    if not verifier.is_available():
        print(f"Error: Could not load Constitution from {constitution_path}")
        return 1

    verified = verifier.constitution
    if verified is not None and verifier.verify_signature():
        print("Constitution signature is VALID")
        print(f"  Version: {verified.version}")
        print(f"  Rules: {len(verified.rules)}")
        print(f"  Signed at: {verified.signed_at}")
        return 0
    else:
        print("Constitution signature is INVALID or missing")
        return 1


def cmd_create_default(args: argparse.Namespace) -> int:
    """Create a default Constitution file."""
    constitution_path = Path(args.constitution or DEFAULT_CONSTITUTION_PATH)

    if constitution_path.exists() and not args.force:
        print(f"Constitution already exists at {constitution_path}")
        print("Use --force to overwrite")
        return 1

    constitution = create_default_constitution()
    save_constitution(constitution, constitution_path)

    print(f"Default Constitution created at {constitution_path}")
    print(f"  Version: {constitution.version}")
    print(f"  Rules: {len(constitution.rules)}")
    print()
    print("Next steps:")
    print("  1. Generate keys: python scripts/sign_constitution.py generate-key")
    print("  2. Add private key to .env: ARAGORA_CONSTITUTION_KEY=...")
    print("  3. Sign constitution: python scripts/sign_constitution.py sign")

    return 0


def cmd_show(args: argparse.Namespace) -> int:
    """Show Constitution contents."""
    constitution_path = Path(args.constitution or DEFAULT_CONSTITUTION_PATH)

    if not constitution_path.exists():
        print(f"Constitution not found at {constitution_path}")
        return 1

    with open(constitution_path) as f:
        data = json.load(f)
    constitution = Constitution.from_dict(data)

    print("=" * 60)
    print(f"Constitution v{constitution.version}")
    print("=" * 60)
    print()

    print("RULES:")
    for rule in constitution.rules:
        category_marker = {
            "immutable": "[IMMUTABLE]",
            "amendable": "[AMENDABLE]",
            "advisory": "[ADVISORY]",
        }.get(rule.category, f"[{rule.category}]")
        print(f"  {rule.id} {category_marker}")
        print(f"    {rule.rule}")
        print(f"    Rationale: {rule.rationale}")
        print()

    print("PROTECTED FILES:")
    for protected_file in constitution.protected_files:
        print(f"  - {protected_file}")
    print()

    print("PROTECTED FUNCTIONS:")
    for file_path, funcs in constitution.protected_functions.items():
        print(f"  {file_path}:")
        for func in funcs:
            print(f"    - {func}")
    print()

    print(f"Amendment threshold: {constitution.amendment_threshold * 100:.0f}%")
    if constitution.signature:
        print(f"Signed at: {constitution.signed_at}")
        print(f"Signature: {constitution.signature[:32]}...")
    else:
        print("NOT SIGNED")

    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Constitution signing tool for Aragora nomic loop",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    # generate-key command
    gen_parser = subparsers.add_parser("generate-key", help="Generate new Ed25519 key pair")
    gen_parser.add_argument("--output", "-o", help="Save keys to file")
    gen_parser.set_defaults(func=cmd_generate_key)

    # sign command
    sign_parser = subparsers.add_parser("sign", help="Sign the Constitution")
    sign_parser.add_argument("--constitution", "-c", help="Path to constitution.json")
    sign_parser.add_argument("--key-file", "-k", help="Path to key file (alternative to env var)")
    sign_parser.set_defaults(func=cmd_sign)

    # verify command
    verify_parser = subparsers.add_parser("verify", help="Verify Constitution signature")
    verify_parser.add_argument("--constitution", "-c", help="Path to constitution.json")
    verify_parser.add_argument("--key-file", "-k", help="Path to key file (for public key)")
    verify_parser.set_defaults(func=cmd_verify)

    # create-default command
    create_parser = subparsers.add_parser("create-default", help="Create default Constitution")
    create_parser.add_argument("--constitution", "-c", help="Path to constitution.json")
    create_parser.add_argument("--force", "-f", action="store_true", help="Overwrite existing")
    create_parser.set_defaults(func=cmd_create_default)

    # show command
    show_parser = subparsers.add_parser("show", help="Show Constitution contents")
    show_parser.add_argument("--constitution", "-c", help="Path to constitution.json")
    show_parser.set_defaults(func=cmd_show)

    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
