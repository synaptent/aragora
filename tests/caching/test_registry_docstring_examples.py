"""The usage example in the aragora.caching.registry docstring matches the real API."""

from __future__ import annotations

import ast
import inspect
import textwrap

import aragora.caching as caching
import aragora.caching.registry as registry


def _usage_tree() -> ast.Module:
    doc = registry.__doc__ or ""
    _, marker, after = doc.partition("Usage:\n")
    assert marker, "registry docstring no longer has a 'Usage:' section"
    block, _, _ = after.partition("\nCache Implementations:")
    return ast.parse(textwrap.dedent(block))


def _example_calls(tree: ast.Module) -> list[tuple[str, ast.Call]]:
    calls: list[tuple[str, ast.Call]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            if node.func.id in caching.__all__:
                calls.append((node.func.id, node))
    return calls


def test_usage_imports_are_exported() -> None:
    imported = [
        alias.name
        for node in ast.walk(_usage_tree())
        if isinstance(node, ast.ImportFrom) and node.module == "aragora.caching"
        for alias in node.names
    ]

    assert imported
    assert sorted(set(imported) - set(caching.__all__)) == []


def test_usage_calls_bind_to_real_signatures() -> None:
    calls = _example_calls(_usage_tree())
    assert {"cached", "TTLCache", "register_cache"} <= {name for name, _ in calls}

    failures = []
    for name, call in calls:
        signature = inspect.signature(getattr(caching, name))
        args = [object()] * len(call.args)
        kwargs = {kw.arg: object() for kw in call.keywords if kw.arg is not None}
        try:
            signature.bind(*args, **kwargs)
        except TypeError as exc:
            failures.append(f"{ast.unparse(call)}: {exc}")

    assert failures == []
