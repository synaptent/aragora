"""Characterization of the specialist-model evaluator hook.

``aragora.training`` (domain layer) must not import ``aragora.gauntlet`` (application
layer). The gauntlet registers its evaluation runner through the
``aragora.training_evaluators`` entry point, and
``SpecialistTrainingPipeline.complete_training`` builds the runner through the hook while
keeping the metrics it derived from the gauntlet result before the inversion.
"""

from __future__ import annotations

import ast
import importlib.metadata
import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from aragora.training import evaluation_protocols as protocols
from aragora.training.model_registry import ModelRegistry
from aragora.training.specialist_models import (
    SpecialistModelConfig,
    SpecialistModelRegistry,
    SpecialistTrainingPipeline,
    TrainingStatus,
    Vertical,
)
from aragora.utils.declared_registrations import DeclaredRegistrations

REPO_ROOT = Path(__file__).resolve().parents[2]
TRAINING_DIR = REPO_ROOT / "aragora" / "training"
GAUNTLET_REGISTRATION = ("gauntlet", "aragora.gauntlet.training_adapter:register_training_adapter")


@pytest.fixture
def isolated_evaluator(monkeypatch, tmp_path):
    """An empty hook whose declared registrations have not run and come only from a test."""
    monkeypatch.setattr(protocols, "_factory", None)
    monkeypatch.setattr(
        protocols,
        "_declared_registrations",
        DeclaredRegistrations(
            protocols.TRAINING_EVALUATORS_ENTRY_POINT_GROUP,
            source_pyproject=tmp_path / "missing.toml",
        ),
    )
    monkeypatch.setattr(importlib.metadata, "entry_points", lambda *, group: [])
    return protocols


def _declare(monkeypatch, *registrations):
    entry_points = [
        SimpleNamespace(name=f"d{i}", value=f"tests.declared:d{i}", load=lambda fn=fn: fn)
        for i, fn in enumerate(registrations)
    ]
    monkeypatch.setattr(
        importlib.metadata,
        "entry_points",
        lambda *, group: (
            entry_points if group == protocols.TRAINING_EVALUATORS_ENTRY_POINT_GROUP else []
        ),
    )


def test_an_unregistered_evaluator_raises(isolated_evaluator):
    with pytest.raises(
        protocols.SpecialistEvaluatorNotRegisteredError, match="aragora.training_evaluators"
    ):
        protocols.create_specialist_evaluator(vertical="legal")


def test_registering_again_replaces_the_factory(isolated_evaluator):
    first, second = object(), object()
    protocols.register_specialist_evaluator(lambda *, vertical: first)
    protocols.register_specialist_evaluator(lambda *, vertical: second)
    assert protocols.create_specialist_evaluator(vertical="legal") is second


def test_a_lookup_miss_runs_the_declared_registrations_once(isolated_evaluator, monkeypatch):
    calls = []

    def register():
        calls.append("register")
        protocols.register_specialist_evaluator(lambda *, vertical: object())

    _declare(monkeypatch, register)

    first = protocols.create_specialist_evaluator(vertical="legal")
    assert protocols.create_specialist_evaluator(vertical="legal") is not first
    assert calls == ["register"]


def test_pyproject_declares_the_gauntlet_registration():
    if sys.version_info < (3, 11):
        pytest.importorskip("tomli")
    declared = DeclaredRegistrations(
        protocols.TRAINING_EVALUATORS_ENTRY_POINT_GROUP
    )._source_declarations()
    assert [(ep.name, ep.value) for ep in declared] == [GAUNTLET_REGISTRATION]


def test_the_gauntlet_adapter_builds_the_pre_inversion_runner(isolated_evaluator):
    from aragora.gauntlet.runner import GauntletRunner
    from aragora.gauntlet.training_adapter import register_training_adapter

    register_training_adapter()
    register_training_adapter()
    runner = protocols.create_specialist_evaluator(vertical="legal")

    assert isinstance(runner, GauntletRunner)
    assert runner.config.agents == ["claude", "gpt-4"]
    assert runner.config.run_scenario_matrix is False
    assert runner.config.domain == "legal"


def test_the_gauntlet_config_keeps_the_pre_inversion_settings():
    from aragora.gauntlet import training_adapter

    config = training_adapter.build_gauntlet_config(vertical="healthcare")

    assert config.agents == ["claude", "gpt-4"]
    assert config.run_scenario_matrix is False
    assert config.domain == "healthcare"


def test_the_scoring_rules_are_shared_by_the_hook_and_the_adapter():
    from aragora.gauntlet import training_adapter

    assert protocols.ELO_DEFAULTS == (1200, 900, 1050)
    assert training_adapter.ELO_DEFAULTS is protocols.ELO_DEFAULTS
    assert training_adapter.win_rate_from_vulnerability is protocols.win_rate_from_vulnerability
    assert protocols.win_rate_from_vulnerability(0.25) == pytest.approx(0.75)
    assert [protocols.elo_rating_for_verdict(v) for v in ("PASS", "FAIL", "CONDITIONAL", "")] == [
        1200,
        900,
        1050,
        1050,
    ]


def test_a_training_only_process_reaches_the_gauntlet_evaluator():
    if sys.version_info < (3, 11):
        pytest.importorskip("tomli")
    script = (
        "import sys\n"
        "import aragora.training.specialist_models\n"
        "from aragora.training.evaluation_protocols import create_specialist_evaluator\n"
        "assert not any(m.startswith('aragora.gauntlet') for m in sys.modules), 'preloaded'\n"
        "print(type(create_specialist_evaluator(vertical='legal')).__name__)\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", script],
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
        env={**os.environ, "PYTHONPATH": str(REPO_ROOT)},
        timeout=120,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.split()[-1] == "GauntletRunner"


class _FakeEvaluator:
    def __init__(self, result):
        self.result = result
        self.calls: list[tuple[str, str]] = []

    async def run(self, input_content: str, context: str = ""):
        self.calls.append((input_content, context))
        return self.result


async def _trained_model(vertical=Vertical.LEGAL, run_gauntlet=True):
    registry = SpecialistModelRegistry(MagicMock(spec=ModelRegistry))
    pipeline = SpecialistTrainingPipeline(registry)
    model = await pipeline.create_training_job(
        SpecialistModelConfig(vertical=vertical, run_gauntlet=run_gauntlet), created_by="t"
    )
    return registry, pipeline, model.id


@pytest.mark.parametrize(
    ("verdict", "elo_rating"), [("PASS", 1200), ("FAIL", 900), ("CONDITIONAL", 1050)]
)
async def test_complete_training_keeps_the_gauntlet_metrics(
    isolated_evaluator, verdict, elo_rating
):
    evaluator = _FakeEvaluator(
        SimpleNamespace(verdict=verdict, robustness_score=0.75, vulnerability_rate=0.25)
    )
    verticals: list[str] = []

    def factory(*, vertical: str) -> _FakeEvaluator:
        verticals.append(vertical)
        return evaluator

    protocols.register_specialist_evaluator(factory)
    registry, pipeline, model_id = await _trained_model()

    await pipeline.complete_training(model_id, final_loss=0.1, checkpoint_path="/ckpt")

    model = registry.get(model_id)
    assert model.status is TrainingStatus.READY
    assert model.elo_rating == elo_rating
    assert model.win_rate == pytest.approx(0.75)
    assert model.vertical_accuracy == pytest.approx(0.75)
    assert evaluator.calls == [
        (
            "Review this contract clause for potential risks and liabilities.",
            "Evaluating specialist model for legal vertical",
        )
    ]
    assert verticals == ["legal"]


async def test_complete_training_scores_the_adapter_runner_result(isolated_evaluator, monkeypatch):
    from aragora.gauntlet import training_adapter

    configs = []

    class StubRunner:
        def __init__(self, config):
            configs.append(config)

        async def run(self, input_content: str, context: str = ""):
            return SimpleNamespace(verdict="FAIL", robustness_score=0.4, vulnerability_rate=0.6)

    monkeypatch.setattr(training_adapter, "GauntletRunner", StubRunner)
    training_adapter.register_training_adapter()
    registry, pipeline, model_id = await _trained_model(vertical=Vertical.SECURITY)

    await pipeline.complete_training(model_id, final_loss=0.1, checkpoint_path="/ckpt")

    [config] = configs
    assert (config.agents, config.run_scenario_matrix, config.domain) == (
        ["claude", "gpt-4"],
        False,
        "security",
    )
    model = registry.get(model_id)
    assert model.elo_rating == 900
    assert model.win_rate == pytest.approx(0.4)
    assert model.vertical_accuracy == pytest.approx(0.4)


async def test_complete_training_without_gauntlet_builds_no_evaluator(isolated_evaluator):
    registry, pipeline, model_id = await _trained_model(run_gauntlet=False)

    await pipeline.complete_training(model_id, final_loss=0.1, checkpoint_path="/ckpt")

    assert registry.get(model_id).status is TrainingStatus.READY


async def test_complete_training_with_no_registered_evaluator_raises(isolated_evaluator):
    registry, pipeline, model_id = await _trained_model()

    with pytest.raises(protocols.SpecialistEvaluatorNotRegisteredError):
        await pipeline.complete_training(model_id, final_loss=0.1, checkpoint_path="/ckpt")
    assert registry.get(model_id).status is TrainingStatus.EVALUATING


def _imported_names(node: ast.AST, path: Path) -> list[str]:
    if isinstance(node, ast.Import):
        return [alias.name for alias in node.names]
    if isinstance(node, ast.ImportFrom):
        if node.level == 0:
            return [node.module or ""]
        package = path.relative_to(REPO_ROOT).with_suffix("").parts[: -node.level]
        return [".".join(package + ((node.module,) if node.module else ()))]
    return []


def test_training_has_no_import_of_gauntlet_at_any_scope():
    offenders = [
        f"{path.relative_to(REPO_ROOT)}:{node.lineno}: {name}"
        for path in sorted(TRAINING_DIR.rglob("*.py"))
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8")))
        for name in _imported_names(node, path)
        if name == "aragora.gauntlet" or name.startswith("aragora.gauntlet.")
    ]
    assert offenders == []
