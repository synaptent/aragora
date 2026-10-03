#!/usr/bin/env bash
# Explicit Claude CLI profile selector for local Aragora runs.
#
# This helper is intentionally explicit. It does not auto-fail over between
# accounts. Instead, it lets you choose which Claude profile Aragora should
# inherit for one command or one login flow.

set -euo pipefail

usage() {
  cat <<'EOF'
Usage:
  claude_profile.sh home <profile-name-or-home>
  claude_profile.sh status <profile-name-or-home>
  claude_profile.sh login <profile-name-or-home>
  claude_profile.sh logout <profile-name-or-home>
  claude_profile.sh exec <profile-name-or-home> -- <command...>
  claude_profile.sh exec-claude <profile-name> --model MODEL --timeout-seconds N -- [--output-format json|text]

Examples:
  scripts/claude_profile.sh status max-01
  scripts/claude_profile.sh login max-02
  scripts/claude_profile.sh exec max-01 -- \
    python3 -m aragora.cli.main ralph campaign-supervisor status --json

Conventions:
  Bare profile names resolve under ~/.aragora-claude by default.
  <profile-home> is a directory that contains its own .claude state.
  The helper sets HOME=<profile-home> for the command it runs.
EOF
}

die() {
  echo "error: $*" >&2
  exit 1
}

require_command() {
  command -v "$1" >/dev/null 2>&1 || die "missing required command: $1"
}

if [[ $# -lt 2 ]]; then
  usage
  exit 1
fi

MODE="$1"
PROFILE_HOME="$2"
shift 2

# Deliberately bypass generic exec: only the native child may receive its token.
# Do this before profile-directory creation or the unrelated GitHub-token lookup.
if [[ "$MODE" == "exec-claude" ]]; then
  exec python3 "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/native_claude_launch.py" \
    "$PROFILE_HOME" "$@"
fi

require_command claude

ORIGINAL_HOME="$HOME"
ORIGINAL_GH_CONFIG_DIR="${GH_CONFIG_DIR:-${ORIGINAL_HOME}/.config/gh}"
ORIGINAL_GH_TOKEN=""

PROFILE_ROOT="${CLAUDE_PROFILE_ROOT:-${HOME}/.aragora-claude}"

if [[ -n "${ARAGORA_CLAUDE_PROFILE:-}" ]]; then
  PROFILE_HOME="${ARAGORA_CLAUDE_PROFILE}"
fi

resolve_profile_home() {
  local raw_path="$1"

  case "$raw_path" in
    "~") raw_path="${HOME}" ;;
    "~"/*) raw_path="${HOME}${raw_path#"~"}" ;;
    /*) ;;
    ./*|../*)
      raw_path="$(cd "$(dirname "$raw_path")" && pwd)/$(basename "$raw_path")"
      ;;
    *)
      raw_path="${PROFILE_ROOT}/${raw_path}"
      ;;
  esac

  local raw_parent
  raw_parent="$(dirname "$raw_path")"
  mkdir -p "$raw_parent"
  raw_path="$(cd "$raw_parent" && pwd)/$(basename "$raw_path")"
  mkdir -p "$raw_path"
  printf '%s\n' "$raw_path"
}

PROFILE_HOME="$(resolve_profile_home "$PROFILE_HOME")"

if command -v gh >/dev/null 2>&1; then
  if ORIGINAL_GH_TOKEN="$(
    HOME="${ORIGINAL_HOME}" \
    GH_CONFIG_DIR="${ORIGINAL_GH_CONFIG_DIR}" \
    gh auth token 2>/dev/null
  )"; then
    :
  else
    ORIGINAL_GH_TOKEN=""
  fi
fi

run_with_profile() {
  HOME="$PROFILE_HOME" \
  XDG_CONFIG_HOME="${PROFILE_HOME}/.config" \
  CLAUDE_CONFIG_DIR="${PROFILE_HOME}/.claude" \
  CODEX_HOME="${CODEX_HOME:-${ORIGINAL_HOME}/.codex}" \
  GH_CONFIG_DIR="${ORIGINAL_GH_CONFIG_DIR}" \
  GH_TOKEN="${GH_TOKEN:-${ORIGINAL_GH_TOKEN}}" \
  PATH="${PATH}" \
  env \
    -u ANTHROPIC_API_KEY \
    -u CLAUDECODE \
    -u CLAUDE_CODE_ENTRYPOINT \
    ARAGORA_OPENROUTER_FALLBACK_ENABLED=false \
    OPENROUTER_API_KEY= \
    "$@"
}

case "$MODE" in
  home)
    if [[ $# -ne 0 ]]; then
      die "home does not take extra arguments"
    fi
    printf '%s\n' "$PROFILE_HOME"
    ;;
  status)
    if [[ $# -ne 0 ]]; then
      die "status does not take extra arguments"
    fi
    run_with_profile claude auth status
    ;;
  login)
    if [[ $# -ne 0 ]]; then
      die "login does not take extra arguments"
    fi
    mkdir -p "${PROFILE_HOME}/.claude" "${PROFILE_HOME}/.config"
    echo "Using profile home: ${PROFILE_HOME}"
    run_with_profile claude auth login
    ;;
  logout)
    if [[ $# -ne 0 ]]; then
      die "logout does not take extra arguments"
    fi
    run_with_profile claude auth logout
    ;;
  exec)
    if [[ $# -lt 2 || "$1" != "--" ]]; then
      die "exec requires '-- <command...>'"
    fi
    shift
    mkdir -p "${PROFILE_HOME}/.claude" "${PROFILE_HOME}/.config"
    echo "Using profile home: ${PROFILE_HOME}"
    echo "Command: $*"
    run_with_profile "$@"
    ;;
  *)
    usage
    exit 1
    ;;
esac
