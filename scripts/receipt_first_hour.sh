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
# Versions are positional pins, so a run names the exact aragora and
# aragora-verify under test; their dependencies resolve at install time:
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
  awk 'NR == 1 { next } /^#/ { sub(/^# ?/, ""); print; next } { exit }' "$0"
}

# pip runs from the scratch directory, so a wheel given as dist/x.whl must be
# resolved against the caller's cwd before that move.
wheel_path() {
  local dir base
  dir=$(dirname -- "$1")
  base=$(basename -- "$1")
  if [ ! -f "$1" ]; then
    printf 'receipt-first-hour: no such wheel: %s\n' "$1" >&2
    exit 2
  fi
  printf '%s/%s\n' "$(cd -- "$dir" && pwd)" "$base"
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
      ARAGORA_SPEC=$(wheel_path "${2:?--aragora-wheel needs a path}") || exit 2
      shift 2
      ;;
    --verify-wheel)
      VERIFY_SPEC=$(wheel_path "${2:?--verify-wheel needs a path}") || exit 2
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
# The run is only evidence about the PUBLISHED packages, so a caller's index,
# find-links or constraint file must not decide what gets installed. pip reads
# those from pip.conf as well as the environment, and PIP_CONFIG_FILE outranks
# even --isolated, so pointing it at /dev/null is what disables every config
# file (user, site and environment-level) for the install step.
INSTALL_ENV=(env -u PIP_INDEX_URL -u PIP_EXTRA_INDEX_URL -u PIP_FIND_LINKS -u PIP_CONSTRAINT
  PIP_CONFIG_FILE=/dev/null)
"${INSTALL_ENV[@]}" "$VENV/bin/pip" install --quiet "$ARAGORA_SPEC" "$VERIFY_SPEC" \
  ${EXTRA_SPECS[@]+"${EXTRA_SPECS[@]}"} || fail install $?

# The key variables are one way in; the secrets-manager switches are the other,
# because the exporter asks AWS for a key when the environment says it may. An
# explicit false is required: with the flag merely absent, an AWS-hosted runner
# still opts in through AWS_EXECUTION_ENV (aragora/config/secrets.py:330-338).
UNSIGNED_ENV=(env -u ARAGORA_ODR_SIGNING_KEY_FILE -u ARAGORA_ODR_SIGNING_KEY_SECRET
  -u ARAGORA_ENV -u ARAGORA_ENVIRONMENT ARAGORA_USE_SECRETS_MANAGER=false)

printf 'step: demo\n'
"${UNSIGNED_ENV[@]}" \
  "$VENV/bin/aragora" demo rate-limiter --offline --receipt r.json || fail demo $?

printf 'step: export\n'
"${UNSIGNED_ENV[@]}" \
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
