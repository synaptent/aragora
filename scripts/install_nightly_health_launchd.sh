#!/usr/bin/env bash
# Render or install the nightly pristine-main, throughput, and weekly-digest
# LaunchAgents. All generated XML values are escaped before interpolation.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="${REPO_ROOT:-$(cd "${SCRIPT_DIR}/.." && pwd)}"
LAUNCH_AGENTS_DIR="${HOME}/Library/LaunchAgents"
LAUNCHD_PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"
PLUTIL_BIN="${PLUTIL_BIN:-$(command -v plutil || true)}"
LAUNCHCTL_BIN="${LAUNCHCTL_BIN:-$(command -v launchctl || true)}"

LABELS=(
  "com.aragora.pristine-main-health"
  "com.aragora.throughput-snapshot"
  "com.aragora.weekly-digest"
)

xml_escape() {
  local value="$1"
  value="${value//&/&amp;}"
  value="${value//</&lt;}"
  value="${value//>/&gt;}"
  printf '%s' "${value}"
}

shell_quote() {
  printf '%q' "$1"
}

usage() {
  cat >&2 <<'EOF'
usage:
  install_nightly_health_launchd.sh --dry-run LABEL
  install_nightly_health_launchd.sh --install

LABEL may be a full com.aragora.* label or one of:
  pristine-main-health | throughput-snapshot | weekly-digest
EOF
  exit 64
}

normalize_label() {
  case "$1" in
    pristine-main-health|com.aragora.pristine-main-health)
      printf '%s' "com.aragora.pristine-main-health"
      ;;
    throughput-snapshot|com.aragora.throughput-snapshot)
      printf '%s' "com.aragora.throughput-snapshot"
      ;;
    weekly-digest|com.aragora.weekly-digest)
      printf '%s' "com.aragora.weekly-digest"
      ;;
    *)
      echo "unknown label: $1" >&2
      return 64
      ;;
  esac
}

command_for() {
  local label="$1"
  local runtime_q repo_q script_q pristine_q halt_q handoff_q probe_q import_label_q runtime_label_q
  runtime_q="$(shell_quote "${REPO_ROOT}/scripts/aragora_runtime.sh")"
  repo_q="$(shell_quote "${REPO_ROOT}")"

  case "${label}" in
    com.aragora.pristine-main-health)
      script_q="$(shell_quote "${REPO_ROOT}/scripts/pristine_main_health.py")"
      pristine_q="$(shell_quote "${HOME}/.aragora/pristine-main-health")"
      halt_q="$(shell_quote "${REPO_ROOT}/.aragora/merge_executor.halt")"
      probe_q="$(shell_quote "import pytest")"
      import_label_q="$(shell_quote "pytest")"
      runtime_label_q="$(shell_quote "pristine-main health runtime")"
      # --suite required pinned explicitly: the full suite cannot finish in the
      # nightly timeout budget on this host (issue #9045); "full" is manual-only.
      printf 'source %s && PYTHON_BIN="$(resolve_aragora_python %s %s %s)" && exec "$PYTHON_BIN" %s --repo-root %s --pristine-dir %s --halt-file %s --suite required' \
        "${runtime_q}" "${probe_q}" "${import_label_q}" "${runtime_label_q}" \
        "${script_q}" "${repo_q}" "${pristine_q}" "${halt_q}"
      ;;
    com.aragora.throughput-snapshot)
      script_q="$(shell_quote "${REPO_ROOT}/scripts/throughput_ledger.py")"
      printf 'source %s && PYTHON_BIN="$(resolve_aragora_python)" && exec "$PYTHON_BIN" %s --repo-root %s snapshot --limit 40' \
        "${runtime_q}" "${script_q}" "${repo_q}"
      ;;
    com.aragora.weekly-digest)
      script_q="$(shell_quote "${REPO_ROOT}/scripts/weekly_digest.py")"
      handoff_q="$(shell_quote "${REPO_ROOT}/.aragora/operator-handoffs")"
      printf 'source %s && mkdir -p %s && PYTHON_BIN="$(resolve_aragora_python)" && exec "$PYTHON_BIN" %s --repo-root %s --out %s/weekly-digest-$(date +%%F).md' \
        "${runtime_q}" "${handoff_q}" "${script_q}" "${repo_q}" "${handoff_q}"
      ;;
    *)
      echo "unsupported label: ${label}" >&2
      return 64
      ;;
  esac
}

schedule_for() {
  case "$1" in
    com.aragora.pristine-main-health)
      printf '%s\n' '        <key>Hour</key><integer>3</integer>'
      printf '%s\n' '        <key>Minute</key><integer>30</integer>'
      ;;
    com.aragora.throughput-snapshot)
      printf '%s\n' '        <key>Hour</key><integer>7</integer>'
      printf '%s\n' '        <key>Minute</key><integer>30</integer>'
      ;;
    com.aragora.weekly-digest)
      printf '%s\n' '        <key>Weekday</key><integer>5</integer>'
      printf '%s\n' '        <key>Hour</key><integer>7</integer>'
      printf '%s\n' '        <key>Minute</key><integer>45</integer>'
      ;;
  esac
}

render_plist() {
  local label="$1"
  local command log_path schedule
  command="$(command_for "${label}")"
  log_path="${HOME}/.aragora/${label}.log"
  schedule="$(schedule_for "${label}")"

  cat <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>$(xml_escape "${label}")</string>
    <key>ProgramArguments</key>
    <array>
        <string>/bin/bash</string>
        <string>-lc</string>
        <string>$(xml_escape "${command}")</string>
    </array>
    <key>EnvironmentVariables</key>
    <dict>
        <key>PATH</key>
        <string>$(xml_escape "${LAUNCHD_PATH}")</string>
    </dict>
    <key>WorkingDirectory</key>
    <string>$(xml_escape "${REPO_ROOT}")</string>
    <key>StartCalendarInterval</key>
    <dict>
${schedule}
    </dict>
    <key>StandardOutPath</key>
    <string>$(xml_escape "${log_path}")</string>
    <key>StandardErrorPath</key>
    <string>$(xml_escape "${log_path}")</string>
</dict>
</plist>
EOF
}

install_all() {
  local stage_dir label staged destination
  [ -n "${PLUTIL_BIN}" ] || { echo "plutil is required" >&2; return 69; }
  [ -n "${LAUNCHCTL_BIN}" ] || { echo "launchctl is required" >&2; return 69; }

  stage_dir="$(mktemp -d "${TMPDIR:-/tmp}/aragora-nightly-launchd.XXXXXX")"
  trap "rm -rf $(shell_quote "${stage_dir}")" EXIT

  for label in "${LABELS[@]}"; do
    staged="${stage_dir}/${label}.plist"
    render_plist "${label}" > "${staged}"
    "${PLUTIL_BIN}" -lint "${staged}"
  done

  mkdir -p "${LAUNCH_AGENTS_DIR}" "${HOME}/.aragora"
  for label in "${LABELS[@]}"; do
    staged="${stage_dir}/${label}.plist"
    destination="${LAUNCH_AGENTS_DIR}/${label}.plist"
    if [ -f "${destination}" ]; then
      "${LAUNCHCTL_BIN}" unload "${destination}" 2>/dev/null || true
    fi
    install -m 0644 "${staged}" "${destination}"
    "${LAUNCHCTL_BIN}" load "${destination}"
    echo "installed ${label} -> ${destination}"
  done
}

case "${1:-}" in
  --dry-run)
    [ "$#" -eq 2 ] || usage
    render_plist "$(normalize_label "$2")"
    ;;
  --install)
    [ "$#" -eq 1 ] || usage
    install_all
    ;;
  *)
    usage
    ;;
esac
