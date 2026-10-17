# aragora-verify

**Verify an [Open Decision Receipt](https://github.com/synaptent/aragora/blob/main/docs/specs/OPEN_DECISION_RECEIPT.md) offline — no Aragora install, no server, no account.**

Action-level receipts (Microsoft AGT, SCITT, in-toto/SLSA) prove *what happened
and whether policy allowed it*. An **Open Decision Receipt (ODR)** proves the
layer above: *why it was decided, who adversarially examined it with what model
diversity, who dissented, how calibrated the confidence was, and whether an
accountable human accepted the risk.*

`aragora-verify` is the free, standalone tool that lets anyone — an auditor, a
customer, a skeptic — check such a receipt is genuine and well-formed:

- **Schema conformance** to the ODR v0.1 content profile.
- **Canonical digest** — recomputes `SHA-256(JCS(receipt − signatures))` per
  RFC 8785, the value any detached signature covers.
- **Ed25519 signature** — verifies detached signatures with only the public key.
- **Quorum consistency** — every supporting/dissenting agent is a disclosed
  participant (a mismatch is a tamper/malformed signal).
- **Hash-chain linkage** — when a chain is supplied, the receipt is anchored in
  it and the links are continuous.

It depends only on the Python standard library plus `cryptography`.

## Install

```bash
pip install aragora-verify
```

## Configuration

All package-specific `ARAGORA_*` environment variables are optional:

| Variable | Default | Meaning |
|----------|---------|---------|
| `ARAGORA_LOG_FORMAT` | `text` | `json` selects JSON lines; any other value selects text |
| `ARAGORA_LOG_LEVEL` | `WARNING` | Case-insensitive stdlib logging level; invalid names fall back to WARNING |

Logging settings take effect only when explicitly calling `configure_logging()`.
Verification itself is offline and requires no environment variables, credentials,
server, or account. Receipt, public-key, and chain paths are CLI arguments (see Use).

## Logging

Importing the package does not configure logging or import telemetry SDKs.
Logging is local only, with no PostHog/Sentry client or network exporter:

```python
from aragora_verify._logging import configure_logging

configure_logging()
```

This explicitly replaces root handlers with one stderr handler, including on
repeated calls. Defaults are plain `LEVEL logger: message` text at WARNING
(INFO is suppressed). Set `ARAGORA_LOG_FORMAT=json` for one JSON object per line:
`ts` (UTC ISO-8601 timestamp), `level`, `logger`, and `msg`; optional fields are
`exception`, `stack`, and structured extras.

Both formatters use `redact()` to mask values as `***`. Redaction is name-based
and takes linear time. A value is masked when it follows a name containing a
secret word, `(?i)(api[_-]?key|token|secret|password|authorization)`, anywhere
in the name: as a key in nested mappings and sequences, or in a message as a
`key=value` or `key: value` assignment (quoted keys and values as in JSON or
Python reprs, keys with dots, spaces or colons such as
`http.request.header.authorization`, and Bearer/Basic values), as a header
tuple, a two-argument exception, an `OrderedDict` repr or a HAR entry with the
name first (`('Authorization', '…')`, `{"name": "Authorization", "value": "…"}`),
or after Authorization phrasing (`Authorization header: …`,
`Authorization value = …`, or an Authorization word followed on its line by a
scheme such as `Bearer …`, with no `=` or `:` in between). An unquoted value
ends at whitespace, or at a `,` `;` `}` `]` that is followed by whitespace, a
quote, another of them, the end, or another secret name and its separator
(`token=a,b` masks `a,b`; `token=a,secret=b` masks `a` and `b` separately); a
list, tuple or object value that closes within one bracket level is masked inside
its brackets (`[***]`).

An `Authorization` or `Proxy-Authorization` value is masked whole without being
parsed, whatever the scheme: the scheme, the credential, every parameter and the
rest of the line, including continuation lines that start with a space or tab.
That holds inside a JSON or Python-repr string too, so the rest of the line after
the header name is masked, past the string's closing quote; only a quoted key
with a quoted value that closes its container (`{"Authorization": "…", "n": 1}`)
masks just that string. Where a value's end is uncertain, the rest of its line
is masked: after a backslash-escaped key quote (a JSON string inside another, or
`%r` of a string holding both quote kinds), a header tuple or HAR name/value
pair, a bracket that does not close within one level, a quoted or bracketed
value that runs on into more text (`'x'y`, `(x)y`), a value that opens with an
escaped quote (a repr inside a JSON string), an unquoted value that ends in
another secret name and its separator, or a value that runs into an
`Authorization` name. A secret value that starts before that line end and
runs past it is masked to the end of its own line, and pprint string literals
that continue a quoted value are masked with it. A HAR entry written one field
per line (`json.dumps(..., indent=0)`, indented JSON or pprint) is masked from
its name to the end of the text, or up to the first line that starts with an
unindented `}` or `]` at or after the line where a `}` or `]` starts at the
name's indentation or less (outside the containers its other fields open). Its
other fields are masked with its value, and in indented JSON so are the entries
after it, up to that line. A HAR `value` field found shortly after the masked
text, with no `{` or `}` in between, is masked with it, and the mask goes on
from there. A bracket that ends its line without closing within one level
(`json.dumps(..., indent=0)` of a list whose strings hold escaped quotes) also
masks the lines after it, up to the line where its closing bracket starts at
the key's indentation, or to the end of the text. Log objects rather than their
repr to keep their other fields readable: mappings are redacted field by field.
Sets and bytes keep their type; bytes that are not UTF-8 are masked whole.

Matching fails closed, so it over-masks: labels such as `token_count: 5` are
masked, keys such as `authorization_token` or `Authorization.value` get
Authorization handling, and the rest of the line is masked after the uncertain
forms above and after an Authorization phrase with a scheme
(`Invalid Authorization header format - expected 'Bearer <token>'` loses
`Bearer <token>'`). Mapping keys JSON cannot encode become strings with their values
masked, and a container that contains itself is logged as `<cycle>`. When the
arguments do not fit the format string or cannot be converted, the message
template is logged with an `[unformattable log arguments: …]` note instead of
the arguments. If any other part of a record cannot be formatted, either
formatter writes one JSON line with the redacted template and a `format_error`
field naming the exception type, and the handler from `configure_logging()`
reports a failed write by error type only. Interpolated messages and exceptions
are redacted without mutating the original record.

### Remaining limitations

These forms still leave a secret visible; avoid logging them:

- A raw line feed inside a quoted Digest parameter (invalid HTTP): the
  Authorization mask ends at that physical line, so the parameters after it
  stay visible.
- A name and value split across separate `%`-arguments when the name ends
  another secret's unquoted value
  (`logger.warning("%s%s", "token=x&Authorization:", " Bearer …")`): arguments
  are redacted one at a time, and the second one has no name.
- Unquoted values containing spaces for keys other than Authorization
  (`password=correct horse battery`): only the first word is masked. Quote the
  value or log the mapping.
- pprint output that wraps a value onto the next string literal
  (`'password: '` followed by `'…'` on the next line).
- HAR entries serialized with the value before the name
  (`{"value": "…", "name": "Authorization"}`).
- Secret values nested more than one container level across lines, such as
  `json.dumps(..., indent=0)` of nested lists under a secret key.
- Credentials logged with no name at all (`calling upstream with Bearer …`):
  unlabelled sensitive text is not recognized, so avoid logging credentials or
  user content.

## Use

```bash
# Structural + canonical-digest check
aragora-verify receipt.odr.json

# Full authenticity check against the issuer's published public key
aragora-verify receipt.odr.json --pubkey aragora-odr-signing-key.pem

# Also confirm the receipt is anchored in a hash chain
aragora-verify receipt.odr.json --pubkey key.pem --chain intent-chain.jsonl

# Machine-readable result
aragora-verify receipt.odr.json --pubkey key.pem --json

# Confirm the ACTA-02 projection envelope really carries this receipt
aragora-verify receipt.odr.json --pubkey key.pem --acta receipt.acta.json

# v0.2 signature policy: fix the expiry clock, fail on expiry, demand a signer
aragora-verify receipt.odr.json --pubkey key.pem --now 2026-01-15T12:00:00Z
aragora-verify receipt.odr.json --pubkey key.pem --strict-expiry
aragora-verify receipt.odr.json --pubkey key.pem --require-issuer aragora
```

A v0.2 signature that carries `expires_at` and has passed it still verifies, with
an `expired at <timestamp>` warning; `--strict-expiry` turns that warning into a
failure. `--require-issuer NAME` needs at least one signature whose
signer-committed `issuer` is NAME to verify under `--pubkey`, and **a verified but
expired signature satisfies it unless `--strict-expiry` is given as well**. On a
v0.1 document `issuer` is not covered by the signature, so `--require-issuer` can
never pass there.

Exit code `0` means verified (no failed checks, and any present signatures were
checked); `1` means a check failed; `2` is a usage/input error; `3` means the
receipt is structurally OK but carries signatures that were **not** checked
(no `--pubkey` supplied) — authenticity is unestablished, so it is deliberately
not reported as `0`/VERIFIED.

The public key for receipts emitted by an Aragora deployment is published at
`GET /.well-known/aragora-odr-signing-key` and `GET /api/v2/receipts/signing-key`
(both endpoints are live in the Aragora unified server; see #8804/#8809). Verify
that a specific deployment actually serves the key at those paths before relying
on them for automated verification.

### Weakening vs. failing

Absent markers (`{"status": "absent", ...}`) and `"undisclosed"` model families
are **honesty signals** — a receipt full of them is visibly weak, not a
strong-looking fabrication. They are reported as *weakening signals* and do
**not** fail verification; the policy thresholds (e.g. "require ≥2 model
families", "require human attestation") are yours to apply on top.

### Known limitations (v0.1)

The verifier is deliberately conservative and these are documented, not silent:

- **Hash-chain (`--chain`) is anchoring + self-consistency, not integrity.** It
  confirms the receipt's content digest appears in the chain and that declared
  `prev_hash`/`hash` links are internally consistent, but it does **not** recompute
  entry hashes — so it reports `chain_link` as `WARN` when links are present. A
  party who controls the chain file can fabricate consistent-looking linkage; the
  chain is corroborating evidence, not a tamper proof on its own.
- **Signature verification is single-key, Ed25519-only.** It verifies that at least
  one `signatures[]` entry validates against the supplied `--pubkey` (and fails if
  an entry targeting that key fails). Richer multi-signer / threshold policies are
  out of scope for v0.1.
- **I-JSON numeric range.** Canonicalization assumes IEEE-754-double-safe numbers
  (per RFC 8785 / I-JSON). Integers at or beyond 1e21 are not expected in ODR
  payloads and are not specially handled.

## Library

```python
from aragora_verify import verify, load_public_key

result = verify(receipt_dict, public_key=load_public_key(pem_bytes))
print(result.ok, result.odr_digest)
for check in result.checks:
    print(check.name, check.status, check.detail)
```

## What this is part of

ODR-3 of the [Open Decision Receipt epic](https://github.com/synaptent/aragora/issues/8223).
The verifier is free and standalone by design — the *emitter* (adversarial
debate + signed decision receipts) is the product. See the
[content-profile spec](https://github.com/synaptent/aragora/blob/main/docs/specs/OPEN_DECISION_RECEIPT.md).

## License

MIT
