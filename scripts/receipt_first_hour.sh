#!/usr/bin/env bash
# receipt_first_hour.sh - empty machine to a verified Decision Receipt.
#
# Installs the PUBLISHED aragora and aragora-verify into a throwaway virtualenv,
# runs the offline rate-limiter demo, exports its receipt as an Open Decision
# Receipt and verifies that document. Only verifier exit 0 counts as success.
#
# Usage:
#   bash scripts/receipt_first_hour.sh [<pkg>==<ver> ...] [options]
#
# Versions are positional pins, so a run can be replayed exactly:
#   bash scripts/receipt_first_hour.sh aragora==2.9.0 aragora-verify==0.1.1
#
# Options:
#   --aragora-wheel PATH     install this local aragora wheel instead of PyPI
#   --verify-wheel PATH      install this local aragora-verify wheel instead of PyPI
#   --published-receipt URL  also download and verify a published receipt
#   --pubkey-url URL         public key for --published-receipt (required with it)
#   -h, --help               print this help and exit 0
#
# Transcript: one `step: <install|demo|export|verify>` line as each step starts,
# `venv: <path>` and `odr: <path>` once they exist, and a final
# `total wall time: <n>s`. A failing step, or a run over 300 s, exits non-zero.
# The virtualenv and the exported document are left on disk for inspection.

set -uo pipefail

START=$(date +%s)
ARAGORA_SPEC=aragora
VERIFY_SPEC=aragora-verify
EXTRA_SPECS=()
PUBLISHED_RECEIPT=""
PUBKEY_URL=""

usage() {
  sed -n '2,23p' "$0" | sed -e 's/^#$//' -e 's/^# //'
}

finish() {
  local elapsed=$(($(date +%s) - START))
  printf 'total wall time: %ss\n' "$elapsed"
  if [ "$1" -eq 0 ] && [ "$elapsed" -gt 300 ]; then
    printf 'receipt-first-hour: %ss over the 300s budget\n' "$elapsed" >&2
    exit 1
  fi
  exit "$1"
}

fail() {
  printf 'receipt-first-hour: %s step failed, exit=%s\n' "$1" "$2" >&2
  finish "$2"
}

while [ $# -gt 0 ]; do
  case "$1" in
    -h | --help)
      usage
      exit 0
      ;;
    --aragora-wheel)
      ARAGORA_SPEC=${2:?--aragora-wheel needs a path}
      shift 2
      ;;
    --verify-wheel)
      VERIFY_SPEC=${2:?--verify-wheel needs a path}
      shift 2
      ;;
    --published-receipt)
      PUBLISHED_RECEIPT=${2:?--published-receipt needs a URL}
      shift 2
      ;;
    --pubkey-url)
      PUBKEY_URL=${2:?--pubkey-url needs a URL}
      shift 2
      ;;
    aragora-verify==*)
      VERIFY_SPEC=$1
      shift
      ;;
    aragora==*)
      ARAGORA_SPEC=$1
      shift
      ;;
    *==*)
      EXTRA_SPECS+=("$1")
      shift
      ;;
    *)
      printf 'receipt-first-hour: unknown argument %s\n' "$1" >&2
      usage >&2
      exit 2
      ;;
  esac
done

if [ -n "$PUBLISHED_RECEIPT" ] && [ -z "$PUBKEY_URL" ]; then
  printf 'receipt-first-hour: --published-receipt also needs --pubkey-url\n' >&2
  exit 2
fi
if [ -z "$PUBLISHED_RECEIPT" ] && [ -n "$PUBKEY_URL" ]; then
  printf 'receipt-first-hour: --pubkey-url also needs --published-receipt\n' >&2
  exit 2
fi

# A repository checkout on the interpreter path would shadow the installed packages.
unset PYTHONPATH

TMPROOT=${TMPDIR:-/tmp}
ROOT=$(mktemp -d "${TMPROOT%/}/receipt-first-hour.XXXXXX") || exit 1
VENV="$ROOT/venv"
WORK="$ROOT/work"
mkdir -p "$WORK" || exit 1
cd "$WORK" || exit 1

printf 'step: install\n'
python3 -m venv "$VENV" || fail install $?
printf 'venv: %s\n' "$VENV"
"$VENV/bin/pip" install --quiet "$ARAGORA_SPEC" "$VERIFY_SPEC" \
  ${EXTRA_SPECS[@]+"${EXTRA_SPECS[@]}"} || fail install $?

printf 'step: demo\n'
env -u ARAGORA_ODR_SIGNING_KEY_FILE -u ARAGORA_ODR_SIGNING_KEY_SECRET \
  "$VENV/bin/aragora" demo rate-limiter --offline --receipt r.json || fail demo $?

printf 'step: export\n'
env -u ARAGORA_ODR_SIGNING_KEY_FILE -u ARAGORA_ODR_SIGNING_KEY_SECRET \
  "$VENV/bin/aragora" receipt export r.json --format odr --output r.odr.json || fail export $?
printf 'odr: %s\n' "$WORK/r.odr.json"

printf 'step: verify\n'
"$VENV/bin/aragora-verify" "$WORK/r.odr.json" || fail verify $?

if [ -n "$PUBLISHED_RECEIPT" ]; then
  printf 'published receipt: %s\n' "$PUBLISHED_RECEIPT"
  curl -fsSL --max-time 60 -o "$WORK/published.odr.json" "$PUBLISHED_RECEIPT" || fail download $?
  curl -fsSL --max-time 60 -o "$WORK/published.pub.pem" "$PUBKEY_URL" || fail download $?
  "$VENV/bin/aragora-verify" "$WORK/published.odr.json" \
    --pubkey "$WORK/published.pub.pem" || fail published $?
fi

finish 0
