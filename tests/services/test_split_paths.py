"""Old aragora.services paths re-export the objects that moved to lower layers."""

from __future__ import annotations

import ast
import inspect
import os
import subprocess
import sys
from pathlib import Path

import pytest

import aragora.billing.metering_models as new_models
import aragora.billing.usage_metering as new_metering
import aragora.embeddings.service_markers as markers
import aragora.runtime.service_registry as new_registry
import aragora.services as services
import aragora.services.metering_models as old_models
import aragora.services.registry as old_registry
import aragora.services.usage_metering as old_metering

REPO_ROOT = Path(__file__).resolve().parents[2]

# Public names of aragora/services/registry.py before the move (it had no __all__).
REGISTRY_NAMES = (
    "RegistryStats",
    "ServiceDescriptor",
    "ServiceNotFoundError",
    "ServiceRegistry",
    "ServiceScope",
    "get_service",
    "has_service",
    "register_service",
)
MARKER_NAMES = ("EmbeddingCacheService", "EmbeddingProviderService")
# __all__ of aragora/services/metering_models.py before the move.
METERING_MODEL_NAMES = (
    "MeteringPeriod",
    "UsageType",
    "MODEL_PRICING",
    "TIER_USAGE_CAPS",
    "TokenUsageRecord",
    "DebateUsageRecord",
    "ApiCallRecord",
    "HourlyAggregate",
    "UsageSummary",
    "UsageLimits",
    "UsageBreakdown",
)
# __all__ of aragora/services/usage_metering.py before the move, plus its public DB default.
USAGE_METERING_NAMES = (
    "UsageMeter",
    "UsageSummary",
    "UsageBreakdown",
    "UsageLimits",
    "TokenUsageRecord",
    "DebateUsageRecord",
    "ApiCallRecord",
    "HourlyAggregate",
    "MeteringPeriod",
    "UsageType",
    "MODEL_PRICING",
    "TIER_USAGE_CAPS",
    "get_usage_meter",
    "DEFAULT_METERING_DB",
)

PAIRS = (
    [(old_registry, new_registry, name) for name in REGISTRY_NAMES]
    + [(services, new_registry, name) for name in REGISTRY_NAMES]
    + [(services, markers, name) for name in MARKER_NAMES]
    + [(old_models, new_models, name) for name in METERING_MODEL_NAMES]
    + [(old_metering, new_metering, name) for name in USAGE_METERING_NAMES]
)
HOME_MODULES = {
    "aragora.runtime.service_registry",
    "aragora.embeddings.service_markers",
    "aragora.billing.metering_models",
    "aragora.billing.usage_metering",
}


@pytest.fixture
def clean_registry():
    new_registry.ServiceRegistry.reset()
    yield
    new_registry.ServiceRegistry.reset()


@pytest.mark.parametrize(
    ("old", "new", "name"),
    PAIRS,
    ids=lambda value: value if isinstance(value, str) else value.__name__,
)
def test_old_path_reexports_identical_object(old, new, name: str) -> None:
    assert getattr(old, name) is getattr(new, name)


@pytest.mark.parametrize(
    ("old", "new", "name"),
    PAIRS,
    ids=lambda value: value if isinstance(value, str) else value.__name__,
)
def test_implementation_lives_in_the_lower_layer(old, new, name: str) -> None:
    value = getattr(old, name)
    if inspect.isclass(value) or inspect.isfunction(value):
        home = inspect.getmodule(value)
        assert home is not None and home.__name__ in HOME_MODULES
        assert getattr(home, name) is value


def test_old_path_all_lists_unchanged() -> None:
    assert sorted(old_models.__all__) == sorted(METERING_MODEL_NAMES)
    assert sorted(old_metering.__all__) == sorted(
        set(USAGE_METERING_NAMES) - {"DEFAULT_METERING_DB"}
    )
    assert set(REGISTRY_NAMES) | set(MARKER_NAMES) <= set(services.__all__)


def test_registry_state_is_shared(clean_registry) -> None:
    class Probe:
        pass

    probe = Probe()
    old_registry.register_service(Probe, probe)
    assert new_registry.get_service(Probe) is probe
    assert services.has_service(Probe)

    cache = object()
    new_registry.register_service(services.EmbeddingCacheService, cache)
    assert old_registry.get_service(markers.EmbeddingCacheService) is cache

    old_registry.ServiceRegistry.reset()
    assert not new_registry.has_service(Probe)
    assert not services.has_service(markers.EmbeddingCacheService)


def test_fixed_input_registry_calls_at_both_paths(clean_registry) -> None:
    old_registry.register_service(str, "value")
    old_stats = old_registry.ServiceRegistry.get().stats()
    new_stats = new_registry.ServiceRegistry.get().stats()
    assert old_stats == new_stats
    assert new_stats.total_services == 1
    with pytest.raises(old_registry.ServiceNotFoundError):
        new_registry.get_service(int)


def test_runtime_package_exports_resolve_lazily() -> None:
    import aragora.runtime as runtime
    import aragora.runtime.autotune as autotune
    import aragora.runtime.metadata as metadata

    assert runtime.Autotuner is autotune.Autotuner
    assert runtime.DebateMetadata is metadata.DebateMetadata
    with pytest.raises(AttributeError):
        runtime.not_a_runtime_export  # noqa: B018


def _run(code: str) -> str:
    env = {**os.environ, "PYTHONPATH": str(REPO_ROOT)}
    result = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        cwd=str(REPO_ROOT),
        env=env,
        timeout=120,
    )
    assert result.returncode == 0, result.stderr[-2000:]
    return result.stdout


@pytest.mark.parametrize("first", ["aragora.services", "aragora.runtime", "aragora.billing"])
def test_identity_holds_in_every_import_order(first: str) -> None:
    out = _run(
        f"import importlib; importlib.import_module({first!r})\n"
        "import aragora.services as s, aragora.services.registry as r\n"
        "import aragora.services.usage_metering as u\n"
        "from aragora.runtime import service_registry as nr\n"
        "from aragora.embeddings import service_markers as m\n"
        "from aragora.billing import usage_metering as nu\n"
        "assert s.ServiceRegistry is r.ServiceRegistry is nr.ServiceRegistry\n"
        "assert s.EmbeddingProviderService is m.EmbeddingProviderService\n"
        "assert u.get_usage_meter is nu.get_usage_meter\n"
        "print('ok')\n"
    )
    assert out.strip() == "ok"


def test_registry_import_stays_light() -> None:
    out = _run(
        "import sys\n"
        "import aragora.runtime.service_registry\n"
        "print(sorted(m for m in sys.modules if m.startswith(("
        "'aragora.runtime.metadata', 'aragora.storage', 'aragora.embeddings'))))\n"
    )
    assert out.strip() == "[]"


def test_usage_meter_singleton_shared(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    meter = old_metering.UsageMeter(db_path=tmp_path / "metering.db")
    monkeypatch.setattr(new_metering, "_usage_meter", meter)
    assert old_metering.get_usage_meter() is meter
    assert new_metering.get_usage_meter() is meter


async def test_usage_written_via_old_path_reads_via_new(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(new_metering, "_usage_meter", None)
    monkeypatch.setattr(new_metering, "DEFAULT_METERING_DB", tmp_path / "metering.db")
    meter = old_metering.get_usage_meter()
    try:
        await meter.record_token_usage(
            org_id="se2", input_tokens=10, output_tokens=5, model="gpt-4o", provider="openai"
        )
        await meter.flush_all()
        summary = await new_metering.get_usage_meter().get_usage_summary(org_id="se2", period="day")
        assert summary.input_tokens == 10
        assert summary.output_tokens == 5
        assert summary.total_tokens == 15
    finally:
        await meter.close()


def test_fixed_input_cost_at_both_paths(tmp_path: Path) -> None:
    old_cost = old_metering.UsageMeter(db_path=tmp_path / "a.db")._calculate_token_cost(
        "openai", "gpt-4o", 1_000_000, 1_000_000
    )
    new_cost = new_metering.UsageMeter(db_path=tmp_path / "b.db")._calculate_token_cost(
        "openai", "gpt-4o", 1_000_000, 1_000_000
    )
    assert old_cost == new_cost
    assert old_models.MODEL_PRICING is new_models.MODEL_PRICING


def _imported_modules(path: Path) -> list[tuple[int, str]]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    found: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found.extend((node.lineno, alias.name) for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            found.append((node.lineno, node.module))
            if node.module == "aragora":
                found.extend((node.lineno, f"aragora.{alias.name}") for alias in node.names)
        elif isinstance(node, ast.Call) and node.args and isinstance(node.args[0], ast.Constant):
            func = node.func
            name = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", "")
            if name in {"import_module", "__import__"} and isinstance(node.args[0].value, str):
                found.append((node.lineno, node.args[0].value))
    return found


MOVED_MODULES = [
    "aragora/runtime/__init__.py",
    "aragora/runtime/service_registry.py",
    "aragora/embeddings/service_markers.py",
    "aragora/billing/metering_models.py",
    "aragora/billing/usage_metering.py",
]
FLIPPED_SITES = [
    "aragora/agents/api_agents/rate_limiter.py",
    "aragora/billing/usage_metering_integration.py",
    "aragora/debate/orchestrator_runner.py",
    "aragora/debate/telemetry_config.py",
    "aragora/memory/embeddings.py",
    "aragora/memory/streams.py",
    "aragora/memory/tier_manager.py",
]


@pytest.mark.parametrize("relative_path", MOVED_MODULES + FLIPPED_SITES)
def test_no_import_of_services(relative_path: str) -> None:
    offenders = [
        f"{relative_path}:{lineno} {module}"
        for lineno, module in _imported_modules(REPO_ROOT / relative_path)
        if ".".join(module.split(".")[:2]) == "aragora.services"
    ]
    assert offenders == []
