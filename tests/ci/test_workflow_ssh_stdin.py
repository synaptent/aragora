"""Guard against ssh draining a `while read` loop's stdin in workflow run blocks.

`ssh` forwards its inherited stdin to the remote command. Inside a
``while read ...; do ... done < <(producer)`` loop, that inherited stdin *is* the
producer stream, so the first ssh consumes every remaining item and the loop exits
after one iteration — silently. This is the ShellCheck SC2095 class.

The failure mode is specifically nasty for health checks: the loop finishes with an
empty alert list and reports everything healthy, having contacted exactly one host.
That is what `mac-runner-health-poll.yml` did — a monitor that would have reported
"All Mac runners healthy" while `macbook-m1-16gb` was crash-looping and
`macbook-intel-64gb` was deregistered entirely.

The fix is `ssh -n` (or an explicit `< /dev/null`) on every ssh call inside such a loop.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
WORKFLOW_DIR = REPO_ROOT / ".github" / "workflows"

_LOOP = re.compile(r"\bwhile\b[^\n]*\bread\b")
_SSH_START = re.compile(r"(?:^|[|&;(]|\$\()\s*ssh\s")


def _run_blocks(path: Path) -> list[str]:
    """Every `run:` script in a workflow, including inside composite step lists."""
    try:
        doc = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError:  # pragma: no cover - surfaced by the yaml lint hook
        return []
    blocks: list[str] = []

    def walk(node: object) -> None:
        if isinstance(node, dict):
            run = node.get("run")
            if isinstance(run, str):
                blocks.append(run)
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for item in node:
                walk(item)

    walk(doc)
    return blocks


def _ssh_invocations(script: str) -> list[str]:
    """Join backslash-continued ssh invocations into single logical commands."""
    lines = script.splitlines()
    found: list[str] = []
    i = 0
    while i < len(lines):
        if _SSH_START.search(lines[i]):
            parts = [lines[i]]
            while parts[-1].rstrip().endswith("\\") and i + 1 < len(lines):
                i += 1
                parts.append(lines[i])
            found.append(" ".join(p.strip().rstrip("\\").strip() for p in parts))
        i += 1
    return found


# ssh options that consume a following argument; their values must not be scanned
# for flags (e.g. `-o SendEnv=-n` would otherwise read as ssh's own -n).
_OPTS_WITH_ARG = frozenset("-b -c -D -E -e -F -I -i -J -L -l -m -O -o -p -Q -R -S -W -w".split())


def _ssh_own_flags(invocation: str) -> set[str]:
    """Flags belonging to ssh itself, i.e. before the [user@]host destination.

    Scanning the whole string is wrong: the *remote command* frequently contains
    `-n` of its own (`tail -n 1 ...`), which would mask a missing ssh `-n` and make
    this guard silently vacuous — the exact failure it exists to prevent.
    """
    tokens = invocation.split()
    try:
        idx = next(i for i, t in enumerate(tokens) if t == "ssh" or t.endswith("(ssh")) + 1
    except StopIteration:  # pragma: no cover - caller only passes ssh invocations
        return set()
    flags: set[str] = set()
    while idx < len(tokens):
        tok = tokens[idx]
        if tok in _OPTS_WITH_ARG:
            idx += 2
            continue
        if tok.startswith("-") and len(tok) > 1:
            flags.update(f"-{ch}" for ch in tok[1:])
            idx += 1
            continue
        break  # destination reached; everything after belongs to the remote command
    return flags


def _stdin_is_safe(invocation: str) -> bool:
    if "-n" in _ssh_own_flags(invocation):
        return True
    # An explicit input redirect: `< /dev/null`, `</dev/null`, `0< /dev/null`.
    # `2>/dev/null` must NOT count — that is stderr, and it does not detach stdin.
    return bool(re.search(r"(?:^|\s)0?<\s*/dev/null", invocation))


def _offenders() -> list[tuple[str, str]]:
    bad: list[tuple[str, str]] = []
    for path in sorted(WORKFLOW_DIR.glob("*.yml")):
        for script in _run_blocks(path):
            if not _LOOP.search(script):
                continue
            for invocation in _ssh_invocations(script):
                if not _stdin_is_safe(invocation):
                    bad.append((path.name, invocation[:120]))
    return bad


def test_workflow_dir_is_readable() -> None:
    """A moved/renamed workflow dir must fail loudly, not vacuously pass."""
    assert WORKFLOW_DIR.is_dir(), f"missing workflow dir: {WORKFLOW_DIR}"
    assert list(WORKFLOW_DIR.glob("*.yml")), "no workflows found — glob drifted"


def test_no_ssh_drains_a_read_loop() -> None:
    offenders = _offenders()
    assert not offenders, (
        "ssh inside a `while read` loop without `-n` (or `< /dev/null`) will consume the "
        "loop's input stream and silently stop after the first iteration:\n"
        + "\n".join(f"  {name}: {cmd}" for name, cmd in offenders)
        + "\n\nAdd `-n` to each ssh invocation above. See tests/ci/test_workflow_ssh_stdin.py."
    )


def test_mac_poll_ssh_is_pinned() -> None:
    """Pin the known regression so a revert cannot silently reintroduce it."""
    poll = WORKFLOW_DIR / "mac-runner-health-poll.yml"
    if not poll.is_file():
        pytest.skip("mac-runner-health-poll.yml not present")
    scripts = [s for s in _run_blocks(poll) if _LOOP.search(s)]
    assert scripts, "expected a `while read` host loop in mac-runner-health-poll.yml"
    for script in scripts:
        for invocation in _ssh_invocations(script):
            assert _stdin_is_safe(invocation), (
                "mac-runner-health-poll.yml lost `ssh -n`; the poll would report every "
                f"Mac healthy after contacting only the first host: {invocation[:120]}"
            )


def test_guard_detects_a_synthetic_offender(tmp_path: Path) -> None:
    """The guard must actually fire — verified against a synthetic bad workflow."""
    bad = "while read -r h; do\n  OUT=$(ssh -o ConnectTimeout=5 user@\"$h\" 'uptime')\ndone < <(cat hosts)\n"
    good = bad.replace("ssh -o", "ssh -n -o")
    assert _LOOP.search(bad)
    assert _ssh_invocations(bad), "ssh extraction failed on the synthetic sample"
    assert not _stdin_is_safe(_ssh_invocations(bad)[0])
    assert _stdin_is_safe(_ssh_invocations(good)[0])


def test_remote_command_flags_do_not_mask_a_missing_ssh_n() -> None:
    """Regression: the first version of this guard read `-n` out of the remote command.

    `ssh ... host 'tail -n 1 file'` has no ssh-level `-n`, but a naive
    `"-n" in invocation.split()` sees the one belonging to `tail` and passes — making
    the guard vacuous against precisely the bug it was written for.
    """
    masked = "LAST_LINE=$(ssh -o ConnectTimeout=10 -i ~/.ssh/k user@host 'tail -n 1 log')"
    assert not _stdin_is_safe(masked), "remote-command -n must not count as ssh's -n"
    assert _stdin_is_safe(masked.replace("ssh -o", "ssh -n -o"))
    # stderr redirection is not stdin detachment
    assert not _stdin_is_safe("ssh -o X=1 user@host 'cmd' 2>/dev/null")
    assert _stdin_is_safe("ssh -o X=1 user@host 'cmd' < /dev/null")
    # an option *value* must not be mined for flags
    assert not _stdin_is_safe("ssh -o SendEnv=-n user@host 'cmd'")
