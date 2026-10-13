"""``trace_state`` is the dependency-free leaf shared by ``tracing`` and ``otel_bridge``.

The OpenTelemetry bridge falls back to the internal trace context when no
collector is configured, and internal spans export to the bridge when one is.
Both sides consume the leaf instead of each other; the bridge publishes its
exporter through the leaf's hook so span export is unchanged.
"""

from __future__ import annotations

import ast
import subprocess
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from aragora.observability.middleware import otel_bridge, trace_state, tracing

_MIDDLEWARE_DIR = Path(trace_state.__file__).resolve().parent
_PACKAGE = "aragora.observability.middleware"
_LEAF = f"{_PACKAGE}.trace_state"
_TRACING = f"{_PACKAGE}.tracing"
_BRIDGE = f"{_PACKAGE}.otel_bridge"


def _runtime_imports(path: Path) -> set[str]:
    """Absolute dotted names imported at runtime (``TYPE_CHECKING`` blocks excluded)."""
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    names: set[str] = set()

    def visit(nodes: list[ast.stmt]) -> None:
        for node in nodes:
            if isinstance(node, ast.If) and getattr(node.test, "id", None) == "TYPE_CHECKING":
                visit(node.orelse)
                continue
            if isinstance(node, ast.Import):
                names.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                if node.level:
                    parts = _PACKAGE.split(".")
                    base = ".".join(parts[: len(parts) - node.level + 1])
                    module = f"{base}.{node.module}" if node.module else base
                else:
                    module = node.module or ""
                names.add(module)
                names.update(f"{module}.{alias.name}" for alias in node.names)
            for field in ("body", "orelse", "finalbody", "handlers"):
                children = getattr(node, field, None)
                if isinstance(children, list):
                    visit([c for c in children if isinstance(c, ast.stmt)])
                    for handler in [c for c in children if isinstance(c, ast.ExceptHandler)]:
                        visit(handler.body)

    visit(tree.body)
    return names


@pytest.fixture(autouse=True)
def _bridge_disabled():
    otel_bridge._otel_available = False
    otel_bridge._tracer = None
    trace_state.set_span_exporter(None)
    yield
    otel_bridge._otel_available = False
    otel_bridge._tracer = None
    trace_state.set_span_exporter(None)


def test_leaf_imports_nothing_from_aragora():
    imports = _runtime_imports(_MIDDLEWARE_DIR / "trace_state.py")
    assert not any(name.startswith("aragora") for name in imports), imports


def test_bridge_has_no_runtime_edge_into_tracing():
    imports = _runtime_imports(_MIDDLEWARE_DIR / "otel_bridge.py")
    assert not any(name.startswith(_TRACING) for name in imports), imports
    assert any(name.startswith(_LEAF) for name in imports)


@pytest.mark.parametrize(
    "name",
    [
        "Span",
        "trace_context",
        "generate_trace_id",
        "generate_span_id",
        "get_trace_id",
        "get_span_id",
        "get_parent_span_id",
        "set_trace_id",
        "set_span_id",
        "_trace_id",
        "_span_id",
        "_parent_span_id",
        "_span_stack",
    ],
)
def test_tracing_re_exports_the_leaf_object(name: str):
    assert getattr(tracing, name) is getattr(trace_state, name)


def test_span_finish_exports_through_the_registered_bridge_exporter():
    tracer = MagicMock()
    otel_bridge._otel_available = True
    otel_bridge._tracer = tracer
    trace_state.set_span_exporter(otel_bridge.export_span_to_otel)

    with patch.dict(
        "sys.modules", {"opentelemetry": MagicMock(), "opentelemetry.trace": MagicMock()}
    ):
        with tracing.trace_context("leaf.export") as span:
            span.set_tag("k", "v")

    tracer.start_as_current_span.assert_called_once()
    assert tracer.start_as_current_span.call_args.args[0] == "leaf.export"


def test_span_finish_is_silent_without_an_exporter():
    tracer = MagicMock()
    otel_bridge._otel_available = True
    otel_bridge._tracer = tracer

    with tracing.trace_context("leaf.noexport"):
        pass

    tracer.start_as_current_span.assert_not_called()


def test_shutdown_unregisters_the_exporter():
    otel_bridge._otel_available = True
    otel_bridge._tracer = MagicMock()
    trace_state.set_span_exporter(otel_bridge.export_span_to_otel)

    with patch.dict(
        "sys.modules", {"opentelemetry": MagicMock(), "opentelemetry.trace": MagicMock()}
    ):
        otel_bridge.shutdown_otel_bridge()

    assert trace_state._span_exporter is None
    assert otel_bridge.is_otel_available() is False


def test_bridge_fallbacks_read_the_internal_context():
    with tracing.trace_context("bridge.fallback") as span:
        assert otel_bridge.get_current_trace_id() == span.trace_id
        assert otel_bridge.get_current_span_id() == span.span_id
        headers = otel_bridge.inject_trace_context({})
        assert headers["X-Trace-ID"] == span.trace_id
        with otel_bridge.create_span_context("bridge.child") as child:
            assert isinstance(child, trace_state.Span)
            assert child.parent_span_id == span.span_id


@pytest.mark.parametrize(
    ("first", "second"),
    [(_BRIDGE, _TRACING), (_TRACING, _BRIDGE), (_LEAF, _BRIDGE)],
)
def test_modules_import_in_either_order(first: str, second: str):
    result = subprocess.run(
        [sys.executable, "-c", f"import {first}, {second}; print('ok')"],
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "ok"
