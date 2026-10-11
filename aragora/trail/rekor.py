"""Minimal Sigstore Rekor v1 client for intent-chain head anchoring (ODR-7).

Spec: ``docs/specs/TAMPER_EVIDENT_TRAIL.md`` Component 2 ("External anchor",
Rekor variant) and issue #8231. This module submits a chain-head SHA-256 to
the public Rekor transparency log (https://rekor.sigstore.dev) as a
``hashedrekord`` entry, and can fetch an entry back by UUID for a consistency
check. It deliberately uses only the stdlib HTTP machinery (``urllib``) plus
a lazy import of ``cryptography`` for ephemeral signing — no sigstore SDK,
no new hard dependencies.

How a hash gets into Rekor
--------------------------
Rekor's ``hashedrekord`` type requires a signature that verifies over the
artifact digest. We have no managed signing identity for the trail (and want
none — no standing keys), so each submission generates an **ephemeral**
ECDSA P-256 keypair, signs the digest once, and discards the private key.
The log entry therefore proves *existence of the hash at integration time*,
not *who* submitted it; identity is out of scope for this phase (the
commit-status anchor carries the identity story).

Verification scope — READ THIS (honesty contract)
-------------------------------------------------
What this module DOES verify:

- The submission response (HTTP 201) parses to exactly one entry carrying a
  ``logIndex``, entry UUID, and ``integratedTime``.
- On :func:`verify_inclusion_consistency`: the entry fetched by UUID decodes
  to a ``hashedrekord`` whose embedded SHA-256 equals the expected hash.

What this module does NOT verify (deferred to the ODR-3 offline verifier):

- The Merkle **inclusion proof** of the entry against a signed log
  checkpoint (``verification.inclusionProof`` is *not* checked).
- The **SET** (Signed Entry Timestamp) signature over the entry.
- Log **consistency** between checkpoints.

In other words: a malicious Rekor front-end could lie to this client. The
threat model this phase defends against is a *local* rewrite of the chain —
the public log is a second, independent witness, and full cryptographic
inclusion verification is the ODR-3 verifier's job.

Failure model: every failure raises :exc:`RekorError`. Callers (the anchor
script) treat that as a graceful degrade — they log it and continue; they
never fabricate an anchor record from a failed submission.
"""

from __future__ import annotations

import base64
import binascii
import json
import re
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any, Callable

__all__ = [
    "DEFAULT_REKOR_URL",
    "RekorEntry",
    "RekorError",
    "build_hashedrekord",
    "parse_entry_response",
    "submit_hash",
    "fetch_entry",
    "verify_inclusion_consistency",
]

DEFAULT_REKOR_URL = "https://rekor.sigstore.dev"
ENTRIES_PATH = "/api/v1/log/entries"
HTTP_TIMEOUT_SECONDS = 30.0
_USER_AGENT = "aragora-trail-anchor/1.0 (+https://github.com/synaptent/aragora)"

_SHA256_HEX_RE = re.compile(r"^[0-9a-f]{64}$")

# Transport contract: (method, url, body_bytes_or_None) -> (status_code, body_bytes).
# Injectable so tests never touch the network.
HttpCallable = Callable[[str, str, "bytes | None"], "tuple[int, bytes]"]
# Signer contract: sha256 hex digest -> (signature_b64, public_key_b64).
SignerCallable = Callable[[str], "tuple[str, str]"]


class RekorError(RuntimeError):
    """A Rekor submission, fetch, or consistency check failed."""


@dataclass(frozen=True)
class RekorEntry:
    """The fields of a Rekor log entry this phase records and reasons about."""

    uuid: str
    log_index: int
    integrated_time: int
    log_id: str = ""
    body: str = ""  # base64 canonical entry body, as returned by the log

    def as_anchor_record(self) -> dict[str, Any]:
        """The exact shape recorded in anchor-result JSON (issue #8231)."""
        return {
            "log_index": self.log_index,
            "uuid": self.uuid,
            "integrated_time": self.integrated_time,
        }


def _validate_sha256_hex(sha256_hex: str) -> str:
    """Fail-closed input gate: only a lowercase 64-char hex digest may leave."""
    if not isinstance(sha256_hex, str) or not _SHA256_HEX_RE.match(sha256_hex):
        raise RekorError("refusing to submit: not a lowercase sha256 hex digest")
    return sha256_hex


def _ephemeral_sign(sha256_hex: str) -> tuple[str, str]:
    """Sign the digest with a one-shot ECDSA P-256 key; discard the key.

    Lazy-imports ``cryptography`` (repo convention: optional heavy deps are
    imported at call time). Raises :exc:`RekorError` when unavailable so the
    caller degrades instead of crashing.
    """
    try:
        from cryptography.hazmat.primitives import hashes, serialization
        from cryptography.hazmat.primitives.asymmetric import ec, utils
    except ImportError as exc:
        raise RekorError("cryptography library unavailable for ephemeral signing") from exc

    private_key = ec.generate_private_key(ec.SECP256R1())
    signature = private_key.sign(
        bytes.fromhex(sha256_hex),
        ec.ECDSA(utils.Prehashed(hashes.SHA256())),
    )
    public_pem = private_key.public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    return (
        base64.b64encode(signature).decode("ascii"),
        base64.b64encode(public_pem).decode("ascii"),
    )


def build_hashedrekord(sha256_hex: str, signature_b64: str, public_key_b64: str) -> dict[str, Any]:
    """The Rekor v1 ``hashedrekord`` proposed-entry JSON for a digest."""
    return {
        "apiVersion": "0.0.1",
        "kind": "hashedrekord",
        "spec": {
            "data": {"hash": {"algorithm": "sha256", "value": _validate_sha256_hex(sha256_hex)}},
            "signature": {
                "content": signature_b64,
                "publicKey": {"content": public_key_b64},
            },
        },
    }


def _default_http(method: str, url: str, body: bytes | None) -> tuple[int, bytes]:
    """Stdlib transport. HTTPS only; returns (status, body) even on 4xx/5xx."""
    if not url.startswith("https://"):
        raise RekorError("rekor transport requires an https:// URL")
    request = urllib.request.Request(  # scheme pinned to https above
        url,
        data=body,
        method=method,
        headers={
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": _USER_AGENT,
        },
    )
    try:
        with urllib.request.urlopen(  # nosec B310 - scheme pinned to https above
            request, timeout=HTTP_TIMEOUT_SECONDS
        ) as response:
            return int(response.status), response.read()
    except urllib.error.HTTPError as exc:
        return int(exc.code), exc.read()
    except (urllib.error.URLError, OSError, TimeoutError) as exc:
        raise RekorError(f"rekor request failed: {exc}") from exc


def parse_entry_response(payload: Any) -> RekorEntry:
    """Parse the ``{uuid: {logIndex, integratedTime, ...}}`` map Rekor returns."""
    if not isinstance(payload, dict) or len(payload) != 1:
        raise RekorError("unexpected rekor response shape: expected a single-entry map")
    uuid, entry = next(iter(payload.items()))
    if not isinstance(entry, dict):
        raise RekorError("unexpected rekor response shape: entry is not an object")
    try:
        log_index = int(entry["logIndex"])
        integrated_time = int(entry["integratedTime"])
    except (KeyError, TypeError, ValueError) as exc:
        raise RekorError("rekor entry missing logIndex/integratedTime") from exc
    return RekorEntry(
        uuid=str(uuid),
        log_index=log_index,
        integrated_time=integrated_time,
        log_id=str(entry.get("logID") or ""),
        body=str(entry.get("body") or ""),
    )


def submit_hash(
    sha256_hex: str,
    *,
    base_url: str = DEFAULT_REKOR_URL,
    http: HttpCallable | None = None,
    signer: SignerCallable | None = None,
) -> RekorEntry:
    """Submit a digest to Rekor as a hashedrekord; return the created entry.

    Raises:
        RekorError: on invalid input, transport failure, a non-201 response,
            or an unparseable response. Never returns a fabricated entry.
    """
    digest = _validate_sha256_hex(sha256_hex)
    sign = signer if signer is not None else _ephemeral_sign
    signature_b64, public_key_b64 = sign(digest)
    proposed = build_hashedrekord(digest, signature_b64, public_key_b64)
    transport = http if http is not None else _default_http
    url = base_url.rstrip("/") + ENTRIES_PATH
    status, body = transport("POST", url, json.dumps(proposed).encode("utf-8"))
    if status != 201:
        raise RekorError(f"rekor submission failed: HTTP {status}: {body[:200]!r}")
    try:
        payload = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RekorError("rekor returned a non-JSON submission response") from exc
    return parse_entry_response(payload)


def fetch_entry(
    entry_uuid: str,
    *,
    base_url: str = DEFAULT_REKOR_URL,
    http: HttpCallable | None = None,
) -> RekorEntry:
    """Fetch a log entry by UUID. Raises :exc:`RekorError` on any failure."""
    uuid = str(entry_uuid).strip()
    if not re.match(r"^[0-9a-f]{64,80}$", uuid):
        raise RekorError("invalid rekor entry uuid")
    transport = http if http is not None else _default_http
    url = base_url.rstrip("/") + ENTRIES_PATH + "/" + uuid
    status, body = transport("GET", url, None)
    if status != 200:
        raise RekorError(f"rekor fetch failed: HTTP {status}: {body[:200]!r}")
    try:
        payload = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RekorError("rekor returned a non-JSON fetch response") from exc
    return parse_entry_response(payload)


def verify_inclusion_consistency(
    entry_uuid: str,
    expected_sha256: str,
    *,
    base_url: str = DEFAULT_REKOR_URL,
    http: HttpCallable | None = None,
) -> RekorEntry:
    """Fetch an entry and check it is a hashedrekord over ``expected_sha256``.

    SCOPE (see module docstring): this is a *consistency* check of what the
    log front-end serves — it does NOT verify the Merkle inclusion proof or
    the SET signature. Full cryptographic verification is ODR-3 territory.

    Raises:
        RekorError: when the entry cannot be fetched, decoded, or does not
            embed the expected digest.
    """
    expected = _validate_sha256_hex(expected_sha256)
    entry = fetch_entry(entry_uuid, base_url=base_url, http=http)
    try:
        decoded = json.loads(base64.b64decode(entry.body, validate=True))
    except (binascii.Error, ValueError) as exc:
        raise RekorError("rekor entry body is not base64-encoded JSON") from exc
    if not isinstance(decoded, dict) or decoded.get("kind") != "hashedrekord":
        raise RekorError("rekor entry is not a hashedrekord")
    embedded = (
        decoded.get("spec", {}).get("data", {}).get("hash", {})
        if isinstance(decoded.get("spec"), dict)
        else {}
    )
    if embedded.get("algorithm") != "sha256" or embedded.get("value") != expected:
        raise RekorError("rekor entry digest does not match the expected sha256")
    return entry
