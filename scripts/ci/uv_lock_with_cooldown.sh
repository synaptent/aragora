#!/usr/bin/env bash
# Regenerate uv.lock under a 7-day release-age cooldown without baking the
# cooldown into the committed lock. See --help for the two-step flow.
set -euo pipefail

COOLDOWN_DAYS=7
SCRATCH_ROOT=/tmp/aragora-readiness

usage() {
    cat <<'EOF'
Usage: bash scripts/ci/uv_lock_with_cooldown.sh [--help]

Regenerate uv.lock in the current directory ($PWD must hold pyproject.toml and,
normally, uv.lock) so that the resolution honours a release-age cooldown of
7 days, while the committed uv.lock never carries an exclude-newer pin.

Why two steps: a lock produced with --exclude-newer records an
`[options] exclude-newer = ...` table, and plain `uv lock --check` (the
BLOCKING step in security-gate.yml and dependabot-uv-lock.yml) fails on such
a lock. So `exclude-newer` is never written into uv.lock or pyproject.toml
(no `[tool.uv] exclude-newer`), and this script is the ONLY place the
cooldown applies. CI install steps run `uv sync --frozen`/`--locked` and
never set UV_EXCLUDE_NEWER.

Flow (every uv call runs with UV_EXCLUDE_NEWER unset):
  0. print `exclude-newer cutoff: <YYYY-MM-DD>` (UTC now minus 7 days)
  1. plain `uv lock` from the original lock -> temp copy (the plain resolution)
  2. `uv lock --exclude-newer <cutoff>` (the cutoff is 7 days ago) from the
     original lock -> temp copy (the cooled-down resolution)
  3. re-run plain `uv lock` on top of the cooled-down lock: uv keeps the
     cooled-down pins as preferences and drops only the `[options]` table,
     so the resulting uv.lock passes plain `uv lock --check`
  4. compare the package versions of the two temp copies; any package whose
     version differs was held back by the cooldown and is printed as
     `held back: <name> <plain> -> <cooled>`

Exit codes:
  0  cooled-down resolution equals the plain resolution; uv.lock is regenerated
  2  packages were held back (listed on stdout); uv.lock holds the cooled-down
     resolution and a human decides whether to commit it
  3  `uv` is not on PATH (nothing is touched)
  1  pyproject.toml missing, a uv step failed, or bad usage; the original
     uv.lock is restored byte-for-byte

Temp copies and any environment uv creates live under /tmp/aragora-readiness/.
EOF
}

case "${1:-}" in
    "") ;;
    -h|--help) usage; exit 0 ;;
    *) echo "error: unknown argument: $1" >&2; usage >&2; exit 1 ;;
esac

# GNU date takes -d; BSD/macOS date takes -v.
if date --version >/dev/null 2>&1; then
    CUTOFF="$(date -u -d "${COOLDOWN_DAYS} days ago" +%F)"
else
    CUTOFF="$(date -u -v-"${COOLDOWN_DAYS}"d +%F)"
fi
echo "exclude-newer cutoff: ${CUTOFF}"

if ! command -v uv >/dev/null 2>&1; then
    echo "error: 'uv' is not on PATH; install uv (https://docs.astral.sh/uv/) and re-run" >&2
    exit 3
fi

if [[ ! -f pyproject.toml ]]; then
    echo "error: no pyproject.toml in $PWD; run from the workspace root" >&2
    exit 1
fi

mkdir -p "${SCRATCH_ROOT}"
TMP="$(mktemp -d "${SCRATCH_ROOT}/uv-cooldown.XXXXXX")"
export UV_PROJECT_ENVIRONMENT="${UV_PROJECT_ENVIRONMENT:-${TMP}/env}"

HAD_LOCK=0
if [[ -f uv.lock ]]; then
    HAD_LOCK=1
    cp uv.lock "${TMP}/original.lock"
fi

restore_original() {
    if [[ "${HAD_LOCK}" -eq 1 ]]; then
        cp "${TMP}/original.lock" uv.lock
    else
        rm -f uv.lock
    fi
}

DONE=0
on_exit() {
    local rc=$?
    if [[ "${DONE}" -eq 0 ]]; then
        restore_original
        echo "error: step failed (exit ${rc}); original uv.lock restored" >&2
    fi
    rm -f "${TMP}/original.lock" "${TMP}/plain.lock" "${TMP}/cooled.lock"
    rmdir "${TMP}" 2>/dev/null || true
    # A failing uv step may itself exit 2, which must not read as "held back".
    if [[ "${DONE}" -eq 0 ]]; then
        exit 1
    fi
}
trap on_exit EXIT

# Step 1: plain resolution.
env -u UV_EXCLUDE_NEWER uv lock
cp uv.lock "${TMP}/plain.lock"
restore_original

# Step 2: cooled-down resolution.
env -u UV_EXCLUDE_NEWER uv lock --exclude-newer "${CUTOFF}"
cp uv.lock "${TMP}/cooled.lock"

# Step 3: drop the [options] table while keeping the cooled-down pins.
env -u UV_EXCLUDE_NEWER uv lock
if grep -q 'exclude-newer' uv.lock; then
    echo "error: final uv.lock still carries exclude-newer" >&2
    exit 1
fi

# Step 4: report packages whose version differs between the two resolutions.
# Emits "name version" per [[package]] block (a name may appear twice when the
# lock forks on markers).
package_versions() {
    awk '
        /^\[\[package\]\]/ { inpkg = 1; name = ""; next }
        /^\[/ { inpkg = 0 }
        inpkg && /^name = / { gsub(/"/, "", $3); name = $3 }
        inpkg && /^version = / { gsub(/"/, "", $3); print name, $3 }
    ' "$1" | sort
}

HELD_BACK="$(
    awk '
        FNR == NR { plain[$1] = (plain[$1] == "" ? $2 : plain[$1] "," $2); next }
        { cooled[$1] = (cooled[$1] == "" ? $2 : cooled[$1] "," $2) }
        END {
            for (n in plain) {
                c = (n in cooled) ? cooled[n] : "(absent)"
                if (plain[n] != c) printf "held back: %s %s -> %s\n", n, plain[n], c
            }
            for (n in cooled) {
                if (!(n in plain)) printf "held back: %s (absent) -> %s\n", n, cooled[n]
            }
        }
    ' <(package_versions "${TMP}/plain.lock") <(package_versions "${TMP}/cooled.lock") | sort
)"

DONE=1
if [[ -n "${HELD_BACK}" ]]; then
    echo "${HELD_BACK}"
    echo "cooldown held back $(printf '%s\n' "${HELD_BACK}" | wc -l | tr -d ' ') package(s); uv.lock holds the cooled-down resolution (review before committing)"
    exit 2
fi
echo "cooled-down resolution equals the plain resolution; uv.lock regenerated"
exit 0
