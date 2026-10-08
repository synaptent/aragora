"""The callable debate API lives in aragora.debate.api; aragora.golden re-exports it."""

from __future__ import annotations

import ast
import asyncio
import importlib
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
DEBATE_PACKAGE = REPO_ROOT / "aragora" / "debate"

_IMPORT_ORDER_PROBE = """
import asyncio, sys, warnings
warnings.simplefilter("ignore")
order = sys.argv[1]

def run(fn):
    r = fn("se2 offline probe", agents=2, rounds=1)
    r = asyncio.run(r) if asyncio.iscoroutine(r) else r
    assert getattr(r, "task", None) == "se2 offline probe", r
    return r

if order == "root-first":
    import aragora; run(aragora.debate)
elif order == "subpackage-first":
    import aragora.debate; import aragora; run(aragora.debate)
elif order == "saved-callable":
    import aragora; f = aragora.debate; import aragora.debate; run(f); run(aragora.debate)
elif order == "arena-first":
    from aragora.debate import Arena; import aragora; run(aragora.debate)
elif order == "resolved-then-subpackage-attribute":
    import aragora; f = aragora.debate
    assert "aragora.debate" not in sys.modules, "resolving aragora.debate loaded the engine"
    import aragora.debate
    assert aragora.debate.Arena is aragora.debate.orchestrator.Arena, type(aragora.debate)
    run(f); run(aragora.debate)
import aragora.golden, aragora.debate.api
assert aragora.golden.debate is aragora.debate.api.debate
assert aragora.debate.Arena is aragora.debate.orchestrator.Arena
print("OK", order)
"""


def test_golden_debate_is_the_api_debate() -> None:
    import aragora.debate.api
    import aragora.golden

    assert aragora.golden.debate is aragora.debate.api.debate
    assert "debate" in aragora.golden.__all__


@pytest.mark.parametrize("module_name", ["aragora.golden", "aragora.debate.api"])
def test_debate_runs_offline_at_both_paths(module_name: str) -> None:
    module = importlib.import_module(module_name)

    result = asyncio.run(module.debate("se2 offline probe", agents=2, rounds=1))

    assert result.task == "se2 offline probe"
    assert result.participants == ["agent-1", "agent-2"]


@pytest.mark.parametrize(
    "order",
    [
        "root-first",
        "subpackage-first",
        "saved-callable",
        "arena-first",
        "resolved-then-subpackage-attribute",
    ],
)
def test_callable_debate_survives_import_order(order: str) -> None:
    proc = subprocess.run(
        [sys.executable, "-c", _IMPORT_ORDER_PROBE, order],
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
        timeout=300,
    )
    assert proc.returncode == 0, f"stdout:\n{proc.stdout}\nstderr:\n{proc.stderr}"
    assert f"OK {order}" in proc.stdout


def test_importing_golden_does_not_load_the_debate_engine() -> None:
    code = (
        "import sys, aragora.golden\n"
        "assert callable(aragora.golden.remember)\n"
        "assert 'aragora.debate' not in sys.modules, 'aragora.golden imported aragora.debate'\n"
        "print('LIGHT')\n"
    )
    proc = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, cwd=REPO_ROOT, timeout=300
    )
    assert proc.returncode == 0, proc.stderr
    assert "LIGHT" in proc.stdout


def test_golden_debate_before_the_engine_loads_runs_and_then_resolves_to_the_api() -> None:
    code = (
        "import asyncio, sys, warnings\n"
        "warnings.simplefilter('ignore')\n"
        "import aragora.golden\n"
        "early = aragora.golden.debate\n"
        "assert 'aragora.debate' not in sys.modules, 'aragora.golden.debate loaded the engine'\n"
        "result = asyncio.run(early('se2 offline probe', agents=2, rounds=1))\n"
        "assert result.task == 'se2 offline probe', result\n"
        "import aragora.debate.api\n"
        "assert aragora.golden.debate is aragora.debate.api.debate\n"
        "print('FORWARDED')\n"
    )
    proc = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, cwd=REPO_ROOT, timeout=300
    )
    assert proc.returncode == 0, proc.stderr
    assert "FORWARDED" in proc.stdout


def _is_type_checking(test: ast.expr) -> bool:
    return (isinstance(test, ast.Name) and test.id == "TYPE_CHECKING") or (
        isinstance(test, ast.Attribute) and test.attr == "TYPE_CHECKING"
    )


def _runtime_imports(tree: ast.AST) -> list[tuple[int, str]]:
    found: list[tuple[int, str]] = []

    def visit(node: ast.AST) -> None:
        if isinstance(node, ast.If) and _is_type_checking(node.test):
            for child in node.orelse:
                visit(child)
            return
        if isinstance(node, ast.Import):
            found.extend((node.lineno, alias.name) for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            found.append((node.lineno, node.module))
        elif isinstance(node, ast.Call):
            func = node.func
            name = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", "")
            if name in {"import_module", "__import__"} and node.args:
                arg = node.args[0]
                if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                    found.append((node.lineno, arg.value))
        for child in ast.iter_child_nodes(node):
            visit(child)

    visit(tree)
    return found


@pytest.mark.parametrize("target", ["aragora.golden"])
def test_debate_package_does_not_import_target_at_runtime(target: str) -> None:
    offenders = []
    for path in sorted(DEBATE_PACKAGE.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for lineno, module in _runtime_imports(tree):
            if module == target or module.startswith(f"{target}."):
                offenders.append(f"{path.relative_to(REPO_ROOT)}:{lineno} imports {module}")
    assert offenders == []
