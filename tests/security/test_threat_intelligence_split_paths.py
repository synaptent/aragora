"""Old aragora.services threat-intelligence paths re-export the objects that moved to aragora.security."""

from __future__ import annotations

import ast
import importlib
import inspect
import os
import subprocess
import sys
from pathlib import Path

import pytest

import aragora.security.threat_intelligence as new_ti
import aragora.services.threat_intelligence as old_ti

REPO_ROOT = Path(__file__).resolve().parents[2]

# Public names of each aragora/services/threat_intelligence/<name>.py before the move (none had __all__).
SUBMODULE_NAMES = {
    "assessment": ("ThreatAssessmentMixin",),
    "cache": ("ThreatCacheMixin",),
    "checkers": ("ThreatCheckersMixin",),
    "config": ("ThreatEventHandler", "ThreatIntelConfig"),
    "enums": (
        "MALICIOUS_URL_PATTERNS",
        "SUSPICIOUS_TLDS",
        "ThreatSeverity",
        "ThreatSource",
        "ThreatType",
    ),
    "models": (
        "FileHashResult",
        "IPReputationResult",
        "SourceResult",
        "ThreatAssessment",
        "ThreatResult",
    ),
    "service": ("ThreatIntelligenceService", "check_threat"),
}
# Names each old submodule also exposed because it imported them from a sibling module.
SUBMODULE_SIBLING_NAMES = {
    "assessment": (
        "SourceResult",
        "ThreatAssessment",
        "ThreatResult",
        "ThreatSeverity",
        "ThreatSource",
        "ThreatType",
    ),
    "cache": ("ThreatResult", "ThreatSeverity", "ThreatSource", "ThreatType"),
    "checkers": (
        "FileHashResult",
        "IPReputationResult",
        "SUSPICIOUS_TLDS",
        "ThreatResult",
        "ThreatSeverity",
        "ThreatSource",
        "ThreatType",
    ),
    "models": ("ThreatSeverity", "ThreatSource", "ThreatType"),
    "service": (
        "MALICIOUS_URL_PATTERNS",
        "ThreatAssessmentMixin",
        "ThreatCacheMixin",
        "ThreatCheckersMixin",
        "ThreatEventHandler",
        "ThreatIntelConfig",
        "ThreatResult",
        "ThreatSeverity",
        "ThreatSource",
        "ThreatType",
    ),
}
# __all__ of aragora/services/threat_intelligence/__init__.py before the move.
PACKAGE_NAMES = (
    "ThreatType",
    "ThreatSeverity",
    "ThreatSource",
    "MALICIOUS_URL_PATTERNS",
    "SUSPICIOUS_TLDS",
    "ThreatResult",
    "SourceResult",
    "ThreatAssessment",
    "IPReputationResult",
    "FileHashResult",
    "ThreatIntelConfig",
    "ThreatEventHandler",
    "ThreatIntelligenceService",
    "check_threat",
)
API_KEY_ENV = (
    "VIRUSTOTAL_API_KEY",
    "ABUSEIPDB_API_KEY",
    "PHISHTANK_API_KEY",
    "URLHAUS_API_KEY",
    "ARAGORA_REDIS_URL",
    "REDIS_URL",
)

PAIRS = (
    [
        (
            f"aragora.services.threat_intelligence.{sub}",
            f"aragora.security.threat_intelligence.{sub}",
            name,
        )
        for sub, names in SUBMODULE_NAMES.items()
        for name in names
    ]
    + [
        (
            f"aragora.services.threat_intelligence.{sub}",
            f"aragora.security.threat_intelligence.{sub}",
            name,
        )
        for sub, names in SUBMODULE_SIBLING_NAMES.items()
        for name in names
    ]
    + [
        ("aragora.services.threat_intelligence", "aragora.security.threat_intelligence", name)
        for name in PACKAGE_NAMES
    ]
)


@pytest.mark.parametrize(("old", "new", "name"), PAIRS)
def test_old_path_reexports_identical_object(old: str, new: str, name: str) -> None:
    value = getattr(importlib.import_module(old), name)
    assert value is getattr(importlib.import_module(new), name)
    if inspect.isclass(value) or inspect.isfunction(value):
        home = inspect.getmodule(value)
        assert home is not None
        assert home.__name__.startswith("aragora.security.threat_intelligence.")


def test_old_path_all_lists_unchanged() -> None:
    assert old_ti.__all__ == list(PACKAGE_NAMES)
    assert new_ti.__all__ == list(PACKAGE_NAMES)
    for sub, names in SUBMODULE_NAMES.items():
        shim = importlib.import_module(f"aragora.services.threat_intelligence.{sub}")
        expected = set(names) | set(SUBMODULE_SIBLING_NAMES.get(sub, ()))
        assert sorted(shim.__all__) == sorted(expected)


def _services(monkeypatch: pytest.MonkeyPatch) -> tuple[object, object]:
    for name in API_KEY_ENV:
        monkeypatch.delenv(name, raising=False)
    old_service = old_ti.ThreatIntelligenceService(
        config=old_ti.ThreatIntelConfig(enable_caching=False, enable_event_emission=False)
    )
    new_service = new_ti.ThreatIntelligenceService(
        config=new_ti.ThreatIntelConfig(enable_caching=False, enable_event_emission=False)
    )
    return old_service, new_service


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        (
            "https://bank-verify.example.com/x",
            {"threat_type": "PHISHING", "pattern": r"(?i)bank.*verify"},
        ),
        (
            "https://files.example.xyz/a",
            {"threat_type": "SUSPICIOUS", "pattern": "suspicious_tld:.xyz"},
        ),
        ("https://example.com/", None),
    ],
)
def test_fixed_input_url_patterns_at_both_paths(
    monkeypatch: pytest.MonkeyPatch, url: str, expected: dict[str, str] | None
) -> None:
    old_service, new_service = _services(monkeypatch)
    old_result = old_service._check_url_patterns(url)
    assert old_result == new_service._check_url_patterns(url)
    if expected is None:
        assert old_result is None
    else:
        assert old_result == {
            "threat_type": new_ti.ThreatType[expected["threat_type"]],
            "pattern": expected["pattern"],
        }


def test_fixed_input_aggregate_risk_at_both_paths(monkeypatch: pytest.MonkeyPatch) -> None:
    old_service, new_service = _services(monkeypatch)
    results = {
        "virustotal": old_ti.SourceResult(new_ti.ThreatSource.VIRUSTOTAL, True, 0.9),
        "local_rules": new_ti.SourceResult(old_ti.ThreatSource.LOCAL_RULES, False, 0.5),
    }
    old_risk = old_service._calculate_aggregate_risk(results)
    assert old_risk == new_service._calculate_aggregate_risk(results)
    overall, confidence, is_malicious = old_risk
    assert confidence == pytest.approx(1.06 / 1.4)
    assert overall == pytest.approx((1.06 / 1.4) * 0.6 + (0.9 / 1.4) * 0.4)
    assert is_malicious is True


def test_circuit_breakers_are_shared_across_paths(monkeypatch: pytest.MonkeyPatch) -> None:
    old_service, new_service = _services(monkeypatch)
    for source in ("virustotal", "abuseipdb", "phishtank", "urlhaus"):
        assert old_service._circuit_breakers[source] is new_service._circuit_breakers[source]


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


@pytest.mark.parametrize(
    "first",
    [
        "aragora.services",
        "aragora.services.threat_intelligence.service",
        "aragora.security",
        "aragora.server.handlers.security.threat_intel",
    ],
)
def test_identity_holds_in_every_import_order(first: str) -> None:
    out = _run(
        f"import importlib; importlib.import_module({first!r})\n"
        "import aragora.services.threat_intelligence as o\n"
        "import aragora.services.threat_intelligence.service as os_\n"
        "from aragora.security import threat_intelligence as n\n"
        "from aragora.security.threat_intelligence import service as ns\n"
        "assert o.ThreatIntelligenceService is os_.ThreatIntelligenceService\n"
        "assert os_.ThreatIntelligenceService is n.ThreatIntelligenceService\n"
        "assert n.ThreatIntelligenceService is ns.ThreatIntelligenceService\n"
        "print('ok')\n"
    )
    assert out.strip() == "ok"


def test_security_threat_intelligence_import_does_not_load_services() -> None:
    out = _run(
        "import sys\n"
        "import aragora.security.threat_intelligence\n"
        "import aragora.security.threat_intel_enrichment\n"
        "print(sorted(m for m in sys.modules if m.startswith('aragora.services')))\n"
    )
    assert out.strip() == "[]"


def _imports(path: Path) -> list[tuple[int, str]]:
    """Every absolute import, including TYPE_CHECKING and function-scope ones."""
    found: list[tuple[int, str]] = []

    def visit(node: ast.AST) -> None:
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
        for child in ast.iter_child_nodes(node):
            visit(child)

    visit(ast.parse(path.read_text(encoding="utf-8"), filename=str(path)))
    return found


MOVED_MODULES = [f"aragora/security/threat_intelligence/{sub}.py" for sub in SUBMODULE_NAMES] + [
    "aragora/security/threat_intelligence/__init__.py"
]
FLIPPED_SITES = ["aragora/security/threat_intel_enrichment.py"]


@pytest.mark.parametrize("relative_path", MOVED_MODULES + FLIPPED_SITES)
def test_no_import_of_services(relative_path: str) -> None:
    offenders = [
        f"{relative_path}:{lineno} {module}"
        for lineno, module in _imports(REPO_ROOT / relative_path)
        if ".".join(module.split(".")[:2]) == "aragora.services"
    ]
    assert offenders == []
