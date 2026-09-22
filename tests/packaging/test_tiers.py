"""Tier import validation tests.

Validates that each packaging tier's core modules can be imported
independently. See docs/PACKAGING.md for tier definitions.

These tests verify *importability*, not full functionality — modules
may defer heavy imports (e.g. web3, playwright) behind try/except.
"""

import importlib
import sys

import pytest
from packaging.requirements import Requirement


# ---------------------------------------------------------------------------
# Tier 1: Core Primitives (always installed)
# ---------------------------------------------------------------------------


class TestTier1Core:
    """Core debate/gauntlet/ranking/knowledge modules must always import."""

    @pytest.mark.parametrize(
        "module",
        [
            "aragora.debate.orchestrator",
            "aragora.debate.consensus",
            "aragora.debate.convergence",
            "aragora.debate.phases",
            "aragora.gauntlet.runner",
            "aragora.gauntlet.receipt",
            "aragora.gauntlet.result",
            "aragora.ranking.elo",
            "aragora.knowledge.mound",
            "aragora.knowledge.bridges",
        ],
    )
    def test_core_module_imports(self, module: str) -> None:
        mod = importlib.import_module(module)
        assert mod is not None

    def test_arena_class_available(self) -> None:
        from aragora.debate.orchestrator import Arena

        assert Arena is not None

    def test_consensus_builder_available(self) -> None:
        from aragora.debate.consensus import ConsensusBuilder

        assert ConsensusBuilder is not None

    def test_elo_system_available(self) -> None:
        from aragora.ranking.elo import EloSystem

        assert EloSystem is not None

    def test_gauntlet_runner_available(self) -> None:
        from aragora.gauntlet.runner import GauntletRunner

        assert GauntletRunner is not None


# ---------------------------------------------------------------------------
# Tier 2: Gateway (OpenClaw)
# ---------------------------------------------------------------------------


class TestTier2Gateway:
    """OpenClaw gateway modules import without extra deps."""

    @pytest.mark.parametrize(
        "module",
        [
            "aragora.compat.openclaw",
            "aragora.compat.openclaw.standalone",
            "aragora.compat.openclaw.skill_scanner",
        ],
    )
    def test_gateway_module_imports(self, module: str) -> None:
        mod = importlib.import_module(module)
        assert mod is not None


# ---------------------------------------------------------------------------
# Tier 3: Blockchain (ERC-8004)
# ---------------------------------------------------------------------------


class TestTier3Blockchain:
    """Blockchain modules import; web3 dependency is lazy."""

    @pytest.mark.parametrize(
        "module",
        [
            "aragora.blockchain",
            "aragora.blockchain.models",
        ],
    )
    def test_blockchain_module_imports(self, module: str) -> None:
        mod = importlib.import_module(module)
        assert mod is not None

    def test_blockchain_adapter_imports(self) -> None:
        mod = importlib.import_module("aragora.knowledge.mound.adapters.erc8004_adapter")
        assert mod is not None


# ---------------------------------------------------------------------------
# Tier 4: Enterprise
# ---------------------------------------------------------------------------


class TestTier4Enterprise:
    """Enterprise auth/RBAC/security/compliance modules import."""

    @pytest.mark.parametrize(
        "module",
        [
            "aragora.auth",
            "aragora.auth.oidc",
            "aragora.rbac",
            "aragora.rbac.models",
            "aragora.rbac.checker",
            "aragora.rbac.decorators",
            "aragora.tenancy",
            "aragora.compliance",
            "aragora.security",
            "aragora.security.encryption",
            "aragora.backup",
            "aragora.backup.manager",
        ],
    )
    def test_enterprise_module_imports(self, module: str) -> None:
        mod = importlib.import_module(module)
        assert mod is not None

    def test_rbac_permission_checker(self) -> None:
        from aragora.rbac.checker import PermissionChecker

        assert PermissionChecker is not None


# ---------------------------------------------------------------------------
# Tier 5: Connectors
# ---------------------------------------------------------------------------


class TestTier5Connectors:
    """Connector modules import; heavy deps are lazy."""

    @pytest.mark.parametrize(
        "module",
        [
            "aragora.connectors",
            "aragora.integrations",
        ],
    )
    def test_connector_module_imports(self, module: str) -> None:
        mod = importlib.import_module(module)
        assert mod is not None

    @pytest.mark.parametrize(
        "module",
        [
            "aragora.connectors.enterprise.streaming.kafka",
            "aragora.connectors.enterprise.streaming.rabbitmq",
        ],
    )
    def test_streaming_modules_import(self, module: str) -> None:
        """Streaming connectors should import even without aiokafka/aio-pika."""
        mod = importlib.import_module(module)
        assert mod is not None


# ---------------------------------------------------------------------------
# Tier 6: Experimental
# ---------------------------------------------------------------------------


class TestTier6Experimental:
    """Experimental modules import without extra deps."""

    @pytest.mark.parametrize(
        "module",
        [
            "aragora.genesis",
            "aragora.introspection",
            "aragora.visualization",
        ],
    )
    def test_experimental_module_imports(self, module: str) -> None:
        mod = importlib.import_module(module)
        assert mod is not None


# ---------------------------------------------------------------------------
# Cross-tier: no tier should pull in another tier's required imports
# ---------------------------------------------------------------------------


class TestTierIsolation:
    """Verify that importing one tier doesn't force-import another tier's packages."""

    def test_core_does_not_require_web3(self) -> None:
        """Core tier must not depend on web3 (blockchain tier)."""
        # If web3 is installed, temporarily hide it
        hidden = {}
        for name in list(sys.modules):
            if name == "web3" or name.startswith("web3."):
                hidden[name] = sys.modules.pop(name)
        try:
            # Re-import core modules — they must succeed
            importlib.reload(importlib.import_module("aragora.debate.orchestrator"))
            importlib.reload(importlib.import_module("aragora.ranking.elo"))
        finally:
            sys.modules.update(hidden)

    def test_core_does_not_require_playwright(self) -> None:
        """Core tier must not depend on playwright (experimental tier)."""
        hidden = {}
        for name in list(sys.modules):
            if name == "playwright" or name.startswith("playwright."):
                hidden[name] = sys.modules.pop(name)
        try:
            importlib.reload(importlib.import_module("aragora.debate.orchestrator"))
            importlib.reload(importlib.import_module("aragora.gauntlet.runner"))
        finally:
            sys.modules.update(hidden)

    def test_core_does_not_require_saml(self) -> None:
        """Core tier must not depend on python3-saml (enterprise tier)."""
        hidden = {}
        for name in list(sys.modules):
            if name == "onelogin" or name.startswith("onelogin."):
                hidden[name] = sys.modules.pop(name)
        try:
            importlib.reload(importlib.import_module("aragora.debate.orchestrator"))
        finally:
            sys.modules.update(hidden)


# ---------------------------------------------------------------------------
# Dependency group metadata
# ---------------------------------------------------------------------------


class TestDependencyGroups:
    """Verify pyproject.toml declares the expected tier groups."""

    @pytest.fixture()
    def optional_deps(self) -> dict:
        """Parse optional-dependencies from pyproject.toml."""
        import tomllib
        from pathlib import Path

        pyproject = Path(__file__).resolve().parents[2] / "pyproject.toml"
        with open(pyproject, "rb") as f:
            data = tomllib.load(f)
        return data["project"]["optional-dependencies"]

    @pytest.mark.parametrize(
        "group",
        [
            "gateway",
            "blockchain",
            "enterprise",
            "connectors",
            "experimental",
        ],
    )
    def test_tier_group_exists(self, optional_deps: dict, group: str) -> None:
        assert group in optional_deps, f"Missing optional-dependencies group: {group}"

    def test_enterprise_includes_saml(self, optional_deps: dict) -> None:
        deps = " ".join(optional_deps.get("enterprise", []))
        assert "python3-saml" in deps

    def test_connectors_includes_kafka(self, optional_deps: dict) -> None:
        deps = " ".join(optional_deps.get("connectors", []))
        assert "aiokafka" in deps

    def test_all_group_exists(self, optional_deps: dict) -> None:
        assert "all" in optional_deps

    def test_test_group_includes_jsonschema(self, optional_deps: dict) -> None:
        jsonschema_requirement = next(
            Requirement(raw_requirement)
            for raw_requirement in optional_deps["test"]
            if Requirement(raw_requirement).name == "jsonschema"
        )
        assert str(jsonschema_requirement.specifier) == "<5.0,>=4.23"
