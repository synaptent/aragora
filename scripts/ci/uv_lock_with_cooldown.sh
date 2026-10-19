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
  D. compare the final lock with the ORIGINAL lock in PEP 440 order (python3).
     The cutoff also filters versions the original lock already pins, so a
     package released less than 7 days ago (for example a transitive security
     bump from a manual security relock) would roll back. Each [[package]]
     entry of the original lock is compared with the final entry of the same
     name and the same resolution-markers (its marker fork). A package whose
     set of forks changed (forks added, removed, merged or re-partitioned)
     passes only if every final version is >= every original version. Every
     package that would go down is printed as
     `downgraded: <name> <original> -> <cooled>` (a forked package lists its
     versions fork by fork), the original uv.lock is restored and the script
     exits 5: a downgraded lock is never kept
  E. compare the package versions of the two temp copies; any package whose
     version differs was held back by the cooldown and is printed as
     `held back: <name> <plain> -> <cooled>`

Manual security relock (humans only, never in CI or a workflow):
  --allow-package NAME
     Lift the cooldown for NAME only (repeat the option for each package the
     resolver names). Step A adds `--exclude-newer-package NAME=<now>`, so NAME
     may be newer than the cutoff while every other package, including any new
     dependency of NAME, keeps the cooldown. Prints `cooldown lifted for: NAME`.
     Use it when a security fix needs a release younger than 7 days, for
     example after the Dependabot relock failed with exit 4 or 5. Name every
     package a run lists as `downgraded:` too. See "Manual security relock"
     in docs/RATCHETS.md for what the PR must state.

Exit codes:
  0  cooled-down resolution equals the plain resolution; uv.lock is regenerated
  2  packages were held back by the cooldown and reported (listed on stdout);
     uv.lock holds the verified cooled-down resolution
  3  `uv` is not on PATH (nothing is touched)
  4  no resolution satisfies the cooldown; the original uv.lock is restored
     byte-for-byte and nothing is relocked without the cooldown
  5  the cooled-down resolution would give a package of the original lock a
     lower version in any marker fork, or re-partition its forks with a
     version below an original one (each listed on stdout as
     `downgraded: <name> <original> -> <cooled>`); the original uv.lock is
     restored byte-for-byte
  1  pyproject.toml missing, a uv step failed, the final lock drifted from the
     cooled-down resolution, the downgrade check could not order a version,
     or bad usage; the original uv.lock is restored byte-for-byte

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
    # only the explicit no-solution and downgrade branches set FAIL_RC (4, 5).
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

# Reads two locks (original, final) and prints
# "downgraded: <name> <original> -> <final>" for each package of the original
# that the final lock lowers in PEP 440 order. Entries are matched on name and
# resolution-markers, so every marker fork is checked, not only the lowest and
# highest versions. When the set of forks differs (or a fork is ambiguous),
# every final version must be >= every original version. A changed version it
# cannot parse fails the run.
find_downgrades() {
    python3 -I - "$1" "$2" <<'PY'
import re
import sys

VERSION = re.compile(
    r"^v?(?:(\d+)!)?(\d+(?:\.\d+)*)"
    r"(?:[-_.]?(a|b|c|rc|alpha|beta|pre|preview)[-_.]?(\d*))?"
    r"(?:-(\d+)|[-_.]?(?:post|rev|r)[-_.]?(\d*))?"
    r"(?:[-_.]?dev[-_.]?(\d*))?"
    r"(?:\+([a-z0-9]+(?:[-_.][a-z0-9]+)*))?$",
    re.IGNORECASE,
)
PRE_RANK = {"a": 0, "alpha": 0, "b": 1, "beta": 1, "c": 2, "rc": 2, "pre": 2, "preview": 2}


def key(version):
    match = VERSION.match(version)
    if match is None:
        sys.exit(f"error: cannot order version {version!r} for the downgrade check")
    epoch, release, pre_l, pre_n, post_n1, post_n2, dev_n, local = match.groups()
    parts = [int(p) for p in release.split(".")]
    while len(parts) > 1 and parts[-1] == 0:
        parts.pop()
    has_post = post_n1 is not None or post_n2 is not None
    has_dev = dev_n is not None
    if pre_l is not None:
        pre = (0, PRE_RANK[pre_l.lower()], int(pre_n or 0))
    elif has_dev and not has_post:
        pre = (-1, 0, 0)  # 1.0.dev1 sorts before 1.0a1
    else:
        pre = (1, 0, 0)
    post = (1, int(post_n1 or post_n2 or 0)) if has_post else (0, 0)
    dev = (0, int(dev_n or 0)) if has_dev else (1, 0)
    if local:
        segments = re.split(r"[-_.]", local.lower())
        loc = (1, tuple((1, int(s), "") if s.isdigit() else (0, 0, s) for s in segments))
    else:
        loc = (0, ())
    return (int(epoch or 0), tuple(parts), pre, post, dev, loc)


STRING = re.compile(r'"(?:[^"\\]|\\.)*"')
FIELD = re.compile(r"^(name|version|resolution-markers) = (.*)$")


def blocks(path):
    """Yield the name, version and resolution-markers of each [[package]] block."""
    with open(path, encoding="utf-8") as handle:
        lines = iter(handle.read().splitlines())
    entry = None
    for line in lines:
        if line.startswith("["):
            if entry is not None:
                yield entry
            entry = {} if line.rstrip() == "[[package]]" else None
            continue
        match = FIELD.match(line)
        if entry is None or match is None:
            continue
        field, value = match.groups()
        if field != "resolution-markers":
            entry[field] = value.strip().strip('"')
            continue
        # uv writes this array over several lines.
        while STRING.sub("", value).count("[") > STRING.sub("", value).count("]"):
            more = next(lines, None)
            if more is None:
                sys.exit(f"error: unterminated resolution-markers in {path} for the downgrade check")
            value += more
        entry["markers"] = STRING.findall(value)
    if entry is not None:
        yield entry


def read(path):
    """Map each package name to its (fork, version) entries; fork is the sorted
    tuple of the entry's resolution-markers (empty when it does not fork)."""
    packages = {}
    for entry in blocks(path):
        if entry.get("name") and entry.get("version"):
            fork = tuple(sorted(entry.get("markers", ())))
            packages.setdefault(entry["name"], []).append((fork, entry["version"]))
    return packages


def listing(entries):
    return ",".join(version for _, version in entries)


original = read(sys.argv[1])
final = read(sys.argv[2])
for name in sorted(original):
    if name not in final:
        continue
    old = sorted(original[name])
    new = sorted(final[name])
    if old == new:
        continue
    old_forks = [fork for fork, _ in old]
    new_forks = [fork for fork, _ in new]
    if old_forks == new_forks and len(set(old_forks)) == len(old_forks):
        # Same forks, one entry each: compare fork by fork.
        lowered = [key(n) < key(o) for (_, o), (_, n) in zip(old, new) if o != n]
        downgraded = any(lowered)
    else:
        # Forks added, removed, merged, re-partitioned or ambiguous.
        downgraded = min(key(v) for _, v in new) < max(key(v) for _, v in old)
        old = sorted(old, key=lambda item: key(item[1]))
        new = sorted(new, key=lambda item: key(item[1]))
        if downgraded and set(old_forks) != set(new_forks):
            print(
                f"note: {name} forks on other markers than in the original uv.lock; "
                "it passes only if every cooled version is >= every original version",
                file=sys.stderr,
            )
    if downgraded:
        print(f"downgraded: {name} {listing(old)} -> {listing(new)}")
PY
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

# Step D: no package of the original lock may end up at a lower version.
if [[ "${HAD_LOCK}" -eq 1 ]]; then
    DOWNGRADED="$(find_downgrades "${TMP}/original.lock" uv.lock)"
    if [[ -n "${DOWNGRADED}" ]]; then
        restore_original
        FAIL_RC=5
        echo "${DOWNGRADED}"
        echo "error: the cooled-down resolution would downgrade $(printf '%s\n' "${DOWNGRADED}" | wc -l | tr -d ' ') package(s) already in uv.lock (listed as \`downgraded: <name> <original> -> <cooled>\`); original uv.lock restored; nothing to commit (manual security relock: docs/RATCHETS.md)" >&2
        exit 5
    fi
fi

# Step E: report packages whose version differs between the two resolutions.
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
