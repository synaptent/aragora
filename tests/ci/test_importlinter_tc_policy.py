"""Pin the TYPE_CHECKING exclusion policy of the import-layer contract.

`.importlinter` sets ``exclude_type_checking_imports = True`` so annotation-only
imports guarded by ``if TYPE_CHECKING:`` do not create layer edges, while runtime
imports (module scope or function scope) still do. import-linter only honours
the literal spellings ``True``/``true``; configparser-truthy values such as
``yes`` or ``1`` are silently treated as false, so the raw value is pinned.
"""

from __future__ import annotations

import ast
import configparser
import importlib.util
import uuid
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
_CONFIG = REPO_ROOT / ".importlinter"
_CHECKER_PATH = REPO_ROOT / "scripts" / "ci" / "check_import_contracts.py"
_POLICY_KEY = "exclude_type_checking_imports"


def _real_config() -> configparser.ConfigParser:
    parser = configparser.ConfigParser(interpolation=None)
    parser.read(_CONFIG, encoding="utf-8")
    return parser


def _load_checker():
    spec = importlib.util.spec_from_file_location("check_import_contracts_tc_policy", _CHECKER_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# --- config pin ---------------------------------------------------------------


def test_policy_set_in_importlinter_section_with_exact_spelling():
    parser = _real_config()
    assert parser.has_option("importlinter", _POLICY_KEY)
    assert parser.get("importlinter", _POLICY_KEY, raw=True) == "True"


def test_policy_not_set_inside_a_contract_section():
    parser = _real_config()
    for section in parser.sections():
        if section.startswith("importlinter:contract:"):
            assert not parser.has_option(section, _POLICY_KEY), section


def test_import_linter_reads_policy_from_real_config():
    # Importing importlinter.api runs import-linter's configure() step.
    pytest.importorskip("importlinter.api")
    from importlinter.application import use_cases

    options = use_cases.read_user_options(config_filename=str(_CONFIG))
    assert options.session_options.get(_POLICY_KEY) in ("True", "true")


# --- behaviour on a synthetic package ------------------------------------------


def _write_probe_package(
    root: Path, package: str, low_module_body: str, policy_value: str | None
) -> Path:
    """Create ``<package>.high`` / ``<package>.low`` with a two-layer contract.

    The ``[importlinter]`` policy value is copied from the real config so the
    probe exercises the repository's policy rather than a hand-written one.
    """
    pkg = root / package
    (pkg / "high").mkdir(parents=True)
    (pkg / "low").mkdir()
    (pkg / "__init__.py").write_text("", encoding="utf-8")
    (pkg / "high" / "__init__.py").write_text("VALUE = 1\n", encoding="utf-8")
    (pkg / "low" / "__init__.py").write_text("", encoding="utf-8")
    (pkg / "low" / "probe.py").write_text(low_module_body, encoding="utf-8")
    policy_line = f"{_POLICY_KEY} = {policy_value}\n" if policy_value is not None else ""
    config = root / ".importlinter"
    config.write_text(
        "[importlinter]\n"
        f"root_package = {package}\n"
        f"{policy_line}\n"
        "[importlinter:contract:probe-layers]\n"
        "name = probe layers\n"
        "type = layers\n"
        "containers =\n"
        f"    {package}\n"
        "layers =\n"
        "    high\n"
        "    low\n",
        encoding="utf-8",
    )
    return config


_TC_ONLY_BODY = (
    "from __future__ import annotations\n"
    "from typing import TYPE_CHECKING\n"
    "if TYPE_CHECKING:\n"
    "    from {package}.high import VALUE\n"
)
_RUNTIME_BODY = "def read():\n    from {package}.high import VALUE\n    return VALUE\n"


def _violations(tmp_path: Path, monkeypatch, body: str, policy_value: str | None) -> set[str]:
    pytest.importorskip("importlinter")
    package = f"se2_tcprobe_{uuid.uuid4().hex[:12]}"
    config = _write_probe_package(tmp_path, package, body.format(package=package), policy_value)
    monkeypatch.syspath_prepend(str(tmp_path))
    current = _load_checker().compute_current_violations(config)
    return current["probe layers"]


def test_type_checking_only_import_creates_no_edge_under_real_policy(tmp_path, monkeypatch):
    policy = _real_config().get("importlinter", _POLICY_KEY, raw=True, fallback=None)
    found = _violations(tmp_path, monkeypatch, _TC_ONLY_BODY, policy)
    assert not any(v.endswith(".high") for v in found), found


def _assert_single_low_to_high(found: set[str]) -> None:
    assert len(found) == 1, found
    importer, imported = next(iter(found)).split(" -> ")
    assert importer.endswith(".low") and imported.endswith(".high"), found


def test_type_checking_only_import_is_an_edge_without_the_policy(tmp_path, monkeypatch):
    # Control: proves the probe sees the edge, so the policy test above is meaningful.
    _assert_single_low_to_high(_violations(tmp_path, monkeypatch, _TC_ONLY_BODY, None))


def test_function_scope_import_still_violates_under_real_policy(tmp_path, monkeypatch):
    policy = _real_config().get("importlinter", _POLICY_KEY, raw=True, fallback=None)
    _assert_single_low_to_high(_violations(tmp_path, monkeypatch, _RUNTIME_BODY, policy))


# --- fixed importer sites --------------------------------------------------------


def _runtime_imported_modules(path: Path) -> set[str]:
    """Modules imported outside ``if TYPE_CHECKING:`` blocks (any scope)."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    guarded: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.If):
            test = node.test
            name = test.id if isinstance(test, ast.Name) else getattr(test, "attr", None)
            if name == "TYPE_CHECKING":
                for child in node.body:
                    guarded.update(id(n) for n in ast.walk(child))
    found: set[str] = set()
    for node in ast.walk(tree):
        if id(node) in guarded:
            continue
        if isinstance(node, ast.ImportFrom) and node.module:
            found.add(node.module)
        elif isinstance(node, ast.Import):
            found.update(alias.name for alias in node.names)
        elif isinstance(node, ast.Call):
            func = node.func
            callee = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", "")
            if callee in {"import_module", "__import__"}:
                found.add("<dynamic import>")
    return found


def test_situation_frame_has_no_runtime_import_reaching_gauntlet():
    modules = _runtime_imported_modules(REPO_ROOT / "aragora" / "reasoning" / "situation_frame.py")
    reaching = {
        m
        for m in modules
        if m == "<dynamic import>"
        or m.startswith("aragora.gauntlet")
        or m.startswith("aragora.export")
    }
    assert not reaching, reaching
