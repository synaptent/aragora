#!/usr/bin/env bash
# Install a launchd job that runs one X intake digest cycle per interval
# (bookmarks + likes -> ideacloud vault -> digest artifact + receipt).
#
# Same shape as scripts/install_codex_insights_digest_launchd.sh so operators
# have one mental model for periodic digest jobs.
#
# Defaults: weekly (604800 seconds), logs to .aragora/overnight/x-intake-digest.log.
# Requires OAuth tokens from scripts/x_oauth_setup.py; the job degrades to a
# no-op warning without them.

set -euo pipefail

SCRIPT_REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"

first_worktree_root() {
    git -C "${SCRIPT_REPO_ROOT}" worktree list --porcelain 2>/dev/null \
        | awk 'NR == 1 && $1 == "worktree" { sub(/^worktree /, ""); print; exit }'
}

REPO_ROOT="${ARAGORA_X_INTAKE_REPO_ROOT:-}"
if [[ -z "${REPO_ROOT}" ]]; then
    CANONICAL_REPO_ROOT="$(first_worktree_root || true)"
    if [[ -n "${CANONICAL_REPO_ROOT}" && -f "${CANONICAL_REPO_ROOT}/scripts/run_x_intake_digest.sh" ]]; then
        REPO_ROOT="${CANONICAL_REPO_ROOT}"
    else
        REPO_ROOT="${SCRIPT_REPO_ROOT}"
    fi
fi
LABEL="com.aragora.x-intake-digest"
LAUNCHD_DOMAIN="gui/$(id -u)"
INTERVAL_SECONDS=604800
LOG_PATH="${REPO_ROOT}/.aragora/overnight/x-intake-digest.log"
MAX_ITEMS="200"

usage() {
    cat <<'EOF'
Usage: ./scripts/install_x_intake_digest_launchd.sh [options]

Options:
  --interval-seconds <n>   launchd StartInterval (default: 604800 = weekly)
  --max-items <n>          Max new items fetched per source per run (default: 200)
  --log-path <file>        Log file path (default: .aragora/overnight/x-intake-digest.log)
  --help                   Show this help
EOF
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --interval-seconds)
            INTERVAL_SECONDS="${2:-604800}"
            shift 2
            ;;
        --max-items)
            MAX_ITEMS="${2:-200}"
            shift 2
            ;;
        --log-path)
            LOG_PATH="${2:-}"
            shift 2
            ;;
        --help|-h)
            usage
            exit 0
            ;;
        *)
            echo "Unknown option: $1" >&2
            usage
            exit 2
            ;;
    esac
done

if ! [[ "${INTERVAL_SECONDS}" =~ ^[0-9]+$ ]]; then
    echo "interval must be numeric" >&2
    exit 2
fi
if ! [[ "${MAX_ITEMS}" =~ ^[0-9]+$ ]]; then
    echo "--max-items must be numeric" >&2
    exit 2
fi
# REPO_ROOT and LOG_PATH are interpolated into the plist (bash -lc string /
# XML); refuse values that could break out of the quoting.
for interpolated in "${REPO_ROOT}" "${LOG_PATH}"; do
    case "${interpolated}" in
        *'"'*|*'$'*|*'`'*|*'&'*|*'<'*|*'>'*)
            echo "path contains shell/XML metacharacters unsafe for the plist: ${interpolated}" >&2
            exit 2
            ;;
    esac
done

PLIST_PATH="${HOME}/Library/LaunchAgents/${LABEL}.plist"
mkdir -p "$(dirname "${PLIST_PATH}")"
mkdir -p "$(dirname "${LOG_PATH}")"

cat >"${PLIST_PATH}" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>${LABEL}</string>
  <key>ProgramArguments</key>
  <array>
    <string>/bin/bash</string>
    <string>-lc</string>
    <string>cd "${REPO_ROOT}" &amp;&amp; ARAGORA_X_INTAKE_MAX_ITEMS="${MAX_ITEMS}" ./scripts/run_x_intake_digest.sh</string>
  </array>
  <key>StartInterval</key>
  <integer>${INTERVAL_SECONDS}</integer>
  <key>RunAtLoad</key>
  <false/>
  <key>WorkingDirectory</key>
  <string>${REPO_ROOT}</string>
  <key>StandardOutPath</key>
  <string>${LOG_PATH}</string>
  <key>StandardErrorPath</key>
  <string>${LOG_PATH}</string>
</dict>
</plist>
EOF

launchctl bootout "${LAUNCHD_DOMAIN}/${LABEL}" >/dev/null 2>&1 || true
launchctl bootstrap "${LAUNCHD_DOMAIN}" "${PLIST_PATH}"

echo "Installed launchd job: ${LABEL}"
echo "Plist:    ${PLIST_PATH}"
echo "Log:      ${LOG_PATH}"
echo "Interval: ${INTERVAL_SECONDS}s"
echo "Max items: ${MAX_ITEMS}"
echo
echo "Uninstall:  launchctl bootout ${LAUNCHD_DOMAIN}/${LABEL}; rm '${PLIST_PATH}'"
