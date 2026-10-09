"""Issue validation-contract audit helpers for ``aragora swarm``.

Runs the commands in a queued issue's validation contract and classifies
whether the issue is still actionable. Each command runs without a shell, and
commands containing shell operators are rejected rather than run. The commands
come from issue text and run in the audit checkout; the shell-operator screen is
not a sandbox. ``aragora.cli.commands.swarm`` re-exports every name here.
"""

from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
import shlex
import subprocess
import tempfile


def _trim_command_output(text: str, *, limit: int = 240) -> str | None:
    normalized = " ".join(str(text or "").strip().split())
    if not normalized:
        return None
    if len(normalized) <= limit:
        return normalized
    return normalized[: limit - 3] + "..."


_UNSAFE_VALIDATION_SHELL_FRAGMENTS = (
    "|",
    "&&",
    "||",
    ";",
    "<",
    ">",
    "$(",
    "`",
    "\n",
    "\r",
)


def _probe_validation_command(
    command: str,
    *,
    repo_root: Path,
    timeout_seconds: float,
) -> dict[str, object]:
    normalized = str(command or "").strip()
    if not normalized:
        return {
            "command": command,
            "status": "unsafe",
            "detail": "empty validation command",
        }
    for fragment in _UNSAFE_VALIDATION_SHELL_FRAGMENTS:
        if fragment in normalized:
            return {
                "command": command,
                "status": "unsafe",
                "detail": (
                    "shell operators are not allowed in auto-probed validation commands; "
                    "use a single direct command instead"
                ),
            }
    try:
        argv = shlex.split(normalized, posix=True)
    except ValueError as exc:
        return {
            "command": command,
            "status": "unsafe",
            "detail": f"invalid shell quoting: {exc}",
        }
    if not argv:
        return {
            "command": command,
            "status": "unsafe",
            "detail": "empty validation command",
        }
    try:
        proc = subprocess.run(
            argv,
            cwd=str(repo_root),
            text=True,
            capture_output=True,
            timeout=max(1, int(timeout_seconds)),
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        return {
            "command": command,
            "status": "timeout",
            "stdout": _trim_command_output(getattr(exc, "stdout", "") or ""),
            "stderr": _trim_command_output(getattr(exc, "stderr", "") or ""),
        }
    except (FileNotFoundError, OSError) as exc:
        return {
            "command": command,
            "status": "error",
            "stderr": _trim_command_output(str(exc)),
        }

    return {
        "command": command,
        "status": "passed" if proc.returncode == 0 else "failed",
        "returncode": proc.returncode,
        "stdout": _trim_command_output(proc.stdout),
        "stderr": _trim_command_output(proc.stderr),
    }


def _classify_issue_validation_status(
    *,
    validation_contract: list[str],
    commands: list[str],
    probe_results: list[dict[str, object]],
) -> tuple[str, str]:
    if not validation_contract:
        return (
            "missing_validation_contract",
            "Add an Acceptance Criteria, Validation, or Test section with at least one concrete command.",
        )
    if not commands:
        return (
            "non_runnable_validation_contract",
            "Rewrite the validation contract so it contains runnable commands instead of prose.",
        )
    if probe_results and all(str(item.get("status")) == "passed" for item in probe_results):
        return (
            "passes_now",
            "Issue validations already pass on the current branch; close, relabel, or rewrite the stale queue item.",
        )
    first_failure = next(
        (item for item in probe_results if str(item.get("status")) != "passed"),
        None,
    )
    command = str(first_failure.get("command") if isinstance(first_failure, dict) else "")
    returncode_value = first_failure.get("returncode") if isinstance(first_failure, dict) else None
    returncode = int(returncode_value) if isinstance(returncode_value, int) else None
    stdout_text = str(first_failure.get("stdout") if isinstance(first_failure, dict) else "" or "")
    stderr_text = str(first_failure.get("stderr") if isinstance(first_failure, dict) else "" or "")
    combined_output = f"{stdout_text}\n{stderr_text}".lower()
    if isinstance(first_failure, dict) and str(first_failure.get("status")) == "unsafe":
        return (
            "unsafe_validation_contract",
            "Rewrite the validation contract as a single direct command without shell pipelines, redirects, or chaining.",
        )
    if command.startswith("python3 -m aragora.cli.main ") and (
        returncode in {1, 2}
        and ("unrecognized arguments" in combined_output or "usage: main.py" in combined_output)
    ):
        return (
            "cli_usage_failure",
            "The current Aragora parser rejects this queued CLI command. Refresh the contract if the flags were renamed, or keep the issue queued if it is meant to add that CLI surface.",
        )
    if returncode == 5 and (
        command.startswith("pytest ")
        or command.startswith("python -m pytest ")
        or command.startswith("python3 -m pytest ")
    ):
        return (
            "no_matching_tests_collected",
            "The queued pytest selector collects no tests on the current branch. Refresh the selector if tests moved, or keep the issue queued if the expected coverage has not been added yet.",
        )
    if any(
        cmd.startswith(prefix)
        for cmd in commands
        for prefix in (
            "pytest tests/ -q",
            "python -m pytest tests/ -q",
            "python3 -m pytest tests/ -q",
        )
    ):
        return (
            "broad_validation_contract",
            "Replace the broad test-suite command with focused validation tied to the intended file scope.",
        )
    return (
        "validation_fails_now",
        "Validation still fails on the current branch; confirm whether the issue remains real or the contract is stale.",
    )


def _audit_issue_validation_contract(
    issue: object,
    *,
    repo_root: Path,
    timeout_seconds: float = 45.0,
) -> dict[str, object]:
    from aragora.swarm.boss_loop import (
        extract_issue_validation_contract,
        extract_pre_dispatch_validation_commands,
    )

    body = str(getattr(issue, "body", "") or "")
    validation_contract = extract_issue_validation_contract(body)
    commands = extract_pre_dispatch_validation_commands(body)
    probe_results: list[dict[str, object]] = []

    for command in commands:
        result = _probe_validation_command(
            command,
            repo_root=repo_root,
            timeout_seconds=timeout_seconds,
        )
        probe_results.append(result)
        if result["status"] != "passed":
            break

    status, next_action = _classify_issue_validation_status(
        validation_contract=validation_contract,
        commands=commands,
        probe_results=probe_results,
    )
    return {
        "number": int(getattr(issue, "number", 0) or 0),
        "title": str(getattr(issue, "title", "") or "").strip(),
        "url": str(getattr(issue, "url", "") or "").strip(),
        "labels": list(getattr(issue, "labels", []) or []),
        "validation_contract": validation_contract,
        "commands": commands,
        "probe_results": probe_results,
        "status": status,
        "next_action": next_action,
    }


@contextmanager
def _open_audit_checkout(repo_root: Path, *, git_ref: str | None):
    if not git_ref:
        yield repo_root
        return

    with tempfile.TemporaryDirectory(prefix="aragora-audit-") as temp_dir:
        checkout_root = Path(temp_dir) / "checkout"
        add_proc = subprocess.run(
            [
                "git",
                "-C",
                str(repo_root),
                "worktree",
                "add",
                "--detach",
                str(checkout_root),
                git_ref,
            ],
            text=True,
            capture_output=True,
            check=False,
        )
        if add_proc.returncode != 0:
            stderr = _trim_command_output(add_proc.stderr or "") or "git worktree add failed"
            raise RuntimeError(f"Failed to open audit checkout for {git_ref}: {stderr}")
        try:
            yield checkout_root
        finally:
            subprocess.run(
                [
                    "git",
                    "-C",
                    str(repo_root),
                    "worktree",
                    "remove",
                    "--force",
                    str(checkout_root),
                ],
                text=True,
                capture_output=True,
                check=False,
            )
