"""Launch-command building, launch authorization and task-context enrichment.

``WorkerLauncher`` (``aragora.swarm.worker_launcher``) inherits these helpers. Import
the launcher from ``aragora.swarm.worker_launcher``.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
from typing import Any

from aragora.pipeline.execution_mode import ExecutionMode
from aragora.security.capability_gate import (
    Capability,
    CapabilityApprovalRequiredError,
    authorize_capability_dispatch,
    ensure_capability_approval_id,
)
from aragora.swarm.worker_process import LaunchConfig

# The facade's logger name, so log filters and caplog assertions keyed on
# "aragora.swarm.worker_launcher" still see records from the moved helpers.
logger = logging.getLogger("aragora.swarm.worker_launcher")


class WorkerLauncherCommandMixin:
    """Command, authorization and task-context helpers inherited by ``WorkerLauncher``."""

    config: LaunchConfig

    def _build_command(
        self,
        agent: str,
        prompt: str,
        worktree_path: str,
        *,
        session_id: str = "",
        admin_approved: bool = False,
        claude_profile: str | None = None,
        claude_profile_script: str | None = None,
    ) -> list[str]:
        """Build the launch command for the given agent type."""
        inner = self._build_agent_command(
            agent,
            prompt,
            worktree_path=worktree_path,
            admin_approved=admin_approved,
            claude_profile=claude_profile,
            claude_profile_script=claude_profile_script,
        )
        if not self.config.use_managed_session_script:
            return inner

        session_script = Path(worktree_path).resolve() / "scripts" / "codex_session.sh"
        managed_dir = str(Path(worktree_path).resolve().parent)
        cmd = [
            "bash",
            str(session_script),
            "--agent",
            agent,
            "--base",
            self.config.base_branch,
            "--managed-dir",
            managed_dir,
            "--no-maintain",
            "--no-reconcile",
        ]
        effective_session_id = session_id or Path(worktree_path).resolve().name
        cmd.extend(["--session-id", effective_session_id])
        cmd.append("--")
        cmd.extend(inner)
        return cmd

    def _build_agent_command(
        self,
        agent: str,
        prompt: str,
        *,
        worktree_path: str = "",
        admin_approved: bool = False,
        claude_profile: str | None = None,
        claude_profile_script: str | None = None,
    ) -> list[str]:
        if agent == "claude":
            session_mode = os.environ.get("ARAGORA_CLAUDE_SESSION_MODE", "single").strip()
            if session_mode.lower() == "multi_turn":
                prompt_path = self._write_worker_prompt(worktree_path, prompt)
                cmd = [
                    sys.executable,
                    "-m",
                    "aragora.swarm.claude_session_runner",
                    "--prompt-file",
                    prompt_path,
                    "--claude-path",
                    self.config.claude_path,
                ]
                if self.config.claude_model:
                    cmd.extend(["--model", self.config.claude_model])
                if (
                    self.config.allow_claude_dangerously_skip_permissions
                    and self.config.execution_mode == ExecutionMode.AUTONOMOUS
                ):
                    cmd.append("--dangerously-skip-permissions")
            else:
                cmd = [self.config.claude_path, "-p", prompt]
                if (
                    self.config.allow_claude_dangerously_skip_permissions
                    and self.config.execution_mode == ExecutionMode.AUTONOMOUS
                ):
                    cmd.append("--dangerously-skip-permissions")
                if self.config.claude_model:
                    cmd.extend(["--model", self.config.claude_model])
            profile = str(claude_profile or self.config.claude_profile or "").strip() or None
            if profile:
                profile_script = (
                    claude_profile_script
                    or self.config.claude_profile_script
                    or str(Path(worktree_path).resolve() / "scripts" / "claude_profile.sh")
                )
                return [profile_script, "exec", profile, "--", *cmd]
            return cmd

        if agent == "codex":
            # Use stdin ("-") for prompts to avoid OS arg length limits.
            # Long prompts with issue bodies + file lists can exceed ARG_MAX.
            cmd = [self.config.codex_path, "exec", "-"]
            if (
                self.config.allow_codex_full_auto
                and self.config.execution_mode == ExecutionMode.AUTONOMOUS
            ):
                cmd.append("--full-auto")
            if self.config.codex_model:
                cmd.extend(["--model", self.config.codex_model])
            git_dir = self._resolve_worktree_gitdir(worktree_path) if admin_approved else ""
            if git_dir:
                cmd.extend(["--add-dir", git_dir])
            return cmd

        logger.warning("Unknown agent %r, falling back to claude", agent)
        cmd = [self.config.claude_path, "-p", prompt]
        if (
            self.config.allow_claude_dangerously_skip_permissions
            and self.config.execution_mode == ExecutionMode.AUTONOMOUS
        ):
            cmd.append("--dangerously-skip-permissions")
        if self.config.claude_profile:
            profile_script = self.config.claude_profile_script or str(
                Path(worktree_path).resolve() / "scripts" / "claude_profile.sh"
            )
            return [profile_script, "exec", self.config.claude_profile, "--", *cmd]
        return cmd

    @staticmethod
    def _write_worker_prompt(worktree_path: str, prompt: str) -> str:
        prompt_dir = Path(worktree_path).resolve() / ".aragora"
        prompt_dir.mkdir(parents=True, exist_ok=True)
        prompt_path = prompt_dir / "worker_prompt.txt"
        prompt_path.write_text(prompt, encoding="utf-8")
        return str(prompt_path)

    @staticmethod
    def _metadata_dict(work_order: dict[str, Any]) -> dict[str, Any]:
        metadata = work_order.get("metadata")
        return dict(metadata) if isinstance(metadata, dict) else {}

    @staticmethod
    def _strict_bool(value: Any) -> bool | None:
        if isinstance(value, bool):
            return value
        return None

    @classmethod
    def _is_admin_approved(cls, work_order: dict[str, Any], metadata: dict[str, Any]) -> bool:
        return (
            cls._strict_bool(work_order.get("admin_approved")) is True
            or cls._strict_bool(metadata.get("admin_approved")) is True
        )

    @staticmethod
    def _actor_id_for_work_order(work_order: dict[str, Any], metadata: dict[str, Any]) -> str:
        for candidate in (
            metadata.get("requested_by"),
            metadata.get("user_id"),
            work_order.get("owner_session_id"),
            work_order.get("lease_id"),
            work_order.get("work_order_id"),
            "system",
        ):
            text = str(candidate or "").strip()
            if text:
                return text
        return "system"

    @staticmethod
    def _receipt_id_for_work_order(work_order: dict[str, Any], metadata: dict[str, Any]) -> str:
        return str(
            work_order.get("receipt_id")
            or metadata.get("receipt_id")
            or metadata.get("decision_receipt_id")
            or ""
        ).strip()

    def _authorize_worker_launch(
        self,
        *,
        work_order: dict[str, Any],
        worktree_path: str,
        agent: str,
        actor_id: str,
        receipt_id: str,
        admin_approved: bool,
        metadata: dict[str, Any],
        prompt: str,
    ) -> tuple[str, str]:
        if self.config.require_explicit_approval and not self.config.use_managed_session_script:
            raise CapabilityApprovalRequiredError(
                Capability.CODE_EXEC,
                "managed session wrapper is required for code execution lanes",
            )

        # When the caller (e.g. boss loop) has already authorized the run,
        # skip the per-launch approval flow entirely.
        if not self.config.require_explicit_approval:
            return "", ""

        target_resource = str(Path(worktree_path).resolve())
        payload = {
            "work_order_id": str(work_order.get("work_order_id", "")).strip(),
            "agent": agent,
            "prompt_hash": hash(prompt),
            "expected_tests": list(work_order.get("expected_tests") or []),
            "file_scope": list(work_order.get("file_scope") or []),
        }
        approval_id = ensure_capability_approval_id(
            capability=Capability.CODE_EXEC,
            actor_id=actor_id,
            target_resource=target_resource,
            input_payload=payload,
            approval_id=str(
                metadata.get("approval_id") or work_order.get("approval_id") or ""
            ).strip(),
            receipt_id=receipt_id,
            admin_approved=admin_approved,
            approved_by=str(metadata.get("approved_by") or actor_id or "system").strip(),
            metadata={
                "work_order_id": str(work_order.get("work_order_id", "")).strip(),
                "approval_request_id": str(metadata.get("approval_request_id", "")).strip(),
            },
        )
        action = authorize_capability_dispatch(
            capability=Capability.CODE_EXEC,
            actor_id=actor_id,
            target_resource=target_resource,
            input_payload=payload,
            approval_id=approval_id,
            receipt_id=receipt_id,
            metadata={"agent": agent},
        )
        return approval_id, action.action_id

    @staticmethod
    def _resolve_worktree_gitdir(worktree_path: str) -> str:
        """Return the common git directory for a git worktree, or '' for regular repos.

        Git worktrees have a `.git` *file* (not directory) containing
        ``gitdir: <path>`` pointing to ``.git/worktrees/<name>/``.
        That worktree-specific dir has a ``commondir`` file pointing
        back to the parent ``.git/`` directory.

        The Codex ``--full-auto`` sandbox only allows writes inside the
        worktree itself.  ``git add`` needs write access to both
        ``.git/worktrees/<name>/`` (index, HEAD) and ``.git/objects/``
        (blob storage), so we return the common ``.git/`` directory to
        cover both via a single ``--add-dir``.
        """
        if not worktree_path:
            return ""
        dot_git = Path(worktree_path) / ".git"
        if not dot_git.exists() or dot_git.is_dir():
            return ""
        try:
            text = dot_git.read_text().strip()
            if not text.startswith("gitdir:"):
                return ""
            gitdir = text.split(":", 1)[1].strip()
            resolved = (dot_git.parent / gitdir).resolve()
            if not resolved.is_dir():
                return ""
            # Resolve the common directory (parent .git/) via commondir
            # file.  This covers .git/objects/, .git/refs/, and the
            # worktree-specific .git/worktrees/<name>/ subdirectory.
            commondir_file = resolved / "commondir"
            if commondir_file.is_file():
                commondir = commondir_file.read_text().strip()
                common = (resolved / commondir).resolve()
                if common.is_dir():
                    return str(common)
            # Fallback to the worktree gitdir itself if commondir
            # is missing (shouldn't happen in practice).
            return str(resolved)
        except OSError:
            pass
        return ""

    def _validate_launch_command(self, cmd: list[str], agent: str) -> None:
        if not cmd:
            raise RuntimeError("Empty launch command")
        if self.config.use_managed_session_script:
            inner_cli = self.config.claude_path if agent == "claude" else self.config.codex_path
            if agent not in {"claude", "codex"}:
                inner_cli = self.config.claude_path
            if not shutil.which(inner_cli):
                raise FileNotFoundError(f"{inner_cli} CLI not found on PATH")
            session_script = Path(cmd[1]) if len(cmd) > 1 else None
            if session_script is None or not session_script.exists():
                raise FileNotFoundError(f"session script not found: {session_script}")
            return

        cli_path = cmd[0]
        if not shutil.which(cli_path):
            raise FileNotFoundError(f"{cli_path} CLI not found on PATH")

    @staticmethod
    @staticmethod
    def _enrich_task_context(
        work_order: dict[str, Any],
        worktree_path: str,
    ) -> dict[str, Any]:
        """Read target files and related code to build rich task context.

        Design: Give the worker FULL file contents (not truncated) for focused
        tasks. Include the test file, caller context, and directory CLAUDE.md.
        This is the single highest-impact factor for worker success rate.
        """
        file_scope = work_order.get("file_scope", [])
        if not file_scope or not worktree_path:
            return work_order

        context_snippets: list[str] = []
        wt = Path(worktree_path)
        max_lines_per_file = 500  # Full content for focused files

        # 1. Read target files (full content up to 500 lines)
        for file_path in file_scope[:3]:  # Focus on top 3 files
            full_path = wt / file_path
            if not full_path.exists():
                context_snippets.append(
                    f"--- {file_path} DOES NOT EXIST ---\n"
                    "This file needs to be created as part of this task."
                )
                continue
            try:
                content = full_path.read_text(errors="replace")
                lines = content.splitlines()
                if len(lines) > max_lines_per_file:
                    snippet = "\n".join(lines[:max_lines_per_file])
                    context_snippets.append(
                        f"--- {file_path} (first {max_lines_per_file} of {len(lines)} lines) ---\n"
                        f"{snippet}\n--- end (truncated) ---"
                    )
                else:
                    context_snippets.append(
                        f"--- {file_path} ({len(lines)} lines, complete) ---\n"
                        f"{content}\n--- end ---"
                    )
            except OSError:
                pass

        # 2. Read the test file (if validation points to a test)
        expected_tests = work_order.get("expected_tests", [])
        for test_path in expected_tests[:1]:  # Include first test file
            test_full = wt / test_path
            if test_full.exists() and test_path not in file_scope:
                try:
                    test_content = test_full.read_text(errors="replace")
                    test_lines = test_content.splitlines()
                    if len(test_lines) > max_lines_per_file:
                        snippet = "\n".join(test_lines[:max_lines_per_file])
                        context_snippets.append(
                            f"--- {test_path} (test file, first {max_lines_per_file} of "
                            f"{len(test_lines)} lines) ---\n{snippet}\n--- end (truncated) ---"
                        )
                    else:
                        context_snippets.append(
                            f"--- {test_path} (test file, {len(test_lines)} lines, complete) ---\n"
                            f"{test_content}\n--- end ---"
                        )
                except OSError:
                    pass

        # 3. Find callers/importers of the target module
        for file_path in file_scope[:2]:
            full_path = wt / file_path
            if not full_path.exists():
                continue
            try:
                content = full_path.read_text(errors="replace")
                # Find key public symbols
                symbols = re.findall(r"(?:def|class)\s+(\w+)", content)
                caller_notes: list[str] = []
                for sym in symbols[:8]:
                    try:
                        result = subprocess.run(
                            ["grep", "-rn", sym, "aragora/", "--include=*.py", "-l"],
                            capture_output=True,
                            text=True,
                            cwd=worktree_path,
                            timeout=5,
                        )
                        callers = [
                            f for f in result.stdout.strip().splitlines()[:5] if f != file_path
                        ]
                        if callers:
                            caller_notes.append(f"`{sym}` used in: {', '.join(callers)}")
                    except (subprocess.TimeoutExpired, OSError):
                        pass
                if caller_notes:
                    context_snippets.append(
                        f"Cross-references for {file_path}:\n"
                        + "\n".join(f"  - {n}" for n in caller_notes)
                    )
            except OSError:
                pass

        # 4. Include directory CLAUDE.md if present
        for file_path in file_scope[:1]:
            dir_path = (wt / file_path).parent
            claude_md = dir_path / "CLAUDE.md"
            if claude_md.exists():
                try:
                    md_content = claude_md.read_text(errors="replace")
                    if len(md_content) < 3000:  # Only include if reasonably short
                        context_snippets.append(
                            f"--- {dir_path.relative_to(wt)}/CLAUDE.md (local conventions) ---\n"
                            f"{md_content}\n--- end ---"
                        )
                except OSError:
                    pass

        # 5. Recent git history for the target file
        for file_path in file_scope[:1]:
            full_path = wt / file_path
            if not full_path.exists():
                continue
            try:
                result = subprocess.run(
                    ["git", "log", "--oneline", "-5", "--", file_path],
                    capture_output=True,
                    text=True,
                    cwd=worktree_path,
                    timeout=5,
                )
                if result.returncode == 0 and result.stdout.strip():
                    context_snippets.append(
                        f"Recent changes to {file_path}:\n{result.stdout.strip()}"
                    )
            except (subprocess.TimeoutExpired, OSError):
                pass

        if context_snippets:
            work_order = dict(work_order)
            work_order["_enriched_context"] = "\n\n".join(context_snippets)

        return work_order
