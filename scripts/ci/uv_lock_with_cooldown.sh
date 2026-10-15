#!/usr/bin/env bash
# Regenerate uv.lock under a 7-day release-age cooldown without baking the
# cooldown into the committed lock. See --help for the flow and exit codes.
set -euo pipefail

COOLDOWN_DAYS=7
SCRATCH_ROOT=/tmp/aragora-readiness
PACKAGE_NAME_RE='^[A-Za-z0-9]([A-Za-z0-9._-]*[A-Za-z0-9])?$'

usage() {
    cat <<'EOF'
Usage: bash scripts/ci/uv_lock_with_cooldown.sh [--allow-package NAME]... [--help]

Regenerate uv.lock in the current directory ($PWD must hold pyproject.toml and,
normally, uv.lock) so that the resolution honours a release-age cooldown of
7 days, while the committed uv.lock never carries an exclude-newer pin.

Why: a lock produced with --exclude-newer records an
`[options] exclude-newer = ...` table, and plain `uv lock --check` (the
BLOCKING step in security-gate.yml and the check after the relock in
dependabot-uv-lock.yml) fails on such a lock. So `exclude-newer` is never
written into uv.lock or pyproject.toml (no `[tool.uv] exclude-newer`), and this
script is the ONLY place the cooldown applies. The Dependabot relock job runs
main's copy of this script; CI install steps run `uv sync --frozen`/`--locked`
and never set UV_EXCLUDE_NEWER.

Flow (every uv call runs with UV_EXCLUDE_NEWER unset):
  0. print `exclude-newer cutoff: <YYYY-MM-DDTHH:MM:SSZ>` (UTC now minus 7 days)
  A. `uv lock --exclude-newer <cutoff>` from the original lock -> temp copy
     (the cooled-down resolution). If no resolution satisfies the cooldown,
     restore the original uv.lock and exit 4: there is no unrestricted fallback
  B. plain `uv lock` from the original lock -> temp copy (the plain
     resolution), for comparison only; it is never kept
  C. re-run plain `uv lock` on top of the cooled-down lock: uv keeps the
     cooled-down pins as preferences and drops only the `[options]` tables;
     the final uv.lock must carry no exclude-newer and pin exactly the
     cooled-down versions
  D. compare the package versions of the two temp copies; any package whose
     version differs was held back by the cooldown and is printed as
     `held back: <name> <plain> -> <cooled>`

Manual security relock (humans only, never in CI or a workflow):
  --allow-package NAME
     Lift the cooldown for NAME only (repeat the option for each package the
     resolver names). Step A adds `--exclude-newer-package NAME=<now>`, so NAME
     may be newer than the cutoff while every other package, including any new
     dependency of NAME, keeps the cooldown. Prints `cooldown lifted for: NAME`.
     Use it when a security fix needs a release younger than 7 days, for
     example after the Dependabot relock failed with exit 4. See "Manual
     security relock" in docs/RATCHETS.md for what the PR must state.

Exit codes:
  0  cooled-down resolution equals the plain resolution; uv.lock is regenerated
  2  packages were held back by the cooldown and reported (listed on stdout);
     uv.lock holds the verified cooled-down resolution
  3  `uv` is not on PATH (nothing is touched)
  4  no resolution satisfies the cooldown; the original uv.lock is restored
     byte-for-byte and nothing is relocked without the cooldown
  1  pyproject.toml missing, a uv step failed, the final lock drifted from the
     cooled-down resolution, or bad usage; the original uv.lock is restored
     byte-for-byte

Temp copies and any environment uv creates live under /tmp/aragora-readiness/.
EOF
}

ALLOW_PACKAGES=""
while [[ $# -gt 0 ]]; do
    case "$1" in
        -h|--help) usage; exit 0 ;;
        --allow-package)
            if [[ $# -lt 2 ]]; then
                echo "error: --allow-package requires a package name" >&2
                usage >&2
                exit 1
            fi
            if ! [[ "$2" =~ ${PACKAGE_NAME_RE} ]]; then
                echo "error: invalid package name for --allow-package: '$2'" >&2
                exit 1
            fi
            ALLOW_PACKAGES="${ALLOW_PACKAGES} $2"
            shift 2
            ;;
        *) echo "error: unknown argument: $1" >&2; usage >&2; exit 1 ;;
    esac
done

# GNU date takes -d; BSD/macOS date takes -v. A full UTC timestamp keeps the
# cooldown at exactly 7 days: uv reads a bare date as the next local midnight.
if date --version >/dev/null 2>&1; then
    CUTOFF="$(date -u -d "${COOLDOWN_DAYS} days ago" +%Y-%m-%dT%H:%M:%SZ)"
else
    CUTOFF="$(date -u -v-"${COOLDOWN_DAYS}"d +%Y-%m-%dT%H:%M:%SZ)"
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

COOLED_ARGS=(--exclude-newer "${CUTOFF}")
if [[ -n "${ALLOW_PACKAGES}" ]]; then
    NOW="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
    # Names are validated above, so word splitting is safe here.
    for name in ${ALLOW_PACKAGES}; do
        COOLED_ARGS+=(--exclude-newer-package "${name}=${NOW}")
        echo "cooldown lifted for: ${name}"
    done
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
        if [[ -z "${FAIL_RC:-}" ]]; then
            echo "error: step failed (exit ${rc}); original uv.lock restored" >&2
        fi
    fi
    rm -f "${TMP}/original.lock" "${TMP}/plain.lock" "${TMP}/cooled.lock" "${TMP}/cooled.err"
    rmdir "${TMP}" 2>/dev/null || true
    # A failing uv step may itself exit 2, which must not read as "held back";
    # only the explicit no-solution branch sets FAIL_RC=4.
    if [[ "${DONE}" -eq 0 ]]; then
        exit "${FAIL_RC:-1}"
    fi
}
trap on_exit EXIT

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

# Step A: cooled-down resolution, the only resolution that can be kept.
uv_rc=0
env -u UV_EXCLUDE_NEWER uv lock "${COOLED_ARGS[@]}" 2>"${TMP}/cooled.err" || uv_rc=$?
cat "${TMP}/cooled.err" >&2
if [[ "${uv_rc}" -ne 0 ]]; then
    restore_original
    if grep -q 'No solution found' "${TMP}/cooled.err"; then
        FAIL_RC=4
        echo "error: no resolution satisfies the ${COOLDOWN_DAYS}-day cooldown (exclude-newer ${CUTOFF}); original uv.lock restored; no unrestricted fallback (manual security relock: docs/RATCHETS.md)" >&2
    fi
    exit "${uv_rc}"
fi
cp uv.lock "${TMP}/cooled.lock"

# Step B: plain resolution, only to report what the cooldown held back.
restore_original
env -u UV_EXCLUDE_NEWER uv lock
cp uv.lock "${TMP}/plain.lock"

# Step C: drop the [options] tables while keeping the cooled-down pins.
cp "${TMP}/cooled.lock" uv.lock
env -u UV_EXCLUDE_NEWER uv lock
if grep -q 'exclude-newer' uv.lock \
    || [[ "$(package_versions uv.lock)" != "$(package_versions "${TMP}/cooled.lock")" ]]; then
    restore_original
    FAIL_RC=1
    echo "error: final uv.lock drifted from the cooled-down resolution; original uv.lock restored" >&2
    exit 1
fi

# Step D: report packages whose version differs between the two resolutions.
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
