"""Tests for ``scripts/check_charter_compliance.py``."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

import yaml


def _load_module() -> Any:
    here = Path(__file__).resolve()
    script_path = here.parents[2] / "scripts" / "check_charter_compliance.py"
    spec = importlib.util.spec_from_file_location(
        "check_charter_compliance_under_test",
        script_path,
    )
    if spec is None or spec.loader is None:
        raise RuntimeError(f"could not load spec for {script_path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


checker = _load_module()


def _write_charters(tmp_path: Path, payload: dict[str, Any]) -> Path:
    path = tmp_path / "charters.yaml"
    path.write_text(yaml.safe_dump(payload), encoding="utf-8")
    return path


def _charters_payload() -> dict[str, Any]:
    return {
        "meta": {
            "charter": "docs/architecture/INTENDED_ARCHITECTURE.md",
            "version": "0.4",
            "status": "DRAFT",
        },
        "authorities": [
            {
                "id": "ARCH-015",
                "concern": "durable-server-jobs",
                "authority": "aragora/queue",
                "registry_refs": ["CHR-P4A-004"],
            },
            {
                "id": "ARCH-014",
                "concern": "fleet-task-scheduling",
                "authority": "aragora/swarm",
                "registry_refs": ["CHR-X-040"],
            },
            {
                "id": "ARCH-029",
                "concern": "observability",
                "authority": "aragora/observability",
                "registry_refs": ["CHR-E-004"],
            },
        ],
        "registry": [
            {
                "id": "CHR-P4A-004",
                "state": "REMOVED",
                "binding_in_draft": True,
                "paths": ["aragora/queue/__init__.py"],
                "symbols": ["aragora.queue:create_default_executor"],
                "evidence": "Removed by #8890, re-removed by #8909.",
            },
            {
                "id": "CHR-X-040",
                "state": "PARKED",
                "paths": [
                    "aragora/control_plane/scheduler.py",
                    "aragora/control_plane/registry.py",
                ],
                "symbols": [],
                "kept_symbols": [
                    "aragora.control_plane.registry:AgentRegistry",
                    "aragora.control_plane.registry:AgentStatus",
                    "aragora.control_plane.registry:AgentInfo.is_alive",
                ],
                "evidence": "registry health/liveness surface is KEPT.",
            },
            {
                "id": "CHR-E-004",
                "state": "EXCLUSION",
                "paths": ["aragora/server/"],
                "symbols": [],
                "evidence": "no server-local metrics/tracing/http-pool homes.",
            },
        ],
    }


def test_removed_symbol_readd_is_binding_and_cites_authority(tmp_path: Path) -> None:
    charter_path = _write_charters(tmp_path, _charters_payload())
    diff_text = """diff --git a/some.py b/some.py
--- a/some.py
+++ b/some.py
@@ -0,0 +1,2 @@
+from aragora.queue import create_default_executor
+executor = create_default_executor()
"""

    result = checker.check_diff(diff_text, charter_path=charter_path)

    assert result.ok is False
    assert [violation.entry_id for violation in result.binding_violations] == ["CHR-P4A-004"]
    violation = result.binding_violations[0]
    assert violation.binding == "BINDING"
    assert violation.authority_ids == ["ARCH-015"]
    assert "create_default_executor" in violation.line


def test_multiline_removed_symbol_readd_is_binding(tmp_path: Path) -> None:
    charter_path = _write_charters(tmp_path, _charters_payload())
    diff_text = """diff --git a/some.py b/some.py
--- a/some.py
+++ b/some.py
@@ -0,0 +1,4 @@
+from aragora.queue import (
+    create_default_executor,
+)
+executor = create_default_executor()
"""

    result = checker.check_diff(diff_text, charter_path=charter_path)

    assert result.ok is False
    assert [violation.entry_id for violation in result.binding_violations] == ["CHR-P4A-004"]
    assert "create_default_executor" in result.binding_violations[0].line


def test_kept_symbol_does_not_trip_path_level_park(tmp_path: Path) -> None:
    charter_path = _write_charters(tmp_path, _charters_payload())
    diff_text = """diff --git a/aragora/debate/team_selector.py b/aragora/debate/team_selector.py
--- a/aragora/debate/team_selector.py
+++ b/aragora/debate/team_selector.py
@@ -1,0 +2,2 @@
+from aragora.control_plane.registry import AgentRegistry, AgentInfo, AgentStatus
+registry = AgentRegistry()
"""

    result = checker.check_diff(diff_text, charter_path=charter_path)

    assert result.ok is True
    assert result.violations == []


def test_wildcard_import_is_not_kept_symbol_exemption(tmp_path: Path) -> None:
    charter_path = _write_charters(tmp_path, _charters_payload())
    entries, _authority_by_ref, _status = checker.load_charter_entries(charter_path)
    entry = next(item for item in entries if item.entry_id == "CHR-X-040")

    assert (
        checker._line_reexports_or_defines_kept_symbol(
            "from aragora.control_plane.registry import *",
            entry,
        )
        is False
    )

    diff_text = """diff --git a/aragora/control_plane/registry.py b/aragora/control_plane/registry.py
--- a/aragora/control_plane/registry.py
+++ b/aragora/control_plane/registry.py
@@ -0,0 +1 @@
+from aragora.control_plane.registry import *
"""

    result = checker.check_diff(diff_text, charter_path=charter_path)

    assert result.ok is False
    assert result.binding_violations == []
    assert [violation.entry_id for violation in result.proposed_violations] == ["CHR-X-040"]


def test_kept_symbol_mention_does_not_hide_new_parked_surface(tmp_path: Path) -> None:
    charter_path = _write_charters(tmp_path, _charters_payload())
    diff_text = """diff --git a/aragora/control_plane/registry.py b/aragora/control_plane/registry.py
--- a/aragora/control_plane/registry.py
+++ b/aragora/control_plane/registry.py
@@ -0,0 +1,2 @@
+def new_surface():
+    return AgentRegistry()
"""

    result = checker.check_diff(diff_text, charter_path=charter_path)

    assert result.ok is False
    assert result.binding_violations == []
    assert [violation.entry_id for violation in result.proposed_violations] == ["CHR-X-040"]
    assert result.proposed_violations[0].authority_ids == ["ARCH-014"]


def test_dotted_kept_symbol_does_not_exempt_bare_top_level_export(tmp_path: Path) -> None:
    charter_path = _write_charters(tmp_path, _charters_payload())
    diff_text = """diff --git a/aragora/control_plane/scheduler.py b/aragora/control_plane/scheduler.py
--- a/aragora/control_plane/scheduler.py
+++ b/aragora/control_plane/scheduler.py
@@ -0,0 +1,2 @@
+def is_alive():
+    return True
"""

    result = checker.check_diff(diff_text, charter_path=charter_path)

    assert result.ok is False
    assert result.binding_violations == []
    assert [violation.entry_id for violation in result.proposed_violations] == ["CHR-X-040"]
    assert "is_alive" in result.proposed_violations[0].line


def test_dotted_kept_member_does_not_exempt_root_definition(tmp_path: Path) -> None:
    charter_path = _write_charters(tmp_path, _charters_payload())
    diff_text = """diff --git a/aragora/control_plane/registry.py b/aragora/control_plane/registry.py
--- a/aragora/control_plane/registry.py
+++ b/aragora/control_plane/registry.py
@@ -0,0 +1,2 @@
+class AgentInfo:
+    pass
"""

    result = checker.check_diff(diff_text, charter_path=charter_path)

    assert result.ok is False
    assert result.binding_violations == []
    assert [violation.entry_id for violation in result.proposed_violations] == ["CHR-X-040"]
    assert "AgentInfo" in result.proposed_violations[0].line


def test_wildcard_import_in_parked_path_is_not_kept_only(tmp_path: Path) -> None:
    charter_path = _write_charters(tmp_path, _charters_payload())
    diff_text = """diff --git a/aragora/control_plane/registry.py b/aragora/control_plane/registry.py
--- a/aragora/control_plane/registry.py
+++ b/aragora/control_plane/registry.py
@@ -0,0 +1 @@
+from some_module import *
"""

    result = checker.check_diff(diff_text, charter_path=charter_path)

    assert result.ok is False
    assert result.binding_violations == []
    assert [violation.entry_id for violation in result.proposed_violations] == ["CHR-X-040"]
    assert "*" in result.proposed_violations[0].line


def test_parked_path_non_kept_surface_is_proposed(tmp_path: Path) -> None:
    charter_path = _write_charters(tmp_path, _charters_payload())
    diff_text = """diff --git a/aragora/control_plane/registry.py b/aragora/control_plane/registry.py
--- a/aragora/control_plane/registry.py
+++ b/aragora/control_plane/registry.py
@@ -0,0 +1,2 @@
+class RegionalLoadBalancer:
+    pass
"""

    result = checker.check_diff(diff_text, charter_path=charter_path)

    assert result.ok is False
    assert result.binding_violations == []
    assert [violation.entry_id for violation in result.proposed_violations] == ["CHR-X-040"]
    assert result.proposed_violations[0].binding == "PROPOSED"
    assert result.proposed_violations[0].authority_ids == ["ARCH-014"]


def test_removed_symbol_split_fully_qualified_use_is_binding(tmp_path: Path) -> None:
    charter_path = _write_charters(tmp_path, _charters_payload())
    diff_text = """diff --git a/some.py b/some.py
--- a/some.py
+++ b/some.py
@@ -0,0 +1,2 @@
+import aragora.queue
+executor = aragora.queue.create_default_executor()
"""

    result = checker.check_diff(diff_text, charter_path=charter_path)

    assert result.ok is False
    assert [violation.entry_id for violation in result.binding_violations] == ["CHR-P4A-004"]
    assert "create_default_executor" in result.binding_violations[0].line


def test_removed_symbol_split_alias_use_is_binding(tmp_path: Path) -> None:
    charter_path = _write_charters(tmp_path, _charters_payload())
    diff_text = """diff --git a/some.py b/some.py
--- a/some.py
+++ b/some.py
@@ -0,0 +1,2 @@
+import aragora.queue as queue_mod
+executor = queue_mod.create_default_executor()
"""

    result = checker.check_diff(diff_text, charter_path=charter_path)

    assert result.ok is False
    assert [violation.entry_id for violation in result.binding_violations] == ["CHR-P4A-004"]
    assert "create_default_executor" in result.binding_violations[0].line


def test_removed_symbol_wildcard_import_is_binding(tmp_path: Path) -> None:
    charter_path = _write_charters(tmp_path, _charters_payload())
    diff_text = """diff --git a/some.py b/some.py
--- a/some.py
+++ b/some.py
@@ -0,0 +1 @@
+from aragora.queue import *
"""

    result = checker.check_diff(diff_text, charter_path=charter_path)

    assert result.ok is False
    assert [violation.entry_id for violation in result.binding_violations] == ["CHR-P4A-004"]
    assert "*" in result.binding_violations[0].line


def test_exclusion_path_violation_reports_arch_context(tmp_path: Path) -> None:
    charter_path = _write_charters(tmp_path, _charters_payload())
    diff_text = """diff --git a/aragora/server/metrics_pool.py b/aragora/server/metrics_pool.py
--- /dev/null
+++ b/aragora/server/metrics_pool.py
@@ -0,0 +1,2 @@
+def record_metric(name: str) -> None:
+    pass
"""

    result = checker.check_diff(diff_text, charter_path=charter_path)

    assert result.ok is False
    assert [violation.entry_id for violation in result.proposed_violations] == ["CHR-E-004"]
    assert result.proposed_violations[0].authority_ids == ["ARCH-029"]


def test_repository_server_exclusion_is_scoped_to_retired_homes() -> None:
    charter_path = Path(__file__).resolve().parents[2] / "docs/architecture/charters.yaml"
    handler_diff = """diff --git a/aragora/server/handlers/tasks/execution.py b/aragora/server/handlers/tasks/execution.py
--- a/aragora/server/handlers/tasks/execution.py
+++ b/aragora/server/handlers/tasks/execution.py
@@ -0,0 +1 @@
+class TaskRouter: pass
"""

    handler_result = checker.check_diff(handler_diff, charter_path=charter_path)

    assert all(violation.entry_id != "CHR-E-004" for violation in handler_result.violations)

    retired_home_diff = """diff --git a/aragora/server/metrics.py b/aragora/server/metrics.py
--- /dev/null
+++ b/aragora/server/metrics.py
@@ -0,0 +1 @@
+def record_metric(name: str) -> None: pass
"""
    retired_home_result = checker.check_diff(retired_home_diff, charter_path=charter_path)

    assert retired_home_result.ok is False
    assert "CHR-E-004" in {violation.entry_id for violation in retired_home_result.violations}


def test_cli_json_exits_nonzero_with_citable_ids(tmp_path: Path, capsys: Any) -> None:
    charter_path = _write_charters(tmp_path, _charters_payload())
    diff_path = tmp_path / "diff.patch"
    diff_path.write_text(
        """diff --git a/some.py b/some.py
--- a/some.py
+++ b/some.py
@@ -0,0 +1 @@
+from aragora.queue import create_default_executor
""",
        encoding="utf-8",
    )

    rc = checker.main(
        [
            "--charters",
            str(charter_path),
            "--diff-file",
            str(diff_path),
            "--format",
            "json",
        ]
    )
    payload = json.loads(capsys.readouterr().out)

    assert rc == 1
    assert payload["ok"] is False
    assert payload["binding_violations"][0]["entry_id"] == "CHR-P4A-004"
    assert payload["binding_violations"][0]["authority_ids"] == ["ARCH-015"]
