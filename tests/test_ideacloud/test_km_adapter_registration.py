"""Regression coverage for Idea Cloud Knowledge Mound adapter registration."""

from aragora.knowledge.mound.adapters._base import ADAPTER_CIRCUIT_CONFIGS
from aragora.knowledge.mound.adapters.factory import _ADAPTER_DEFS


def test_ideacloud_adapter_registered_in_factory() -> None:
    names = [spec_kwargs.get("name", "") for _, _, spec_kwargs in _ADAPTER_DEFS]
    assert "ideacloud" in names


def test_ideacloud_adapter_has_circuit_breaker_config() -> None:
    assert "ideacloud" in ADAPTER_CIRCUIT_CONFIGS
