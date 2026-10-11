"""Provider-availability probes under mounted secret custody.

Keys served from a protected ``ARAGORA_SECRETS_DIR`` report presence source
``mounted_file``. Consumers must read availability through
``is_secret_presence_available`` rather than enumerate sources, or a mounted key
looks absent. A rejected mounted file fails reads of its own name; the boolean
probes that unrelated work runs first must report it unavailable, not raise.
"""

from __future__ import annotations

import ast
import importlib
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import pytest

from aragora.config import secrets as secrets_module

_REPO_ROOT = Path(__file__).resolve().parents[2]
_PROVIDER_NAMES = (
    "ANTHROPIC_API_KEY",
    "OPENAI_API_KEY",
    "OPENROUTER_API_KEY",
    "GEMINI_API_KEY",
    "GOOGLE_API_KEY",
)
_SYNTHETIC_VALUE = "synthetic-presence-consumer-value-0000000000"


def _attr(module: str, name: str) -> Callable[..., Any]:
    return getattr(importlib.import_module(module), name)


_CONSUMERS: dict[str, Callable[[], object]] = {
    "cli.review._has_api_key": lambda: _attr("aragora.cli.review", "_has_api_key")(
        "ANTHROPIC_API_KEY"
    ),
    "config.minimal._secret_available": lambda: _attr(
        "aragora.config.minimal", "_secret_available"
    )("ANTHROPIC_API_KEY"),
    "swarm.boss_loop_selection._has_api_key": lambda: _attr(
        "aragora.swarm.boss_loop_selection", "_has_api_key"
    )("ANTHROPIC_API_KEY"),
    "inbox.triage_runner._has_api_key": lambda: _attr(
        "aragora.inbox.triage_runner", "_has_api_key"
    )("ANTHROPIC_API_KEY"),
    "rlm.bridge._secret_configured": lambda: _attr("aragora.rlm.bridge", "_secret_configured")(
        "OPENROUTER_API_KEY"
    ),
    "swarm.review_routing._direct_api_provider_preflight": lambda: _attr(
        "aragora.swarm.review_routing", "_direct_api_provider_preflight"
    )("gemini")["ok"],
    "config.model_pins.route_through_openrouter is False": lambda: not _attr(
        "aragora.config.model_pins", "route_through_openrouter"
    )(),
    "routing.domain_matcher.DomainDetector.use_llm": lambda: _attr(
        "aragora.routing.domain_matcher", "DomainDetector"
    )(use_llm=True).use_llm,
    "server.stream.debate_executor._openrouter_key_available": lambda: _attr(
        "aragora.server.stream.debate_executor", "_openrouter_key_available"
    )(),
}


@pytest.fixture
def mount_keys(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Callable[..., Path]]:
    """Serve synthetic provider keys only from a protected mounted directory."""
    for name in _PROVIDER_NAMES:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.delenv("ARAGORA_SECRETS_STRICT", raising=False)
    monkeypatch.setenv("ARAGORA_ENV", "development")
    monkeypatch.setenv("ARAGORA_USE_SECRETS_MANAGER", "false")

    def mount(**modes: int) -> Path:
        directory = tmp_path / "secrets"
        directory.mkdir()
        directory.chmod(0o700)
        for name, mode in modes.items():
            path = directory / name
            path.write_text(_SYNTHETIC_VALUE)
            path.chmod(mode)
        monkeypatch.setenv("ARAGORA_SECRETS_DIR", str(directory))
        secrets_module.reset_secret_manager()
        return directory

    secrets_module.reset_secret_manager()
    yield mount
    secrets_module.reset_secret_manager()


@pytest.mark.parametrize("consumer", sorted(_CONSUMERS))
def test_mounted_provider_keys_are_available_to_consumers(
    mount_keys: Callable[..., Path], consumer: str
) -> None:
    mount_keys(**dict.fromkeys(_PROVIDER_NAMES, 0o600))
    assert secrets_module.get_secret_presence("ANTHROPIC_API_KEY").source == "mounted_file"

    assert _CONSUMERS[consumer]() is True


def test_rejected_mounted_key_fails_its_reads_but_not_the_availability_probe(
    mount_keys: Callable[..., Path],
) -> None:
    mount_keys(ANTHROPIC_API_KEY=0o600, OPENROUTER_API_KEY=0o644)
    available = _attr("aragora.server.stream.debate_executor", "_openrouter_key_available")

    assert available() is False
    with pytest.raises(secrets_module.SecretSourceError, match="OPENROUTER_API_KEY"):
        secrets_module.get_secret("OPENROUTER_API_KEY")
    assert secrets_module.get_secret("ANTHROPIC_API_KEY") == _SYNTHETIC_VALUE


def test_unusable_custody_still_raises_from_the_availability_probe(
    mount_keys: Callable[..., Path],
) -> None:
    directory = mount_keys(OPENROUTER_API_KEY=0o600)
    directory.chmod(0o777)
    secrets_module.reset_secret_manager()
    available = _attr("aragora.server.stream.debate_executor", "_openrouter_key_available")

    with pytest.raises(secrets_module.SecretSourceError, match="ARAGORA_SECRETS_DIR"):
        available()


def _enumerated_source_checks(path: Path) -> list[int]:
    """Lines comparing a presence ``.source`` against a literal set of source names."""
    lines = []
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if not isinstance(node, ast.Compare) or not isinstance(node.left, ast.Attribute):
            continue
        if node.left.attr != "source" or not isinstance(node.left.value, ast.Call):
            continue
        func = node.left.value.func
        called = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", "")
        if called not in {"get_secret_presence", "presence"}:
            continue
        for op, comparator in zip(node.ops, node.comparators):
            if isinstance(op, (ast.In, ast.NotIn)) and isinstance(
                comparator, (ast.Set, ast.Tuple, ast.List)
            ):
                lines.append(node.lineno)
    return lines


def test_no_consumer_enumerates_available_custody_sources() -> None:
    offenders: list[str] = []
    for path in sorted((_REPO_ROOT / "aragora").rglob("*.py")):
        if path == _REPO_ROOT / "aragora" / "config" / "secrets.py":
            continue
        text = path.read_text(encoding="utf-8")
        if "get_secret_presence" not in text and ".presence(" not in text:
            continue
        offenders.extend(
            f"{path.relative_to(_REPO_ROOT)}:{line}" for line in _enumerated_source_checks(path)
        )

    assert offenders == [], "use is_secret_presence_available() instead of: " + ", ".join(offenders)
