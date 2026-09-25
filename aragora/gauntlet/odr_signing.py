"""Ed25519 detached signing for Open Decision Receipts (ODR-2, issue #8225).

The verifier shipped first: ``aragora-verify`` (PR #8388) and the
``/api/v2/receipts/*/verify-signature`` endpoints can already *verify* a
signed ODR receipt, but until now nothing on main could *produce* one — a
consumer with no producer. This module is that producer.

It is deliberately written against the verifier's exact contract
(``aragora_verify.verifier`` / ``aragora_verify.jcs``) so producer and
consumer are guaranteed compatible:

    digest_hex = SHA-256( JCS(receipt without "signatures") )      # hex
    message    = bytes.fromhex(digest_hex)                          # 32 raw bytes
    signature  = Ed25519_sign(private_key, message)                # 64 raw bytes
    key_id     = "ed25519-" + SHA-256(raw_public_key).hexdigest()[:16]
    entry      = {"alg": "Ed25519", "key_id": key_id, "signature": base64(signature)}

That is the ``odr_version`` ``"0.1"`` construction (also used for non-ODR
payloads reusing the signer). A ``"0.2"`` document instead signs
``JCS({"odr_digest": digest_hex, "odr_signature_input": "0.2", "protected"})``
where ``protected`` = ``{alg, key_id, issuer, role, signed_at[, expires_at]}``
is the entry minus ``signature``, so the metadata is signer-committed (spec §6).

The digest is computed with :func:`aragora.gauntlet.odr_jcs.odr_content_digest`
(re-exported by :mod:`aragora.gauntlet.odr_export`), which the verifier's own
docstring states it "mirrors exactly". Excluding the
``signatures`` array from the digest is what makes the signatures *detached*:
attaching one never changes the bytes it covers. On a 0.2 document the entry's
metadata sits inside the signed message, so changing or stripping any member
invalidates the signature while the digest still passes.

Key management (per the post-incident security architecture):
    The private key is NEVER read from a raw environment variable or committed
    to the repo. It is read from the PKCS#8 Ed25519 PEM file named by
    ``ARAGORA_ODR_SIGNING_KEY_FILE``; otherwise production resolves
    ``odr-signing-key.pem`` from the protected directory configured by
    ``ARAGORA_SECRETS_DIR``. Explicitly enabled AWS Secrets Manager remains a
    compatibility backend (PEM in the secret named by
    ``ARAGORA_ODR_SIGNING_KEY_SECRET``, default ``aragora/odr-signing-key``).
    Only the *public* key is published (repo + a ``.well-known`` endpoint).
    A loader from explicit PEM bytes is provided for tests and offline tooling.
"""

from __future__ import annotations

import base64
import binascii
import copy
import hashlib
import logging
import os
import re
import stat
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any

from aragora.config.env_helpers import env_bool
from aragora.gauntlet.odr_jcs import odr_content_digest, odr_signature_message

if TYPE_CHECKING:  # pragma: no cover - typing only
    from cryptography.hazmat.primitives.asymmetric.ed25519 import (
        Ed25519PrivateKey,
        Ed25519PublicKey,
    )

logger = logging.getLogger(__name__)

#: Algorithm token recorded in each signature entry (schema-required; the
#: verifier accepts ODR signatures as Ed25519).
ODR_SIGNATURE_ALG = "Ed25519"

#: ``signatures[].role`` values defined by the schema for v0.2 documents.
ODR_SIGNATURE_ROLES = ("emitter", "reviewer", "attestor", "notary")
_SIGNATURE_ENTRY_MEMBERS = {
    "alg",
    "key_id",
    "signature",
    "issuer",
    "role",
    "signed_at",
    "expires_at",
}

MOUNTED_SIGNING_KEY_FILENAME = "odr-signing-key.pem"

#: Name of the AWS Secrets Manager compatibility secret holding the PEM private key.
DEFAULT_SIGNING_KEY_SECRET = "aragora/odr-signing-key"
SIGNING_KEY_SECRET_ENV = "ARAGORA_ODR_SIGNING_KEY_SECRET"
SIGNING_KEY_FILE_ENV = "ARAGORA_ODR_SIGNING_KEY_FILE"
SIGNING_KEY_STRICT_MODE_ENV = "ARAGORA_ODR_SIGNING_KEY_STRICT_MODE"
#: ``signatures[].issuer`` written by the CLI/script producer on v0.2 documents.
SIGNING_ISSUER_ENV = "ARAGORA_ODR_SIGNING_ISSUER"
DEFAULT_SIGNING_ISSUER = "aragora"


class OdrSigningError(Exception):
    """Raised when a private key cannot be loaded or a receipt cannot be signed."""


class OdrSigningUnconfiguredError(OdrSigningError):
    """No signing key is configured — an EXPECTED deployment state.

    Raised only when the deployment genuinely has no key: Secrets Manager is
    not enabled, or the signing secret does not exist in any configured
    region. Every other loader failure (unreadable secret, bad AWS setup,
    invalid key material) stays a plain :class:`OdrSigningError` so callers
    that degrade to unsigned output on *unconfigured* deployments still fail
    closed when a configured key is broken.
    """


def _load_ed25519():  # noqa: ANN202 - lazy import keeps the error actionable
    try:
        from cryptography.exceptions import InvalidSignature
        from cryptography.hazmat.primitives import serialization
        from cryptography.hazmat.primitives.asymmetric.ed25519 import (
            Ed25519PrivateKey,
            Ed25519PublicKey,
        )
    except ImportError as exc:  # pragma: no cover - environment-dependent
        raise OdrSigningError(
            "the 'cryptography' package is required for ODR signing; "
            "install it (already an Aragora dependency) to sign receipts"
        ) from exc
    return Ed25519PrivateKey, Ed25519PublicKey, serialization, InvalidSignature


def compute_key_id(public_key: Ed25519PublicKey) -> str:
    """``ed25519-`` + first 16 hex of SHA-256(raw public key).

    Mirrors ``aragora_verify.verifier.compute_key_id`` exactly so a signed
    receipt's ``key_id`` matches what the verifier derives from the public key.
    """
    _, _, serialization, _ = _load_ed25519()
    raw = public_key.public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    return "ed25519-" + hashlib.sha256(raw).hexdigest()[:16]


def load_private_key_from_pem(pem: str | bytes) -> Ed25519PrivateKey:
    """Load an Ed25519 private key from PEM (for tests/offline tooling).

    Production callers should prefer :func:`load_signing_key_from_secrets`,
    which never lets the key material transit a raw environment variable.
    """
    Ed25519PrivateKey, _, serialization, _ = _load_ed25519()
    from cryptography.exceptions import UnsupportedAlgorithm

    data = pem.encode("utf-8") if isinstance(pem, str) else pem
    try:
        key = serialization.load_pem_private_key(data, password=None)
    except (ValueError, TypeError, UnsupportedAlgorithm) as exc:
        raise OdrSigningError("could not parse Ed25519 private key from PEM") from exc
    if not isinstance(key, Ed25519PrivateKey):
        raise OdrSigningError(
            f"private key is not Ed25519 (got {type(key).__name__}); ODR signatures use Ed25519"
        )
    return key


def _secret_id_label(secret_id: str, *, explicitly_named: bool = False) -> str:
    """Return a log-safe secret identifier label."""
    if explicitly_named or _secret_id_contains_key_material(secret_id) or len(secret_id) > 160:
        return "<redacted-secret-id>"
    return secret_id


def _secret_id_contains_key_material(secret_id: str) -> bool:
    if "-----BEGIN" in secret_id or "PRIVATE KEY" in secret_id or "\n" in secret_id:
        return True
    compact = secret_id.strip()
    if not compact or not re.fullmatch(r"[A-Za-z0-9+/_=-]+", compact):
        return False
    try:
        decoded = base64.b64decode(compact, altchars=b"-_", validate=True)
    except (ValueError, binascii.Error):
        return False
    if b"-----BEGIN" in decoded or b"PRIVATE KEY" in decoded:
        return True
    try:
        from cryptography.exceptions import UnsupportedAlgorithm

        _, _, serialization, _ = _load_ed25519()
        serialization.load_der_private_key(decoded, password=None)
    except (OdrSigningError, UnsupportedAlgorithm, ValueError, TypeError):
        return False
    return True


def _load_pem_from_mounted_custody() -> str | None:
    """Read the fixed ODR key file from configured protected custody."""
    try:
        from aragora.config import secrets as secret_config
    except ImportError as exc:  # pragma: no cover - environment-dependent
        raise OdrSigningError("aragora.config.secrets is unavailable") from exc

    config = secret_config.SecretsConfig.from_env()
    if not config.secrets_dir:
        return None

    manager = secret_config.SecretManager(config)
    try:
        directory_fd = manager._open_secrets_directory()  # noqa: SLF001
        try:
            pem = manager._read_protected_file(  # noqa: SLF001
                directory_fd, MOUNTED_SIGNING_KEY_FILENAME
            )
            if pem is None:
                raise OdrSigningError("mounted ODR signing key is missing")
            return pem
        finally:
            os.close(directory_fd)
    except secret_config.SecretSourceError as exc:
        raise OdrSigningError("mounted ODR signing key failed custody validation") from exc


def _load_pem_secret_from_aws(secret_id: str, *, explicitly_named: bool = False) -> str:
    """Fetch a standalone PEM secret from AWS Secrets Manager.

    This intentionally does not call ``get_secret(secret_id)`` because that API
    looks up a key inside Aragora's configured JSON secret bundle and may fall
    back to environment variables in non-strict local mode. ODR signing keys are
    standalone custody material: the environment may name the SecretId, but it
    must never carry the raw private key.

    ``explicitly_named`` marks a secret id the operator chose (env var or
    argument) rather than the built-in default. An explicitly named secret
    that does not exist is a configuration ERROR (typo, deleted secret) and
    must fail closed, never be treated as "not configured".
    """
    secret_label = _secret_id_label(secret_id, explicitly_named=explicitly_named)
    if _secret_id_contains_key_material(secret_id):
        raise OdrSigningError(
            "ODR signing key secret identifier appears to contain raw key material; "
            "set ARAGORA_ODR_SIGNING_KEY_SECRET to an AWS Secrets Manager SecretId"
        )

    try:
        from aragora.config import secrets as secret_config
    except ImportError as exc:  # pragma: no cover - environment-dependent
        raise OdrSigningError("aragora.config.secrets is unavailable") from exc

    config = secret_config.SecretsConfig.from_env()
    if not config.use_aws:
        message = (
            "AWS Secrets Manager is not enabled for ODR signing; set "
            "ARAGORA_USE_SECRETS_MANAGER=true and provision the PEM private key "
            f"in secret '{secret_label}'"
        )
        if explicitly_named:
            # The operator explicitly named a signing secret: signing is
            # intended, so an unusable secrets backend must fail closed.
            raise OdrSigningError(message)
        raise OdrSigningUnconfiguredError(message)

    manager = secret_config.SecretManager(config)
    regions = config.aws_regions or [config.aws_region]
    last_error: Exception | None = None
    all_not_found = True
    for region in regions:
        client = manager._get_aws_client(region)  # noqa: SLF001 - reuse repo AWS client setup.
        if client is None:
            all_not_found = False
            continue
        try:
            response = client.get_secret_value(SecretId=secret_id)
        except secret_config.ClientError as exc:
            last_error = exc
            code = exc.response.get("Error", {}).get("Code") if hasattr(exc, "response") else None
            if code != "ResourceNotFoundException":
                all_not_found = False
            continue
        except secret_config.BotoCoreError as exc:
            last_error = exc
            all_not_found = False
            continue
        except (OSError, RuntimeError, ValueError, KeyError) as exc:
            last_error = exc
            all_not_found = False
            continue

        secret_string = response.get("SecretString")
        if isinstance(secret_string, str) and secret_string.strip():
            return secret_string

        all_not_found = False
        secret_binary = response.get("SecretBinary")
        if isinstance(secret_binary, bytes) and secret_binary:
            try:
                return secret_binary.decode("utf-8")
            except UnicodeDecodeError:
                last_error = OdrSigningError(
                    f"ODR signing key secret '{secret_label}' binary value is not UTF-8 PEM"
                )
                continue

        last_error = OdrSigningError(f"ODR signing key secret '{secret_label}' is empty")
        continue

    if all_not_found and last_error is not None and not explicitly_named:
        # Every configured region answered ResourceNotFound for the DEFAULT
        # secret name: the key was never provisioned. This is the expected
        # pre-provisioning deployment state, distinct from a
        # configured-but-unreadable key. An explicitly named secret that is
        # missing falls through to the hard error below (typo/deletion must
        # fail closed).
        raise OdrSigningUnconfiguredError(
            f"ODR signing key secret '{secret_label}' does not exist in any "
            "configured AWS region (not provisioned yet)"
        )

    detail = f" (last error: {type(last_error).__name__})" if last_error else ""
    raise OdrSigningError(
        f"ODR signing key secret '{secret_label}' could not be read from AWS Secrets Manager{detail}"
    )


def _key_file_permission_reason(file_mode: int, *, warn: bool = True) -> str | None:
    mode = stat.S_IMODE(file_mode)
    if not stat.S_ISREG(file_mode):
        return "not a regular file"
    if mode & 0o022:
        return f"writable by group or other (mode {mode:04o})"
    if mode & 0o044:
        if env_bool(SIGNING_KEY_STRICT_MODE_ENV, False):
            return f"readable by group or other in strict mode (mode {mode:04o})"
        if warn:
            # Container secret mounts commonly require these bits for non-root users.
            logger.warning(
                "ODR signing key file is readable by group or other (mode %04o); "
                "set %s=true to reject it",
                mode,
                SIGNING_KEY_STRICT_MODE_ENV,
            )
    return None


def load_signing_key_from_secrets(
    secret_name: str | None = None,
) -> Ed25519PrivateKey:
    """Resolve the signing key from file, mounted, or AWS custody.

    An explicit ``secret_name`` ignores file and mounted configuration. Otherwise a
    non-empty ``ARAGORA_ODR_SIGNING_KEY_FILE`` path takes precedence; empty file
    configuration is equivalent to unset and an unusable file fails closed. Next,
    when ``ARAGORA_SECRETS_DIR`` is configured its fixed ``odr-signing-key.pem`` is
    authoritative: missing, unsafe, or invalid material fails closed before AWS
    compatibility or unsigned degradation. Environment variables name custody
    locations, never raw key material.
    """
    if secret_name:
        return load_private_key_from_pem(
            _load_pem_secret_from_aws(secret_name, explicitly_named=True)
        )

    key_file = os.environ.get(SIGNING_KEY_FILE_ENV)
    if key_file:
        if (os.environ.get("ARAGORA_SECRETS_DIR") or "").strip():
            # Both custody locations are configured. The explicit per-key file is
            # the more specific instruction, so it wins; say so, because the
            # mounted directory is then never consulted for the signing key.
            logger.warning(
                "Both %s and ARAGORA_SECRETS_DIR are set; signing with the key file "
                "and ignoring %s in the mounted directory",
                SIGNING_KEY_FILE_ENV,
                MOUNTED_SIGNING_KEY_FILENAME,
            )
        try:
            if os.name != "posix":
                return load_private_key_from_pem(Path(key_file).read_bytes())
            reason = _key_file_permission_reason(os.stat(key_file).st_mode, warn=False)
            if reason is None:
                # Recheck the opened target; O_NONBLOCK prevents a swapped FIFO from hanging.
                with os.fdopen(os.open(key_file, os.O_RDONLY | os.O_NONBLOCK), "rb") as stream:
                    reason = _key_file_permission_reason(os.fstat(stream.fileno()).st_mode)
                    if reason is None:
                        return load_private_key_from_pem(stream.read())
        except (OSError, ValueError, OdrSigningError) as exc:
            # A path could contain mistakenly pasted key bytes; suppress it and
            # parser exception chains rather than disclosing them in producer logs.
            logger.warning("ODR signing key file could not be loaded (%s)", type(exc).__name__)
            raise OdrSigningError(
                "ODR signing key file is configured but could not be used; "
                "expected a readable PKCS#8 Ed25519 private-key PEM"
            ) from None
        raise OdrSigningError(f"ODR signing key file is configured but could not be used; {reason}")

    pem = _load_pem_from_mounted_custody()
    if pem is not None:
        return load_private_key_from_pem(pem)

    explicit = os.environ.get(SIGNING_KEY_SECRET_ENV)
    name = explicit or DEFAULT_SIGNING_KEY_SECRET
    return load_private_key_from_pem(
        _load_pem_secret_from_aws(name, explicitly_named=bool(explicit))
    )


def generate_signing_key() -> Ed25519PrivateKey:
    """Generate a fresh Ed25519 private key (key-rotation / bootstrap tooling)."""
    Ed25519PrivateKey, _, _, _ = _load_ed25519()
    return Ed25519PrivateKey.generate()


def public_key_pem(private_key: Ed25519PrivateKey) -> str:
    """Return the PEM SubjectPublicKeyInfo for the private key's public half.

    This is the artifact to publish (repo + ``.well-known``) so any third party
    can verify receipts offline of Aragora.
    """
    _, _, serialization, _ = _load_ed25519()
    pem = private_key.public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    return pem.decode("utf-8")


def _parse_rfc3339(value: Any, member: str) -> datetime:
    """Parse a ``signatures[]`` timestamp; it must carry a UTC (zero) offset."""
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (AttributeError, ValueError) as exc:
        raise OdrSigningError(f"{member} is not an RFC 3339 timestamp: {value!r}") from exc
    if parsed.utcoffset() != timedelta(0):
        raise OdrSigningError(f"{member} must carry a UTC timezone offset: {value!r}")
    return parsed


def _protected_members(
    key_id: str,
    *,
    issuer: str | None,
    role: str,
    signed_at: str | None,
    expires_at: str | None,
) -> dict[str, Any]:
    """Validate and assemble the signer-committed members of a v0.2 entry.

    Timestamps are re-emitted at whatever precision the caller supplied: a
    ``signed_at``/``expires_at`` carrying a fractional second keeps it, and ``Z``
    becomes the equivalent ``+00:00`` offset. Only the generated default
    ``signed_at`` is truncated to whole seconds. Both forms are valid RFC 3339 and
    both verifiers compare parsed instants, not the strings.
    """
    if not isinstance(issuer, str) or not issuer:
        raise OdrSigningError("issuer is required (non-empty string) to sign a v0.2 document")
    if role not in ODR_SIGNATURE_ROLES:
        raise OdrSigningError(f"role must be one of {', '.join(ODR_SIGNATURE_ROLES)}; got {role!r}")
    if signed_at is None:
        signed_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    signed_at_dt = _parse_rfc3339(signed_at, "signed_at")
    protected: dict[str, Any] = {"alg": ODR_SIGNATURE_ALG, "key_id": key_id, "issuer": issuer}
    protected.update(role=role, signed_at=signed_at_dt.isoformat())
    if expires_at is not None:
        expires_at_dt = _parse_rfc3339(expires_at, "expires_at")
        if expires_at_dt <= signed_at_dt:
            raise OdrSigningError("expires_at must be later than signed_at")
        protected["expires_at"] = expires_at_dt.isoformat()
    return protected


def sign_odr_receipt(
    odr: dict[str, Any],
    private_key: Ed25519PrivateKey,
    *,
    replace: bool = False,
    issuer: str | None = None,
    role: str = "emitter",
    signed_at: str | None = None,
    expires_at: str | None = None,
) -> dict[str, Any]:
    """Attach an Ed25519 detached signature to an ODR receipt.

    ``odr["odr_version"]`` picks the construction (spec §6, module docstring):
    a ``"0.2"`` document gets the metadata entry over the JCS message
    (``issuer`` required, ``signed_at`` defaulting to now UTC, ``expires_at``
    only when supplied and later than ``signed_at``); anything else (``"0.1"``
    or a non-ODR payload) gets the historical three-member entry over the 32
    raw digest bytes, and the metadata arguments raise because a 0.1
    signature cannot commit them.

    Args:
        odr: An ODR profile dict (as produced by
            :func:`aragora.gauntlet.odr_export.decision_receipt_to_odr`). The
            input is not mutated; a new dict is returned.
        private_key: The Ed25519 signing key.
        replace: When True, drop any existing signatures before appending
            (re-sign). When False (default), append alongside existing ones —
            the digest excludes ``signatures``, so this never invalidates a
            prior signature; an existing entry outside the schema shape
            (unknown member, bad type, unknown role) raises instead.
        issuer, role, signed_at, expires_at: The v0.2 entry metadata (``role``
            from :data:`ODR_SIGNATURE_ROLES`, timestamps RFC 3339 with a UTC offset).

    Returns:
        A copy of ``odr`` with the new entry appended to its ``signatures``
        array, covering exactly the message the verifiers re-derive.
    """
    signed = copy.deepcopy(odr)
    is_v02 = signed.get("odr_version") == "0.2"
    if not is_v02 and (issuer, role, signed_at, expires_at) != (None, "emitter", None, None):
        raise OdrSigningError(
            "signature metadata (issuer/role/signed_at/expires_at) is only signer-committed "
            "on odr_version 0.2 documents; a 0.1 document takes the three-member entry"
        )

    existing = signed.get("signatures")
    signatures: list[Any] = []
    if not replace and isinstance(existing, list):
        invalid_index = next(
            (
                index
                for index, entry in enumerate(existing)
                if not _is_signature_entry_compatible(entry)
            ),
            None,
        )
        if invalid_index is not None:
            raise OdrSigningError(
                f"existing signatures[{invalid_index}] is not a valid ODR signature entry; "
                "use replace=True to drop existing signatures before signing"
            )
        signatures = existing

    key_id = compute_key_id(private_key.public_key())
    if is_v02:
        protected = _protected_members(
            key_id, issuer=issuer, role=role, signed_at=signed_at, expires_at=expires_at
        )
    else:
        protected = {"alg": ODR_SIGNATURE_ALG, "key_id": key_id}

    # The digest excludes the signatures array (detached) — compute it against
    # the payload as the verifier will, regardless of what's already attached.
    try:
        digest_hex = odr_content_digest(signed)
        message = odr_signature_message(digest_hex, signed.get("odr_version"), protected)
    except (TypeError, ValueError) as exc:
        raise OdrSigningError("could not compute ODR content digest for signing") from exc

    signature_bytes = private_key.sign(message)
    entry = dict(protected, signature=base64.b64encode(signature_bytes).decode("ascii"))
    signatures.append(entry)
    signed["signatures"] = signatures
    return signed


def _is_signature_entry_compatible(entry: Any) -> bool:
    if not isinstance(entry, dict):
        return False
    if entry.get("alg") != ODR_SIGNATURE_ALG:
        return False
    for field in ("key_id", "signature"):
        if not isinstance(entry.get(field), str) or not entry[field]:
            return False
    issuer_ok = "issuer" not in entry or (isinstance(entry["issuer"], str) and entry["issuer"])
    role_ok = "role" not in entry or entry["role"] in ODR_SIGNATURE_ROLES
    times_ok = all(isinstance(entry.get(f, ""), str) for f in ("signed_at", "expires_at"))
    known = set(entry) <= _SIGNATURE_ENTRY_MEMBERS
    return bool(issuer_ok and role_ok and times_ok and known)


__all__ = [
    "DEFAULT_SIGNING_ISSUER",
    "MOUNTED_SIGNING_KEY_FILENAME",
    "ODR_SIGNATURE_ALG",
    "ODR_SIGNATURE_ROLES",
    "SIGNING_ISSUER_ENV",
    "OdrSigningError",
    "OdrSigningUnconfiguredError",
    "compute_key_id",
    "generate_signing_key",
    "load_private_key_from_pem",
    "load_signing_key_from_secrets",
    "public_key_pem",
    "sign_odr_receipt",
]
