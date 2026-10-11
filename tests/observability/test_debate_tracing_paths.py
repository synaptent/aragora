"""Old and new import paths of the debate tracing module share one implementation and state."""

from __future__ import annotations

import ast
import asyncio
import importlib
import inspect
from pathlib import Path

import pytest

import aragora.debate.tracing as old
import aragora.logging_config as logging_config
import aragora.observability.debate_tracing as new

REPO_ROOT = Path(__file__).resolve().parents[2]

PUBLIC_NAMES = (
    "DebateMetrics",
    "Span",
    "SpanContext",
    "SpanRecorder",
    "Tracer",
    "clear_metrics",
    "generate_span_id",
    "generate_trace_id",
    "get_debate_context",
    "get_debate_id",
    "get_metrics",
    "get_tracer",
    "set_debate_context",
    "set_tracer",
    "trace_agent_call",
    "trace_phase",
    "trace_round",
    "with_debate_context",
)


@pytest.fixture(autouse=True)
def _isolate_tracing_state():
    tracer = new._tracer
    debate_token = new._debate_context.set({})
    log_token = logging_config._log_context.set({})
    new.clear_metrics()
    yield
    new.clear_metrics()
    logging_config._log_context.reset(log_token)
    new._debate_context.reset(debate_token)
    new._tracer = tracer


@pytest.mark.parametrize("name", PUBLIC_NAMES)
def test_old_path_reexports_identical_object(name: str) -> None:
    assert getattr(old, name) is getattr(new, name)


def test_old_path_all_matches_public_names() -> None:
    assert sorted(old.__all__) == sorted(PUBLIC_NAMES)


def test_implementation_lives_in_observability() -> None:
    module = inspect.getmodule(old.get_debate_id)
    assert module is not None
    assert module.__name__ == "aragora.observability.debate_tracing"
    assert new.Tracer.__module__ == "aragora.observability.debate_tracing"


def test_fixed_input_debate_context_at_both_paths() -> None:
    old.set_debate_context("debate-old", round=2)
    assert new.get_debate_context() == {"debate_id": "debate-old", "round": 2}
    assert new.get_debate_id() == "debate-old"

    new.set_debate_context("debate-new")
    assert old.get_debate_id() == "debate-new"


def test_tracer_and_metrics_state_shared() -> None:
    custom = old.Tracer(service_name="paths-test", log_spans=False)
    old.set_tracer(custom)
    assert new.get_tracer() is custom

    metrics = old.get_metrics("d-metrics")
    metrics.record_agent_latency("agent-a", 10.0)
    assert new.get_metrics("d-metrics") is metrics
    assert new.get_metrics("d-metrics").get_agent_avg_latency("agent-a") == 10.0
    old.clear_metrics("d-metrics")
    assert new.get_metrics("d-metrics") is not metrics


def test_generated_ids_have_fixed_shape_at_both_paths() -> None:
    for module in (old, new):
        trace_id = module.generate_trace_id()
        span_id = module.generate_span_id()
        assert len(trace_id) == 32 and int(trace_id, 16) >= 0
        assert len(span_id) == 16 and int(span_id, 16) >= 0


def test_tracer_debate_context_binds_and_restores() -> None:
    tracer = old.get_tracer()
    assert old.get_debate_id() is None
    with tracer.debate_context("dbg-1", round=1) as ctx:
        assert ctx == {"debate_id": "dbg-1", "round": 1}
        assert old.get_debate_id() == new.get_debate_id() == "dbg-1"
        assert logging_config.get_context()["debate_id"] == "dbg-1"
        with tracer.debate_context("dbg-2"):
            assert new.get_debate_id() == "dbg-2"
        assert new.get_debate_id() == "dbg-1"
    assert old.get_debate_id() is None
    assert "debate_id" not in logging_config.get_context()


def test_tracer_debate_context_restores_after_exception() -> None:
    tracer = new.get_tracer()
    with pytest.raises(RuntimeError):
        with tracer.debate_context("dbg-err"):
            raise RuntimeError("boom")
    assert old.get_debate_id() is None


def test_tracer_debate_context_isolated_per_task() -> None:
    tracer = new.get_tracer()

    async def child(debate_id: str) -> tuple[str | None, str | None]:
        with tracer.debate_context(debate_id):
            await asyncio.sleep(0)
            return old.get_debate_id(), new.get_debate_id()

    async def main() -> None:
        with tracer.debate_context("parent"):
            results = await asyncio.gather(child("a"), child("b"))
            assert results == [("a", "a"), ("b", "b")]
            assert old.get_debate_id() == "parent"

    asyncio.run(main())


def test_logging_config_injects_context_from_new_module() -> None:
    tracer = old.Tracer(service_name="paths-test", log_spans=False)
    old.set_tracer(tracer)
    with tracer.debate_context("dbg-log"):
        with tracer.span("op") as span:
            logging_config.inject_trace_context()
            ctx = logging_config.get_context()
    assert ctx["debate_id"] == "dbg-log"
    assert ctx["trace_id"] == span.trace_id
    assert ctx["span_id"] == span.span_id


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
        elif (
            isinstance(node, ast.Call)
            and node.args
            and isinstance(node.args[0], ast.Constant)
            and isinstance(node.args[0].value, str)
        ):
            func = node.func
            name = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", "")
            if name in {"import_module", "__import__"}:
                found.append((node.lineno, node.args[0].value))
    return found


@pytest.mark.parametrize(
    "relative_path",
    ["aragora/logging_config.py", "aragora/observability/debate_tracing.py"],
)
def test_no_import_of_debate_package(relative_path: str) -> None:
    offenders = [
        f"{relative_path}:{lineno} {module}"
        for lineno, module in _imported_modules(REPO_ROOT / relative_path)
        if module == "aragora.debate" or module.startswith("aragora.debate.")
    ]
    assert offenders == []


def test_old_module_reload_keeps_identity() -> None:
    reloaded = importlib.reload(old)
    assert reloaded.get_tracer is new.get_tracer
