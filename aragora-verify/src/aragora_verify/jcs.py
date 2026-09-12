"""RFC 8785 (JSON Canonicalization Scheme) for Open Decision Receipts.

A dependency-free port of ``aragora.gauntlet.odr_export.jcs_canonicalize`` so
that ``aragora-verify`` can recompute an ODR receipt's content digest without
installing Aragora. Byte-for-byte identical output to the reference emitter is
the whole point: the digest a verifier computes here must match the digest the
signatures cover.

Canonicalization rules (RFC 8785):

- UTF-8 output, no insignificant whitespace;
- object members sorted by UTF-16 code units;
- strings minimally escaped per JSON with lowercase ``\\u00xx`` for controls;
- numbers serialized with the ECMAScript ``Number::toString`` shortest
  round-trip algorithm; ``NaN``/``Infinity`` are forbidden.

ODR payloads are I-JSON-safe (no numbers needing more than IEEE-754 double
precision), so any conforming JCS implementation produces identical bytes.
"""

from __future__ import annotations

import hashlib
import json
import math
from typing import Any

__all__ = ["jcs_canonicalize", "odr_content_digest"]

_ES_INT_LIMIT = 10**21  # ECMAScript switches to exponent notation at 1e21.


def _es_number_to_string(value: float) -> str:
    """Serialize a float per ECMAScript ``Number::toString`` (RFC 8785 3.2.2.3)."""
    if math.isnan(value) or math.isinf(value):
        raise ValueError("NaN and Infinity cannot be canonicalized per RFC 8785")
    if value == 0:
        # Covers -0.0 as well: JCS serializes negative zero as "0".
        return "0"

    sign = "-" if value < 0 else ""
    # Python's repr() yields the shortest digit string that round-trips the
    # IEEE-754 double, the same digit selection ECMAScript uses. Only the
    # *formatting* rules differ; they are applied below.
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


def _jcs_serialize(value: Any, out: list[str]) -> None:  # noqa: C901 - Keep RFC 8785 type dispatch auditable in one place.
    """Append the JCS serialization of ``value`` to ``out``."""
    if value is None:
        out.append("null")
    elif value is True:
        out.append("true")
    elif value is False:
        out.append("false")
    elif isinstance(value, str):
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
    """Canonicalize ``value`` to RFC 8785 (JCS) UTF-8 bytes."""
    out: list[str] = []
    _jcs_serialize(value, out)
    return "".join(out).encode("utf-8")


def odr_content_digest(odr: dict[str, Any]) -> str:
    """SHA-256 hex digest over the JCS bytes of the ODR payload.

    The ``signatures`` array is excluded so that attaching detached signatures
    never changes the digest they cover. This mirrors
    ``aragora.gauntlet.odr_export.odr_content_digest`` exactly.
    """
    payload = {k: v for k, v in odr.items() if k != "signatures"}
    return hashlib.sha256(jcs_canonicalize(payload)).hexdigest()
