#!/usr/bin/env bash
# Run one X intake digest cycle: fetch new bookmarks + likes from the X API
# (OAuth2 user context; see scripts/x_oauth_setup.py) into the ideacloud
# vault, then emit a digest artifact with a SHA-256 receipt line.
#
# Posture: "panel evaluates, creates nothing" — this job ingests and
# digests; issue filing stays a human-triggered step through
# scripts/rank_research_candidates.py and the research-intake lane.
#
# Designed for periodic invocation via launchd or cron. Exits 0 on success.

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "${REPO_ROOT}"
# shellcheck source=scripts/aragora_runtime.sh
source "${REPO_ROOT}/scripts/aragora_runtime.sh"

MAX_ITEMS="${ARAGORA_X_INTAKE_MAX_ITEMS:-200}"
VAULT="${ARAGORA_X_INTAKE_VAULT:-.aragora_ideas}"
DIGEST_DIR="${ARAGORA_X_INTAKE_DIGEST_DIR:-${REPO_ROOT}/.aragora/x_intake/digests}"

mkdir -p "${DIGEST_DIR}"

if ! ARAGORA_PYTHON="$(resolve_aragora_python 'import pydantic' 'x-intake' 'x intake digest')"; then
    echo "$(date -u +'%Y-%m-%dT%H:%M:%SZ') ERROR: no usable python3 found" >&2
    exit 2
fi

stamp="$(date -u +'%Y%m%dT%H%M%SZ')"
log() { echo "$(date -u +'%Y-%m-%dT%H:%M:%SZ') $*"; }

log "START x intake digest (max_items=${MAX_ITEMS}, vault=${VAULT})"

for source in twitter-bookmarks twitter-likes; do
    if ! "${ARAGORA_PYTHON}" -m aragora.cli.main ideacloud load \
        --source "${source}" --api "${MAX_ITEMS}" --vault "${VAULT}"; then
        log "WARN ${source} ingestion failed (missing OAuth tokens?) — continuing"
    fi
done

digest_file="${DIGEST_DIR}/digest-${stamp}.md"
# --limit: the CLI defaults to 20, which would silently truncate the digest
if ! "${ARAGORA_PYTHON}" -m aragora.cli.main ideacloud list --vault "${VAULT}" \
    --limit 100000 > "${digest_file}" 2>/dev/null; then
    log "WARN ideacloud list failed; digest file may be empty"
fi

if command -v shasum >/dev/null 2>&1; then
    checksum="$(shasum -a 256 "${digest_file}" | awk '{print $1}')"
else
    checksum="$(sha256sum "${digest_file}" | awk '{print $1}')"
fi
echo "{\"digest\": \"${digest_file}\", \"sha256\": \"${checksum}\", \"generated_at\": \"${stamp}\"}" \
    > "${DIGEST_DIR}/digest-${stamp}.receipt.json"

log "OK x intake digest complete (${digest_file}, sha256=${checksum})"
