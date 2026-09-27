#!/usr/bin/env bash
# Install a launchd job that runs the codex automation publisher bridge on an interval.

set -euo pipefail

SCRIPT_REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"

first_worktree_root() {
    git -C "${SCRIPT_REPO_ROOT}" worktree list --porcelain 2>/dev/null \
        | awk 'NR == 1 && $1 == "worktree" { sub(/^worktree /, ""); print; exit }'
}

REPO_ROOT="${ARAGORA_AUTOMATION_PUBLISHER_REPO_ROOT:-}"
if [[ -z "${REPO_ROOT}" ]]; then
    CANONICAL_REPO_ROOT="$(first_worktree_root || true)"
    if [[ -n "${CANONICAL_REPO_ROOT}" && -f "${CANONICAL_REPO_ROOT}/scripts/run_codex_automation_publisher.sh" ]]; then
        REPO_ROOT="${CANONICAL_REPO_ROOT}"
    else
        REPO_ROOT="${SCRIPT_REPO_ROOT}"
    fi
fi
LABEL="com.aragora.codex-automation-publisher"
LAUNCHD_DOMAIN="gui/$(id -u)"
INTERVAL_SECONDS=300
LOG_PATH="${REPO_ROOT}/.aragora/overnight/codex-automation-publisher.log"
CACHE_ONLY="false"
DRY_RUN="false"
PLIST_PATH_OVERRIDE=""

usage() {
    cat <<'EOF'
Usage: ./scripts/install_codex_automation_publisher_launchd.sh [options]

Options:
  --interval-seconds <n>        launchd StartInterval (default: 300)
  --log-path <file>             Log file path (default: .aragora/overnight/codex-automation-publisher.log)
  --cache-only                 Refresh health/cache without publishing branches or handoffs
  --dry-run                    Render the plist without calling launchctl
  --plist-path <file>          Write the plist to this path (useful with --dry-run)
  --help                        Show this help
EOF
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --interval-seconds)
            INTERVAL_SECONDS="${2:-300}"
            shift 2
            ;;
        --log-path)
            LOG_PATH="${2:-}"
            shift 2
            ;;
        --cache-only)
            CACHE_ONLY="true"
            shift
            ;;
        --dry-run)
            DRY_RUN="true"
            shift
            ;;
        --plist-path)
            PLIST_PATH_OVERRIDE="${2:-}"
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

PLIST_PATH="${PLIST_PATH_OVERRIDE:-${HOME}/Library/LaunchAgents/${LABEL}.plist}"
PUBLISHER_COMMAND="cd \"${REPO_ROOT}\" && ./scripts/run_codex_automation_publisher.sh"
if [[ "${CACHE_ONLY}" == "true" ]]; then
    PUBLISHER_COMMAND="cd \"${REPO_ROOT}\" && ARAGORA_AUTOMATION_CACHE_ONLY=1 ./scripts/run_codex_automation_publisher.sh"
fi
PUBLISHER_COMMAND_XML="${PUBLISHER_COMMAND//&/&amp;}"

render_plist() {
cat <<EOF
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
    <string>${PUBLISHER_COMMAND_XML}</string>
  </array>
  <key>RunAtLoad</key>
  <true/>
  <key>StartInterval</key>
  <integer>${INTERVAL_SECONDS}</integer>
  <key>WorkingDirectory</key>
  <string>${REPO_ROOT}</string>
  <key>StandardOutPath</key>
  <string>${LOG_PATH}</string>
  <key>StandardErrorPath</key>
  <string>${LOG_PATH}</string>
</dict>
</plist>
EOF
}

if [[ "${DRY_RUN}" == "true" ]]; then
    if [[ -n "${PLIST_PATH_OVERRIDE}" ]]; then
        mkdir -p "$(dirname "${PLIST_PATH}")"
        render_plist >"${PLIST_PATH}"
        echo "Rendered launchd job: ${LABEL}" >&2
        echo "Plist: ${PLIST_PATH}" >&2
        echo "Mode: $([[ "${CACHE_ONLY}" == "true" ]] && echo cache-only || echo publish)" >&2
    else
        render_plist
    fi
    exit 0
fi

mkdir -p "$(dirname "${PLIST_PATH}")"
mkdir -p "$(dirname "${LOG_PATH}")"
render_plist >"${PLIST_PATH}"

launchctl bootout "${LAUNCHD_DOMAIN}" "${PLIST_PATH}" >/dev/null 2>&1 || true
launchctl bootstrap "${LAUNCHD_DOMAIN}" "${PLIST_PATH}"
launchctl kickstart -k "${LAUNCHD_DOMAIN}/${LABEL}" >/dev/null 2>&1 || true

echo "Installed launchd job: ${LABEL}"
echo "Plist: ${PLIST_PATH}"
echo "Interval: ${INTERVAL_SECONDS}s"
echo "Log: ${LOG_PATH}"
echo "Mode: $([[ "${CACHE_ONLY}" == "true" ]] && echo cache-only || echo publish)"
echo "--- launchctl ---"
launchctl print "${LAUNCHD_DOMAIN}/${LABEL}" | sed -n '1,20p'
