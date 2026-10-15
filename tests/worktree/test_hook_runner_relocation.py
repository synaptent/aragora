"""The git hook runner lives in ``aragora.worktree.hook_runner``.

``aragora.nomic`` (application layer) builds a ``HookRunner`` to create and remove
worktrees. The runner used to live in ``aragora.extensions.gastown.hooks`` (interface
layer); it now sits next to the worktree lifecycle service it wraps, and the gastown
paths re-export the same objects.
"""

from __future__ import annotations

import ast
import asyncio
import importlib
import os
import subprocess
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

from aragora.extensions.gastown import hooks as old_hooks
from aragora.extensions.gastown import models as old_models

REPO_ROOT = Path(__file__).resolve().parents[2]
NEW_HOME = "aragora.worktree.hook_runner"
OLD_HOME = "aragora.extensions.gastown.hooks"
MOVED_NAMES = ("HookRunner", "Hook", "HookType")
OLD_PATHS = [
    ("aragora.extensions.gastown.hooks", "HookRunner"),
    ("aragora.extensions.gastown.hooks", "Hook"),
    ("aragora.extensions.gastown.hooks", "HookType"),
    ("aragora.extensions.gastown.models", "Hook"),
    ("aragora.extensions.gastown.models", "HookType"),
    ("aragora.extensions.gastown", "HookRunner"),
    ("aragora.extensions.gastown", "Hook"),
    ("aragora.extensions.gastown", "HookType"),
]
EXPECTED_SCENARIO = {
    "ok": {"success": True, "returncode": 0, "stdout": "hi 1\n", "stderr": ""},
    "off": {"success": False, "error": "Hook is disabled"},
    "missing": {"success": False, "error": "Hook not found"},
    "listed": ["post-commit", "pre-push"],
    "stats": {
        "hooks_total": 2,
        "hooks_enabled": 1,
        "hooks_by_type": {"post-commit": 1, "pre-push": 1},
        "total_triggers": 1,
    },
    "deleted": True,
    "script_removed": True,
    "reloaded": [("post-commit", 1)],
}


@pytest.fixture
def new() -> ModuleType:
    return importlib.import_module(NEW_HOME)


def test_the_runner_and_its_models_are_defined_in_the_worktree_package(new):
    assert {name: getattr(new, name).__module__ for name in MOVED_NAMES} == dict.fromkeys(
        MOVED_NAMES, NEW_HOME
    )


@pytest.mark.parametrize(("module_name", "name"), OLD_PATHS)
def test_the_old_paths_are_the_same_objects(new, module_name, name):
    assert getattr(importlib.import_module(module_name), name) is getattr(new, name)


def test_the_old_hooks_module_exports_only_the_moved_names():
    assert sorted(old_hooks.__all__) == sorted(MOVED_NAMES)


def test_hook_type_values_are_unchanged_at_both_paths(new):
    values = [
        "pre-commit",
        "post-commit",
        "pre-push",
        "post-checkout",
        "post-merge",
        "prepare-commit-msg",
    ]
    assert [member.value for member in old_models.HookType] == values
    assert [member.value for member in new.HookType] == values
    assert old_hooks.HookType("pre-push") is new.HookType.PRE_PUSH


async def _scenario(module_name: str, wd: Path) -> dict[str, Any]:
    module = importlib.import_module(module_name)
    runner = module.HookRunner(storage_path=wd / "state", auto_commit=False)
    ok = await runner.create_hook(
        "rig-1", module.HookType.POST_COMMIT, str(wd / "h" / "ok"), "#!/bin/sh\necho hi $HOOK_X\n"
    )
    off = await runner.create_hook(
        "rig-1",
        module.HookType.PRE_PUSH,
        str(wd / "h" / "off"),
        "#!/bin/sh\nexit 3\n",
        enabled=False,
    )
    result = {
        "ok": await runner.trigger_hook(ok.id, {"x": "1"}),
        "off": await runner.trigger_hook(off.id),
        "missing": await runner.trigger_hook("nope"),
        "listed": sorted(hook.type.value for hook in await runner.list_hooks(rig_id="rig-1")),
        "stats": await runner.get_stats(),
        "deleted": await runner.delete_hook(off.id),
        "script_removed": not (wd / "h" / "off").exists(),
    }
    reloaded = module.HookRunner(storage_path=wd / "state", auto_commit=False)
    result["reloaded"] = [
        (hook.type.value, hook.trigger_count) for hook in await reloaded.list_hooks()
    ]
    return result


@pytest.mark.parametrize("module_name", [OLD_HOME, NEW_HOME])
def test_the_runner_gives_the_same_results_through_both_paths(module_name, tmp_path):
    assert asyncio.run(_scenario(module_name, tmp_path)) == EXPECTED_SCENARIO


def test_state_written_through_the_old_path_reloads_through_the_new_path(new, tmp_path):
    async def write() -> Any:
        runner = old_hooks.HookRunner(storage_path=tmp_path, auto_commit=False)
        return await runner.create_hook(
            "rig-9", old_models.HookType.POST_MERGE, str(tmp_path / "unused"), metadata={"k": "v"}
        )

    written = asyncio.run(write())
    reloaded = asyncio.run(
        new.HookRunner(storage_path=tmp_path, auto_commit=False).get_hook(written.id)
    )
    assert reloaded == written
    assert isinstance(reloaded, old_models.Hook)
    assert reloaded.type is new.HookType.POST_MERGE


def test_the_nomic_glue_builds_one_relocated_runner(new, tmp_path, monkeypatch):
    from aragora.nomic.worktree_manager import WorktreeManager

    monkeypatch.setenv("ARAGORA_STORE_DIR", str(tmp_path / "store"))
    manager = WorktreeManager(repo_path=tmp_path)
    runner = manager._get_hook_runner()
    assert type(runner) is new.HookRunner
    assert manager._get_hook_runner() is runner
    assert runner._storage_path == tmp_path / "store"


def test_the_nomic_glue_does_not_load_the_extensions_package(tmp_path):
    script = (
        "import sys\n"
        "from pathlib import Path\n"
        "import aragora.nomic.worktree_manager as W\n"
        "assert 'aragora.extensions' not in sys.modules, 'extensions loaded on import'\n"
        "runner = W.WorktreeManager(repo_path=Path('.'))._get_hook_runner()\n"
        "print(type(runner).__module__, type(runner).__qualname__)\n"
        "print('aragora.extensions' in sys.modules)\n"
    )
    env = {
        **os.environ,
        "PYTHONPATH": str(REPO_ROOT),
        "ARAGORA_STORE_DIR": str(tmp_path / "store"),
    }
    result = subprocess.run(
        [sys.executable, "-c", script],
        capture_output=True,
        text=True,
        cwd=tmp_path,
        env=env,
        timeout=180,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip().splitlines()[-2:] == [f"{NEW_HOME} HookRunner", "False"]


def _module_name(node: ast.ImportFrom, path: Path) -> str:
    if node.level == 0:
        return node.module or ""
    package = path.relative_to(REPO_ROOT).with_suffix("").parts[: -node.level]
    return ".".join(package + ((node.module,) if node.module else ()))


def _is_extensions(name: str) -> bool:
    return name == "aragora.extensions" or name.startswith("aragora.extensions.")


def test_nomic_has_no_import_of_extensions_at_any_scope():
    offenders = []
    for path in sorted((REPO_ROOT / "aragora" / "nomic").rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            names: list[str] = []
            if isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom):
                names = [_module_name(node, path)]
            elif isinstance(node, ast.Call) and node.args:
                func = node.func
                callee = getattr(func, "attr", None) or getattr(func, "id", None)
                if callee in {"import_module", "__import__"}:
                    names = [ast.unparse(node.args[0]).strip("'\"")]
            offenders += [
                f"{path.relative_to(REPO_ROOT)}:{node.lineno}: {name}"
                for name in names
                if _is_extensions(name)
            ]
    assert offenders == []


def test_the_new_home_imports_nothing_from_the_interface_layer(new):
    tree = ast.parse(Path(new.__file__).read_text(encoding="utf-8"))
    imported = {
        node.module or ""
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.level == 0
    } | {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    }
    assert sorted(name for name in imported if name.startswith("aragora.")) == [
        "aragora.nomic.stores.paths",
        "aragora.worktree.lifecycle",
    ]
