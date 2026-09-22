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
# Environment:
#   RECEIPT_FIRST_HOUR_BUDGET  tighten the wall-clock budget below its 300 s
#                              ceiling; a larger value is ignored
#
# With neither --published-receipt nor --pubkey-url the run resolves the newest
# published `receipts-*` release itself and verifies that release's clean receipt
# against the public key shipped beside it. With no such release it prints
# `published receipt: skipped (no receipts-* release)` and still exits 0.
#
# Transcript: one `step: <install|demo|export|verify|published>` line as each step
# starts, `venv: <path>` and `odr: <path>` once they exist, and a final
# `total wall time: <n>s`. A failing step, or a run over the budget, exits
# non-zero. The virtualenv and the exported document are left on disk for
# inspection; the next run reclaims the scratch trees of earlier runs that
# finished cleanly and have since gone idle.

set -uo pipefail

START=$(date +%s)
# Wall-clock budget in seconds. It is enforced DURING the run as well as after
# it: run_step stops a step that would outlast the budget, and finish() turns an
# otherwise clean over-budget run into exit 1.
BUDGET_SECONDS=300
# The ceiling is the contract, so a caller may only tighten it. The override
# exists so the mid-run stop can be proven without a five-minute test.
if [ "${RECEIPT_FIRST_HOUR_BUDGET:-0}" -gt 0 ] 2> /dev/null \
  && [ "$RECEIPT_FIRST_HOUR_BUDGET" -lt "$BUDGET_SECONDS" ]; then
  BUDGET_SECONDS=$RECEIPT_FIRST_HOUR_BUDGET
fi
# A completed tree stays reclaimable only well past the budget, so a run that is
# still going (or a failure someone just started reading) is never swept.
SWEEP_IDLE_MINUTES=10
ARAGORA_SPEC=aragora
VERIFY_SPEC=aragora-verify
EXTRA_SPECS=()
PUBLISHED_RECEIPT=""
PUBKEY_URL=""
PUBLISHED_REPO=synaptent/aragora

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
  if [ "$1" -eq 0 ] && [ "$elapsed" -gt "$BUDGET_SECONDS" ]; then
    printf 'receipt-first-hour: %ss over the %ss budget\n' "$elapsed" "$BUDGET_SECONDS" >&2
    exit 1
  fi
  # Only a clean run is marked reclaimable: a failed run's tree is the evidence
  # a reader needs, so it outlives every later sweep.
  if [ "$1" -eq 0 ] && [ -n "${ROOT:-}" ] && [ -d "${ROOT:-}" ]; then
    : > "$ROOT/.complete"
  fi
  exit "$1"
}

fail() {
  printf 'receipt-first-hour: %s step failed, exit=%s\n' "$1" "$2" >&2
  if [ $(($(date +%s) - START)) -ge "$BUDGET_SECONDS" ]; then
    printf 'receipt-first-hour: %s step was stopped at the %ss budget\n' \
      "$1" "$BUDGET_SECONDS" >&2
  fi
  finish "$2"
}

# Run a step under whatever is left of the wall-clock budget. Without this the
# budget is only read after everything finishes, so one hung download holds the
# job open indefinitely; a stopped step returns a non-zero status and takes the
# caller's normal failure path.
run_step() {
  local remaining=$((BUDGET_SECONDS - ($(date +%s) - START)))
  if [ "$remaining" -le 0 ]; then
    return 124
  fi
  # Job control gives the step its own process group, so the watchdog can signal
  # the whole tree. Signalling the direct child alone is not enough: pip and the
  # CLIs spawn their own children, which would survive as orphans still holding
  # the run's stdout open.
  set -m
  "$@" &
  local cmd_pid=$! dog_pid rc
  set +m
  (
    sleep "$remaining"
    kill -TERM -"$cmd_pid" 2> /dev/null
    sleep 5
    kill -KILL -"$cmd_pid" 2> /dev/null
  ) > /dev/null 2>&1 &
  dog_pid=$!
  wait "$cmd_pid"
  rc=$?
  kill "$dog_pid" 2> /dev/null
  wait "$dog_pid" 2> /dev/null
  return "$rc"
}

# The scratch tree is deliberately left behind so the `venv:` and `odr:` lines
# keep pointing at real paths, but the first-hour CI job runs on a PERSISTENT
# self-hosted runner where that means one abandoned virtualenv per publish and
# nothing to reclaim it. Each run therefore sweeps earlier runs' trees, and only
# those that recorded a clean finish and have been idle far longer than the
# budget -- never a concurrent run, and never a failure left for a human.
sweep_completed_scratch() {
  local dir
  for dir in "${TMPROOT%/}"/receipt-first-hour.*; do
    [ -d "$dir" ] || continue
    [ "$dir" != "$ROOT" ] || continue
    [ -f "$dir/.complete" ] || continue
    [ -z "$(find "$dir/.complete" -mmin -"$SWEEP_IDLE_MINUTES" 2>/dev/null)" ] || continue
    rm -rf -- "$dir" || continue
    printf 'reclaimed: %s\n' "$dir"
  done
}

# Resolve the newest published receipts-* release tag, or print nothing.
resolve_receipts_tag() {
  gh release list -R "$PUBLISHED_REPO" --limit 100 \
    --json tagName,isDraft,publishedAt \
    --jq 'map(select(.isDraft == false and (.tagName | startswith("receipts-"))))
          | sort_by(.publishedAt) | last | .tagName // empty'
}

# The published key is the trust anchor: a key an attacker can substitute makes
# the whole check meaningless. The fetch is therefore pinned to https on the
# request AND on every hop, and the hop count is bounded, so no redirect can
# move it to another scheme or send it wandering. (Refusing redirects outright
# is not available here: GitHub answers every release-asset URL with a 302 to
# its object CDN, so the published key would simply be unreachable.)
fetch_pubkey() {
  curl -fsSL --proto '=https' --proto-redir '=https' --max-redirs 2 \
    --max-time 60 -o "$WORK/published.pub.pem" "$1"
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
sweep_completed_scratch

printf 'step: install\n'
# `python3 -m venv` without ensurepip dies with a bare non-zero status that tells
# a stranger nothing; the component is packaged separately on several distros.
if ! python3 -c 'import ensurepip' >/dev/null 2>&1; then
  printf 'receipt-first-hour: this python3 is missing the standard-library ensurepip module, so `python3 -m venv` cannot create the virtualenv; install the venv package for this interpreter (Debian/Ubuntu: apt-get install python3-venv, Fedora/RHEL: dnf install python3-libs) and re-run\n' >&2
  fail install 127
fi
run_step python3 -m venv "$VENV" || fail install $?
printf 'venv: %s\n' "$VENV"
# The run is only evidence about the PUBLISHED packages, so a caller's index,
# find-links or constraint file must not decide what gets installed. pip reads
# those from pip.conf as well as the environment, and PIP_CONFIG_FILE outranks
# even --isolated, so pointing it at /dev/null is what disables every config
# file (user, site and environment-level) for the install step.
INSTALL_ENV=(env -u PIP_INDEX_URL -u PIP_EXTRA_INDEX_URL -u PIP_FIND_LINKS -u PIP_CONSTRAINT
  PIP_CONFIG_FILE=/dev/null)
run_step "${INSTALL_ENV[@]}" "$VENV/bin/pip" install --quiet "$ARAGORA_SPEC" "$VERIFY_SPEC" \
  ${EXTRA_SPECS[@]+"${EXTRA_SPECS[@]}"} || fail install $?

# The key variables are one way in; the secrets-manager switches are the other,
# because the exporter asks AWS for a key when the environment says it may. An
# explicit false is required: with the flag merely absent, an AWS-hosted runner
# still opts in through AWS_EXECUTION_ENV (aragora/config/secrets.py:330-338).
UNSIGNED_ENV=(env -u ARAGORA_ODR_SIGNING_KEY_FILE -u ARAGORA_ODR_SIGNING_KEY_SECRET
  -u ARAGORA_ENV -u ARAGORA_ENVIRONMENT ARAGORA_USE_SECRETS_MANAGER=false)

printf 'step: demo\n'
run_step "${UNSIGNED_ENV[@]}" \
  "$VENV/bin/aragora" demo rate-limiter --offline --receipt r.json || fail demo $?

printf 'step: export\n'
run_step "${UNSIGNED_ENV[@]}" \
  "$VENV/bin/aragora" receipt export r.json --format odr --output r.odr.json || fail export $?
printf 'odr: %s\n' "$WORK/r.odr.json"

printf 'step: verify\n'
run_step "$VENV/bin/aragora-verify" "$WORK/r.odr.json" || fail verify $?

if [ -n "$PUBLISHED_RECEIPT" ]; then
  printf 'step: published\n'
  printf 'published receipt: %s\n' "$PUBLISHED_RECEIPT"
  run_step curl -fsSL --max-time 60 \
    -o "$WORK/published.odr.json" "$PUBLISHED_RECEIPT" || fail receipt-download $?
  run_step fetch_pubkey "$PUBKEY_URL" || fail pubkey-download $?
  run_step "$VENV/bin/aragora-verify" "$WORK/published.odr.json" \
    --pubkey "$WORK/published.pub.pem" || fail published $?
elif ! command -v gh > /dev/null 2>&1; then
  printf 'published receipt: skipped (gh not available)\n'
else
  printf 'step: published\n'
  RECEIPTS_TAG=$(resolve_receipts_tag 2> /dev/null) || RECEIPTS_TAG=""
  if [ -z "$RECEIPTS_TAG" ]; then
    printf 'published receipt: skipped (no receipts-* release)\n'
  else
    printf 'published receipt: %s %s\n' "$PUBLISHED_REPO" "$RECEIPTS_TAG"
    # Both assets come from the SAME release, so the key that is checked is the
    # one that release published alongside the receipt.
    run_step gh release download "$RECEIPTS_TAG" -R "$PUBLISHED_REPO" -D "$WORK" \
      -p 'pr*-clean.odr.json' -p 'aragora-odr-signing.pub.pem' --clobber \
      || fail receipt-download $?
    PUBLISHED_ODR=""
    for candidate in "$WORK"/pr*-clean.odr.json; do
      if [ -f "$candidate" ]; then
        PUBLISHED_ODR=$candidate
        break
      fi
    done
    if [ -z "$PUBLISHED_ODR" ] || [ ! -f "$WORK/aragora-odr-signing.pub.pem" ]; then
      printf 'receipt-first-hour: release %s has no pr*-clean.odr.json + public key pair\n' \
        "$RECEIPTS_TAG" >&2
      fail published 1
    fi
    run_step "$VENV/bin/aragora-verify" "$PUBLISHED_ODR" \
      --pubkey "$WORK/aragora-odr-signing.pub.pem" || fail published $?
  fi
fi

finish 0
