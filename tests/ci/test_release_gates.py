"""
Tests for release gate configurations and the pre-release check script.

Validates:
- Workflow YAML files are parseable and well-structured
- Pre-release check script runs correctly
- Individual gates produce correct pass/fail results
- Smoke test integration works
- Secret pattern detection is functional
"""

from __future__ import annotations

import datetime as dt
import os
import re
import subprocess
import sys
import textwrap
from pathlib import Path
from unittest.mock import MagicMock, patch

from packaging.requirements import Requirement
import pytest
import yaml

if sys.version_info >= (3, 11):
    import tomllib
else:
    import tomli as tomllib

PROJECT_ROOT = Path(__file__).resolve().parents[2]
WORKFLOWS_DIR = PROJECT_ROOT / ".github" / "workflows"
ACTIONS_DIR = PROJECT_ROOT / ".github" / "actions"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _load_yaml(path: Path) -> dict:
    """Load and parse a YAML file."""
    return yaml.safe_load(path.read_text())


def _get_triggers(data: dict) -> dict:
    """Get the 'on' triggers from a workflow dict.

    PyYAML 1.1 parses the bare key ``on:`` as the boolean True, so we
    look for both ``"on"`` and ``True`` as keys.
    """
    if "on" in data:
        return data["on"]
    if True in data:
        return data[True]
    raise KeyError("Workflow has no 'on' trigger key")


def _shell_array_values(script: str, name: str) -> set[str]:
    """Return quoted values from a simple bash array assignment."""
    array_match = re.search(
        rf"^(?:readonly\s+)?{re.escape(name)}=\((?P<body>[^\n]*)\)",
        script,
        re.MULTILINE,
    )
    if array_match is None:
        array_match = re.search(
            rf"^(?:readonly\s+)?{re.escape(name)}=\(\n(?P<body>.*?)^\)",
            script,
            re.MULTILINE | re.DOTALL,
        )
    assert array_match is not None
    return set(re.findall(r'"([^"]+)"', array_match.group("body")))


# ---------------------------------------------------------------------------
# 1. Workflow YAML parsing and structure
# ---------------------------------------------------------------------------


class TestSecurityGateWorkflow:
    """Validate security-gate.yml structure."""

    @pytest.fixture(autouse=True)
    def setup(self):
        self.path = WORKFLOWS_DIR / "security-gate.yml"

    def test_workflow_file_exists(self):
        assert self.path.exists(), "security-gate.yml does not exist"

    def test_workflow_is_valid_yaml(self):
        data = _load_yaml(self.path)
        assert isinstance(data, dict)
        assert "name" in data
        triggers = _get_triggers(data)
        assert isinstance(triggers, dict)
        assert "jobs" in data

    def test_workflow_triggers(self):
        data = _load_yaml(self.path)
        triggers = _get_triggers(data)
        assert "pull_request" in triggers, "should trigger on pull_request"
        assert "workflow_call" in triggers or triggers.get("workflow_call") is None, (
            "should support workflow_call for reusable invocation"
        )

    def test_workflow_has_python_security_job(self):
        data = _load_yaml(self.path)
        jobs = data["jobs"]
        assert "python-security" in jobs, "should have python-security job"
        steps = jobs["python-security"]["steps"]
        step_names = [s.get("name", "") for s in steps]
        assert any("bandit" in n.lower() for n in step_names), (
            "python-security should include bandit scan"
        )
        assert any("pip-audit" in n.lower() or "dependency" in n.lower() for n in step_names), (
            "python-security should include pip-audit"
        )

    def test_workflow_has_npm_security_job(self):
        data = _load_yaml(self.path)
        jobs = data["jobs"]
        assert "npm-security" in jobs, "should have npm-security job"

    def test_workflow_has_summary_job(self):
        data = _load_yaml(self.path)
        jobs = data["jobs"]
        assert "security-summary" in jobs, "should have security-summary job"
        summary_job = jobs["security-summary"]
        assert "needs" in summary_job
        needs = summary_job["needs"]
        assert "python-security" in needs
        assert "npm-security" in needs


class TestIntegrationGateWorkflow:
    """Validate integration-gate.yml structure."""

    @pytest.fixture(autouse=True)
    def setup(self):
        self.path = WORKFLOWS_DIR / "integration-gate.yml"

    def test_workflow_file_exists(self):
        assert self.path.exists(), "integration-gate.yml does not exist"

    def test_workflow_is_valid_yaml(self):
        data = _load_yaml(self.path)
        assert isinstance(data, dict)
        assert "name" in data
        triggers = _get_triggers(data)
        assert isinstance(triggers, dict)
        assert "jobs" in data

    def test_workflow_has_smoke_tests_job(self):
        data = _load_yaml(self.path)
        jobs = data["jobs"]
        assert "smoke-tests" in jobs, "should have smoke-tests job"

    def test_workflow_has_api_contract_sync_job(self):
        data = _load_yaml(self.path)
        jobs = data["jobs"]
        assert "api-contract-sync" in jobs, "should have api-contract-sync job"

    def test_workflow_has_status_doc_validation_job(self):
        data = _load_yaml(self.path)
        jobs = data["jobs"]
        assert "status-doc-validation" in jobs, "should have status-doc-validation job"

    def test_workflow_has_summary_job(self):
        data = _load_yaml(self.path)
        jobs = data["jobs"]
        assert "integration-summary" in jobs, "should have integration-summary job"
        summary_job = jobs["integration-summary"]
        assert "needs" in summary_job


class TestReleaseReadinessWorkflow:
    """Validate release-readiness.yml structure and installer policy."""

    @pytest.fixture(autouse=True)
    def setup(self):
        self.path = WORKFLOWS_DIR / "release-readiness.yml"

    def test_workflow_file_exists(self):
        assert self.path.exists(), "release-readiness.yml does not exist"

    def test_workflow_uses_shared_ci_installer(self):
        data = _load_yaml(self.path)
        job = data["jobs"]["release-readiness"]
        install_step = next(
            step for step in job["steps"] if "scripts/ci_install_project.sh" in step.get("run", "")
        )
        run = install_step.get("run", "")
        assert "scripts/ci_install_project.sh" in run
        assert "--extras dev,test" in run


class TestSharedCiInstaller:
    """Validate shared CI installer package-name compatibility."""

    def test_control_plane_root_names_include_renamed_package(self):
        script = (PROJECT_ROOT / "scripts" / "ci_install_project.sh").read_text()
        names = _shell_array_values(script, "LEGACY_CONTROL_PLANE_PACKAGE_NAMES")
        assert {"aragora-debate", "aragora"} <= names
        assert 'LEGACY_CONTROL_PLANE_MARKER_PATH="aragora/server"' in script

    def test_control_plane_test_deps_install_real_anthropic_sdk(self):
        script = (PROJECT_ROOT / "scripts" / "ci_install_project.sh").read_text()
        deps = _shell_array_values(script, "LEGACY_CONTROL_PLANE_TEST_EXTRA_DEPS")
        anthropic_dep = next(
            Requirement(dep) for dep in deps if Requirement(dep).name == "anthropic"
        )
        assert str(anthropic_dep.specifier) == "<1.0,>=0.111"

    def test_control_plane_test_uv_matches_declared_test_extra(self):
        project = tomllib.loads((PROJECT_ROOT / "pyproject.toml").read_text())
        test_deps = project["project"]["optional-dependencies"]["test"]
        declared = [Requirement(dep) for dep in test_deps if Requirement(dep).name == "uv"]
        script = (PROJECT_ROOT / "scripts" / "ci_install_project.sh").read_text()
        ci_deps = _shell_array_values(script, "LEGACY_CONTROL_PLANE_TEST_EXTRA_DEPS")
        installed = [Requirement(dep) for dep in ci_deps if Requirement(dep).name == "uv"]

        assert len(declared) == 1, "test extra must declare exactly one uv requirement"
        assert len(installed) == 1, "legacy CI test installer must install uv"
        assert installed[0] == declared[0]


class TestAragoraReviewGateWorkflow:
    """Validate Aragora PR review gate structure."""

    @pytest.fixture(autouse=True)
    def setup(self):
        self.gate_path = WORKFLOWS_DIR / "aragora-review-gate.yml"
        self.manual_path = WORKFLOWS_DIR / "aragora-review.yml"

    def test_gate_workflow_file_exists(self):
        assert self.gate_path.exists(), "aragora-review-gate.yml does not exist"

    def test_gate_triggers_on_pull_request_without_paths_filter(self):
        data = _load_yaml(self.gate_path)
        triggers = _get_triggers(data)
        assert "pull_request" in triggers, "review gate should trigger on pull_request"
        pr_trigger = triggers["pull_request"]
        assert isinstance(pr_trigger, dict)
        assert "paths" not in pr_trigger, "required review gate must not use trigger-level paths"

    def test_gate_has_stable_terminal_job(self):
        data = _load_yaml(self.gate_path)
        jobs = data["jobs"]
        assert "aragora-review" in jobs, "gate should expose terminal aragora-review job"
        gate_job = jobs["aragora-review"]
        assert gate_job.get("if") == "always()"
        assert gate_job.get("needs") == ["changes", "review"]

    def test_manual_review_workflow_is_not_pr_triggered(self):
        data = _load_yaml(self.manual_path)
        triggers = _get_triggers(data)
        assert "pull_request" not in triggers, (
            "manual review workflow must not create a second PR context"
        )


class TestReleaseReadinessBootstrapWorkflow:
    """Validate release-readiness workflow bootstraps the monorepo correctly."""

    @pytest.fixture(autouse=True)
    def setup(self):
        self.path = WORKFLOWS_DIR / "release-readiness.yml"

    def test_workflow_file_exists(self):
        assert self.path.exists(), "release-readiness.yml does not exist"

    def test_workflow_uses_monorepo_safe_installer(self):
        data = _load_yaml(self.path)
        jobs = data["jobs"]
        workflow = jobs["release-readiness"]
        install_step = next(
            step for step in workflow["steps"] if step.get("name") == "Install dependencies"
        )
        command = install_step["run"]
        assert "scripts/ci_install_project.sh --extras dev,test" in command


class TestAutopilotWorktreeE2EWorkflow:
    """Validate autopilot-worktree-e2e workflow bootstrap policy."""

    @pytest.fixture(autouse=True)
    def setup(self):
        self.path = WORKFLOWS_DIR / "autopilot-worktree-e2e.yml"

    def test_workflow_file_exists(self):
        assert self.path.exists(), "autopilot-worktree-e2e.yml does not exist"

    def test_autopilot_api_e2e_uses_shared_ci_installer(self):
        data = _load_yaml(self.path)
        workflow = data["jobs"]["autopilot-api-e2e"]
        install_step = next(
            step for step in workflow["steps"] if step.get("name") == "Install dependencies"
        )
        command = install_step["run"]
        assert "scripts/ci_install_project.sh --extras dev,test" in command


class TestDocsBuildWorkflow:
    """Validate docs-build workflow bootstrap policy."""

    @pytest.fixture(autouse=True)
    def setup(self):
        self.path = WORKFLOWS_DIR / "docs-build.yml"

    def test_docs_build_uses_shared_ci_installer(self):
        data = _load_yaml(self.path)
        workflow = data["jobs"]["build"]
        install_step = next(
            step for step in workflow["steps"] if step.get("name") == "Install Python dependencies"
        )
        command = install_step["run"]
        assert "scripts/ci_install_project.sh --extras dev" in command


class TestFrontendE2EWorkflow:
    """Validate frontend E2E workflow backend bootstrap policy."""

    @pytest.fixture(autouse=True)
    def setup(self):
        self.path = WORKFLOWS_DIR / "test.yml"

    def test_frontend_e2e_job_uses_shared_python_installer(self):
        data = _load_yaml(self.path)
        workflow = data["jobs"]["frontend"]
        install_step = next(
            step for step in workflow["steps"] if step.get("name") == "Install Python dependencies"
        )
        command = install_step["run"]
        assert "scripts/ci_install_project.sh --extras dev,test" in command

    def test_frontend_e2e_job_bootstraps_backend_and_redis(self):
        data = _load_yaml(self.path)
        workflow = data["jobs"]["frontend"]
        redis = workflow["services"]["redis"]
        assert redis["image"] == "redis:7-alpine"

        backend_step = next(
            step for step in workflow["steps"] if step.get("name") == "Start Aragora backend"
        )
        backend_command = backend_step["run"]
        assert "python -m aragora serve --api-port 8080 --ws-port 8765 --host 127.0.0.1" in (
            backend_command
        )
        env = backend_step["env"]
        assert env["ARAGORA_REDIS_URL"] == "redis://localhost:6379/0"
        assert env["ARAGORA_DATA_DIR"] == ".nomic"

    def test_frontend_e2e_job_is_sharded(self):
        data = _load_yaml(self.path)
        workflow = data["jobs"]["frontend"]

        assert workflow["timeout-minutes"] == 25
        assert workflow["strategy"]["fail-fast"] is False
        assert workflow["strategy"]["matrix"]["shard"] == [1, 2, 3]
        assert "matrix.shard" in workflow["name"]

        run_step = next(step for step in workflow["steps"] if step.get("name") == "Run E2E tests")
        assert "timeout 16m npx playwright test" in run_step["run"]
        assert "--project=ci-smoke" in run_step["run"]
        assert "--project=chromium" not in run_step["run"]
        assert "--project=firefox" not in run_step["run"]
        assert "--project=webkit" not in run_step["run"]
        assert '--project="Mobile Chrome"' not in run_step["run"]
        assert '--project="Mobile Safari"' not in run_step["run"]
        assert "--shard=${{ matrix.shard }}/3" in run_step["run"]
        assert "--pass-with-no-tests" in run_step["run"]

        artifact_steps = [
            step for step in workflow["steps"] if step.get("uses") == "actions/upload-artifact@v4"
        ]
        artifact_names = {step["with"]["name"] for step in artifact_steps}
        assert "playwright-report-shard-${{ matrix.shard }}" in artifact_names
        assert "playwright-results-shard-${{ matrix.shard }}" in artifact_names
        assert "frontend-e2e-server-logs-shard-${{ matrix.shard }}" in artifact_names

    def test_test_workflow_changes_trigger_frontend_e2e_scope(self):
        classifier = _load_yaml(ACTIONS_DIR / "pr-scope-classifier" / "action.yml")
        filters = classifier["runs"]["steps"][0]["with"]["filters"]

        assert "frontend_e2e:" in filters
        frontend_e2e_section = filters.split("frontend_e2e:", 1)[1].split("smoke:", 1)[0]
        assert "- '.github/workflows/test.yml'" in frontend_e2e_section


class TestCoverageWorkflow:
    """Validate coverage workflow bootstrap policy."""

    @pytest.fixture(autouse=True)
    def setup(self):
        self.path = WORKFLOWS_DIR / "coverage.yml"

    def test_coverage_workflow_uses_shared_ci_installer(self):
        data = _load_yaml(self.path)
        workflow = data["jobs"]["coverage"]
        install_step = next(
            step for step in workflow["steps"] if step.get("name") == "Install dependencies"
        )
        command = install_step["run"]
        assert "scripts/ci_install_project.sh --extras dev,test" in command


class TestIntegrationWorkflow:
    """Validate integration workflow bootstrap and self-host env policy."""

    @pytest.fixture(autouse=True)
    def setup(self):
        self.path = WORKFLOWS_DIR / "integration.yml"

    def test_integration_jobs_use_shared_ci_installer(self):
        data = _load_yaml(self.path)
        jobs = data["jobs"]

        for job_name in ("e2e-harness", "integration-tests", "control-plane-tests"):
            workflow = jobs[job_name]
            install_step = next(
                step for step in workflow["steps"] if step.get("name") == "Install dependencies"
            )
            command = install_step["run"]
            assert "scripts/ci_install_project.sh --extras dev,test" in command

    def test_integration_self_host_env_sets_sentinel_redis_password(self):
        data = _load_yaml(self.path)
        workflow = data["jobs"]["self-host-readiness"]
        prepare_step = next(
            step
            for step in workflow["steps"]
            if step.get("name") == "Prepare CI production env file"
        )
        command = prepare_step["run"]
        assert "ARAGORA_REDIS_MODE=sentinel" in command
        assert "REDIS_PASSWORD=aragora-ci-redis-password-0123456789" in command


class TestMigrationWorkflow:
    """Validate migration workflow bootstrap policy."""

    @pytest.fixture(autouse=True)
    def setup(self):
        self.path = WORKFLOWS_DIR / "migration-tests.yml"

    def test_migration_workflow_uses_shared_ci_installer(self):
        data = _load_yaml(self.path)
        workflow = data["jobs"]["migration-tests"]
        install_step = next(
            step for step in workflow["steps"] if step.get("name") == "Install dependencies"
        )
        command = install_step["run"]
        assert "scripts/ci_install_project.sh --extras dev,test" in command

    def test_migration_workflow_uses_python_module_pytest(self):
        data = _load_yaml(self.path)
        workflow = data["jobs"]["migration-tests"]
        runner_step = next(
            step for step in workflow["steps"] if step.get("name") == "Run migration runner tests"
        )
        command = runner_step["run"]
        assert "python -m pytest tests/test_migrations.py" in command


class TestSelfHostedShadowWorkflow:
    """Validate self-hosted shadow bootstrap stays lightweight on Hetzner."""

    @pytest.fixture(autouse=True)
    def setup(self):
        self.path = WORKFLOWS_DIR / "self-hosted-shadow.yml"

    def test_hetzner_shadow_uses_shared_ci_installer(self):
        data = _load_yaml(self.path)
        workflow = data["jobs"]["hetzner-offline-golden-path-shadow"]
        install_step = next(
            step for step in workflow["steps"] if step.get("name") == "Install dependencies"
        )
        command = install_step["run"]
        assert "scripts/ci_install_project.sh --extras dev,test" in command

    def test_hetzner_shadow_skips_heavy_ml_test_deps(self):
        data = _load_yaml(self.path)
        workflow = data["jobs"]["hetzner-offline-golden-path-shadow"]
        install_step = next(
            step for step in workflow["steps"] if step.get("name") == "Install dependencies"
        )
        env = install_step["env"]
        assert env["ARAGORA_CI_SKIP_HEAVY_ML_TEST_DEPS"] == "1"


class TestReleaseWorkflow:
    """Validate release.yml integrates all gates."""

    @pytest.fixture(autouse=True)
    def setup(self):
        self.path = WORKFLOWS_DIR / "release.yml"

    def test_workflow_file_exists(self):
        assert self.path.exists(), "release.yml does not exist"

    def test_workflow_is_valid_yaml(self):
        data = _load_yaml(self.path)
        assert isinstance(data, dict)

    def test_build_job_requires_all_gates(self):
        data = _load_yaml(self.path)
        build_job = data["jobs"]["build"]
        needs = build_job["needs"]
        assert "security-gate" in needs, "build should require security-gate"
        assert "integration-smoke" in needs, "build should require integration-smoke"
        assert "release-checks" in needs, "build should require release-checks"
        assert "test" in needs, "build should require test"
        assert "docs-sync" in needs, "build should require docs-sync"
        assert "frontend-build" in needs, "build should require frontend-build"

    def test_security_gate_has_secrets_scan(self):
        data = _load_yaml(self.path)
        security_job = data["jobs"]["security-gate"]
        steps = security_job["steps"]
        step_names = [s.get("name", "") for s in steps]
        assert any("secret" in n.lower() for n in step_names), (
            "security-gate should include hardcoded secrets scan"
        )

    def test_integration_smoke_has_contract_tests(self):
        data = _load_yaml(self.path)
        integration_job = data["jobs"]["integration-smoke"]
        steps = integration_job["steps"]
        step_names = [s.get("name", "") for s in steps]
        assert any("openapi" in n.lower() or "contract" in n.lower() for n in step_names), (
            "integration-smoke should include API contract tests"
        )

    def test_release_checks_has_version_tag(self):
        data = _load_yaml(self.path)
        release_checks_job = data["jobs"]["release-checks"]
        steps = release_checks_job["steps"]
        step_names = [s.get("name", "") for s in steps]
        assert any("version" in n.lower() for n in step_names), (
            "release-checks should include version-tag consistency check"
        )

    def test_release_checks_has_status_doc(self):
        data = _load_yaml(self.path)
        release_checks_job = data["jobs"]["release-checks"]
        steps = release_checks_job["steps"]
        step_names = [s.get("name", "") for s in steps]
        assert any("status" in n.lower() for n in step_names), (
            "release-checks should include STATUS.md validation"
        )


class TestTestTiersScript:
    """Validate stable smoke-tier collection policy."""

    @pytest.fixture(autouse=True)
    def setup(self):
        self.path = PROJECT_ROOT / "scripts" / "test_tiers.sh"

    def test_smoke_tier_skips_optional_demo_command_imports(self):
        content = self.path.read_text()
        assert "--ignore=tests/cli/test_demo_command.py" in content


# ---------------------------------------------------------------------------
# 2. Pre-release check script
# ---------------------------------------------------------------------------


class TestPreReleaseCheckScript:
    """Validate the pre_release_check.py script."""

    @pytest.fixture(autouse=True)
    def setup(self):
        self.script = PROJECT_ROOT / "scripts" / "pre_release_check.py"

    def _load_module(self):
        import importlib.util

        spec = importlib.util.spec_from_file_location("pre_release_check", str(self.script))
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    def test_script_exists(self):
        assert self.script.exists(), "scripts/pre_release_check.py does not exist"

    def test_script_is_valid_python(self):
        import ast

        content = self.script.read_text()
        ast.parse(content)

    def test_script_importable(self):
        """Script module can be imported without side effects."""
        import importlib.util

        spec = importlib.util.spec_from_file_location("pre_release_check", str(self.script))
        module = importlib.util.module_from_spec(spec)
        # The module defines ALL_GATES which should be populated
        spec.loader.exec_module(module)
        assert hasattr(module, "ALL_GATES")
        assert len(module.ALL_GATES) >= 8, "should define at least 8 gates"

    def test_script_help_flag(self):
        result = subprocess.run(
            [sys.executable, str(self.script), "--help"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        assert result.returncode == 0
        assert "gate" in result.stdout.lower()

    def test_gate_categories_defined(self):
        """Verify gate categories are properly defined."""
        import importlib.util

        spec = importlib.util.spec_from_file_location("pre_release_check", str(self.script))
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)

        assert hasattr(module, "SECURITY_GATES")
        assert hasattr(module, "INTEGRATION_GATES")
        assert hasattr(module, "RELEASE_GATES")

        # Every gate in categories should be in ALL_GATES
        all_categorized = module.SECURITY_GATES + module.INTEGRATION_GATES + module.RELEASE_GATES
        for gate_name in all_categorized:
            assert gate_name in module.ALL_GATES, (
                f"gate '{gate_name}' in category but not in ALL_GATES"
            )

    def test_pip_audit_gate_invokes_helper_by_absolute_repo_path(self):
        module = self._load_module()

        with patch.object(module, "_run_cmd", return_value=(0, "")) as run_cmd:
            assert module.gate_pip_audit() is True

        cmd = run_cmd.call_args.args[0]
        assert Path(cmd[1]).is_absolute()
        assert Path(cmd[1]) == PROJECT_ROOT / "scripts" / "run_pip_audit_gate.py"

    def test_pip_audit_gate_reports_unique_vulnerability_ids(self):
        module = self._load_module()
        output = "pkg-a CVE-2026-1234\nrepeated CVE-2026-1234\npkg-b GHSA-abcd-1234-efgh"

        with patch.object(module, "_run_cmd", return_value=(1, output)):
            assert module.gate_pip_audit() is False

        assert module._results[-1] == ("pip_audit", False, "2 vulnerability/ies detected")

    def test_pip_audit_gate_preserves_non_vulnerability_failure_diagnostic(self):
        module = self._load_module()
        module._verbose = True

        with patch.object(
            module,
            "_run_cmd",
            return_value=(7, "ERROR: OSV service unavailable while querying locked dependencies"),
        ):
            assert module.gate_pip_audit() is False

        _, passed, detail = module._results[-1]
        assert passed is False
        assert "audit execution failed without vulnerability findings" in detail
        assert "OSV service unavailable" in detail
        assert "0 vulnerability/ies detected" not in detail

    def test_pip_audit_gate_non_verbose_never_echoes_raw_diagnostics(self):
        module = self._load_module()
        assert module._verbose is False

        with patch.object(
            module,
            "_run_cmd",
            return_value=(7, "ERROR: request failed Authorization: Bearer sk-live-abc123"),
        ):
            assert module.gate_pip_audit() is False

        _, passed, detail = module._results[-1]
        assert passed is False
        assert "audit execution failed without vulnerability findings" in detail
        assert "sk-live-abc123" not in detail
        assert "Bearer" not in detail
        assert "request failed" not in detail

    def test_pip_audit_gate_bounds_and_redacts_failure_output(self):
        module = self._load_module()
        module._verbose = True
        output = "\n".join(
            ["old diagnostic"] * 8
            + [
                "request failed https://user:password@example.test/audit?token=top-secret",
                "x" * 500,
            ]
        )

        with patch.object(module, "_run_cmd", return_value=(2, output)):
            assert module.gate_pip_audit() is False

        detail = module._results[-1][2]
        assert len(detail) <= 864
        assert "password" not in detail
        assert "top-secret" not in detail
        assert "[redacted]" in detail

    def test_pip_audit_gate_redacts_authorization_headers(self):
        module = self._load_module()
        module._verbose = True
        output = (
            "HTTP retry failed\n"
            "Authorization: Bearer eyJhbGciOi.secret-part.sig\n"
            "Proxy-Authorization: Basic dXNlcjpwYXNz\n"
            "X-Api-Key: xk-live-9876543210\n"
        )

        with patch.object(module, "_run_cmd", return_value=(3, output)):
            assert module.gate_pip_audit() is False

        detail = module._results[-1][2]
        assert "eyJhbGciOi.secret-part.sig" not in detail
        assert "dXNlcjpwYXNz" not in detail
        assert "xk-live-9876543210" not in detail
        assert "[redacted]" in detail
        assert "HTTP retry failed" in detail

    def test_pip_audit_gate_redacts_index_url_credentials(self):
        module = self._load_module()
        module._verbose = True
        output = (
            "PIP_INDEX_URL=https://deploy-token-abc@pypi.internal.test/simple\n"
            "fallback https://svc:hunter2@mirror.test/simple failed\n"
        )

        with patch.object(module, "_run_cmd", return_value=(3, output)):
            assert module.gate_pip_audit() is False

        detail = module._results[-1][2]
        assert "deploy-token-abc" not in detail
        assert "hunter2" not in detail
        assert "svc:" not in detail
        assert "https://[redacted]@" in detail
        assert "pypi.internal.test" in detail

    def test_pip_audit_gate_redacts_json_yaml_and_query_secrets(self):
        module = self._load_module()
        module._verbose = True
        output = (
            'response body {"token": "tok-abc123", "refresh_token": "tok-def456"}\n'
            "password: yaml-hunter2\n"
            "client_secret=deadbeefcafe\n"
            "retry https://osv.test/query?access_token=qs-secret-1 failed\n"
        )

        with patch.object(module, "_run_cmd", return_value=(3, output)):
            assert module.gate_pip_audit() is False

        detail = module._results[-1][2]
        assert "tok-abc123" not in detail
        assert "tok-def456" not in detail
        assert "yaml-hunter2" not in detail
        assert "deadbeefcafe" not in detail
        assert "qs-secret-1" not in detail
        assert "[redacted]" in detail

    def test_pip_audit_gate_passes_through_benign_diagnostics(self):
        module = self._load_module()
        module._verbose = True
        output = "ERROR: OSV service unavailable (HTTP 503); retried 3 times"

        with patch.object(module, "_run_cmd", return_value=(9, output)):
            assert module.gate_pip_audit() is False

        detail = module._results[-1][2]
        assert "OSV service unavailable (HTTP 503); retried 3 times" in detail
        assert "[redacted]" not in detail

    def test_pip_audit_gate_fails_closed_when_sanitizer_unavailable(self):
        module = self._load_module()
        module._verbose = True

        with (
            patch.object(module, "_load_canonical_sanitizer", return_value=None),
            patch.object(
                module,
                "_run_cmd",
                return_value=(4, "boom Authorization: Bearer sk-live-should-not-leak"),
            ),
        ):
            assert module.gate_pip_audit() is False

        detail = module._results[-1][2]
        assert "sk-live-should-not-leak" not in detail
        assert "boom" not in detail
        assert "diagnostics withheld" in detail


class TestPipAuditGate:
    """Validate the shared pip-audit gate helper."""

    @pytest.fixture(autouse=True)
    def setup(self):
        self.script = PROJECT_ROOT / "scripts" / "run_pip_audit_gate.py"
        self.allowlist = PROJECT_ROOT / "scripts" / "security" / "pip_audit_ignored_vulns.txt"
        self.uv_lock = PROJECT_ROOT / "uv.lock"

    def test_script_exists(self):
        assert self.script.exists(), "scripts/run_pip_audit_gate.py does not exist"

    def _load_module(self):
        import importlib.util

        spec = importlib.util.spec_from_file_location("run_pip_audit_gate", str(self.script))
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    def test_allowlist_omits_resolved_pyjwt_debt(self):
        content = self.allowlist.read_text()
        assert "Format: VULN-ID YYYY-MM-DD" in content
        assert "CVE-2025-14009" in content
        assert "CVE-2026-3219" in content
        assert "PYSEC-2025-183" not in content
        lock_content = self.uv_lock.read_text()
        assert "pyjwt-2.12.1" not in lock_content
        assert "pyjwt-2.13.0" in lock_content
        assert "starlette-1.0.0" not in lock_content
        assert "starlette-1.3.1" in lock_content

    def test_load_ignored_vulns_skips_comments(self, tmp_path):
        allowlist = tmp_path / "allowlist.txt"
        allowlist.write_text(
            textwrap.dedent(
                """
                # comment
                CVE-2025-14009 2026-08-31
                PYSEC-2025-183 2026-09-15 # inline reason
                """
            )
        )
        module = self._load_module()

        assert module.load_ignored_vulns(allowlist, today=dt.date(2026, 5, 21)) == [
            "CVE-2025-14009",
            "PYSEC-2025-183",
        ]

    def test_load_ignored_vulns_rejects_bad_format_with_line_number(self, tmp_path):
        allowlist = tmp_path / "allowlist.txt"
        allowlist.write_text("CVE 2025-14009 2026-08-31\n")
        module = self._load_module()

        with pytest.raises(SystemExit) as excinfo:
            module.load_ignored_vulns(allowlist, today=dt.date(2026, 5, 21))

        assert f"{allowlist}:1:" in str(excinfo.value)
        assert "expected 'VULN-ID YYYY-MM-DD # rationale'" in str(excinfo.value)

    def test_load_ignored_vulns_rejects_invalid_vuln_id_with_line_number(self, tmp_path):
        allowlist = tmp_path / "allowlist.txt"
        allowlist.write_text("pysec-2025-183 2026-08-31\n")
        module = self._load_module()

        with pytest.raises(SystemExit) as excinfo:
            module.load_ignored_vulns(allowlist, today=dt.date(2026, 5, 21))

        assert f"{allowlist}:1:" in str(excinfo.value)
        assert "invalid vulnerability ID 'pysec-2025-183'" in str(excinfo.value)

    def test_load_ignored_vulns_rejects_invalid_expiry_with_line_number(self, tmp_path):
        allowlist = tmp_path / "allowlist.txt"
        allowlist.write_text("PYSEC-2025-183 2026/08/31\n")
        module = self._load_module()

        with pytest.raises(SystemExit) as excinfo:
            module.load_ignored_vulns(allowlist, today=dt.date(2026, 5, 21))

        assert f"{allowlist}:1:" in str(excinfo.value)
        assert "invalid expiry date '2026/08/31'" in str(excinfo.value)

    def test_load_ignored_vulns_drops_expired_entries(self, tmp_path, capsys):
        allowlist = tmp_path / "allowlist.txt"
        allowlist.write_text("PYSEC-2025-183 2026-05-20 # expired\n")
        module = self._load_module()

        assert module.load_ignored_vulns(allowlist, today=dt.date(2026, 5, 21)) == []

        captured = capsys.readouterr()
        assert "expired on 2026-05-20" in captured.err
        assert "not passing it to pip-audit" in captured.err

    def test_load_ignored_vulns_drops_entries_expiring_today(self, tmp_path, capsys):
        allowlist = tmp_path / "allowlist.txt"
        allowlist.write_text("PYSEC-2025-183 2026-05-21 # expires today\n")
        module = self._load_module()

        assert module.load_ignored_vulns(allowlist, today=dt.date(2026, 5, 21)) == []

        captured = capsys.readouterr()
        assert "expired on 2026-05-21" in captured.err
        assert "not passing it to pip-audit" in captured.err

    def test_load_ignored_vulns_warns_near_expiry(self, tmp_path, capsys):
        allowlist = tmp_path / "allowlist.txt"
        allowlist.write_text("PYSEC-2025-183 2026-05-28 # expiring soon\n")
        module = self._load_module()

        assert module.load_ignored_vulns(allowlist, today=dt.date(2026, 5, 21)) == [
            "PYSEC-2025-183"
        ]

        captured = capsys.readouterr()
        assert "expires in 7 day(s) on 2026-05-28" in captured.err

    def test_build_command_audits_requirements_not_environment(self, tmp_path):
        req = tmp_path / "requirements.txt"
        req.write_text("pyjwt==2.12.1\n")
        module = self._load_module()

        cmd = module.build_pip_audit_command(
            req,
            ["PYSEC-2025-183"],
            python_executable="python",
        )

        assert "--requirement" in cmd
        assert str(req) in cmd
        assert "--no-deps" in cmd
        assert "--disable-pip" in cmd
        assert "--ignore-vuln" in cmd
        assert "PYSEC-2025-183" in cmd
        assert "--path" not in cmd

    def test_export_requirements_includes_all_dependency_groups(self, tmp_path):
        module = self._load_module()
        output = tmp_path / "requirements.txt"

        with patch.object(module.subprocess, "run") as run:
            module.export_requirements(output)

        cmd = run.call_args.args[0]
        assert "--frozen" in cmd
        assert "--all-extras" in cmd
        assert "--all-groups" in cmd
        assert "--no-emit-project" in cmd
        assert "--output-file" in cmd
        assert str(output) in cmd
        assert run.call_args.kwargs["cwd"] == module.PROJECT_ROOT
        assert run.call_args.kwargs["capture_output"] is True
        assert run.call_args.kwargs["text"] is True

    def test_export_requirements_missing_uv_has_actionable_message(self, tmp_path):
        module = self._load_module()

        with patch.object(module.subprocess, "run", side_effect=FileNotFoundError):
            with pytest.raises(SystemExit) as excinfo:
                module.export_requirements(tmp_path / "requirements.txt")

        assert "uv is not installed or is not on PATH" in str(excinfo.value)

    def test_export_requirements_failure_includes_stderr(self, tmp_path):
        module = self._load_module()
        error = subprocess.CalledProcessError(2, ["uv", "export"], stderr="bad lockfile")

        with patch.object(module.subprocess, "run", side_effect=error):
            with pytest.raises(SystemExit) as excinfo:
                module.export_requirements(tmp_path / "requirements.txt")

        assert "exit code 2" in str(excinfo.value)
        assert "bad lockfile" in str(excinfo.value)

    def test_run_gate_returns_pip_audit_failure_code(self, tmp_path):
        module = self._load_module()
        req = tmp_path / "requirements.txt"
        req.write_text("pyjwt==2.12.1\n")
        allowlist = tmp_path / "allowlist.txt"
        allowlist.write_text("PYSEC-2025-183 2099-01-01 # temporary\n")

        completed = subprocess.CompletedProcess(["python", "-m", "pip_audit"], 7)
        with patch.object(module.subprocess, "run", return_value=completed) as run:
            assert module.run_gate(req, allowlist) == 7

        cmd = run.call_args.args[0]
        assert "--requirement" in cmd
        assert str(req) in cmd


# ---------------------------------------------------------------------------
# 3. Secret scanning gate
# ---------------------------------------------------------------------------


class TestSecretsScanGate:
    """Test the hardcoded secrets pattern scanner."""

    def test_secret_patterns_defined(self):
        """Verify secret patterns are loaded."""
        import importlib.util

        spec = importlib.util.spec_from_file_location(
            "pre_release_check",
            str(PROJECT_ROOT / "scripts" / "pre_release_check.py"),
        )
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)

        assert len(module.SECRET_PATTERNS) >= 5, "should define at least 5 secret patterns"

    def test_aws_key_pattern_detects_key(self):
        """AWS access key pattern should match a real-format key."""
        pattern = r"(?<![A-Z0-9])(AKIA[0-9A-Z]{16})(?![A-Z0-9])"
        # This is a fake key for testing
        assert re.search(pattern, 'key = "AKIAIOSFODNN7EXAMPLE"')
        assert not re.search(pattern, "# just a comment about AKIA keys")

    def test_private_key_pattern_detects_header(self):
        """Private key pattern should match PEM headers."""
        pattern = r"-----BEGIN\s+(RSA|EC|DSA|OPENSSH)?\s*PRIVATE KEY-----"
        assert re.search(pattern, "-----BEGIN RSA PRIVATE KEY-----")
        assert re.search(pattern, "-----BEGIN PRIVATE KEY-----")
        assert not re.search(pattern, "-----BEGIN CERTIFICATE-----")

    def test_scan_excludes_test_files(self):
        """Scanner should skip test files."""
        import importlib.util

        spec = importlib.util.spec_from_file_location(
            "pre_release_check",
            str(PROJECT_ROOT / "scripts" / "pre_release_check.py"),
        )
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)

        # Create a fake Path that looks like a test file
        test_file = PROJECT_ROOT / "tests" / "test_something.py"
        assert not module._should_scan_file(test_file), "should not scan test files"

    def test_scan_excludes_node_modules(self):
        """Scanner should skip node_modules."""
        import importlib.util

        spec = importlib.util.spec_from_file_location(
            "pre_release_check",
            str(PROJECT_ROOT / "scripts" / "pre_release_check.py"),
        )
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)

        nm_file = PROJECT_ROOT / "aragora" / "live" / "node_modules" / "foo" / "index.js"
        # _should_scan_file checks for "node_modules/" in the relative path
        assert not module._should_scan_file(nm_file), "should not scan node_modules"


# ---------------------------------------------------------------------------
# 4. Status doc validation gate
# ---------------------------------------------------------------------------


class TestStatusDocGate:
    """Test the STATUS.md validation gate."""

    def test_status_doc_exists(self):
        """docs/STATUS.md must exist."""
        status_path = PROJECT_ROOT / "docs" / "STATUS.md"
        assert status_path.exists(), "docs/STATUS.md does not exist"

    def test_status_doc_has_heading(self):
        """STATUS.md must have a top-level heading."""
        status_path = PROJECT_ROOT / "docs" / "STATUS.md"
        content = status_path.read_text()
        assert any(line.startswith("# ") for line in content.splitlines()), (
            "STATUS.md should have a top-level heading"
        )

    def test_status_doc_has_sections(self):
        """STATUS.md must have section headings."""
        status_path = PROJECT_ROOT / "docs" / "STATUS.md"
        content = status_path.read_text()
        sections = [line for line in content.splitlines() if line.startswith("## ")]
        assert len(sections) >= 1, "STATUS.md should have at least one ## section"

    def test_gate_function_passes_for_valid_doc(self):
        """gate_status_doc should pass for the real STATUS.md."""
        import importlib.util

        spec = importlib.util.spec_from_file_location(
            "pre_release_check",
            str(PROJECT_ROOT / "scripts" / "pre_release_check.py"),
        )
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)

        # Clear results
        module._results.clear()
        result = module.gate_status_doc()
        assert result is True, "gate_status_doc should pass for real STATUS.md"


# ---------------------------------------------------------------------------
# 5. Version-tag consistency gate
# ---------------------------------------------------------------------------


class TestVersionTagGate:
    """Test the version-tag consistency gate."""

    def test_pyproject_toml_has_version(self):
        """pyproject.toml must have a valid version."""
        pyproject_path = PROJECT_ROOT / "pyproject.toml"
        content = pyproject_path.read_text()
        match = re.search(r'^version\s*=\s*["\']([^"\']+)["\']', content, re.MULTILINE)
        assert match, "pyproject.toml should have a version field"
        version = match.group(1)
        assert re.match(r"^\d+\.\d+\.\d+", version), f"version should be semver: {version}"

    def test_gate_passes_without_release_env(self):
        """Version gate should pass when RELEASE_VERSION is not set."""
        import importlib.util

        spec = importlib.util.spec_from_file_location(
            "pre_release_check",
            str(PROJECT_ROOT / "scripts" / "pre_release_check.py"),
        )
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)

        module._results.clear()
        # Ensure RELEASE_VERSION is not set
        old_val = os.environ.pop("RELEASE_VERSION", None)
        try:
            result = module.gate_version_tag()
            assert result is True, "gate_version_tag should pass when no release tag is set"
        finally:
            if old_val is not None:
                os.environ["RELEASE_VERSION"] = old_val


# ---------------------------------------------------------------------------
# 6. Smoke test integration
# ---------------------------------------------------------------------------


class TestSmokeTestIntegration:
    """Test that the smoke test script exists and is runnable."""

    def test_smoke_test_script_exists(self):
        script = PROJECT_ROOT / "scripts" / "smoke_test.py"
        assert script.exists(), "scripts/smoke_test.py does not exist"

    def test_smoke_test_has_skip_server_flag(self):
        """smoke_test.py should support --skip-server flag."""
        script = PROJECT_ROOT / "scripts" / "smoke_test.py"
        content = script.read_text()
        assert "--skip-server" in content, "smoke_test.py should support --skip-server"

    def test_integration_smoke_test_exists(self):
        test_file = PROJECT_ROOT / "tests" / "integration" / "test_smoke.py"
        assert test_file.exists(), "tests/integration/test_smoke.py does not exist"

    def test_openapi_sync_test_exists(self):
        test_file = PROJECT_ROOT / "tests" / "sdk" / "test_openapi_sync.py"
        assert test_file.exists(), "tests/sdk/test_openapi_sync.py does not exist"

    def test_contract_parity_test_exists(self):
        test_file = PROJECT_ROOT / "tests" / "sdk" / "test_contract_parity.py"
        assert test_file.exists(), "tests/sdk/test_contract_parity.py does not exist"
