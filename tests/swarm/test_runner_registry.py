from __future__ import annotations

from datetime import datetime, timedelta, timezone
import errno
import json
import os
from pathlib import Path

from aragora.swarm.runner_registry import (
    BossRoutingDecision,
    ClaudeRunnerInspector,
    CodexRunnerInspection,
    CodexRunnerInspector,
    DEFAULT_RUNNER_ROTATION_INTERVAL_SECONDS,
    LocalRunnerRegistry,
    authorization_context_from_env,
    authorization_context_with_defaults,
    configured_claude_runner_profiles,
    discover_runner_inspections,
    prioritized_probe_candidates,
    probe_runner_execution,
)

UTC = timezone.utc


class TestPrioritizedProbeCandidates:
    def test_selected_unverified_precedes_proven_failed_runner(self, tmp_path: Path) -> None:
        now = datetime.now(UTC).isoformat()
        registry_path = tmp_path / "swarm-runners.json"
        registry_path.write_text(
            json.dumps(
                {
                    "registrations": [
                        {
                            "runner_id": "claude-runner-failed",
                            "runner_type": "claude",
                            "profile": "max-01",
                            "owner_binding": {
                                "user_id": "user-123",
                                "workspace_id": "ws-456",
                            },
                            "probe_status": "failed",
                            "probe_checked_at": now,
                        },
                        {
                            "runner_id": "claude-runner-selected",
                            "runner_type": "claude",
                            "profile": "max-10",
                            "owner_binding": {
                                "user_id": "user-123",
                                "workspace_id": "ws-456",
                            },
                        },
                    ]
                }
            ),
            encoding="utf-8",
        )
        registry = LocalRunnerRegistry(path=registry_path)
        owner_context = authorization_context_from_env(
            {"ARAGORA_USER_ID": "user-123", "ARAGORA_WORKSPACE_ID": "ws-456"}
        )
        failed = CodexRunnerInspection(
            runner_id="claude-runner-failed",
            runner_type="claude",
            profile="max-01",
            availability="available",
            available=True,
            auth_mode="subscription",
        )
        selected = CodexRunnerInspection(
            runner_id="claude-runner-selected",
            runner_type="claude",
            profile="max-10",
            availability="available",
            available=True,
            auth_mode="subscription",
        )

        candidates = prioritized_probe_candidates(
            registry=registry,
            runner_type="claude",
            discovered_inspections=[failed, selected],
            owner_context=owner_context,
            selected_runners=[{"runner_id": selected.runner_id}],
        )

        assert [item.runner_id for item in candidates] == [selected.runner_id, failed.runner_id]


class TestAuthorizationContextWithDefaults:
    def test_falls_back_to_local_user_and_repo_workspace(self, monkeypatch, tmp_path: Path) -> None:
        repo_root = tmp_path / "aragora"
        repo_root.mkdir()

        monkeypatch.setattr("aragora.swarm.runner_registry.getpass.getuser", lambda: "armand")
        monkeypatch.setattr(
            "aragora.swarm.runner_registry.subprocess.run",
            lambda *args, **kwargs: type(
                "_Proc",
                (),
                {"returncode": 0, "stdout": f"{repo_root / '.git'}\n", "stderr": ""},
            )(),
        )

        context = authorization_context_with_defaults(repo_root=repo_root, env={})

        assert context is not None
        assert context.user_id == "armand"
        assert context.workspace_id == "aragora"

    def test_backfills_workspace_for_explicit_user_context(
        self, monkeypatch, tmp_path: Path
    ) -> None:
        repo_root = tmp_path / "aragora"
        repo_root.mkdir()

        monkeypatch.setattr(
            "aragora.swarm.runner_registry.subprocess.run",
            lambda *args, **kwargs: type(
                "_Proc",
                (),
                {"returncode": 0, "stdout": f"{repo_root / '.git'}\n", "stderr": ""},
            )(),
        )

        context = authorization_context_with_defaults(
            repo_root=repo_root,
            env={"ARAGORA_USER_ID": "user-123"},
        )

        assert context is not None
        assert context.user_id == "user-123"
        assert context.workspace_id == "aragora"

    def test_prefers_git_common_dir_parent_for_managed_worktree(
        self, monkeypatch, tmp_path: Path
    ) -> None:
        canonical_root = tmp_path / "aragora"
        managed_worktree = (
            canonical_root / ".worktrees" / "codex-auto" / "live-boss-proof-20260330b"
        )
        managed_worktree.mkdir(parents=True)

        calls: list[list[str]] = []

        def _run(command: list[str], **kwargs):
            calls.append(command)
            if "--git-common-dir" in command:
                return type(
                    "_Proc",
                    (),
                    {"returncode": 0, "stdout": f"{canonical_root / '.git'}\n", "stderr": ""},
                )()
            return type(
                "_Proc",
                (),
                {"returncode": 0, "stdout": f"{managed_worktree}\n", "stderr": ""},
            )()

        monkeypatch.setattr("aragora.swarm.runner_registry.getpass.getuser", lambda: "armand")
        monkeypatch.setattr("aragora.swarm.runner_registry.subprocess.run", _run)

        context = authorization_context_with_defaults(repo_root=managed_worktree, env={})

        assert context is not None
        assert context.user_id == "armand"
        assert context.workspace_id == "aragora"
        assert any("--git-common-dir" in call for call in calls)


class TestCodexRunnerInspector:
    def test_codex_unavailable(self, monkeypatch):
        monkeypatch.setattr("aragora.swarm.runner_registry.shutil.which", lambda _name: None)
        inspection = CodexRunnerInspector(env={}).inspect()

        assert inspection.available is False
        assert inspection.availability == "unavailable"
        assert inspection.auth_mode == "unavailable"
        assert inspection.freshness_status == "unavailable"
        assert "Install the codex CLI" in str(inspection.next_action)

    def test_api_key_runner_detected_from_login_status(self, monkeypatch):
        monkeypatch.setattr(
            "aragora.swarm.runner_registry.shutil.which",
            lambda _name: "/usr/local/bin/codex",
        )

        def _run(command: list[str]) -> dict[str, object]:
            joined = " ".join(command)
            if joined.endswith("--version"):
                return {"returncode": 0, "stdout": "codex 1.2.3\n", "stderr": ""}
            if joined.endswith("--help"):
                return {
                    "returncode": 0,
                    "stdout": "Commands:\n  exec\n  review\n  login\n",
                    "stderr": "",
                }
            return {"returncode": 0, "stdout": "Logged in using API key\n", "stderr": ""}

        monkeypatch.setattr(CodexRunnerInspector, "_run_command", staticmethod(_run))
        inspection = CodexRunnerInspector(env={}).inspect()

        assert inspection.available is True
        assert inspection.auth_mode == "api_key"
        assert inspection.freshness_status == "fresh"
        assert inspection.capabilities["supports_exec"] is True
        assert inspection.capabilities["supports_review"] is True

    def test_chatgpt_login_runner_detected(self, monkeypatch):
        monkeypatch.setattr(
            "aragora.swarm.runner_registry.shutil.which",
            lambda _name: "/usr/local/bin/codex",
        )

        def _run(command: list[str]) -> dict[str, object]:
            joined = " ".join(command)
            if joined.endswith("--help"):
                return {
                    "returncode": 0,
                    "stdout": "Commands:\n  exec\n  review\n  login\n",
                    "stderr": "",
                }
            return {"returncode": 0, "stdout": "Logged in using ChatGPT\n", "stderr": ""}

        monkeypatch.setattr(CodexRunnerInspector, "_run_command", staticmethod(_run))
        inspection = CodexRunnerInspector(env={}).inspect()

        assert inspection.auth_mode == "chatgpt_login"
        assert inspection.available is True
        assert inspection.freshness_status == "fresh"

    def test_ambiguous_state_returns_unknown(self, monkeypatch):
        monkeypatch.setattr(
            "aragora.swarm.runner_registry.shutil.which",
            lambda _name: "/usr/local/bin/codex",
        )

        def _run(command: list[str]) -> dict[str, object]:
            joined = " ".join(command)
            if joined.endswith("--help"):
                return {"returncode": 0, "stdout": "Commands:\n  exec\n", "stderr": ""}
            return {"returncode": 0, "stdout": "Authentication status unavailable\n", "stderr": ""}

        monkeypatch.setattr(CodexRunnerInspector, "_run_command", staticmethod(_run))
        inspection = CodexRunnerInspector(env={}).inspect()

        assert inspection.auth_mode == "unknown"
        assert inspection.freshness_status == "unknown"
        assert "Confirm the local codex CLI login state" in str(inspection.next_action)

    def test_openai_api_key_env_alone_does_not_prove_api_key_auth(self, monkeypatch):
        monkeypatch.setattr(
            "aragora.swarm.runner_registry.shutil.which",
            lambda _name: "/usr/local/bin/codex",
        )

        def _run(command: list[str]) -> dict[str, object]:
            joined = " ".join(command)
            if joined.endswith("--help"):
                return {
                    "returncode": 0,
                    "stdout": "Commands:\n  exec\n  review\n",
                    "stderr": "",
                }
            return {"returncode": 0, "stdout": "Authentication status unavailable\n", "stderr": ""}

        monkeypatch.setattr(CodexRunnerInspector, "_run_command", staticmethod(_run))
        inspection = CodexRunnerInspector(env={"OPENAI_API_KEY": "sk-test"}).inspect()

        assert inspection.auth_mode == "unknown"
        assert inspection.freshness_status == "unknown"

    def test_codex_exec_probe_uses_stdin_and_can_pass(self, monkeypatch, tmp_path: Path) -> None:
        inspection = CodexRunnerInspection(
            runner_id="codex-runner-1",
            runner_type="codex",
            availability="available",
            available=True,
            auth_mode="chatgpt_login",
            command_path="/opt/homebrew/bin/codex",
            codex_path="/opt/homebrew/bin/codex",
            capabilities={"supports_exec": True},
            owner_binding={},
            freshness_status="fresh",
        )
        observed: dict[str, object] = {}

        def _run(command: list[str], **kwargs):
            observed["command"] = command
            observed["input"] = kwargs.get("input")
            return type(
                "_Proc",
                (),
                {
                    "returncode": 0,
                    "stdout": "ARAGORA_RUNNER_PROBE_OK\n",
                    "stderr": "",
                },
            )()

        monkeypatch.setattr("aragora.swarm.runner_registry.subprocess.run", _run)

        probe = probe_runner_execution(inspection, repo_root=tmp_path)

        assert probe.status == "passed"
        assert observed["command"] == ["/opt/homebrew/bin/codex", "exec", "-"]
        assert observed["input"] == "Reply with exactly: ARAGORA_RUNNER_PROBE_OK\n"


class TestClaudeRunnerInspector:
    def test_subscription_runner_detected(self, monkeypatch):
        monkeypatch.setattr(
            "aragora.swarm.runner_registry.shutil.which",
            lambda _name: "/usr/local/bin/claude",
        )

        def _run(command: list[str]) -> dict[str, object]:
            joined = " ".join(command)
            if joined.endswith("--version"):
                return {"returncode": 0, "stdout": "claude 2.1.81\n", "stderr": ""}
            if joined.endswith("--help"):
                return {"returncode": 0, "stdout": "Commands:\n  review\n  login\n", "stderr": ""}
            return {"returncode": 0, "stdout": "Logged in with Max subscription\n", "stderr": ""}

        monkeypatch.setattr(ClaudeRunnerInspector, "_run_command", staticmethod(_run))
        inspection = ClaudeRunnerInspector(env={}).inspect()

        assert inspection.available is True
        assert inspection.runner_type == "claude"
        assert inspection.auth_mode == "subscription"
        assert inspection.cost_class == "subscription"
        assert inspection.priority_weight > 0

    def test_profile_runner_detected_via_claude_profile_script(
        self, monkeypatch, tmp_path: Path
    ) -> None:
        script = tmp_path / "scripts" / "claude_profile.sh"
        script.parent.mkdir(parents=True)
        script.write_text("#!/bin/bash\n", encoding="utf-8")
        monkeypatch.setattr(
            "aragora.swarm.runner_registry.shutil.which",
            lambda _name: "/usr/local/bin/claude",
        )

        def _run(command: list[str]) -> dict[str, object]:
            joined = " ".join(command)
            if joined.endswith("--version"):
                return {"returncode": 0, "stdout": "claude 2.1.85\n", "stderr": ""}
            if joined.endswith("--help"):
                return {"returncode": 0, "stdout": "Commands:\n  review\n  login\n", "stderr": ""}
            if "claude_profile.sh status max-01" in joined:
                return {
                    "returncode": 0,
                    "stdout": '{"loggedIn":true,"subscriptionType":"max"}\n',
                    "stderr": "",
                }
            return {"returncode": 1, "stdout": "", "stderr": ""}

        monkeypatch.setattr(ClaudeRunnerInspector, "_run_command", staticmethod(_run))
        inspection = ClaudeRunnerInspector(
            env={},
            profile="max-01",
            repo_root=tmp_path,
        ).inspect()

        assert inspection.available is True
        assert inspection.profile == "max-01"
        assert inspection.auth_mode == "subscription"
        assert inspection.command_path == str(script.resolve())
        assert inspection.status_summary == "loggedIn=True subscriptionType=max"

    def test_profile_runner_uses_canonical_repo_root_script_from_worktree(
        self, monkeypatch, tmp_path: Path
    ) -> None:
        repo_root = tmp_path / "aragora"
        worktree_root = repo_root / ".worktrees" / "codex-auto" / "session-123"
        canonical_script = repo_root / "scripts" / "claude_profile.sh"
        worktree_script = worktree_root / "scripts" / "claude_profile.sh"
        canonical_script.parent.mkdir(parents=True)
        worktree_script.parent.mkdir(parents=True)
        canonical_script.write_text("#!/bin/bash\n", encoding="utf-8")
        worktree_script.write_text("#!/bin/bash\n", encoding="utf-8")
        gitdir = repo_root / ".git" / "worktrees" / "session-123"
        gitdir.mkdir(parents=True)
        (gitdir / "commondir").write_text("../..\n", encoding="utf-8")
        (worktree_root / ".git").write_text(
            f"gitdir: {os.path.relpath(gitdir, worktree_root)}\n",
            encoding="utf-8",
        )
        monkeypatch.setattr(
            "aragora.swarm.runner_registry.shutil.which",
            lambda _name: "/usr/local/bin/claude",
        )

        def _run(command: list[str]) -> dict[str, object]:
            joined = " ".join(command)
            if joined.endswith("--version"):
                return {"returncode": 0, "stdout": "claude 2.1.85\n", "stderr": ""}
            if joined.endswith("--help"):
                return {"returncode": 0, "stdout": "Commands:\n  review\n  login\n", "stderr": ""}
            if command[:3] == [str(canonical_script.resolve()), "status", "max-01"]:
                return {
                    "returncode": 0,
                    "stdout": '{"loggedIn":true,"subscriptionType":"max"}\n',
                    "stderr": "",
                }
            raise AssertionError(f"unexpected command: {command}")

        monkeypatch.setattr(ClaudeRunnerInspector, "_run_command", staticmethod(_run))
        inspection = ClaudeRunnerInspector(
            env={},
            profile="max-01",
            repo_root=worktree_root,
        ).inspect()

        assert inspection.available is True
        assert inspection.command_path == str(canonical_script.resolve())

    def test_profile_list_prefers_runner_profiles_env(self) -> None:
        profiles = configured_claude_runner_profiles(
            {
                "ARAGORA_CLAUDE_REVIEW_PROFILES": "max-09,max-10",
                "ARAGORA_CLAUDE_RUNNER_PROFILES": "max-01,max-02",
            }
        )
        assert profiles == ["max-01", "max-02"]

    def test_discover_runner_inspections_expands_configured_profiles(self, monkeypatch) -> None:
        def _factory(
            runner_type: str,
            *,
            config=None,
            env=None,
            profile=None,
            repo_root=None,
        ):
            class _Inspector:
                def inspect(self_nonlocal) -> CodexRunnerInspection:
                    return CodexRunnerInspection(
                        runner_id=f"{runner_type}:{profile}",
                        runner_type=runner_type,
                        availability="available",
                        available=True,
                        auth_mode="subscription",
                        command_path="/tmp/fake",
                        capabilities={"supports_exec": True},
                        owner_binding={},
                        profile=profile,
                    )

            return _Inspector()

        monkeypatch.setattr("aragora.swarm.runner_registry.make_runner_inspector", _factory)
        inspections = discover_runner_inspections(
            "claude",
            env={"ARAGORA_CLAUDE_RUNNER_PROFILES": "max-01,max-02"},
        )

        assert [item.profile for item in inspections] == ["max-01", "max-02"]

    def test_discover_runner_inspections_prefers_explicit_profiles(self, monkeypatch) -> None:
        def _factory(
            runner_type: str,
            *,
            config=None,
            env=None,
            profile=None,
            repo_root=None,
        ):
            class _Inspector:
                def inspect(self_nonlocal) -> CodexRunnerInspection:
                    return CodexRunnerInspection(
                        runner_id=f"{runner_type}:{profile}",
                        runner_type=runner_type,
                        availability="available",
                        available=True,
                        auth_mode="subscription",
                        command_path="/tmp/fake",
                        capabilities={"supports_exec": True},
                        owner_binding={},
                        profile=profile,
                    )

            return _Inspector()

        monkeypatch.setattr("aragora.swarm.runner_registry.make_runner_inspector", _factory)
        inspections = discover_runner_inspections(
            "claude",
            env={"ARAGORA_CLAUDE_RUNNER_PROFILES": "max-09,max-10"},
            profiles={"max-01", "max-02"},
        )

        assert [item.profile for item in inspections] == ["max-01", "max-02"]


class TestLocalRunnerRegistry:
    def test_registration_persists_owner_binding_and_freshness(self, tmp_path: Path) -> None:
        registry_path = tmp_path / "swarm-runners.json"
        registry = LocalRunnerRegistry(path=registry_path)
        owner_context = authorization_context_from_env(
            {
                "ARAGORA_USER_ID": "user-123",
                "ARAGORA_WORKSPACE_ID": "ws-456",
                "ARAGORA_ORG_ID": "org-789",
            }
        )
        inspection = CodexRunnerInspection(
            runner_id="codex-runner-123",
            runner_type="codex",
            availability="available",
            available=True,
            auth_mode="chatgpt_login",
            codex_path="/usr/local/bin/codex",
            version="codex 1.2.3",
            status_summary="Logged in using ChatGPT",
            capabilities={"supports_exec": True, "supports_review": True, "max_parallel_lanes": 2},
            owner_binding={},
            freshness_status="fresh",
        )

        registered = registry.register(inspection, owner_context=owner_context)

        assert registered.registered is True
        assert registered.owner_binding["user_id"] == "user-123"
        assert registered.owner_binding["workspace_id"] == "ws-456"
        assert registered.freshness_status == "fresh"
        assert registered.heartbeat_at is not None
        assert registry_path.exists()

        stored = json.loads(registry_path.read_text(encoding="utf-8"))
        assert stored["registrations"][0]["runner_id"] == "codex-runner-123"
        assert stored["registrations"][0]["auth_mode"] == "chatgpt_login"
        assert stored["registrations"][0]["owner_binding"]["org_id"] == "org-789"
        assert stored["registrations"][0]["freshness_status"] == "fresh"
        assert stored["registrations"][0]["heartbeat_at"]

    def test_registration_of_unknown_auth_runner_fails_closed(self, tmp_path: Path) -> None:
        registry = LocalRunnerRegistry(path=tmp_path / "swarm-runners.json")
        owner_context = authorization_context_from_env(
            {
                "ARAGORA_USER_ID": "user-123",
                "ARAGORA_WORKSPACE_ID": "ws-456",
            }
        )
        inspection = CodexRunnerInspection(
            runner_id="codex-runner-unknown",
            runner_type="codex",
            availability="available",
            available=True,
            auth_mode="unknown",
            codex_path="/usr/local/bin/codex",
            version="codex 1.2.3",
            status_summary="Authentication status unavailable",
            capabilities={"supports_exec": True},
            owner_binding={},
            freshness_status="unknown",
        )

        registered = registry.register(inspection, owner_context=owner_context)

        assert registered.registered is False
        assert registered.registry_path is not None
        assert registered.registered_at is None
        assert "Registration blocked: codex auth mode is unknown" in str(registered.next_action)
        assert not (tmp_path / "swarm-runners.json").exists()

    def test_heartbeat_refreshes_registered_runner(self, tmp_path: Path) -> None:
        registry_path = tmp_path / "swarm-runners.json"
        registry_path.write_text(
            json.dumps(
                {
                    "registrations": [
                        {
                            "runner_id": "codex-runner-1",
                            "runner_type": "codex",
                            "registered": True,
                            "availability": "available",
                            "available": True,
                            "auth_mode": "chatgpt_login",
                            "owner_binding": {"user_id": "user-123", "workspace_id": "ws-456"},
                            "registered_at": "2026-03-09T00:00:00+00:00",
                            "heartbeat_at": "2026-03-09T00:00:00+00:00",
                            "freshness_status": "stale",
                            "stale_after_seconds": 3600,
                        }
                    ]
                }
            ),
            encoding="utf-8",
        )
        registry = LocalRunnerRegistry(path=registry_path)
        owner_context = authorization_context_from_env(
            {"ARAGORA_USER_ID": "user-123", "ARAGORA_WORKSPACE_ID": "ws-456"}
        )
        inspection = CodexRunnerInspection(
            runner_id="codex-runner-1",
            runner_type="codex",
            availability="available",
            available=True,
            auth_mode="chatgpt_login",
            codex_path="/usr/local/bin/codex",
            version="codex 1.2.3",
            status_summary="Logged in using ChatGPT",
            capabilities={"supports_exec": True},
            owner_binding={},
            freshness_status="fresh",
        )

        heartbeated = registry.heartbeat(inspection, owner_context=owner_context)

        assert heartbeated.registered is True
        assert heartbeated.freshness_status == "fresh"
        assert heartbeated.heartbeat_at is not None
        stored = json.loads(registry_path.read_text(encoding="utf-8"))
        assert stored["registrations"][0]["freshness_status"] == "fresh"
        assert stored["registrations"][0]["heartbeat_at"]

    def test_missing_heartbeat_is_treated_as_stale(self, tmp_path: Path) -> None:
        registry_path = tmp_path / "swarm-runners.json"
        registry_path.write_text(
            json.dumps(
                {
                    "registrations": [
                        {
                            "runner_id": "codex-runner-1",
                            "runner_type": "codex",
                            "registered": True,
                            "availability": "available",
                            "available": True,
                            "auth_mode": "chatgpt_login",
                            "owner_binding": {"user_id": "user-123", "workspace_id": "ws-456"},
                        }
                    ]
                }
            ),
            encoding="utf-8",
        )
        decision = LocalRunnerRegistry(path=registry_path).resolve_boss_routing(
            owner_context=authorization_context_from_env(
                {"ARAGORA_USER_ID": "user-123", "ARAGORA_WORKSPACE_ID": "ws-456"}
            )
        )

        assert decision.is_blocked is True
        assert decision.blocked_reason == "no_fresh_registered_runners"

    def test_resolve_boss_routing_selects_fresh_runner(self, tmp_path: Path) -> None:
        fresh_heartbeat = (datetime.now(UTC) - timedelta(minutes=5)).isoformat()
        registry_path = tmp_path / "swarm-runners.json"
        registry_path.write_text(
            json.dumps(
                {
                    "registrations": [
                        {
                            "runner_id": "codex-runner-1",
                            "runner_type": "codex",
                            "registered": True,
                            "availability": "available",
                            "available": True,
                            "auth_mode": "chatgpt_login",
                            "owner_binding": {"user_id": "user-123", "workspace_id": "ws-456"},
                            "capabilities": {"max_parallel_lanes": 2},
                            "heartbeat_at": fresh_heartbeat,
                            "stale_after_seconds": 3600,
                        }
                    ]
                }
            ),
            encoding="utf-8",
        )
        decision = LocalRunnerRegistry(path=registry_path).resolve_boss_routing(
            owner_context=authorization_context_from_env(
                {"ARAGORA_USER_ID": "user-123", "ARAGORA_WORKSPACE_ID": "ws-456"}
            )
        )

        assert decision.is_blocked is False
        assert decision.selected_runner_ids == ["codex-runner-1"]
        assert decision.selected_runners[0]["freshness_status"] == "fresh"
        assert decision.selected_runners[0]["runner_type"] == "codex"

    def test_resolve_boss_routing_rejects_stale_runner(self, tmp_path: Path) -> None:
        stale_heartbeat = (datetime.now(UTC) - timedelta(hours=3)).isoformat()
        registry_path = tmp_path / "swarm-runners.json"
        registry_path.write_text(
            json.dumps(
                {
                    "registrations": [
                        {
                            "runner_id": "codex-runner-stale",
                            "runner_type": "codex",
                            "registered": True,
                            "availability": "available",
                            "available": True,
                            "auth_mode": "chatgpt_login",
                            "owner_binding": {"user_id": "user-123", "workspace_id": "ws-456"},
                            "heartbeat_at": stale_heartbeat,
                            "stale_after_seconds": 3600,
                        }
                    ]
                }
            ),
            encoding="utf-8",
        )
        decision = LocalRunnerRegistry(path=registry_path).resolve_boss_routing(
            owner_context=authorization_context_from_env(
                {"ARAGORA_USER_ID": "user-123", "ARAGORA_WORKSPACE_ID": "ws-456"}
            )
        )

        assert decision.is_blocked is True
        assert decision.blocked_reason == "no_fresh_registered_runners"
        assert "codex-runner-stale" in decision.rejected_runner_ids

    def test_resolve_boss_routing_rejects_wrong_workspace(self, tmp_path: Path) -> None:
        registry_path = tmp_path / "swarm-runners.json"
        registry_path.write_text(
            json.dumps(
                {
                    "registrations": [
                        {
                            "runner_id": "codex-runner-1",
                            "runner_type": "codex",
                            "registered": True,
                            "availability": "available",
                            "available": True,
                            "auth_mode": "chatgpt_login",
                            "owner_binding": {"user_id": "user-123", "workspace_id": "ws-other"},
                            "heartbeat_at": datetime.now(UTC).isoformat(),
                            "stale_after_seconds": 3600,
                        }
                    ]
                }
            ),
            encoding="utf-8",
        )
        decision = LocalRunnerRegistry(path=registry_path).resolve_boss_routing(
            owner_context=authorization_context_from_env(
                {"ARAGORA_USER_ID": "user-123", "ARAGORA_WORKSPACE_ID": "ws-456"}
            )
        )

        assert decision.is_blocked is True
        assert decision.blocked_reason == "no_eligible_registered_runners"

    def test_resolve_boss_routing_prunes_missing_command_path_registrations(
        self, tmp_path: Path
    ) -> None:
        now = datetime.now(UTC).isoformat()
        valid_script = tmp_path / "scripts" / "claude_profile.sh"
        valid_script.parent.mkdir(parents=True)
        valid_script.write_text("#!/bin/sh\n", encoding="utf-8")
        stale_script = tmp_path / "deleted-worktree" / "scripts" / "claude_profile.sh"
        registry_path = tmp_path / "swarm-runners.json"
        registry_path.write_text(
            json.dumps(
                {
                    "registrations": [
                        {
                            "runner_id": "claude-runner-stale",
                            "runner_type": "claude",
                            "profile": "max-02",
                            "registered": True,
                            "availability": "available",
                            "available": True,
                            "auth_mode": "subscription",
                            "command_path": str(stale_script),
                            "cost_class": "subscription",
                            "priority_weight": 100,
                            "owner_binding": {"user_id": "user-123", "workspace_id": "ws-456"},
                            "heartbeat_at": now,
                            "stale_after_seconds": 3600,
                            "capabilities": {"max_parallel_lanes": 1, "active_lanes": 0},
                        },
                        {
                            "runner_id": "claude-runner-live",
                            "runner_type": "claude",
                            "profile": "max-04",
                            "registered": True,
                            "availability": "available",
                            "available": True,
                            "auth_mode": "subscription",
                            "command_path": str(valid_script),
                            "cost_class": "subscription",
                            "priority_weight": 100,
                            "owner_binding": {"user_id": "user-123", "workspace_id": "ws-456"},
                            "heartbeat_at": now,
                            "stale_after_seconds": 3600,
                            "capabilities": {"max_parallel_lanes": 1, "active_lanes": 0},
                        },
                    ]
                }
            ),
            encoding="utf-8",
        )

        decision = LocalRunnerRegistry(path=registry_path).resolve_boss_routing(
            owner_context=authorization_context_from_env(
                {"ARAGORA_USER_ID": "user-123", "ARAGORA_WORKSPACE_ID": "ws-456"}
            ),
            requested_runner_type="claude",
        )

        assert decision.is_blocked is False
        assert decision.selected_runner_ids == ["claude-runner-live"]

        stored = json.loads(registry_path.read_text(encoding="utf-8"))
        assert [item["runner_id"] for item in stored["registrations"]] == ["claude-runner-live"]

    def test_resolve_boss_routing_dedupes_claude_profile_registrations(
        self, tmp_path: Path
    ) -> None:
        now = datetime.now(UTC).isoformat()
        repo_script = tmp_path / "scripts" / "claude_profile.sh"
        worktree_script = (
            tmp_path / ".worktrees" / "codex-auto" / "lane-1" / "scripts" / "claude_profile.sh"
        )
        repo_script.parent.mkdir(parents=True)
        worktree_script.parent.mkdir(parents=True)
        repo_script.write_text("#!/bin/sh\n", encoding="utf-8")
        worktree_script.write_text("#!/bin/sh\n", encoding="utf-8")
        registry_path = tmp_path / "swarm-runners.json"
        registry_path.write_text(
            json.dumps(
                {
                    "registrations": [
                        {
                            "runner_id": "claude-runner-root",
                            "runner_type": "claude",
                            "profile": "max-02",
                            "registered": True,
                            "availability": "available",
                            "available": True,
                            "auth_mode": "subscription",
                            "command_path": str(repo_script),
                            "cost_class": "subscription",
                            "priority_weight": 100,
                            "owner_binding": {"user_id": "user-123", "workspace_id": "ws-456"},
                            "heartbeat_at": now,
                            "stale_after_seconds": 3600,
                            "capabilities": {"max_parallel_lanes": 1, "active_lanes": 0},
                            "probe_status": "passed",
                            "probe_checked_at": now,
                        },
                        {
                            "runner_id": "claude-runner-worktree",
                            "runner_type": "claude",
                            "profile": "max-02",
                            "registered": True,
                            "availability": "available",
                            "available": True,
                            "auth_mode": "subscription",
                            "command_path": str(worktree_script),
                            "cost_class": "subscription",
                            "priority_weight": 100,
                            "owner_binding": {"user_id": "user-123", "workspace_id": "ws-456"},
                            "heartbeat_at": now,
                            "stale_after_seconds": 3600,
                            "capabilities": {"max_parallel_lanes": 1, "active_lanes": 0},
                        },
                    ]
                }
            ),
            encoding="utf-8",
        )

        decision = LocalRunnerRegistry(path=registry_path).resolve_boss_routing(
            owner_context=authorization_context_from_env(
                {"ARAGORA_USER_ID": "user-123", "ARAGORA_WORKSPACE_ID": "ws-456"}
            ),
            requested_runner_type="claude",
        )

        assert decision.is_blocked is False
        assert decision.selected_runner_ids == ["claude-runner-root"]

        stored = json.loads(registry_path.read_text(encoding="utf-8"))
        assert [item["runner_id"] for item in stored["registrations"]] == ["claude-runner-root"]

    def test_resolve_boss_routing_blocks_without_owner_context(self, tmp_path: Path) -> None:
        decision = LocalRunnerRegistry(path=tmp_path / "swarm-runners.json").resolve_boss_routing(
            owner_context=None
        )

        assert decision == BossRoutingDecision(
            owner_binding={"user_id": None, "workspace_id": None, "org_id": None},
            selection_basis=(
                "registered=true, freshness_status=fresh, availability=available, auth_mode "
                "verified, owner_binding compatible, live probe healthy, capacity available, "
                "ordered by requested runner type, probe health, priority_weight, cost "
                "preference, and rotation-aware profile balancing"
            ),
            blocked_reason="missing_owner_context",
            next_action=(
                "Set `ARAGORA_USER_ID` and `ARAGORA_WORKSPACE_ID` before running Boss mode so "
                "Aragora can route only onto authorized registered runners."
            ),
        )

    def test_resolve_boss_routing_prefers_claude_by_default(self, tmp_path: Path) -> None:
        now = datetime.now(UTC).isoformat()
        registry_path = tmp_path / "swarm-runners.json"
        registry_path.write_text(
            json.dumps(
                {
                    "registrations": [
                        {
                            "runner_id": "codex-runner-1",
                            "runner_type": "codex",
                            "registered": True,
                            "availability": "available",
                            "available": True,
                            "auth_mode": "chatgpt_login",
                            "cost_class": "subscription",
                            "priority_weight": 80,
                            "owner_binding": {"user_id": "user-123", "workspace_id": "ws-456"},
                            "heartbeat_at": now,
                            "stale_after_seconds": 3600,
                            "capabilities": {"max_parallel_lanes": 1, "active_lanes": 0},
                        },
                        {
                            "runner_id": "claude-runner-1",
                            "runner_type": "claude",
                            "registered": True,
                            "availability": "available",
                            "available": True,
                            "auth_mode": "subscription",
                            "cost_class": "subscription",
                            "priority_weight": 100,
                            "owner_binding": {"user_id": "user-123", "workspace_id": "ws-456"},
                            "heartbeat_at": now,
                            "stale_after_seconds": 3600,
                            "capabilities": {"max_parallel_lanes": 2, "active_lanes": 0},
                        },
                    ]
                }
            ),
            encoding="utf-8",
        )
        decision = LocalRunnerRegistry(path=registry_path).resolve_boss_routing(
            owner_context=authorization_context_from_env(
                {"ARAGORA_USER_ID": "user-123", "ARAGORA_WORKSPACE_ID": "ws-456"}
            )
        )

        assert decision.is_blocked is False
        assert decision.selected_runner_ids[:2] == ["claude-runner-1", "codex-runner-1"]
        assert decision.selected_runners[0]["runner_type"] == "claude"

    def test_resolve_boss_routing_prefers_requested_runner_type(self, tmp_path: Path) -> None:
        now = datetime.now(UTC).isoformat()
        registry_path = tmp_path / "swarm-runners.json"
        registry_path.write_text(
            json.dumps(
                {
                    "registrations": [
                        {
                            "runner_id": "claude-runner-1",
                            "runner_type": "claude",
                            "registered": True,
                            "availability": "available",
                            "available": True,
                            "auth_mode": "subscription",
                            "cost_class": "subscription",
                            "priority_weight": 100,
                            "owner_binding": {"user_id": "user-123", "workspace_id": "ws-456"},
                            "heartbeat_at": now,
                            "stale_after_seconds": 3600,
                            "capabilities": {"max_parallel_lanes": 2, "active_lanes": 0},
                        },
                        {
                            "runner_id": "codex-runner-1",
                            "runner_type": "codex",
                            "registered": True,
                            "availability": "available",
                            "available": True,
                            "auth_mode": "chatgpt_login",
                            "cost_class": "subscription",
                            "priority_weight": 80,
                            "owner_binding": {"user_id": "user-123", "workspace_id": "ws-456"},
                            "heartbeat_at": now,
                            "stale_after_seconds": 3600,
                            "capabilities": {"max_parallel_lanes": 1, "active_lanes": 0},
                        },
                    ]
                }
            ),
            encoding="utf-8",
        )
        decision = LocalRunnerRegistry(path=registry_path).resolve_boss_routing(
            owner_context=authorization_context_from_env(
                {"ARAGORA_USER_ID": "user-123", "ARAGORA_WORKSPACE_ID": "ws-456"}
            ),
            requested_runner_type="codex",
        )

        assert decision.is_blocked is False
        assert decision.selected_runner_ids[0] == "codex-runner-1"
        assert decision.requested_runner_type == "codex"

    def test_resolve_boss_routing_falls_back_when_requested_type_is_capacity_exhausted(
        self, tmp_path: Path
    ) -> None:
        now = datetime.now(UTC).isoformat()
        registry_path = tmp_path / "swarm-runners.json"
        registry_path.write_text(
            json.dumps(
                {
                    "registrations": [
                        {
                            "runner_id": "claude-runner-1",
                            "runner_type": "claude",
                            "registered": True,
                            "availability": "available",
                            "available": True,
                            "auth_mode": "subscription",
                            "cost_class": "subscription",
                            "priority_weight": 100,
                            "owner_binding": {"user_id": "user-123", "workspace_id": "ws-456"},
                            "heartbeat_at": now,
                            "stale_after_seconds": 3600,
                            "capabilities": {"max_parallel_lanes": 1, "active_lanes": 1},
                        },
                        {
                            "runner_id": "codex-runner-1",
                            "runner_type": "codex",
                            "registered": True,
                            "availability": "available",
                            "available": True,
                            "auth_mode": "chatgpt_login",
                            "cost_class": "subscription",
                            "priority_weight": 80,
                            "owner_binding": {"user_id": "user-123", "workspace_id": "ws-456"},
                            "heartbeat_at": now,
                            "stale_after_seconds": 3600,
                            "capabilities": {"max_parallel_lanes": 1, "active_lanes": 0},
                        },
                    ]
                }
            ),
            encoding="utf-8",
        )
        decision = LocalRunnerRegistry(path=registry_path).resolve_boss_routing(
            owner_context=authorization_context_from_env(
                {"ARAGORA_USER_ID": "user-123", "ARAGORA_WORKSPACE_ID": "ws-456"}
            ),
            requested_runner_type="claude",
        )

        assert decision.is_blocked is False
        assert decision.selected_runner_ids == ["codex-runner-1"]
        assert decision.fallback_reason == "requested_runner_type_unavailable"

    def test_resolve_boss_routing_rotates_across_claude_profiles(self, tmp_path: Path) -> None:
        now = datetime.now(UTC)
        registry_path = tmp_path / "swarm-runners.json"
        registry_path.write_text(
            json.dumps(
                {
                    "registrations": [
                        {
                            "runner_id": "claude-runner-hot",
                            "runner_type": "claude",
                            "profile": "max-02",
                            "registered": True,
                            "availability": "available",
                            "available": True,
                            "auth_mode": "subscription",
                            "cost_class": "subscription",
                            "priority_weight": 100,
                            "owner_binding": {"user_id": "user-123", "workspace_id": "ws-456"},
                            "heartbeat_at": now.isoformat(),
                            "stale_after_seconds": 3600,
                            "last_selected_at": now.isoformat(),
                            "selection_count": 4,
                            "capabilities": {"max_parallel_lanes": 1, "active_lanes": 0},
                        },
                        {
                            "runner_id": "claude-runner-cool",
                            "runner_type": "claude",
                            "profile": "max-03",
                            "registered": True,
                            "availability": "available",
                            "available": True,
                            "auth_mode": "subscription",
                            "cost_class": "subscription",
                            "priority_weight": 100,
                            "owner_binding": {"user_id": "user-123", "workspace_id": "ws-456"},
                            "heartbeat_at": now.isoformat(),
                            "stale_after_seconds": 3600,
                            "last_selected_at": (now - timedelta(hours=2)).isoformat(),
                            "selection_count": 1,
                            "capabilities": {"max_parallel_lanes": 1, "active_lanes": 0},
                        },
                    ]
                }
            ),
            encoding="utf-8",
        )
        decision = LocalRunnerRegistry(path=registry_path).resolve_boss_routing(
            owner_context=authorization_context_from_env(
                {"ARAGORA_USER_ID": "user-123", "ARAGORA_WORKSPACE_ID": "ws-456"}
            ),
            requested_runner_type="claude",
            rotation_interval_seconds=DEFAULT_RUNNER_ROTATION_INTERVAL_SECONDS,
        )

        assert decision.is_blocked is False
        assert decision.selected_runner_ids[:2] == ["claude-runner-cool", "claude-runner-hot"]

    def test_claim_runner_updates_capacity_until_released(self, tmp_path: Path) -> None:
        now = datetime.now(UTC).isoformat()
        registry_path = tmp_path / "swarm-runners.json"
        registry_path.write_text(
            json.dumps(
                {
                    "registrations": [
                        {
                            "runner_id": "claude-runner-1",
                            "runner_type": "claude",
                            "profile": "max-02",
                            "registered": True,
                            "availability": "available",
                            "available": True,
                            "auth_mode": "subscription",
                            "cost_class": "subscription",
                            "priority_weight": 100,
                            "owner_binding": {"user_id": "user-123", "workspace_id": "ws-456"},
                            "heartbeat_at": now,
                            "stale_after_seconds": 3600,
                            "capabilities": {"max_parallel_lanes": 1, "active_lanes": 0},
                        }
                    ]
                }
            ),
            encoding="utf-8",
        )
        owner_context = authorization_context_from_env(
            {"ARAGORA_USER_ID": "user-123", "ARAGORA_WORKSPACE_ID": "ws-456"}
        )
        registry = LocalRunnerRegistry(path=registry_path)

        claimed = registry.claim_runner("claude-runner-1", owner_context=owner_context)

        assert claimed is not None
        assert claimed["claimed_lanes"] == 1
        assert claimed["claim_owner_pid"] == os.getpid()
        assert claimed["claim_owner_host"]
        blocked = registry.resolve_boss_routing(
            owner_context=owner_context,
            requested_runner_type="claude",
        )
        assert blocked.is_blocked is True
        assert blocked.blocked_reason == "no_eligible_registered_runners"

        released = registry.release_runner_claim("claude-runner-1", owner_context=owner_context)

        assert released is not None
        assert released["claimed_lanes"] == 0
        decision = registry.resolve_boss_routing(
            owner_context=owner_context,
            requested_runner_type="claude",
        )
        assert decision.is_blocked is False
        assert decision.selected_runner_ids == ["claude-runner-1"]

    def test_save_ignores_preexisting_fixed_temp_file(self, tmp_path: Path) -> None:
        registry_path = tmp_path / "swarm-runners.json"
        registry = LocalRunnerRegistry(path=registry_path)
        stale_temp = registry_path.with_suffix(registry_path.suffix + ".tmp")
        stale_temp.write_text("stale-temp", encoding="utf-8")

        registry._save({"registrations": [{"runner_id": "claude-runner-1"}]})

        payload = json.loads(registry_path.read_text(encoding="utf-8"))
        assert payload["registrations"][0]["runner_id"] == "claude-runner-1"
        assert stale_temp.read_text(encoding="utf-8") == "stale-temp"

    def test_requested_runner_capacity_is_not_masked_by_other_type_staleness(
        self, tmp_path: Path
    ) -> None:
        now = datetime.now(UTC)
        registry_path = tmp_path / "swarm-runners.json"
        registry_path.write_text(
            json.dumps(
                {
                    "registrations": [
                        {
                            "runner_id": "claude-runner-stale",
                            "runner_type": "claude",
                            "registered": True,
                            "availability": "available",
                            "available": True,
                            "auth_mode": "subscription",
                            "cost_class": "subscription",
                            "priority_weight": 100,
                            "owner_binding": {"user_id": "user-123", "workspace_id": "ws-456"},
                            "heartbeat_at": (now - timedelta(hours=2)).isoformat(),
                            "stale_after_seconds": 300,
                            "capabilities": {"max_parallel_lanes": 1, "active_lanes": 0},
                        },
                        {
                            "runner_id": "codex-runner-busy",
                            "runner_type": "codex",
                            "registered": True,
                            "availability": "available",
                            "available": True,
                            "auth_mode": "chatgpt_login",
                            "cost_class": "subscription",
                            "priority_weight": 80,
                            "owner_binding": {"user_id": "user-123", "workspace_id": "ws-456"},
                            "heartbeat_at": now.isoformat(),
                            "stale_after_seconds": 3600,
                            "claimed_lanes": 1,
                            "capabilities": {"max_parallel_lanes": 1, "active_lanes": 0},
                        },
                    ]
                }
            ),
            encoding="utf-8",
        )
        owner_context = authorization_context_from_env(
            {"ARAGORA_USER_ID": "user-123", "ARAGORA_WORKSPACE_ID": "ws-456"}
        )

        decision = LocalRunnerRegistry(path=registry_path).resolve_boss_routing(
            owner_context=owner_context,
            requested_runner_type="codex",
        )

        assert decision.is_blocked is True
        assert decision.blocked_reason == "no_eligible_registered_runners"
        assert "Free capacity on the registered codex runner" in str(decision.next_action)

    def test_refresh_clears_stale_claim_for_idle_runner(self, tmp_path: Path, monkeypatch) -> None:
        now = datetime.now(UTC)
        monkeypatch.setattr(
            "aragora.swarm.runner_registry.LocalRunnerRegistry._command_path_exists",
            staticmethod(lambda _value: True),
        )
        registry_path = tmp_path / "swarm-runners.json"
        registry_path.write_text(
            json.dumps(
                {
                    "registrations": [
                        {
                            "runner_id": "codex-runner-stale-claim",
                            "runner_type": "codex",
                            "registered": True,
                            "availability": "available",
                            "available": True,
                            "auth_mode": "chatgpt_login",
                            "cost_class": "subscription",
                            "priority_weight": 80,
                            "owner_binding": {"user_id": "user-123", "workspace_id": "ws-456"},
                            "heartbeat_at": now.isoformat(),
                            "last_selected_at": (now - timedelta(hours=9)).isoformat(),
                            "claimed_lanes": 1,
                            "stale_after_seconds": 3600,
                            "capabilities": {"max_parallel_lanes": 1, "active_lanes": 0},
                        }
                    ]
                }
            ),
            encoding="utf-8",
        )
        owner_context = authorization_context_from_env(
            {"ARAGORA_USER_ID": "user-123", "ARAGORA_WORKSPACE_ID": "ws-456"}
        )
        registry = LocalRunnerRegistry(path=registry_path)
        inspection = CodexRunnerInspection(
            runner_id="codex-runner-stale-claim",
            runner_type="codex",
            availability="available",
            available=True,
            auth_mode="chatgpt_login",
            command_path="/usr/local/bin/codex",
            codex_path="/usr/local/bin/codex",
            version="codex-cli 0.107.0",
            status_summary="Logged in using ChatGPT",
            capabilities={"supports_exec": True, "max_parallel_lanes": 1, "active_lanes": 0},
            owner_binding={"user_id": "user-123", "workspace_id": "ws-456", "org_id": None},
            freshness_status="fresh",
            stale_after_seconds=3600,
            cost_class="subscription",
            priority_weight=80,
        )

        registry.refresh(inspection, owner_context=owner_context)

        stored = registry.list_registrations()[0]
        assert stored["claimed_lanes"] == 0
        decision = registry.resolve_boss_routing(
            owner_context=owner_context,
            requested_runner_type="codex",
        )
        assert decision.is_blocked is False
        assert decision.selected_runner_ids == ["codex-runner-stale-claim"]

    def test_refresh_clears_fresh_orphaned_claim_for_dead_owner_process(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        now = datetime.now(UTC)
        monkeypatch.setattr(
            "aragora.swarm.runner_registry.LocalRunnerRegistry._command_path_exists",
            staticmethod(lambda _value: True),
        )
        monkeypatch.setattr("aragora.swarm.runner_registry.platform.node", lambda: "host-1")

        def _kill(_pid: int, _sig: int) -> None:
            raise ProcessLookupError(errno.ESRCH, "missing")

        monkeypatch.setattr("aragora.swarm.runner_registry.os.kill", _kill)
        registry_path = tmp_path / "swarm-runners.json"
        registry_path.write_text(
            json.dumps(
                {
                    "registrations": [
                        {
                            "runner_id": "claude-runner-orphaned",
                            "runner_type": "claude",
                            "registered": True,
                            "availability": "available",
                            "available": True,
                            "auth_mode": "subscription",
                            "cost_class": "subscription",
                            "priority_weight": 100,
                            "owner_binding": {"user_id": "user-123", "workspace_id": "ws-456"},
                            "heartbeat_at": now.isoformat(),
                            "last_selected_at": now.isoformat(),
                            "claimed_lanes": 1,
                            "claim_owner_host": "host-1",
                            "claim_owner_pid": 424242,
                            "stale_after_seconds": 3600,
                            "capabilities": {"max_parallel_lanes": 1, "active_lanes": 0},
                        }
                    ]
                }
            ),
            encoding="utf-8",
        )
        owner_context = authorization_context_from_env(
            {"ARAGORA_USER_ID": "user-123", "ARAGORA_WORKSPACE_ID": "ws-456"}
        )
        registry = LocalRunnerRegistry(path=registry_path)
        inspection = CodexRunnerInspection(
            runner_id="claude-runner-orphaned",
            runner_type="claude",
            availability="available",
            available=True,
            auth_mode="subscription",
            command_path="/usr/local/bin/claude",
            capabilities={"supports_exec": True, "max_parallel_lanes": 1, "active_lanes": 0},
            owner_binding={"user_id": "user-123", "workspace_id": "ws-456", "org_id": None},
            freshness_status="fresh",
            stale_after_seconds=3600,
            cost_class="subscription",
            priority_weight=100,
        )

        registry.refresh(inspection, owner_context=owner_context)

        stored = registry.list_registrations()[0]
        assert stored["claimed_lanes"] == 0
        assert stored["claim_owner_host"] is None
        assert stored["claim_owner_pid"] is None
        decision = registry.resolve_boss_routing(
            owner_context=owner_context,
            requested_runner_type="claude",
        )
        assert decision.is_blocked is False
        assert decision.selected_runner_ids == ["claude-runner-orphaned"]

    def test_refresh_preserves_fresh_claim_when_owner_process_is_alive(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        now = datetime.now(UTC)
        monkeypatch.setattr(
            "aragora.swarm.runner_registry.LocalRunnerRegistry._command_path_exists",
            staticmethod(lambda _value: True),
        )
        monkeypatch.setattr("aragora.swarm.runner_registry.platform.node", lambda: "host-1")
        monkeypatch.setattr("aragora.swarm.runner_registry.os.kill", lambda _pid, _sig: None)
        registry_path = tmp_path / "swarm-runners.json"
        registry_path.write_text(
            json.dumps(
                {
                    "registrations": [
                        {
                            "runner_id": "claude-runner-live-claim",
                            "runner_type": "claude",
                            "registered": True,
                            "availability": "available",
                            "available": True,
                            "auth_mode": "subscription",
                            "cost_class": "subscription",
                            "priority_weight": 100,
                            "owner_binding": {"user_id": "user-123", "workspace_id": "ws-456"},
                            "heartbeat_at": now.isoformat(),
                            "last_selected_at": now.isoformat(),
                            "claimed_lanes": 1,
                            "claim_owner_host": "host-1",
                            "claim_owner_pid": 777777,
                            "stale_after_seconds": 3600,
                            "capabilities": {"max_parallel_lanes": 1, "active_lanes": 0},
                        }
                    ]
                }
            ),
            encoding="utf-8",
        )
        owner_context = authorization_context_from_env(
            {"ARAGORA_USER_ID": "user-123", "ARAGORA_WORKSPACE_ID": "ws-456"}
        )
        registry = LocalRunnerRegistry(path=registry_path)
        inspection = CodexRunnerInspection(
            runner_id="claude-runner-live-claim",
            runner_type="claude",
            availability="available",
            available=True,
            auth_mode="subscription",
            command_path="/usr/local/bin/claude",
            capabilities={"supports_exec": True, "max_parallel_lanes": 1, "active_lanes": 0},
            owner_binding={"user_id": "user-123", "workspace_id": "ws-456", "org_id": None},
            freshness_status="fresh",
            stale_after_seconds=3600,
            cost_class="subscription",
            priority_weight=100,
        )

        registry.refresh(inspection, owner_context=owner_context)

        stored = registry.list_registrations()[0]
        assert stored["claimed_lanes"] == 1
        assert stored["claim_owner_host"] == "host-1"
        assert stored["claim_owner_pid"] == 777777

    def test_resolve_boss_routing_honors_allowed_claude_profiles(self, tmp_path: Path) -> None:
        now = datetime.now(UTC).isoformat()
        registry_path = tmp_path / "swarm-runners.json"
        registry_path.write_text(
            json.dumps(
                {
                    "registrations": [
                        {
                            "runner_id": "claude-runner-1",
                            "runner_type": "claude",
                            "profile": "max-02",
                            "registered": True,
                            "availability": "available",
                            "available": True,
                            "auth_mode": "subscription",
                            "cost_class": "subscription",
                            "priority_weight": 100,
                            "owner_binding": {"user_id": "user-123", "workspace_id": "ws-456"},
                            "heartbeat_at": now,
                            "stale_after_seconds": 3600,
                            "capabilities": {"max_parallel_lanes": 1, "active_lanes": 0},
                        },
                        {
                            "runner_id": "claude-runner-2",
                            "runner_type": "claude",
                            "profile": "max-03",
                            "registered": True,
                            "availability": "available",
                            "available": True,
                            "auth_mode": "subscription",
                            "cost_class": "subscription",
                            "priority_weight": 100,
                            "owner_binding": {"user_id": "user-123", "workspace_id": "ws-456"},
                            "heartbeat_at": now,
                            "stale_after_seconds": 3600,
                            "capabilities": {"max_parallel_lanes": 1, "active_lanes": 0},
                        },
                    ]
                }
            ),
            encoding="utf-8",
        )

        decision = LocalRunnerRegistry(path=registry_path).resolve_boss_routing(
            owner_context=authorization_context_from_env(
                {"ARAGORA_USER_ID": "user-123", "ARAGORA_WORKSPACE_ID": "ws-456"}
            ),
            requested_runner_type="claude",
            allowed_profiles={"max-03"},
        )

        assert decision.is_blocked is False
        assert decision.selected_runner_ids == ["claude-runner-2"]
