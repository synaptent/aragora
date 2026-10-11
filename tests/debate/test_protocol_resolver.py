"""Tests for the canonical debate protocol resolver and its compatibility paths."""

from __future__ import annotations

import ast
import importlib
import logging
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

import aragora.protocols.debate as canonical_protocols
import aragora.resilience as resilience
from aragora.config import DEFAULT_CONSENSUS, DEFAULT_ROUNDS
from aragora.debate.protocol_resolver import resolve_default_protocol
from aragora.nomic.debate_profile import NomicDebateProfile
from aragora.protocols.debate import DebateProtocol

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _module_imports(relative_path: str) -> set[str]:
    tree = ast.parse((PROJECT_ROOT / relative_path).read_text(encoding="utf-8"))
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            imported.add(node.module)
        elif isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
    return imported


class TestResolveDefaultProtocol:
    def test_explicit_protocol_takes_precedence(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("ARAGORA_DEBATE_PROFILE", "nomic")
        explicit = DebateProtocol(rounds=2)

        assert resolve_default_protocol(explicit) is explicit

    def test_defaults_without_profile(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("ARAGORA_DEBATE_PROFILE", raising=False)

        protocol = resolve_default_protocol()

        assert isinstance(protocol, DebateProtocol)
        assert protocol.rounds == DEFAULT_ROUNDS
        assert protocol.consensus == DEFAULT_CONSENSUS

    @pytest.mark.parametrize("profile", ["full", "nomic", "structured", "NOMIC"])
    def test_profile_env_uses_nomic_profile(
        self, monkeypatch: pytest.MonkeyPatch, profile: str
    ) -> None:
        sentinel = DebateProtocol(rounds=7)

        class _Profile:
            def to_protocol(self) -> DebateProtocol:
                return sentinel

        monkeypatch.setenv("ARAGORA_DEBATE_PROFILE", profile)
        monkeypatch.setattr(NomicDebateProfile, "from_env", classmethod(lambda cls: _Profile()))

        assert resolve_default_protocol() is sentinel

    def test_profile_env_builds_real_nomic_protocol(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("ARAGORA_DEBATE_PROFILE", "full")

        protocol = resolve_default_protocol()

        expected = NomicDebateProfile.from_env().to_protocol()
        assert isinstance(protocol, DebateProtocol)
        assert protocol.rounds == expected.rounds
        assert protocol.consensus == expected.consensus

    def test_unknown_profile_falls_back_to_defaults(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("ARAGORA_DEBATE_PROFILE", "unknown_profile")

        def _unexpected(cls: type[NomicDebateProfile]) -> NomicDebateProfile:
            raise AssertionError("unknown profiles must not load the Nomic profile")

        monkeypatch.setattr(NomicDebateProfile, "from_env", classmethod(_unexpected))

        protocol = resolve_default_protocol()

        assert protocol.rounds == DEFAULT_ROUNDS
        assert protocol.consensus == DEFAULT_CONSENSUS

    def test_profile_failure_logs_warning_and_falls_back(
        self, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
    ) -> None:
        def _broken(cls: type[NomicDebateProfile]) -> NomicDebateProfile:
            raise RuntimeError("profile unavailable")

        monkeypatch.setenv("ARAGORA_DEBATE_PROFILE", "nomic")
        monkeypatch.setattr(NomicDebateProfile, "from_env", classmethod(_broken))

        with caplog.at_level(logging.WARNING, logger="aragora.debate.protocol_resolver"):
            protocol = resolve_default_protocol()

        assert protocol.rounds == DEFAULT_ROUNDS
        assert "Failed to apply debate profile 'nomic': profile unavailable" in caplog.text


class TestCompatibilityExports:
    def test_legacy_protocol_module_reexports_resolver_identity(self) -> None:
        sys.modules.pop("aragora.debate.protocol", None)
        with pytest.warns(DeprecationWarning, match=r"aragora\.debate\.protocol"):
            legacy = importlib.import_module("aragora.debate.protocol")

        assert legacy.resolve_default_protocol is resolve_default_protocol
        assert legacy.DebateProtocol is DebateProtocol
        assert legacy.CircuitBreaker is resilience.CircuitBreaker

    @pytest.mark.parametrize(
        "name",
        [
            "ARAGORA_AI_LIGHT_PROTOCOL",
            "ARAGORA_AI_PROTOCOL",
            "DebateProtocol",
            "RoundPhase",
            "user_vote_multiplier",
        ],
    )
    def test_debate_package_exports_canonical_protocol_objects(self, name: str) -> None:
        import aragora.debate as debate_package

        assert getattr(debate_package, name) is getattr(canonical_protocols, name)

    def test_debate_package_exports_canonical_resolver_and_breaker(self) -> None:
        import aragora.debate as debate_package

        assert debate_package.resolve_default_protocol is resolve_default_protocol
        assert debate_package.CircuitBreaker is resilience.CircuitBreaker


class TestImportBoundaries:
    def test_protocols_debate_stays_data_only(self) -> None:
        imported = _module_imports("aragora/protocols/debate.py")

        assert not {
            module for module in imported if module.startswith(("aragora.debate", "aragora.nomic"))
        }

    def test_nomic_profile_does_not_import_debate_package(self) -> None:
        imported = _module_imports("aragora/nomic/debate_profile.py")

        assert not {module for module in imported if module.startswith("aragora.debate")}

    def test_canonical_imports_do_not_load_legacy_protocol_shim(self) -> None:
        script = textwrap.dedent(
            """
            import sys
            import warnings

            warnings.simplefilter("always")
            with warnings.catch_warnings(record=True) as caught:
                warnings.simplefilter("always")
                import aragora.debate.protocol_resolver
                import aragora.nomic.debate_profile
                import aragora.debate

            loaded = "aragora.debate.protocol" in sys.modules
            shim_warnings = [
                str(w.message)
                for w in caught
                if "aragora.debate.protocol is deprecated" in str(w.message)
            ]
            assert not loaded, "aragora.debate.protocol was imported"
            assert not shim_warnings, shim_warnings
            """
        )

        result = subprocess.run(
            [sys.executable, "-c", script],
            cwd=PROJECT_ROOT,
            capture_output=True,
            text=True,
            check=False,
            timeout=120,
        )

        assert result.returncode == 0, result.stderr or result.stdout
