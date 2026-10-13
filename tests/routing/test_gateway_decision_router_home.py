"""The gateway decision router lives in ``aragora.routing.gateway_decision_router``.

``aragora.routing.unified_router`` (domain layer) drives it. The router used to live
in ``aragora.gateway`` (interface layer) and imports nothing from aragora, so it now
sits in the routing package. ``aragora.gateway.decision_router`` re-exports the same
objects and keeps its deprecation warning; ``aragora.gateway`` re-exports them too.
"""

from __future__ import annotations

import ast
import asyncio
import importlib
import sys
import warnings
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
NEW_HOME = "aragora.routing.gateway_decision_router"
OLD_HOME = "aragora.gateway.decision_router"
NAMES = tuple(
    "ActionCategory AlertHandlerProtocol AnomalyDetectorProtocol CategoryDefaults "
    "DEFAULT_CATEGORY_CONFIGS DecisionRouter RiskLevel RouteDecision RouteDestination "
    "RoutingAuditEntry RoutingCriteria RoutingEventType RoutingMetrics RoutingRule "
    "SimpleAnomalyDetector TenantRoutingConfig".split()
)
_ALIASES = tuple(
    "ActionCategory DecisionRouter DecisionRoutingEventType:RoutingEventType "
    "DecisionRoutingRule:RoutingRule DecisionTenantConfig:TenantRoutingConfig RiskLevel "
    "RouteDecision RouteDestination RoutingCriteria RoutingMetrics SimpleAnomalyDetector".split()
)
GATEWAY_ALIASES = dict(a.split(":") if ":" in a else (a, a) for a in _ALIASES)


@pytest.fixture
def import_fresh(monkeypatch):
    # Restore the cached modules afterwards so later tests keep comparing the original classes.
    def _import(module_name: str):
        parent_name, _, child = module_name.rpartition(".")
        parent = importlib.import_module(parent_name)
        monkeypatch.setattr(parent, child, getattr(parent, child, None), raising=False)
        for key in [k for k in sys.modules if k == module_name or k.startswith(module_name + ".")]:
            monkeypatch.delitem(sys.modules, key)
        return importlib.import_module(module_name)

    return _import


@pytest.fixture
def new():
    return importlib.import_module(NEW_HOME)


@pytest.fixture
def old():
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", DeprecationWarning)
        return importlib.import_module(OLD_HOME)


@pytest.mark.parametrize("name", NAMES)
def test_the_old_path_is_the_same_objects(new, old, name):
    assert getattr(old, name) is getattr(new, name)


@pytest.mark.parametrize(("alias", "name"), sorted(GATEWAY_ALIASES.items()))
def test_the_gateway_package_re_exports_the_same_objects(new, alias, name):
    assert getattr(importlib.import_module("aragora.gateway"), alias) is getattr(new, name)


def test_the_router_is_defined_in_the_routing_package(new, old):
    assert new.DecisionRouter.__module__ == NEW_HOME
    assert new.RouteDestination.__module__ == NEW_HOME
    assert sorted(new.__all__) == sorted(NAMES)
    assert sorted(old.__all__) == sorted(NAMES)


def test_the_old_path_still_warns_and_the_home_does_not(import_fresh):
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        import_fresh(NEW_HOME)
    assert not [w for w in caught if issubclass(w.category, DeprecationWarning)]

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        import_fresh(OLD_HOME)
    messages = [str(w.message) for w in caught if issubclass(w.category, DeprecationWarning)]
    assert any("aragora.core.decision_router" in message for message in messages)


@pytest.mark.parametrize("module_name", [OLD_HOME, NEW_HOME])
@pytest.mark.parametrize(
    ("amount", "destination"), [(50000, "debate"), (5000, "execute")], ids=["above", "below"]
)
def test_a_financial_request_routes_the_same_through_both_paths(module_name, amount, destination):
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", DeprecationWarning)
        module = importlib.import_module(module_name)
    router = module.DecisionRouter(criteria=module.RoutingCriteria(financial_threshold=10000.0))
    decision = asyncio.run(router.route({"amount": amount}))
    assert decision.destination.value == destination
    assert ("financial_threshold" in " ".join(decision.criteria_matched)) is (amount > 10000)


def _imported_modules(path: Path) -> list[tuple[int, str]]:
    found: list[tuple[int, str]] = []
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            found += [(node.lineno, alias.name) for alias in node.names]
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            found.append((node.lineno, node.module))
        elif isinstance(node, ast.Call) and node.args:
            callee = getattr(node.func, "attr", None) or getattr(node.func, "id", None)
            if callee in {"import_module", "__import__"}:
                found.append((node.lineno, ast.unparse(node.args[0]).strip("'\"")))
    return found


def test_routing_holds_no_import_of_gateway_at_any_scope():
    offenders = [
        f"{path.relative_to(REPO_ROOT)}:{lineno}: {name}"
        for path in sorted((REPO_ROOT / "aragora" / "routing").rglob("*.py"))
        for lineno, name in _imported_modules(path)
        if name == "aragora.gateway" or name.startswith("aragora.gateway.")
    ]
    assert offenders == []


def test_the_home_imports_nothing_from_aragora(new):
    imported = {
        name for _, name in _imported_modules(Path(new.__file__)) if name.startswith("aragora")
    }
    assert imported == set()
