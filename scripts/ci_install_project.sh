#!/usr/bin/env bash
set -euo pipefail

EXTRAS=""
PROJECT_DIR=""
INSTALL_MODE="editable"
INSTALL_SCOPE="system"

readonly LEGACY_CONTROL_PLANE_PACKAGE_NAMES=("aragora-debate" "aragora")
readonly LEGACY_CONTROL_PLANE_MARKER_PATH="aragora/server"

# Floor pins below are kept in lockstep with `pyproject.toml`'s
# `[project.optional-dependencies]` (test/gateway/enterprise/dev/all). The
# constraint solver enforces the higher floor at install time — having the
# two files disagree creates noise and confusion. If pyproject.toml raises
# any floor, mirror it here.
LEGACY_CONTROL_PLANE_BASE_DEPS=(
  "aiohttp>=3.14.1,<4.0"             # aligned to pyproject base/[blockchain]/[all]
  "websockets>=13.0,<15.1"
  "pyyaml>=6.0.3,<7.0"
  "pydantic>=2.13.4,<3.0"            # aligned to pyproject [test]
  "pydantic-settings>=2.14.2,<3.0"   # security floor: GHSA-4xgf-cpjx-pc3j
  "bcrypt>=4.2,<6.0"                 # security floor: 4.0 -> 4.2 (defensive)
  "cryptography>=46.0.7,<48.0"       # security floor: 46.0 -> 46.0.7 (latest 46.x patch)
  "markupsafe>=2.1.0,<4.0"
  "defusedxml>=0.7,<1.0"
  "pyotp>=2.9,<3.0"
  "jinja2>=3.1.6,<4.0"
  "urllib3>=2.6.3,<3.0"
  "httpx>=0.27,<1.0"
  "numpy>=2.0,<3.0"
  "watchfiles>=0.21,<2.0"
  "boto3>=1.34,<2.0"
  "PyJWT>=2.10.1,<3.0"               # security floor: 2.8 -> 2.10.1
  "fastapi>=0.135.3,<1.0"            # aligned to pyproject [gateway]/[all]
  "uvicorn[standard]>=0.44.0,<1.0"   # aligned to pyproject [gateway]/[all]
  "python-multipart>=0.0.26"         # security floor: 0.0.22 -> 0.0.26 (CVE-2024-53981 covered by 0.0.18+)
  "mcp>=1.0,<2.0"
)

LEGACY_CONTROL_PLANE_DEV_DEPS=(
  "pytest>=9.1.1,<10.0"              # aligned to pyproject [test]
  "pytest-asyncio>=1.4.0,<2.0"
  "pytest-benchmark>=4.0,<6.0"
  "pytest-cov>=7.0.0,<8.0"
  "pytest-timeout>=2.4.0,<3.0"
  "pytest-xdist>=3.8.0,<4.0"
  "pytest-rerunfailures>=16.1,<17.0"
  "pytest-randomly>=4.0.1,<6.0"
  "black>=23.0,<27.0"
  "ruff>=0.1,<1.0"
  "bandit>=1.7,<2.0"
  "mypy>=1.19.0,<2.0"                # aligned to pyproject [dev]
  "types-jsonschema"
  "types-PyYAML"
  "mutmut>=3.0,<4.0"
  "pre-commit>=3.6,<5.0"
  "datamodel-code-generator==0.54.0"
  "async-timeout>=4.0,<6.0"
  "python3-saml>=1.16.0,<2.0"        # aligned to pyproject [enterprise]/[all]
  "tiktoken>=0.5,<1.0"
)

LEGACY_CONTROL_PLANE_TEST_EXTRA_DEPS=(
  "aiosqlite>=0.19,<1.0"
  "supabase>=2.0,<3.0"
  "redis>=5.0.0,<8.0"
  "asyncpg>=0.31.0,<1.0"             # aligned to pyproject [enterprise]/[all]
  "yt-dlp>=2024.1,<2027.0"
  "anthropic>=0.111,<1.0"
  "openai>=2.0,<3.0"
  "twilio>=8.0,<10.0"
  "langchain>=1.0,<2.0"
  "weaviate-client>=4.0,<5.0"
  "z3-solver>=4.12,<5.0"
  "weasyprint>=68.0,<70.0"
  "reportlab>=3.6,<5.0"
  "scikit-learn>=1.5.0,<2.0"
  "pydub>=0.25.0,<1.0"
  "duckduckgo-search>=6.0,<9.0"
  "pillow>=12.1.1"
)

LEGACY_CONTROL_PLANE_HEAVY_ML_TEST_DEPS=(
  "sentence-transformers>=3.0.0,<6.0"
)

LEGACY_CONTROL_PLANE_MONITORING_DEPS=(
  "prometheus-client>=0.19,<1.0"
  "sentry-sdk>=2.0,<3.0"
)

LEGACY_CONTROL_PLANE_OBSERVABILITY_DEPS=(
  "opentelemetry-api>=1.20.0,<2.0"
  "opentelemetry-sdk>=1.20.0,<2.0"
  "opentelemetry-exporter-otlp>=1.20.0,<2.0"
  "opentelemetry-instrumentation-logging>=0.41b0,<1.0"
  "prometheus-client>=0.19,<1.0"
  "protobuf>=6.33.5"
)

LEGACY_CONTROL_PLANE_REDIS_DEPS=(
  "redis>=5.0.0,<8.0"
)

LEGACY_CONTROL_PLANE_PERSISTENCE_DEPS=(
  "supabase>=2.0,<3.0"
  "sqlalchemy>=2.0.40,<3.0"
)

LEGACY_CONTROL_PLANE_POSTGRES_DEPS=(
  "asyncpg>=0.29.0,<1.0"
  "alembic>=1.13.0,<2.0"
  "nest_asyncio>=1.5,<2.0"
)

while [[ $# -gt 0 ]]; do
  case "$1" in
    --extras)
      EXTRAS="${2:-}"
      shift 2
      ;;
    --project-dir)
      PROJECT_DIR="${2:-}"
      shift 2
      ;;
    --install-mode)
      INSTALL_MODE="${2:-}"
      shift 2
      ;;
    --install-scope)
      INSTALL_SCOPE="${2:-}"
      shift 2
      ;;
    *)
      echo "Unknown argument: $1" >&2
      exit 2
      ;;
  esac
done

if [[ "$INSTALL_MODE" != "editable" && "$INSTALL_MODE" != "standard" ]]; then
  echo "Unknown install mode: $INSTALL_MODE" >&2
  exit 2
fi

if [[ "$INSTALL_SCOPE" != "system" && "$INSTALL_SCOPE" != "user" ]]; then
  echo "Unknown install scope: $INSTALL_SCOPE" >&2
  exit 2
fi

has_project_markers() {
  local dir="$1"
  [[ -f "${dir}/pyproject.toml" || -f "${dir}/setup.py" ]]
}

resolve_project_root() {
  local start="$1"
  [[ -n "$start" ]] || return 1
  local dir
  dir="$(cd "$start" 2>/dev/null && pwd -P)" || return 1
  while [[ "$dir" != "/" ]]; do
    if has_project_markers "$dir"; then
      printf '%s\n' "$dir"
      return 0
    fi
    dir="$(dirname "$dir")"
  done
  if has_project_markers "/"; then
    printf '/\n'
    return 0
  fi
  return 1
}

project_name() {
  local pyproject_path="$1/pyproject.toml"
  [[ -f "$pyproject_path" ]] || return 1
  python - "$pyproject_path" <<'PY'
from __future__ import annotations

import sys
from pathlib import Path
text = Path(sys.argv[1]).read_text(encoding="utf-8")

try:
    import tomllib  # type: ignore[attr-defined]
except ModuleNotFoundError:
    tomllib = None  # type: ignore[assignment]

if tomllib is not None:
    data = tomllib.loads(text)
    name = data.get("project", {}).get("name", "")
else:
    # Python 3.10 hosts may not have tomli installed yet. Fall back to a
    # minimal parser that only needs the root [project].name field.
    name = ""
    in_project = False
    for raw_line in text.splitlines():
        line = raw_line.split("#", 1)[0].strip()
        if not line:
            continue
        if line.startswith("[") and line.endswith("]"):
            in_project = line == "[project]"
            continue
        if not in_project or not line.startswith("name"):
            continue
        _, _, value = line.partition("=")
        value = value.strip()
        if (value.startswith('"') and value.endswith('"')) or (
            value.startswith("'") and value.endswith("'")
        ):
            name = value[1:-1]
        break

print(name if isinstance(name, str) else "")
PY
}

is_legacy_control_plane_root() {
  local root="$1"
  local name
  local package_name
  [[ -d "$root/$LEGACY_CONTROL_PLANE_MARKER_PATH" ]] || return 1
  name="$(project_name "$root")"
  for package_name in "${LEGACY_CONTROL_PLANE_PACKAGE_NAMES[@]}"; do
    if [[ "$name" == "$package_name" ]]; then
      return 0
    fi
  done
  return 1
}

install_legacy_control_plane_deps() {
  local extras="$1"
  local -a deps=("${LEGACY_CONTROL_PLANE_BASE_DEPS[@]}")
  local -a requested_extras=()
  local skip_heavy_ml_test_deps="${ARAGORA_CI_SKIP_HEAVY_ML_TEST_DEPS:-0}"

  append_unique_deps() {
    local dep
    local existing
    local already_present
    for dep in "$@"; do
      already_present=0
      for existing in "${deps[@]}"; do
        if [[ "$existing" == "$dep" ]]; then
          already_present=1
          break
        fi
      done
      if [[ "$already_present" -eq 0 ]]; then
        deps+=("$dep")
      fi
    done
  }

  trim_whitespace() {
    local value="$1"
    value="${value#"${value%%[![:space:]]*}"}"
    value="${value%"${value##*[![:space:]]}"}"
    printf '%s\n' "$value"
  }

  if [[ -n "$extras" ]]; then
    IFS=',' read -r -a requested_extras <<< "$extras"
  fi

  local extra
  for extra in "${requested_extras[@]}"; do
    extra="$(trim_whitespace "$extra")"
    case "$extra" in
      "")
        ;;
      dev)
        append_unique_deps "${LEGACY_CONTROL_PLANE_DEV_DEPS[@]}"
        ;;
      test)
        append_unique_deps "${LEGACY_CONTROL_PLANE_DEV_DEPS[@]}"
        append_unique_deps "${LEGACY_CONTROL_PLANE_TEST_EXTRA_DEPS[@]}"
        if [[ "$skip_heavy_ml_test_deps" != "1" ]]; then
          append_unique_deps "${LEGACY_CONTROL_PLANE_HEAVY_ML_TEST_DEPS[@]}"
        fi
        ;;
      monitoring)
        append_unique_deps "${LEGACY_CONTROL_PLANE_MONITORING_DEPS[@]}"
        ;;
      observability)
        append_unique_deps "${LEGACY_CONTROL_PLANE_OBSERVABILITY_DEPS[@]}"
        ;;
      redis)
        append_unique_deps "${LEGACY_CONTROL_PLANE_REDIS_DEPS[@]}"
        ;;
      persistence)
        append_unique_deps "${LEGACY_CONTROL_PLANE_PERSISTENCE_DEPS[@]}"
        ;;
      postgres)
        append_unique_deps "${LEGACY_CONTROL_PLANE_POSTGRES_DEPS[@]}"
        ;;
      rlm)
        ;;
      *)
        echo "::warning::Unknown legacy control-plane extra '$extra'; skipping." >&2
        ;;
    esac
  done

  if [[ "$skip_heavy_ml_test_deps" == "1" ]]; then
    echo "[ci-install] skipping heavy ML test deps via ARAGORA_CI_SKIP_HEAVY_ML_TEST_DEPS=1"
  fi

  run_pip_install "${deps[@]}"
}

run_pip_install() {
  if [[ "$INSTALL_SCOPE" == "user" ]]; then
    python -m pip install --user "$@"
  else
    python -m pip install "$@"
  fi
}

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
REPO_HINT="$(cd "${SCRIPT_DIR}/.." && pwd -P)"

declare -a CANDIDATES=()
if [[ -n "$PROJECT_DIR" ]]; then
  CANDIDATES+=("$PROJECT_DIR")
fi
CANDIDATES+=("$PWD")
if [[ -n "${GITHUB_WORKSPACE:-}" ]]; then
  CANDIDATES+=("${GITHUB_WORKSPACE}")
fi
CANDIDATES+=("$REPO_HINT")

PROJECT_ROOT=""
for candidate in "${CANDIDATES[@]}"; do
  if root="$(resolve_project_root "$candidate" 2>/dev/null)"; then
    PROJECT_ROOT="$root"
    break
  fi
done

if [[ -z "$PROJECT_ROOT" ]]; then
  echo "::error::Could not find pyproject.toml/setup.py for editable install." >&2
  echo "PWD=$PWD" >&2
  echo "GITHUB_WORKSPACE=${GITHUB_WORKSPACE:-}" >&2
  exit 1
fi

cd "$PROJECT_ROOT"
echo "[ci-install] project_root=$PROJECT_ROOT extras=${EXTRAS:-none}"

if is_legacy_control_plane_root "$PROJECT_ROOT"; then
  echo "[ci-install] detected standalone root metadata; restoring legacy control-plane deps"
  if [[ "$INSTALL_MODE" == "editable" ]]; then
    run_pip_install -e .
  else
    run_pip_install .
  fi
  install_legacy_control_plane_deps "$EXTRAS"
else
  if [[ -n "$EXTRAS" ]]; then
    if [[ "$INSTALL_MODE" == "editable" ]]; then
      run_pip_install -e ".[${EXTRAS}]"
    else
      run_pip_install ".[${EXTRAS}]"
    fi
  else
    if [[ "$INSTALL_MODE" == "editable" ]]; then
      run_pip_install -e .
    else
      run_pip_install .
    fi
  fi
fi
