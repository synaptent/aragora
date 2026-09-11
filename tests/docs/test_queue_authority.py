"""Conformance checks for the #8851 ARCH-015 queue disposition."""

from __future__ import annotations

import ast
from collections import Counter
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
CHARTER = ROOT / "docs/architecture/charters.yaml"
DECISION = ROOT / "docs/architecture/QUEUE_ADOPTION_DISPOSITION.md"

EXPECTED_STORAGE_IMPORTERS = {
    "aragora/nomic/testfixer/queue_worker.py",
    "aragora/queue/workers/transcription_worker.py",
    "aragora/server/handlers/admin/health/workers.py",
    "aragora/server/handlers/transcription.py",
    "aragora/server/workers/gauntlet_worker.py",
    "aragora/server/workers/routing_worker.py",
}
EXPECTED_DYNAMIC_REFERENCERS = {
    "aragora/server/handlers/transcription.py",
    "aragora/server/initialization.py",
    "scripts/init_postgres_db.py",
}
JOB_QUEUE_STORE_MODULE = "aragora.storage.job_queue_store"
SKIPPED_SOURCE_DIRS = {
    ".git",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".venv",
    "__pycache__",
    "node_modules",
    "venv",
}
EXPECTED_BACKEND_CALLS = {
    "aragora/nomic/testfixer/queue_worker.py": {
        "store:complete": 1,
        "store:dequeue": 1,
        "store:fail": 1,
        "store:recover_stale_jobs": 1,
        "symbol:get_job_store": 2,
    },
    "aragora/queue/workers/transcription_worker.py": {
        "store:complete": 1,
        "store:dequeue": 1,
        "store:enqueue": 1,
        "store:fail": 1,
        "symbol:QueuedJob": 1,
        "symbol:get_job_store": 3,
    },
    "aragora/server/handlers/admin/health/workers.py": {
        "store:get_stats": 2,
        "symbol:get_job_store": 1,
    },
    "aragora/server/handlers/transcription.py": {
        "dynamic_factory:get": 2,
        "store:enqueue": 2,
        "store:get": 1,
        "symbol:QueuedJob": 1,
    },
    "aragora/server/initialization.py": {},
    "aragora/server/workers/gauntlet_worker.py": {
        "store:complete": 1,
        "store:dequeue": 1,
        "store:enqueue": 1,
        "store:fail": 1,
        "store:get": 1,
        "store:recover_stale_jobs": 1,
        "symbol:QueuedJob": 1,
        "symbol:get_job_store": 3,
    },
    "aragora/server/workers/routing_worker.py": {
        "store:complete": 1,
        "store:dequeue": 1,
        "store:enqueue": 1,
        "store:fail": 2,
        "store:recover_stale_jobs": 1,
        "symbol:QueuedJob": 1,
        "symbol:get_job_store": 3,
    },
    "scripts/init_postgres_db.py": {},
}


def _resolve_import_from(path: Path, node: ast.ImportFrom, *, root: Path) -> str | None:
    if node.level == 0:
        return node.module

    package_parts = path.relative_to(root).with_suffix("").parts[:-1]
    parent_levels = node.level - 1
    if parent_levels > len(package_parts):
        return None
    base_parts = package_parts[: len(package_parts) - parent_levels]
    if node.module:
        base_parts += tuple(node.module.split("."))
    return ".".join(base_parts)


def _imports_job_queue_store(path: Path, *, root: Path = ROOT) -> bool:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            module = _resolve_import_from(path, node, root=root)
            if module == JOB_QUEUE_STORE_MODULE:
                return True
            if module and any(
                f"{module}.{alias.name}" == JOB_QUEUE_STORE_MODULE for alias in node.names
            ):
                return True
        elif isinstance(node, ast.Import):
            if any(alias.name == JOB_QUEUE_STORE_MODULE for alias in node.names):
                return True
    return False


def _references_job_queue_store_literal(path: Path) -> bool:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    return any(
        isinstance(node, ast.Constant) and node.value == JOB_QUEUE_STORE_MODULE
        for node in ast.walk(tree)
    )


def _dotted_name(node: ast.AST) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        parent = _dotted_name(node.value)
        return f"{parent}.{node.attr}" if parent else None
    return None


def _assignment_names(node: ast.AST) -> set[str]:
    if isinstance(node, (ast.Name, ast.Attribute)):
        name = _dotted_name(node)
        return {name} if name else set()
    if isinstance(node, (ast.Tuple, ast.List)):
        return {name for item in node.elts for name in _assignment_names(item)}
    return set()


def _backend_call_inventory(path: Path, *, root: Path = ROOT) -> Counter[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    symbol_aliases: dict[str, set[str]] = {}
    module_aliases: set[str] = set()
    dynamic_factories: set[str] = set()

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == JOB_QUEUE_STORE_MODULE:
                    module_aliases.add(alias.asname or alias.name)
        elif isinstance(node, ast.ImportFrom):
            module = _resolve_import_from(path, node, root=root)
            if module == JOB_QUEUE_STORE_MODULE:
                for alias in node.names:
                    symbol_aliases.setdefault(alias.asname or alias.name, set()).add(alias.name)
            elif module:
                for alias in node.names:
                    if f"{module}.{alias.name}" == JOB_QUEUE_STORE_MODULE:
                        module_aliases.add(alias.asname or alias.name)
        elif isinstance(node, (ast.Assign, ast.AnnAssign)):
            value = node.value
            if not isinstance(value, ast.Call):
                continue
            call_name = _dotted_name(value.func)
            imports_module_alias = (
                call_name is not None
                and (call_name == "import_module" or call_name.endswith(".import_module"))
                and bool(value.args)
                and isinstance(value.args[0], ast.Constant)
                and value.args[0].value == JOB_QUEUE_STORE_MODULE
            )
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            if imports_module_alias:
                for target in targets:
                    module_aliases.update(_assignment_names(target))
            imports_backend = any(
                keyword.arg == "import_path"
                and isinstance(keyword.value, ast.Constant)
                and keyword.value.value == JOB_QUEUE_STORE_MODULE
                for keyword in value.keywords
            )
            if imports_backend:
                for target in targets:
                    dynamic_factories.update(_assignment_names(target))

    def symbol_candidates(node: ast.AST) -> set[str]:
        name = _dotted_name(node)
        if not name:
            return set()
        if name in symbol_aliases:
            return symbol_aliases[name]
        for module_alias in module_aliases:
            prefix = f"{module_alias}."
            if name.startswith(prefix):
                return {name.removeprefix(prefix)}
        prefix = f"{JOB_QUEUE_STORE_MODULE}."
        if name.startswith(prefix):
            return {name.removeprefix(prefix)}
        return set()

    def canonical_symbol(node: ast.AST) -> str | None:
        candidates = symbol_candidates(node)
        return next(iter(candidates)) if len(candidates) == 1 else None

    changed = True
    while changed:
        changed = False
        for node in ast.walk(tree):
            if not isinstance(node, (ast.Assign, ast.AnnAssign)) or node.value is None:
                continue
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            names = {name for target in targets for name in _assignment_names(target)}
            candidates = symbol_candidates(node.value)
            for name in names:
                aliases = symbol_aliases.setdefault(name, set())
                previous_size = len(aliases)
                aliases.update(candidates)
                changed |= len(aliases) != previous_size
            value_name = _dotted_name(node.value)
            if value_name in module_aliases and not names.issubset(module_aliases):
                module_aliases.update(names)
                changed = True
            if value_name in dynamic_factories and not names.issubset(dynamic_factories):
                dynamic_factories.update(names)
                changed = True

    def is_dynamic_factory_get(node: ast.AST) -> bool:
        return (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "get"
            and _dotted_name(node.func.value) in dynamic_factories
        )

    store_bindings: set[str] = set()

    def is_store_expression(node: ast.AST) -> bool:
        name = _dotted_name(node)
        if name and name in store_bindings:
            return True
        return isinstance(node, ast.Call) and (
            canonical_symbol(node.func) == "get_job_store" or is_dynamic_factory_get(node)
        )

    changed = True
    while changed:
        changed = False
        for node in ast.walk(tree):
            if not isinstance(node, (ast.Assign, ast.AnnAssign)):
                continue
            value = node.value
            if value is None or not is_store_expression(value):
                continue
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            names = {name for target in targets for name in _assignment_names(target)}
            if not names.issubset(store_bindings):
                store_bindings.update(names)
                changed = True

    inventory: Counter[str] = Counter()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        candidates = symbol_candidates(node.func)
        if len(candidates) == 1:
            inventory[f"symbol:{next(iter(candidates))}"] += 1
        elif candidates:
            inventory[f"symbol_conflict:{_dotted_name(node.func)}"] += 1
        if is_dynamic_factory_get(node):
            inventory["dynamic_factory:get"] += 1
        if isinstance(node.func, ast.Attribute) and is_store_expression(node.func.value):
            inventory[f"store:{node.func.attr}"] += 1
    return inventory


def _excess_backend_calls(actual: Counter[str], expected: dict[str, int]) -> dict[str, int]:
    return {
        call: count - expected.get(call, 0)
        for call, count in actual.items()
        if count > expected.get(call, 0)
    }


def _iter_source_paths(root: Path = ROOT) -> set[Path]:
    paths: set[Path] = set()
    for source_root in (root / "aragora", root / "scripts"):
        for path in source_root.rglob("*.py"):
            relative_parts = path.relative_to(source_root).parts[:-1]
            if any(part in SKIPPED_SOURCE_DIRS or part.startswith(".") for part in relative_parts):
                continue
            if path != root / "aragora/storage/job_queue_store.py":
                paths.add(path)
    return paths


@pytest.mark.parametrize(
    ("relative_path", "source"),
    [
        ("consumer.py", "import aragora.storage.job_queue_store\n"),
        ("consumer.py", "from aragora.storage.job_queue_store import QueuedJob\n"),
        ("consumer.py", "from aragora.storage import job_queue_store\n"),
        ("consumer.py", "from aragora.storage import job_queue_store as store\n"),
        ("aragora/storage/consumer.py", "from . import job_queue_store\n"),
        ("aragora/server/consumer.py", "from ..storage import job_queue_store\n"),
        (
            "aragora/server/consumer.py",
            "from ..storage.job_queue_store import QueuedJob\n",
        ),
    ],
)
def test_job_queue_store_import_forms_are_detected(
    tmp_path: Path,
    relative_path: str,
    source: str,
) -> None:
    path = tmp_path / relative_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(source, encoding="utf-8")

    assert _imports_job_queue_store(path, root=tmp_path)


def test_unrelated_queue_import_is_not_a_storage_consumer(tmp_path: Path) -> None:
    path = tmp_path / "consumer.py"
    path.write_text("from aragora.queue import QueueJob\n", encoding="utf-8")

    assert not _imports_job_queue_store(path, root=tmp_path)


def test_backend_call_inventory_rejects_growth_but_allows_removal(tmp_path: Path) -> None:
    path = tmp_path / "consumer.py"
    path.write_text(
        "from aragora.storage import job_queue_store as backend\n"
        "store = backend.get_job_store()\n"
        "store.enqueue(first)\n",
        encoding="utf-8",
    )
    baseline = dict(_backend_call_inventory(path, root=tmp_path))

    path.write_text(
        "from aragora.storage import job_queue_store as backend\n"
        "store = backend.get_job_store()\n"
        "store.enqueue(first)\n"
        "factory = backend.get_job_store\n"
        "factory().enqueue(second)\n",
        encoding="utf-8",
    )
    assert _excess_backend_calls(_backend_call_inventory(path, root=tmp_path), baseline) == {
        "store:enqueue": 1,
        "symbol:get_job_store": 1,
    }

    path.write_text(
        "from aragora.storage import job_queue_store as backend\nstore = backend.get_job_store()\n",
        encoding="utf-8",
    )
    assert not _excess_backend_calls(_backend_call_inventory(path, root=tmp_path), baseline)


def test_dynamic_reference_inventory_rejects_new_backend_calls(tmp_path: Path) -> None:
    path = tmp_path / "consumer.py"
    path.write_text(
        "factory = loader(import_path='aragora.storage.job_queue_store')\n"
        "factory.get().enqueue(first)\n",
        encoding="utf-8",
    )
    baseline = dict(_backend_call_inventory(path, root=tmp_path))

    path.write_text(
        "factory = loader(import_path='aragora.storage.job_queue_store')\n"
        "factory.get().enqueue(first)\n"
        "factory.get().enqueue(second)\n",
        encoding="utf-8",
    )

    assert _excess_backend_calls(_backend_call_inventory(path, root=tmp_path), baseline) == {
        "dynamic_factory:get": 1,
        "store:enqueue": 1,
    }

    path.write_text(
        "factory = loader(import_path='aragora.storage.job_queue_store')\n",
        encoding="utf-8",
    )
    assert not _excess_backend_calls(_backend_call_inventory(path, root=tmp_path), baseline)


def test_positional_import_module_inventory_rejects_new_backend_calls(tmp_path: Path) -> None:
    path = tmp_path / "consumer.py"
    path.write_text(
        "import importlib\n"
        "backend = importlib.import_module('aragora.storage.job_queue_store')\n"
        "backend.get_job_store().enqueue(first)\n",
        encoding="utf-8",
    )
    baseline = dict(_backend_call_inventory(path, root=tmp_path))

    path.write_text(
        "import importlib\n"
        "backend = importlib.import_module('aragora.storage.job_queue_store')\n"
        "backend.get_job_store().enqueue(first)\n"
        "backend.get_job_store().enqueue(second)\n",
        encoding="utf-8",
    )
    assert _excess_backend_calls(_backend_call_inventory(path, root=tmp_path), baseline) == {
        "store:enqueue": 1,
        "symbol:get_job_store": 1,
    }

    path.write_text(
        "import importlib\nbackend = importlib.import_module('aragora.storage.job_queue_store')\n",
        encoding="utf-8",
    )
    assert not _excess_backend_calls(_backend_call_inventory(path, root=tmp_path), baseline)


def test_conflicting_symbol_aliases_terminate_deterministically(tmp_path: Path) -> None:
    path = tmp_path / "consumer.py"
    path.write_text(
        "from aragora.storage.job_queue_store import QueuedJob, get_job_store\n"
        "factory = get_job_store\n"
        "factory = QueuedJob\n"
        "factory()\n",
        encoding="utf-8",
    )

    expected = Counter({"symbol_conflict:factory": 1})
    assert _backend_call_inventory(path, root=tmp_path) == expected
    assert _backend_call_inventory(path, root=tmp_path) == expected


def test_arch_015_is_the_binding_queue_authority() -> None:
    payload = yaml.safe_load(CHARTER.read_text(encoding="utf-8"))
    entry = next(row for row in payload["authorities"] if row["id"] == "ARCH-015")

    assert payload["meta"]["status"] in {"DRAFT", "RATIFIED"}
    assert entry["authority"] == "aragora/queue"
    assert entry["disposition"] == "adopt"
    assert entry["binding_in_draft"] is True
    assert entry["decision_record"] == "docs/architecture/QUEUE_ADOPTION_DISPOSITION.md"
    assert DECISION.is_file()


def test_queue_entrypoints_and_backend_split_remain_explicit() -> None:
    for relative_path in (
        "scripts/queue_worker.py",
        "aragora/server/handlers/queue.py",
        "aragora/server/startup/workers.py",
    ):
        assert (ROOT / relative_path).is_file(), relative_path

    source_paths = _iter_source_paths()
    importers = {
        path.relative_to(ROOT).as_posix() for path in source_paths if _imports_job_queue_store(path)
    }
    dynamic_referencers = {
        path.relative_to(ROOT).as_posix()
        for path in source_paths
        if _references_job_queue_store_literal(path)
    }

    assert not importers - EXPECTED_STORAGE_IMPORTERS
    assert not dynamic_referencers - EXPECTED_DYNAMIC_REFERENCERS
    expected_consumers = EXPECTED_STORAGE_IMPORTERS | EXPECTED_DYNAMIC_REFERENCERS
    assert set(EXPECTED_BACKEND_CALLS) == expected_consumers
    for relative_path in importers | dynamic_referencers:
        actual = _backend_call_inventory(ROOT / relative_path)
        assert not _excess_backend_calls(actual, EXPECTED_BACKEND_CALLS[relative_path]), (
            relative_path,
            actual,
        )
