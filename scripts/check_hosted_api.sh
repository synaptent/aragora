#!/usr/bin/env bash
# External checks for a hosted Aragora API (canary or production), curl only.
#
# Usage:
#   scripts/check_hosted_api.sh https://api-canary.aragora.ai \
#       [--pubkey odr-signing-key.pub.pem] [--expect-sha 272a7ef2] \
#       [--expect-version 2.11.0] [--ws-url wss://api-canary.aragora.ai/ws]
#
# Checks, in order:
#   readyz        GET /readyz answers 200 with status "ready"
#   build         GET /health/build reports a sha and version (compared when --expect-* is given)
#   signing-key   GET /.well-known/aragora-odr-signing-key answers 200 (matches --pubkey when given)
#   verify        POST /api/v2/receipts/verify with the committed signed example answers 200
#                 with a boolean "verified" and a non-null "key_id"
#   websocket     /ws accepts the aragora-v1 subprotocol with 101 Switching Protocols
#
# Exit status is 0 only when every check passes. Nothing is sent except the
# public example receipt, and nothing is printed from the server except the
# fields named above.
set -uo pipefail

BASE=""
PUBKEY=""
EXPECT_SHA=""
EXPECT_VERSION=""
WS_URL=""
TIMEOUT="${CHECK_HOSTED_API_TIMEOUT:-15}"
EXAMPLE="$(cd "$(dirname "$0")/.." && pwd)/docs/specs/examples/example-signed.odr.json"

while [ $# -gt 0 ]; do
  case "$1" in
    --pubkey) PUBKEY="$2"; shift 2 ;;
    --expect-sha) EXPECT_SHA="$2"; shift 2 ;;
    --expect-version) EXPECT_VERSION="$2"; shift 2 ;;
    --ws-url) WS_URL="$2"; shift 2 ;;
    -h|--help) sed -n '2,20p' "$0"; exit 0 ;;
    -*) echo "unknown option: $1" >&2; exit 2 ;;
    *) BASE="${1%/}"; shift ;;
  esac
done
if [ -z "$BASE" ]; then
  echo "usage: $0 <base-url> [--pubkey FILE] [--expect-sha SHA] [--expect-version V] [--ws-url URL]" >&2
  exit 2
fi
if [ -z "$WS_URL" ]; then
  WS_URL="${BASE/#https:/wss:}"
  WS_URL="${WS_URL/#http:/ws:}/ws"
fi

FAILED=0
pass() { printf 'PASS %-12s %s\n' "$1" "$2"; }
fail() { printf 'FAIL %-12s %s\n' "$1" "$2"; FAILED=1; }
json_field() { python3 -c "import json,sys
try:
    d=json.load(sys.stdin)
except ValueError:
    sys.exit(1)
v=d.get('$1') if isinstance(d, dict) else None
print('' if v is None else (str(v).lower() if isinstance(v, bool) else v))"; }

# readyz
body=$(curl -sS -m "$TIMEOUT" -w '\n%{http_code}' "$BASE/readyz" 2>/dev/null)
code=${body##*$'\n'}; body=${body%$'\n'*}
status=$(printf '%s' "$body" | json_field status 2>/dev/null)
if [ "$code" = "200" ] && [ "$status" = "ready" ]; then pass readyz "200 ready"; else fail readyz "HTTP ${code:-none} status=${status:-?}"; fi

# build
body=$(curl -sS -m "$TIMEOUT" -w '\n%{http_code}' "$BASE/health/build" 2>/dev/null)
code=${body##*$'\n'}; body=${body%$'\n'*}
sha=$(printf '%s' "$body" | json_field sha 2>/dev/null)
version=$(printf '%s' "$body" | json_field version 2>/dev/null)
detail="sha=${sha:-?} version=${version:-?}"
if [ "$code" != "200" ]; then
  fail build "HTTP ${code:-none}"
elif [ -n "$EXPECT_SHA" ] && [ "${sha#"$EXPECT_SHA"}" = "$sha" ]; then
  fail build "$detail (expected sha $EXPECT_SHA)"
elif [ -n "$EXPECT_VERSION" ] && [ "$version" != "$EXPECT_VERSION" ]; then
  fail build "$detail (expected version $EXPECT_VERSION)"
elif [ -z "$sha" ] || [ "$sha" = "unknown" ]; then
  fail build "$detail (image carries no build sha)"
else
  pass build "$detail"
fi

# signing-key
tmp_key=$(mktemp)
code=$(curl -sS -m "$TIMEOUT" -o "$tmp_key" -w '%{http_code}' "$BASE/.well-known/aragora-odr-signing-key" 2>/dev/null)
if [ "$code" != "200" ]; then
  fail signing-key "HTTP ${code:-none} (no ODR signing key served)"
elif [ -n "$PUBKEY" ] && ! diff -q <(tr -d '[:space:]' < "$tmp_key") <(tr -d '[:space:]' < "$PUBKEY") > /dev/null; then
  fail signing-key "served key differs from $PUBKEY"
else
  pass signing-key "200${PUBKEY:+ (matches $PUBKEY)}"
fi
rm -f "$tmp_key"

# verify
body=$(curl -sS -m "$TIMEOUT" -w '\n%{http_code}' -X POST -H 'Content-Type: application/json' \
  --data @"$EXAMPLE" "$BASE/api/v2/receipts/verify" 2>/dev/null)
code=${body##*$'\n'}; body=${body%$'\n'*}
verified=$(printf '%s' "$body" | json_field verified 2>/dev/null)
key_id=$(printf '%s' "$body" | json_field key_id 2>/dev/null)
if [ "$code" = "200" ] && { [ "$verified" = "true" ] || [ "$verified" = "false" ]; } && [ -n "$key_id" ]; then
  pass verify "200 verified=$verified key_id=$key_id"
else
  fail verify "HTTP ${code:-none} verified=${verified:-?} key_id=${key_id:-none}"
fi

# websocket
http_ws="${WS_URL/#wss:/https:}"
http_ws="${http_ws/#ws:/http:}"
line=$(curl -sS -m 6 --http1.1 -o /dev/null -D - \
  -H 'Connection: Upgrade' -H 'Upgrade: websocket' -H 'Sec-WebSocket-Version: 13' \
  -H 'Sec-WebSocket-Key: dGhlIHNhbXBsZSBub25jZQ==' -H 'Sec-WebSocket-Protocol: aragora-v1' \
  "$http_ws" 2>/dev/null | head -1 | tr -d '\r')
case "$line" in
  *" 101"*) pass websocket "101 aragora-v1" ;;
  *) fail websocket "${line:-no response}" ;;
esac

exit "$FAILED"
