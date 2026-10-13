"""aragora-verify — standalone offline verifier for Open Decision Receipts.

Validate an ODR v0.1 receipt with nothing but the receipt JSON (and optionally
a public key and a hash chain): schema conformance, RFC 8785 (JCS) canonical
digest, Ed25519 detached signature, quorum consistency, and hash-chain linkage.

No Aragora install, no server, no account. The emitter is the product; the
verifier is free.

    from aragora_verify import verify, load_public_key
    result = verify(receipt_dict, public_key=load_public_key(pem_bytes))
    assert result.ok
"""

from __future__ import annotations

from .acta import project_to_acta, verify_acta_projection
from .jcs import jcs_canonicalize, odr_content_digest
from .schema import ODR_PROFILE_URI, ODR_VERSION, validate_structure
from .verifier import (
    Check,
    VerificationError,
    VerifyResult,
    compute_key_id,
    load_public_key,
    verify,
)

# Single-source the version from installed package metadata (pyproject.toml is
# the only place the number lives). Falls back when running from a source tree
# with no installed dist metadata.
from importlib.metadata import PackageNotFoundError, version as _pkg_version

try:
    __version__ = _pkg_version("aragora-verify")
except PackageNotFoundError:  # pragma: no cover - source tree without metadata
    __version__ = "0.0.0+source"

del PackageNotFoundError, _pkg_version

__all__ = [
    "__version__",
    "verify",
    "load_public_key",
    "compute_key_id",
    "validate_structure",
    "jcs_canonicalize",
    "odr_content_digest",
    "project_to_acta",
    "verify_acta_projection",
    "Check",
    "VerifyResult",
    "VerificationError",
    "ODR_VERSION",
    "ODR_PROFILE_URI",
]
