"""Pin the move of SwarmReport and SwarmReporter into aragora.swarm.swarm_reporter.

aragora.swarm.reporter keeps re-exporting both classes, and the lazy
``aragora.swarm`` exports still resolve through it.
"""

from __future__ import annotations

import ast
import asyncio
import inspect
import logging
from unittest.mock import patch

import aragora.swarm as swarm_package
from aragora.swarm import reporter, swarm_reporter
from aragora.swarm.spec import SwarmSpec


def test_classes_live_in_the_new_module() -> None:
    assert swarm_reporter.SwarmReport.__module__ == "aragora.swarm.swarm_reporter"
    assert swarm_reporter.SwarmReporter.__module__ == "aragora.swarm.swarm_reporter"


def test_facade_and_package_exports_resolve_to_the_same_objects() -> None:
    assert reporter.SwarmReport is swarm_reporter.SwarmReport
    assert reporter.SwarmReporter is swarm_reporter.SwarmReporter
    assert swarm_package.SwarmReport is swarm_reporter.SwarmReport
    assert swarm_package.SwarmReporter is swarm_reporter.SwarmReporter


def test_new_module_does_not_import_the_facade() -> None:
    tree = ast.parse(inspect.getsource(swarm_reporter))
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            assert node.level == 0, f"relative import of {node.module!r} escapes this check"
            imported.add(node.module or "")
        elif isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
    assert "aragora.swarm.reporter" not in imported
    assert swarm_reporter.logger.name == "aragora.swarm.reporter"


class _HarnessThatDeclines:
    async def initialize(self) -> bool:
        return False


def test_generate_falls_back_to_the_template_report() -> None:
    spec = SwarmSpec(raw_goal="Tidy the README", refined_goal="Tidy the README")
    result = type(
        "Result",
        (),
        {"total_subtasks": 2, "completed_subtasks": 2, "failed_subtasks": 0, "skipped_subtasks": 0},
    )()
    with patch("aragora.harnesses.claude_code.ClaudeCodeHarness", _HarnessThatDeclines):
        report = asyncio.run(reporter.SwarmReporter().generate(spec, result, duration_seconds=65))
    assert isinstance(report, swarm_reporter.SwarmReport)
    assert report.spec is spec
    assert report.duration_seconds == 65
    assert "Duration: 1m 5s" in report.to_plain_text()


def test_llm_failure_is_logged_under_the_reporter_logger(caplog) -> None:
    class _Broken:
        def __init__(self) -> None:
            raise RuntimeError("no harness")

    spec = SwarmSpec(raw_goal="Tidy the README")
    with (
        patch("aragora.harnesses.claude_code.ClaudeCodeHarness", _Broken),
        caplog.at_level(logging.DEBUG, logger="aragora.swarm.reporter"),
    ):
        report = asyncio.run(swarm_reporter.SwarmReporter()._try_llm_report(spec, None, 0.0))
    assert report is None
    assert any(
        record.name == "aragora.swarm.reporter"
        and "LLM report generation failed" in record.getMessage()
        for record in caplog.records
    )
