#!/usr/bin/env bash
# Install a launchd job that keeps aragora Claude profiles alive by consuming
# VibeProxy's already-fresh access tokens (scripts/sync_claude_profiles_from_vibeproxy.py).
#
# Why this exists: Anthropic OAuth single-use-rotates refresh tokens, so two
# independent refreshers on the same account revoke each other. VibeProxy stays
# alive because it is the SOLE refresher of its accounts; aragora stops competing
# and instead syncs VibeProxy's fresh access token into the matching profile,
# writing it WITHOUT a usable refresh token (pure consumer). Run more often than
# the ~8h access-token TTL so a synced token never lapses between cycles.
set -euo pipefail

LABEL="com.aragora.claude-profile-sync"
# 5 min: must be <= VibeProxy's refresh lead (~10 min before the ~8h expiry) so a
# sync always lands in the [expiry-10min, expiry] window and picks up the newly
# refreshed token before the old one lapses. A wider interval leaves the profile
# holding an expired, blank-refresh token for up to (interval - lead) every ~8h.
INTERVAL_SECONDS=300
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LOG_PATH="${HOME}/.aragora/claude-profile-sync.log"
PYTHON_BIN="${ARAGORA_PYTHON:-python3}"
SCRIPT_NAME="sync_claude_profiles_from_vibeproxy.py"
# Deploy the sync script to a stable location OUTSIDE any git checkout: session
# worktrees are TTL-cleaned, and pointing launchd at the main checkout would let
# a later merge of the same tracked filename collide with the untracked copy.
DEPLOY_DIR="${HOME}/.aragora/bin"
DEPLOY_PATH="${DEPLOY_DIR}/${SCRIPT_NAME}"
# launchd runs with a minimal PATH; the sync itself needs only python, but keep
# the same explicit PATH as the sibling verify job for the optional probe path.
BIN_PATH="${HOME}/.local/bin:/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin"

usage() {
  cat <<EOF
Usage: $(basename "$0") [--interval-seconds <n>] [--python <path>] [--path <PATH>]
  --interval-seconds <n>   launchd StartInterval (default: ${INTERVAL_SECONDS})
  --python <path>          Python interpreter (default: ${PYTHON_BIN})
  --path <PATH>            PATH for the job
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --interval-seconds) INTERVAL_SECONDS="$2"; shift 2 ;;
    --python) PYTHON_BIN="$2"; shift 2 ;;
    --path) BIN_PATH="$2"; shift 2 ;;
    -h|--help) usage; exit 0 ;;
    *) echo "Unknown argument: $1" >&2; usage; exit 2 ;;
  esac
done

PLIST_PATH="${HOME}/Library/LaunchAgents/${LABEL}.plist"
mkdir -p "$(dirname "$PLIST_PATH")"
mkdir -p "$(dirname "$LOG_PATH")"
mkdir -p "${DEPLOY_DIR}"

# The log records profile/email lines (emails masked, but keep it owner-only).
touch "${LOG_PATH}" && chmod 0600 "${LOG_PATH}"

# Deploy the current repo copy of the sync script to the stable location.
cp "${REPO_ROOT}/scripts/${SCRIPT_NAME}" "${DEPLOY_PATH}"
chmod 0755 "${DEPLOY_PATH}"

# Seed the untracked local mapping config from the example if absent. The map
# (operator emails) is intentionally NOT in tracked source; fill it in before
# the daemon can sync anything.
CONFIG_PATH="${HOME}/.aragora/claude_profile_sync.json"
if [[ ! -f "${CONFIG_PATH}" ]]; then
  cp "${REPO_ROOT}/scripts/claude_profile_sync.json.example" "${CONFIG_PATH}"
  chmod 0600 "${CONFIG_PATH}"
  echo "NOTE: seeded ${CONFIG_PATH} from the example — edit it with your real email->profile map."
fi

# launchd runs with a minimal environment, so capture the sync script's override
# env vars at install time and bake them into the job. Otherwise an operator who
# uses a non-default profile root / config in their shell installs a daemon that
# silently writes to the DEFAULT locations, leaving the real pool stale.
ENV_EXPORTS="export PATH=\"${BIN_PATH}\""
if [[ -n "${CLAUDE_PROFILE_ROOT:-}" ]]; then
  ENV_EXPORTS+=" CLAUDE_PROFILE_ROOT=\"${CLAUDE_PROFILE_ROOT}\""
fi
if [[ -n "${ARAGORA_PROFILE_SYNC_CONFIG:-}" ]]; then
  ENV_EXPORTS+=" ARAGORA_PROFILE_SYNC_CONFIG=\"${ARAGORA_PROFILE_SYNC_CONFIG}\""
fi

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
    <string>${ENV_EXPORTS} &amp;&amp; "${PYTHON_BIN}" "${DEPLOY_PATH}" --apply</string>
  </array>
  <key>RunAtLoad</key>
  <true/>
  <key>StartInterval</key>
  <integer>${INTERVAL_SECONDS}</integer>
  <key>WorkingDirectory</key>
  <string>${HOME}</string>
  <key>StandardOutPath</key>
  <string>${LOG_PATH}</string>
  <key>StandardErrorPath</key>
  <string>${LOG_PATH}</string>
</dict>
</plist>
EOF

launchctl unload "${PLIST_PATH}" >/dev/null 2>&1 || true
launchctl load "${PLIST_PATH}"

echo "Installed launchd job: ${LABEL}"
echo "Plist: ${PLIST_PATH}"
echo "Deployed script: ${DEPLOY_PATH}"
echo "Interval: ${INTERVAL_SECONDS}s"
echo "Log: ${LOG_PATH}"
echo "Uninstall: launchctl unload \"${PLIST_PATH}\" && rm \"${PLIST_PATH}\""
echo
echo "ONE-TIME bootstrap (the daemon runs without --force and skips native/dead"
echo "profiles): once your config is filled in, convert them with --force. Run it"
echo "from the repo so --probe-after can find claude_profile.sh (the deployed copy"
echo "cannot, and would report probe=SKIP):"
echo "  (cd \"${REPO_ROOT}\" && \"${PYTHON_BIN}\" scripts/${SCRIPT_NAME} --apply --force --probe-after)"
