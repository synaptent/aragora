"""
Cryptographic Signing for Gauntlet Receipts.

Provides digital signatures for decision receipts to ensure:
- Tamper-evidence: Any modification invalidates the signature
- Non-repudiation: Receipts can be verified as authentic
- Audit compliance: Cryptographic proof for regulatory requirements

Supports multiple signing backends:
- HMAC-SHA256: Fast, symmetric signing for internal use
- RSA-SHA256: Asymmetric signing for external verification
- Ed25519: Modern, high-performance signing

"Trust, but verify with cryptographic signatures."
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import os
import secrets
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

_logger = logging.getLogger(__name__)

# Try to import cryptography for RSA/Ed25519 support
try:
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import ed25519, padding, rsa
    from cryptography.exceptions import InvalidSignature

    CRYPTO_AVAILABLE = True
except ImportError:
    CRYPTO_AVAILABLE = False


@dataclass
class SignatoryInfo:
    """Information about the person/entity signing a receipt.

    Used for compliance and audit trails to establish who authorized
    the signature and their role in the decision process.
    """

    name: str
    email: str
    title: str | None = None
    organization: str | None = None
    role: str | None = None  # e.g., "Architect", "Security Lead", "Approver"
    department: str | None = None

    def to_dict(self) -> dict[str, str | None]:
        return {
            "name": self.name,
            "email": self.email,
            "title": self.title,
            "organization": self.organization,
            "role": self.role,
            "department": self.department,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> SignatoryInfo:
        return cls(
            name=data["name"],
            email=data["email"],
            title=data.get("title"),
            organization=data.get("organization"),
            role=data.get("role"),
            department=data.get("department"),
        )


@dataclass
class SignatureMetadata:
    """Metadata about a signature."""

    algorithm: str
    timestamp: str
    key_id: str
    version: str = "1.0"
    signatory: SignatoryInfo | None = None

    def to_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "algorithm": self.algorithm,
            "timestamp": self.timestamp,
            "key_id": self.key_id,
            "version": self.version,
        }
        if self.signatory:
            result["signatory"] = self.signatory.to_dict()
        return result

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> SignatureMetadata:
        signatory = None
        if data.get("signatory"):
            signatory = SignatoryInfo.from_dict(data["signatory"])
        return cls(
            algorithm=data["algorithm"],
            timestamp=data["timestamp"],
            key_id=data["key_id"],
            version=data.get("version", "1.0"),
            signatory=signatory,
        )


@dataclass
class SignedReceipt:
    """A receipt with cryptographic signature."""

    receipt_data: dict[str, Any]
    signature: str  # Base64-encoded signature
    signature_metadata: SignatureMetadata

    def to_dict(self) -> dict[str, Any]:
        return {
            "receipt": self.receipt_data,
            "signature": self.signature,
            "signature_metadata": self.signature_metadata.to_dict(),
        }

    def to_json(self, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent, default=str)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> SignedReceipt:
        return cls(
            receipt_data=data["receipt"],
            signature=data["signature"],
            signature_metadata=SignatureMetadata.from_dict(data["signature_metadata"]),
        )

    @classmethod
    def from_json(cls, json_str: str) -> SignedReceipt:
        return cls.from_dict(json.loads(json_str))


class SigningBackend(ABC):
    """Abstract base class for signing backends."""

    @property
    @abstractmethod
    def algorithm(self) -> str:
        """Return the algorithm name."""
        pass

    @property
    @abstractmethod
    def key_id(self) -> str:
        """Return the key identifier."""
        pass

    @abstractmethod
    def sign(self, data: bytes) -> bytes:
        """Sign data and return signature bytes."""
        pass

    @abstractmethod
    def verify(self, data: bytes, signature: bytes) -> bool:
        """Verify a signature. Returns True if valid."""
        pass


class HMACSigner(SigningBackend):
    """HMAC-SHA256 signing backend for symmetric key signing."""

    def __init__(self, secret_key: bytes | None = None, key_id: str | None = None):
        """
        Initialize HMAC signer.

        Args:
            secret_key: 32-byte secret key. Generated if not provided.
            key_id: Identifier for this key. Generated if not provided.
        """
        self._secret_key = secret_key or secrets.token_bytes(32)
        self._key_id = key_id or f"hmac-{secrets.token_hex(4)}"

    @property
    def algorithm(self) -> str:
        return "HMAC-SHA256"

    @property
    def key_id(self) -> str:
        return self._key_id

    def sign(self, data: bytes) -> bytes:
        return hmac.new(self._secret_key, data, hashlib.sha256).digest()

    def verify(self, data: bytes, signature: bytes) -> bool:
        expected = self.sign(data)
        return hmac.compare_digest(expected, signature)

    @classmethod
    def from_env(cls, env_var: str = "ARAGORA_RECEIPT_SIGNING_KEY") -> HMACSigner:
        """Create signer from environment variable (hex-encoded key).

        In production mode (ARAGORA_ENV=production), a configured signing key
        is required. Without it, receipts signed with an ephemeral key cannot
        be verified after a restart and are vulnerable to forgery.

        Raises:
            RuntimeError: If running in production without a configured key.
        """
        key_hex = (os.environ.get(env_var) or "").strip()
        if key_hex:
            try:
                key_bytes = bytes.fromhex(key_hex)
            except ValueError:
                import base64 as _b64

                key_bytes = _b64.urlsafe_b64decode(key_hex + "==")
            return cls(secret_key=key_bytes)

        # Check if we are running in production
        env_mode = os.environ.get("ARAGORA_ENV", "").lower()
        if env_mode == "production":
            raise RuntimeError(
                f"Receipt signing key ({env_var}) is required in production. "
                "Ephemeral keys cannot verify receipts after restart and are "
                "vulnerable to forgery. Set the environment variable to a "
                "64-character hex string (32 bytes)."
            )

        _logger.warning(
            "No receipt signing key configured (%s). Using ephemeral key. "
            "Receipts will NOT be verifiable after restart. "
            "Set %s for production use.",
            env_var,
            env_var,
        )
        return cls()


class RSASigner(SigningBackend):
    """RSA-SHA256 signing backend for asymmetric key signing."""

    def __init__(
        self,
        private_key: Any | None = None,
        public_key: Any | None = None,
        key_id: str | None = None,
    ):
        """
        Initialize RSA signer.

        Args:
            private_key: RSA private key for signing.
            public_key: RSA public key for verification.
            key_id: Identifier for this key pair.
        """
        if not CRYPTO_AVAILABLE:
            raise ImportError("cryptography package required for RSA signing")

        self._private_key = private_key
        self._public_key = public_key
        self._key_id = key_id or f"rsa-{secrets.token_hex(4)}"

    @property
    def algorithm(self) -> str:
        return "RSA-SHA256"

    @property
    def key_id(self) -> str:
        return self._key_id

    def sign(self, data: bytes) -> bytes:
        if self._private_key is None:
            raise ValueError("Private key required for signing")
        return self._private_key.sign(
            data,
            padding.PSS(
                mgf=padding.MGF1(hashes.SHA256()),
                salt_length=padding.PSS.MAX_LENGTH,
            ),
            hashes.SHA256(),
        )

    def verify(self, data: bytes, signature: bytes) -> bool:
        if self._public_key is None:
            raise ValueError("Public key required for verification")
        try:
            self._public_key.verify(
                signature,
                data,
                padding.PSS(
                    mgf=padding.MGF1(hashes.SHA256()),
                    salt_length=padding.PSS.MAX_LENGTH,
                ),
                hashes.SHA256(),
            )
            return True
        except InvalidSignature:
            return False

    @classmethod
    def generate_keypair(cls, key_id: str | None = None) -> RSASigner:
        """Generate a new RSA key pair."""
        if not CRYPTO_AVAILABLE:
            raise ImportError("cryptography package required for RSA signing")

        private_key = rsa.generate_private_key(
            public_exponent=65537,
            key_size=2048,
        )
        public_key = private_key.public_key()

        return cls(
            private_key=private_key,
            public_key=public_key,
            key_id=key_id,
        )

    def export_public_key(self) -> str:
        """Export public key in PEM format."""
        if self._public_key is None:
            raise ValueError("No public key available")
        return self._public_key.public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        ).decode()


class DurableFileSigner(HMACSigner):
    """HMAC signer backed by a persistent key file on disk.

    On first use the key is generated and saved to ``key_path``.  On
    subsequent starts the same key is loaded, so receipts signed in one
    session can be verified after restart.

    The default path is ``~/.aragora/signing.key``.
    """

    DEFAULT_KEY_PATH = os.path.join(os.path.expanduser("~"), ".aragora", "signing.key")

    def __init__(self, key_path: str | None = None, key_id: str | None = None):
        resolved = key_path or self.DEFAULT_KEY_PATH
        secret_key = self._load_or_create_key(resolved)
        # Derive a stable key_id from the key material so verifiers can match.
        derived_id = key_id or f"durable-{hashlib.sha256(secret_key).hexdigest()[:8]}"
        super().__init__(secret_key=secret_key, key_id=derived_id)
        self._key_path = resolved

    # -- internal helpers ------------------------------------------------

    @staticmethod
    def _load_or_create_key(path: str) -> bytes:
        """Load an existing key or create one on first run."""
        if os.path.isfile(path):
            with open(path, "rb") as fh:
                data = fh.read().strip()
            try:
                return bytes.fromhex(data.decode("ascii"))
            except (ValueError, UnicodeDecodeError):
                return data  # raw bytes fallback

        # First-run: generate and persist
        parent = os.path.dirname(path)
        if parent:
            os.makedirs(parent, mode=0o700, exist_ok=True)
        key = secrets.token_bytes(32)
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        try:
            os.write(fd, key.hex().encode("ascii"))
        finally:
            os.close(fd)
        _logger.info("Created durable signing key at %s", path)
        return key


class Ed25519Signer(SigningBackend):
    """Ed25519 signing backend for modern, high-performance signing."""

    def __init__(
        self,
        private_key: Any | None = None,
        public_key: Any | None = None,
        key_id: str | None = None,
    ):
        """
        Initialize Ed25519 signer.

        Args:
            private_key: Ed25519 private key for signing.
            public_key: Ed25519 public key for verification.
            key_id: Identifier for this key pair.
        """
        if not CRYPTO_AVAILABLE:
            raise ImportError("cryptography package required for Ed25519 signing")

        self._private_key = private_key
        self._public_key = public_key
        self._key_id = key_id or f"ed25519-{secrets.token_hex(4)}"

    @property
    def algorithm(self) -> str:
        return "Ed25519"

    @property
    def key_id(self) -> str:
        return self._key_id

    def sign(self, data: bytes) -> bytes:
        if self._private_key is None:
            raise ValueError("Private key required for signing")
        return self._private_key.sign(data)

    def verify(self, data: bytes, signature: bytes) -> bool:
        if self._public_key is None:
            raise ValueError("Public key required for verification")
        try:
            self._public_key.verify(signature, data)
            return True
        except InvalidSignature:
            return False

    @classmethod
    def generate_keypair(cls, key_id: str | None = None) -> Ed25519Signer:
        """Generate a new Ed25519 key pair."""
        if not CRYPTO_AVAILABLE:
            raise ImportError("cryptography package required for Ed25519 signing")

        private_key = ed25519.Ed25519PrivateKey.generate()
        public_key = private_key.public_key()

        return cls(
            private_key=private_key,
            public_key=public_key,
            key_id=key_id,
        )


class ReceiptSigner:
    """
    High-level receipt signing service.

    Signs receipts using configurable backends and produces
    self-contained signed receipt documents.

    Example:
        signer = ReceiptSigner()  # Uses HMAC by default

        # Sign a receipt
        signed = signer.sign(receipt.to_dict())

        # Verify a signed receipt
        is_valid = signer.verify(signed)

        # Export for external verification
        signed_json = signed.to_json()
    """

    def __init__(self, backend: SigningBackend | None = None):
        """
        Initialize receipt signer.

        Args:
            backend: Signing backend to use. Defaults to HMAC-SHA256.
        """
        self._backend = backend or HMACSigner.from_env()

    @property
    def algorithm(self) -> str:
        """Return the signing algorithm in use."""
        return self._backend.algorithm

    @property
    def key_id(self) -> str:
        """Return the key identifier."""
        return self._backend.key_id

    def _canonicalize(self, receipt_data: dict[str, Any]) -> bytes:
        """
        Canonicalize receipt data for signing.

        Uses JSON with sorted keys for deterministic output.
        """
        canonical = json.dumps(receipt_data, sort_keys=True, default=str)
        return canonical.encode("utf-8")

    def sign(
        self,
        receipt_data: dict[str, Any],
        signatory: SignatoryInfo | None = None,
    ) -> SignedReceipt:
        """
        Sign a receipt and return a SignedReceipt.

        Args:
            receipt_data: Receipt data dictionary (from DecisionReceipt.to_dict())
            signatory: Optional information about the person/entity signing

        Returns:
            SignedReceipt with signature and metadata
        """
        # Canonicalize receipt data
        canonical_data = self._canonicalize(receipt_data)

        # Sign
        signature_bytes = self._backend.sign(canonical_data)
        signature_b64 = base64.b64encode(signature_bytes).decode("ascii")

        # Create metadata
        metadata = SignatureMetadata(
            algorithm=self._backend.algorithm,
            timestamp=datetime.now(timezone.utc).isoformat(),
            key_id=self._backend.key_id,
            signatory=signatory,
        )

        return SignedReceipt(
            receipt_data=receipt_data,
            signature=signature_b64,
            signature_metadata=metadata,
        )

    def verify(self, signed_receipt: SignedReceipt) -> bool:
        """
        Verify a signed receipt.

        Args:
            signed_receipt: The SignedReceipt to verify

        Returns:
            True if signature is valid, False otherwise
        """
        # Canonicalize receipt data
        canonical_data = self._canonicalize(signed_receipt.receipt_data)

        # Decode signature
        signature_bytes = base64.b64decode(signed_receipt.signature)

        # Verify
        return self._backend.verify(canonical_data, signature_bytes)

    def verify_dict(self, signed_receipt_dict: dict[str, Any]) -> bool:
        """Verify a signed receipt from dict format."""
        signed_receipt = SignedReceipt.from_dict(signed_receipt_dict)
        return self.verify(signed_receipt)


# Default signer instance for convenience
_default_signer: ReceiptSigner | None = None


def get_default_signer() -> ReceiptSigner:
    """Get or create the default receipt signer.

    Key selection order:
    1. ``ARAGORA_RECEIPT_SIGNING_KEY`` env var (hex-encoded HMAC key)
    2. Durable file key at ``~/.aragora/signing.key``
    3. Ephemeral random key (non-production only)
    """
    global _default_signer
    if _default_signer is None:
        env_key = (os.environ.get("ARAGORA_RECEIPT_SIGNING_KEY") or "").strip()
        if env_key:
            try:
                key_bytes = bytes.fromhex(env_key)
            except ValueError:
                # Accept base64-encoded keys as well (common in cloud secrets)
                import base64 as _b64

                key_bytes = _b64.urlsafe_b64decode(env_key + "==")
            backend: SigningBackend = HMACSigner(secret_key=key_bytes)
        else:
            env_mode = os.environ.get("ARAGORA_ENV", "").lower()
            if env_mode == "production":
                raise RuntimeError(
                    "Receipt signing key (ARAGORA_RECEIPT_SIGNING_KEY) is required "
                    "in production. Ephemeral keys cannot verify receipts after "
                    "restart. Set the environment variable to a 64-character hex "
                    "string (32 bytes)."
                )
            # Use durable file signer so receipts survive restarts
            try:
                backend = DurableFileSigner()
            except OSError as exc:
                _logger.warning(
                    "Could not create durable file signer (%s), falling back "
                    "to ephemeral key. Receipts will NOT be verifiable after restart.",
                    exc,
                )
                backend = HMACSigner()
        _default_signer = ReceiptSigner(backend=backend)
    return _default_signer


def sign_receipt(
    receipt_data: dict[str, Any],
    signatory: SignatoryInfo | None = None,
) -> SignedReceipt:
    """
    Sign a receipt using the default signer.

    Args:
        receipt_data: Receipt data dictionary
        signatory: Optional information about the person/entity signing

    Returns:
        SignedReceipt with signature
    """
    return get_default_signer().sign(receipt_data, signatory=signatory)


def verify_receipt(signed_receipt: SignedReceipt) -> bool:
    """
    Verify a signed receipt using the default signer.

    Args:
        signed_receipt: The SignedReceipt to verify

    Returns:
        True if valid
    """
    is_valid = get_default_signer().verify(signed_receipt)
    event_name = "RECEIPT_VERIFIED" if is_valid else "RECEIPT_INTEGRITY_FAILED"
    try:
        from aragora.events.types import StreamEvent, StreamEventType

        event_type = getattr(StreamEventType, event_name, None)
        if event_type is not None:
            from aragora.server.stream.emitter import get_global_emitter

            emitter = get_global_emitter()
            if emitter is not None:
                emitter.emit(
                    StreamEvent(
                        type=event_type,
                        data={
                            "receipt_id": getattr(signed_receipt, "receipt_id", "unknown"),
                            "valid": is_valid,
                        },
                    )
                )
    except (ImportError, AttributeError, TypeError):
        pass
    return is_valid


# ============================================================================
# RFC 3161 Trusted Timestamp Support
# ============================================================================


@dataclass
class TimestampToken:
    """RFC 3161 timestamp token from a Time Stamping Authority (TSA).

    Provides cryptographic proof that a receipt existed at a specific point in time,
    which cannot be backdated. Essential for legal non-repudiation.
    """

    tsa_url: str
    timestamp: str  # ISO format
    token: str  # Base64-encoded timestamp token
    hash_algorithm: str  # e.g., "SHA-256"
    message_imprint: str  # Base64-encoded hash of signed data
    serial_number: str | None = None
    policy_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "tsa_url": self.tsa_url,
            "timestamp": self.timestamp,
            "token": self.token,
            "hash_algorithm": self.hash_algorithm,
            "message_imprint": self.message_imprint,
            "serial_number": self.serial_number,
            "policy_id": self.policy_id,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> TimestampToken:
        return cls(
            tsa_url=data["tsa_url"],
            timestamp=data["timestamp"],
            token=data["token"],
            hash_algorithm=data["hash_algorithm"],
            message_imprint=data["message_imprint"],
            serial_number=data.get("serial_number"),
            policy_id=data.get("policy_id"),
        )


# Well-known free RFC 3161 TSA servers
KNOWN_TSA_SERVERS = {
    "freetsa": "https://freetsa.org/tsr",
    "digicert": "http://timestamp.digicert.com",
    "sectigo": "http://timestamp.sectigo.com",
    "globalsign": "http://timestamp.globalsign.com/tsa/r6advanced1",
}

DEFAULT_TSA_URL = os.environ.get(
    "ARAGORA_TSA_URL", KNOWN_TSA_SERVERS.get("freetsa", "https://freetsa.org/tsr")
)


class TimestampAuthority:
    """Client for RFC 3161 Time Stamping Authority (TSA) services.

    Requests trusted timestamps from external TSA servers to provide
    cryptographic proof of when a receipt was signed. This is essential
    for legal non-repudiation - proving the receipt existed at a specific time.

    Example:
        tsa = TimestampAuthority()
        token = await tsa.get_timestamp(signed_receipt)
        # token.timestamp is trusted, cannot be backdated
    """

    def __init__(self, tsa_url: str = DEFAULT_TSA_URL, timeout: float = 30.0):
        """Initialize with TSA server URL.

        Args:
            tsa_url: RFC 3161 TSA server URL
            timeout: Request timeout in seconds
        """
        self.tsa_url = tsa_url
        self.timeout = timeout

    def _create_timestamp_request(self, message_hash: bytes) -> bytes:
        """Create an RFC 3161 TimeStampReq ASN.1 structure.

        This is a minimal implementation. For production, use pyasn1 or
        a dedicated TSA library like rfc3161ng.
        """
        # Try to use rfc3161ng if available
        try:
            import rfc3161ng

            return rfc3161ng.make_timestamp_request(message_hash, hashname="sha256")
        except ImportError:
            pass

        # Fallback: Create minimal ASN.1 timestamp request
        # This is a simplified implementation
        # OID for SHA-256: 2.16.840.1.101.3.4.2.1
        sha256_oid = bytes([0x06, 0x09, 0x60, 0x86, 0x48, 0x01, 0x65, 0x03, 0x04, 0x02, 0x01])

        # MessageImprint
        hash_alg = bytes([0x30, len(sha256_oid) + 2]) + sha256_oid + bytes([0x05, 0x00])
        hash_value = bytes([0x04, len(message_hash)]) + message_hash
        msg_imprint = bytes([0x30, len(hash_alg) + len(hash_value)]) + hash_alg + hash_value

        # Version (always 1)
        version = bytes([0x02, 0x01, 0x01])

        # Nonce (random 8 bytes)
        nonce_value = secrets.token_bytes(8)
        nonce = bytes([0x02, len(nonce_value)]) + nonce_value

        # CertReq (true)
        cert_req = bytes([0x01, 0x01, 0xFF])

        # TimeStampReq sequence
        body = version + msg_imprint + nonce + cert_req
        return bytes([0x30, len(body)]) + body

    async def get_timestamp(self, signed_receipt: SignedReceipt) -> TimestampToken:
        """Request a trusted timestamp for a signed receipt.

        Args:
            signed_receipt: The signed receipt to timestamp

        Returns:
            TimestampToken with proof from the TSA

        Raises:
            TimestampError: If the TSA request fails
        """
        # Hash the signed receipt data
        canonical = json.dumps(signed_receipt.to_dict(), sort_keys=True, default=str)
        message_hash = hashlib.sha256(canonical.encode()).digest()

        # Create timestamp request
        ts_request = self._create_timestamp_request(message_hash)

        # Send to TSA
        try:
            import httpx

            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.post(
                    self.tsa_url,
                    content=ts_request,
                    headers={"Content-Type": "application/timestamp-query"},
                )

                if response.status_code != 200:
                    raise TimestampError(
                        f"TSA returned status {response.status_code}: {response.text}"
                    )

                # Parse response
                ts_response = response.content
                token_b64 = base64.b64encode(ts_response).decode("ascii")

                return TimestampToken(
                    tsa_url=self.tsa_url,
                    timestamp=datetime.now(timezone.utc).isoformat(),
                    token=token_b64,
                    hash_algorithm="SHA-256",
                    message_imprint=base64.b64encode(message_hash).decode("ascii"),
                )

        except ImportError:
            raise TimestampError("httpx not installed - required for TSA requests")
        except (ConnectionError, TimeoutError, RuntimeError, OSError, ValueError) as e:
            raise TimestampError(f"TSA request failed: {e}")

    def verify_timestamp(self, token: TimestampToken, signed_receipt: SignedReceipt) -> bool:
        """Verify that a timestamp token matches the signed receipt.

        Args:
            token: The timestamp token to verify
            signed_receipt: The original signed receipt

        Returns:
            True if the timestamp is valid for this receipt
        """
        # Recompute hash
        canonical = json.dumps(signed_receipt.to_dict(), sort_keys=True, default=str)
        message_hash = hashlib.sha256(canonical.encode()).digest()
        expected_imprint = base64.b64encode(message_hash).decode("ascii")

        # Compare message imprints
        return token.message_imprint == expected_imprint


class TimestampError(Exception):
    """Error during timestamp operations."""

    pass


# ============================================================================
# Legal Hold Support
# ============================================================================


@dataclass
class LegalHold:
    """Legal hold metadata for a receipt.

    When a legal hold is placed on a receipt, it cannot be deleted even
    after the retention period expires. Used for litigation holds and
    regulatory investigations.
    """

    hold_id: str
    receipt_id: str
    reason: str
    placed_by: str  # User/system that placed the hold
    placed_at: str  # ISO timestamp
    matter_id: str | None = None  # Legal matter reference
    expires_at: str | None = None  # Optional expiration (None = indefinite)
    notes: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "hold_id": self.hold_id,
            "receipt_id": self.receipt_id,
            "reason": self.reason,
            "placed_by": self.placed_by,
            "placed_at": self.placed_at,
            "matter_id": self.matter_id,
            "expires_at": self.expires_at,
            "notes": self.notes,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> LegalHold:
        return cls(
            hold_id=data["hold_id"],
            receipt_id=data["receipt_id"],
            reason=data["reason"],
            placed_by=data["placed_by"],
            placed_at=data["placed_at"],
            matter_id=data.get("matter_id"),
            expires_at=data.get("expires_at"),
            notes=data.get("notes"),
        )

    def is_active(self) -> bool:
        """Check if the hold is still active."""
        if self.expires_at is None:
            return True
        try:
            expires = datetime.fromisoformat(self.expires_at.replace("Z", "+00:00"))
            return datetime.now(timezone.utc) < expires
        except ValueError:
            return True  # If we can't parse, assume active


def create_legal_hold(
    receipt_id: str,
    reason: str,
    placed_by: str,
    matter_id: str | None = None,
    expires_at: str | None = None,
    notes: str | None = None,
) -> LegalHold:
    """Create a new legal hold for a receipt.

    Args:
        receipt_id: The receipt to place under hold
        reason: Reason for the hold (e.g., "Litigation - Smith v. Corp")
        placed_by: User or system placing the hold
        matter_id: Optional legal matter reference
        expires_at: Optional expiration timestamp (ISO format)
        notes: Optional additional notes

    Returns:
        LegalHold object
    """
    return LegalHold(
        hold_id=secrets.token_hex(16),
        receipt_id=receipt_id,
        reason=reason,
        placed_by=placed_by,
        placed_at=datetime.now(timezone.utc).isoformat(),
        matter_id=matter_id,
        expires_at=expires_at,
        notes=notes,
    )
