"""RFC 8785 (JCS) canonicalization and the ODR content digest.

Canonicalization follows RFC 8785 (JSON Canonicalization Scheme, JCS):
UTF-8 output, no insignificant whitespace, object members sorted by UTF-16
code units, and numbers serialized using the ECMAScript
``Number::toString`` shortest-round-trip algorithm. No external dependency is
required; :func:`jcs_canonicalize` implements the subset of JCS needed for
I-JSON-safe payloads (which all ODR payloads are) and is covered by
byte-stability tests against the RFC 8785 examples.

This is a dependency-free leaf shared by the emitter
(:mod:`aragora.gauntlet.odr_export`) and the signer
(:mod:`aragora.gauntlet.odr_signing`); ``aragora_verify.jcs`` mirrors it
functionally so producer and verifier always agree on the digest.
"""

from __future__ import annotations

import hashlib
import json
import math
from typing import Any

__all__ = ["jcs_canonicalize", "odr_content_digest"]


# ---------------------------------------------------------------------------
# RFC 8785 (JCS) canonicalization
# ---------------------------------------------------------------------------


def _es_number_to_string(value: float) -> str:
    """Serialize a float per ECMAScript ``Number::toString`` (RFC 8785 3.2.2.3).

    Raises:
        ValueError: for NaN or +/-Infinity, which JCS forbids.
    """
    if math.isnan(value) or math.isinf(value):
        raise ValueError("NaN and Infinity cannot be canonicalized per RFC 8785")
    if value == 0:
        # Covers -0.0 as well: JCS serializes negative zero as "0".
        return "0"

    sign = "-" if value < 0 else ""
    # Python's repr() yields the shortest digit string that round-trips the
    # IEEE-754 double, which is the same digit selection ECMAScript uses.
    # Only the *formatting* rules differ; they are applied below.
    text = repr(abs(value))
    if "e" in text or "E" in text:
        mantissa, _, exp_text = text.lower().partition("e")
        exponent = int(exp_text)
    else:
        mantissa, exponent = text, 0

    if "." in mantissa:
        int_part, frac_part = mantissa.split(".", 1)
    else:
        int_part, frac_part = mantissa, ""

    digits = int_part + frac_part
    # Position of the decimal point measured in digits from the left of
    # ``digits``: value == 0.<digits> * 10**point.
    point = len(int_part) + exponent

    stripped = digits.lstrip("0")
    point -= len(digits) - len(stripped)
    digits = stripped.rstrip("0")

    k = len(digits)
    n = point
    if k <= n <= 21:
        out = digits + "0" * (n - k)
    elif 0 < n <= 21:
        out = digits[:n] + "." + digits[n:]
    elif -6 < n <= 0:
        out = "0." + "0" * (-n) + digits
    else:
        e = n - 1
        head = digits[0] + ("." + digits[1:] if k > 1 else "")
        out = f"{head}e{'+' if e >= 0 else '-'}{abs(e)}"
    return sign + out


_ES_INT_LIMIT = 10**21  # ECMAScript switches to exponent notation at 1e21.


def _jcs_serialize(value: Any, out: list[str]) -> None:
    """Append the JCS serialization of ``value`` to ``out``."""
    if value is None:
        out.append("null")
    elif value is True:
        out.append("true")
    elif value is False:
        out.append("false")
    elif isinstance(value, str):
        # json.dumps applies exactly the JCS string rules: minimal escaping,
        # two-character escapes for the common controls, lowercase \u00xx for
        # the rest, and raw UTF-8 for everything else (ensure_ascii=False).
        out.append(json.dumps(value, ensure_ascii=False))
    elif isinstance(value, int):
        if abs(value) < _ES_INT_LIMIT:
            out.append(str(value))
        else:
            out.append(_es_number_to_string(float(value)))
    elif isinstance(value, float):
        out.append(_es_number_to_string(value))
    elif isinstance(value, (list, tuple)):
        out.append("[")
        for i, item in enumerate(value):
            if i:
                out.append(",")
            _jcs_serialize(item, out)
        out.append("]")
    elif isinstance(value, dict):
        out.append("{")
        # RFC 8785 sorts member names by UTF-16 code units; comparing the
        # UTF-16BE encodings byte-wise is equivalent.
        keys = sorted(value.keys(), key=lambda k: str(k).encode("utf-16-be"))
        for i, key in enumerate(keys):
            if i:
                out.append(",")
            if not isinstance(key, str):
                raise TypeError(f"JCS object member names must be strings, got {type(key)!r}")
            out.append(json.dumps(key, ensure_ascii=False))
            out.append(":")
            _jcs_serialize(value[key], out)
        out.append("}")
    else:
        raise TypeError(f"Type {type(value)!r} is not JCS-serializable")


def jcs_canonicalize(value: Any) -> bytes:
    """Canonicalize ``value`` to RFC 8785 (JCS) UTF-8 bytes.

    The output is byte-stable: equal inputs (regardless of dict insertion
    order) always produce identical bytes, which is the hashing basis for the
    ODR profile.
    """
    out: list[str] = []
    _jcs_serialize(value, out)
    return "".join(out).encode("utf-8")


def odr_content_digest(odr: dict[str, Any]) -> str:
    """SHA-256 hex digest over the JCS bytes of the ODR payload.

    The ``signatures`` array is excluded so that attaching detached
    signatures (SCITT/COSE, Ed25519 per #8225) never changes the digest the
    signatures cover.
    """
    payload = {k: v for k, v in odr.items() if k != "signatures"}
    return hashlib.sha256(jcs_canonicalize(payload)).hexdigest()
