"""Tests for ``scripts/check_charter_compliance.py``."""

from __future__ import annotations

import importlib.util
import json
import re
import sys
from pathlib import Path
from typing import Any

import pytest
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
        "package_states": {
            "aragora/advocates": "UNMAPPED",
            "aragora/control_plane": "MAPPED",
            "aragora/queue": "MAPPED",
            "aragora/server": "MAPPED",
        },
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


def test_new_file_under_unmapped_package_is_proposed(tmp_path: Path) -> None:
    charter_path = _write_charters(tmp_path, _charters_payload())
    diff_text = """diff --git a/aragora/advocates/new_surface.py b/aragora/advocates/new_surface.py
new file mode 100644
--- /dev/null
+++ b/aragora/advocates/new_surface.py
@@ -0,0 +1,2 @@
+def expand_architecture() -> None:
+    pass
"""

    result = checker.check_diff(diff_text, charter_path=charter_path)

    assert result.ok is False
    assert result.binding_violations == []
    assert [violation.entry_id for violation in result.proposed_violations] == [
        "APPENDIX-A:aragora/advocates"
    ]
    assert result.proposed_violations[0].state == "UNMAPPED"


def test_empty_new_file_under_unmapped_package_is_proposed(tmp_path: Path) -> None:
    charter_path = _write_charters(tmp_path, _charters_payload())
    diff_text = """diff --git a/aragora/advocates/__init__.py b/aragora/advocates/__init__.py
new file mode 100644
index 0000000..e69de29
"""

    result = checker.check_diff(diff_text, charter_path=charter_path)

    assert result.ok is False
    assert [violation.entry_id for violation in result.proposed_violations] == [
        "APPENDIX-A:aragora/advocates"
    ]


def test_new_top_level_module_absent_from_appendix_a_is_proposed(tmp_path: Path) -> None:
    charter_path = _write_charters(tmp_path, _charters_payload())
    diff_text = """diff --git a/aragora/new_architecture.py b/aragora/new_architecture.py
new file mode 100644
--- /dev/null
+++ b/aragora/new_architecture.py
@@ -0,0 +1 @@
+NEW_SURFACE = True
"""

    result = checker.check_diff(diff_text, charter_path=charter_path)

    assert result.ok is False
    assert [violation.entry_id for violation in result.proposed_violations] == [
        "APPENDIX-A:aragora/new_architecture"
    ]
    assert result.proposed_violations[0].reason == (
        "adds a new Python module under a package absent from Appendix A"
    )


def test_renamed_destination_under_unmapped_package_is_proposed(tmp_path: Path) -> None:
    charter_path = _write_charters(tmp_path, _charters_payload())
    diff_text = """diff --git a/aragora/queue/old.py b/aragora/advocates/renamed.py
similarity index 80%
--- a/aragora/queue/old.py
+++ b/aragora/advocates/renamed.py
@@ -1 +1 @@
-OLD = True
+RENAMED = True
"""

    result = checker.check_diff(diff_text, charter_path=charter_path)

    assert result.ok is False
    assert [violation.entry_id for violation in result.proposed_violations] == [
        "APPENDIX-A:aragora/advocates"
    ]


def test_copied_destination_under_unknown_package_is_proposed(tmp_path: Path) -> None:
    charter_path = _write_charters(tmp_path, _charters_payload())
    diff_text = """diff --git a/aragora/queue/source.py b/aragora/new_architecture/copied.py
similarity index 100%
copy from aragora/queue/source.py
copy to aragora/new_architecture/copied.py
"""

    result = checker.check_diff(diff_text, charter_path=charter_path)

    assert result.ok is False
    assert [violation.entry_id for violation in result.proposed_violations] == [
        "APPENDIX-A:aragora/new_architecture"
    ]


def test_renamed_destination_under_mapped_package_is_allowed(tmp_path: Path) -> None:
    charter_path = _write_charters(tmp_path, _charters_payload())
    diff_text = """diff --git a/aragora/advocates/old.py b/aragora/queue/renamed.py
similarity index 100%
rename from aragora/advocates/old.py
rename to aragora/queue/renamed.py
"""

    result = checker.check_diff(diff_text, charter_path=charter_path)

    assert result.ok is True
    assert result.violations == []


def test_empty_renamed_file_under_unmapped_package_is_proposed(tmp_path: Path) -> None:
    charter_path = _write_charters(tmp_path, _charters_payload())
    diff_text = """diff --git a/aragora/queue/empty.py b/aragora/advocates/empty.py
similarity index 100%
rename from aragora/queue/empty.py
rename to aragora/advocates/empty.py
"""

    result = checker.check_diff(diff_text, charter_path=charter_path)

    assert result.ok is False
    assert [violation.entry_id for violation in result.proposed_violations] == [
        "APPENDIX-A:aragora/advocates"
    ]


def test_existing_file_edit_under_unmapped_package_is_maintenance(tmp_path: Path) -> None:
    charter_path = _write_charters(tmp_path, _charters_payload())
    diff_text = """diff --git a/aragora/advocates/existing.py b/aragora/advocates/existing.py
--- a/aragora/advocates/existing.py
+++ b/aragora/advocates/existing.py
@@ -1,0 +2 @@
+MAINTENANCE_NOTE = "allowed"
"""

    result = checker.check_diff(diff_text, charter_path=charter_path)

    assert result.ok is True
    assert result.violations == []


def test_new_file_under_mapped_package_is_allowed(tmp_path: Path) -> None:
    charter_path = _write_charters(tmp_path, _charters_payload())
    diff_text = """diff --git a/aragora/queue/new_surface.py b/aragora/queue/new_surface.py
new file mode 100644
--- /dev/null
+++ b/aragora/queue/new_surface.py
@@ -0,0 +1 @@
+QUEUE_SURFACE = True
"""

    result = checker.check_diff(diff_text, charter_path=charter_path)

    assert result.ok is True
    assert result.violations == []


def test_unknown_package_defaults_to_unmapped_fail_closed(tmp_path: Path) -> None:
    charter_path = _write_charters(tmp_path, _charters_payload())
    diff_text = """diff --git a/aragora/new_architecture/surface.py b/aragora/new_architecture/surface.py
new file mode 100644
--- /dev/null
+++ b/aragora/new_architecture/surface.py
@@ -0,0 +1 @@
+NEW_SURFACE = True
"""

    result = checker.check_diff(diff_text, charter_path=charter_path)

    assert result.ok is False
    assert [violation.entry_id for violation in result.proposed_violations] == [
        "APPENDIX-A:aragora/new_architecture"
    ]


def test_ratified_unmapped_package_growth_is_binding(tmp_path: Path) -> None:
    payload = _charters_payload()
    payload["meta"]["status"] = "RATIFIED"
    charter_path = _write_charters(tmp_path, payload)
    diff_text = """diff --git a/aragora/advocates/new_surface.py b/aragora/advocates/new_surface.py
new file mode 100644
--- /dev/null
+++ b/aragora/advocates/new_surface.py
@@ -0,0 +1 @@
+NEW_SURFACE = True
"""

    result = checker.check_diff(diff_text, charter_path=charter_path)

    assert result.ok is False
    assert [violation.entry_id for violation in result.binding_violations] == [
        "APPENDIX-A:aragora/advocates"
    ]
    assert result.proposed_violations == []


def test_invalid_package_state_fails_closed(tmp_path: Path) -> None:
    payload = _charters_payload()
    payload["package_states"]["aragora/advocates"] = "UNKNOWN"
    charter_path = _write_charters(tmp_path, payload)

    with pytest.raises(ValueError, match="invalid package state"):
        checker.load_package_states(charter_path)


def test_main_package_states_match_appendix_a() -> None:
    repo_root = Path(__file__).resolve().parents[2]
    charter_path = repo_root / "docs" / "architecture" / "charters.yaml"
    architecture_path = repo_root / "docs" / "architecture" / "INTENDED_ARCHITECTURE.md"
    package_states, status = checker.load_package_states(charter_path)
    row_re = re.compile(r"^\| `(?P<path>aragora/[^`]+)` \| [^|]+ \| (?P<state>MAPPED|UNMAPPED) \|")
    appendix_states = {
        match.group("path"): match.group("state")
        for line in architecture_path.read_text(encoding="utf-8").splitlines()
        if (match := row_re.match(line))
    }
    live_package_dirs = {
        path.relative_to(repo_root).as_posix()
        for path in (repo_root / "aragora").iterdir()
        if path.is_dir() and not path.name.startswith((".", "__"))
    }

    assert status == "DRAFT"
    assert package_states == appendix_states
    assert set(package_states) == live_package_dirs
    assert len(package_states) == 144
    assert sum(state == "MAPPED" for state in package_states.values()) == 63
    assert sum(state == "UNMAPPED" for state in package_states.values()) == 81


def _charters_payload_with_legacy_entries() -> dict[str, Any]:
    payload = _charters_payload()
    payload["authorities"].append(
        {
            "id": "ARCH-016",
            "concern": "legacy-executor",
            "authority": "aragora/queue/legacy",
            "registry_refs": ["CHR-P4A-009", "CHR-X-051"],
        }
    )
    payload["registry"].extend(
        [
            {
                "id": "CHR-P4A-009",
                "state": "REMOVED",
                "binding_in_draft": True,
                "paths": ["aragora/queue/legacy.py"],
                "symbols": ["aragora.queue.legacy:legacy_executor"],
                "kept_symbols": ["aragora.queue.legacy:LegacyStatus"],
                "evidence": "legacy executor removed; status enum kept.",
            },
            {
                "id": "CHR-X-051",
                "state": "REMOVED",
                "paths": ["aragora/legacy_mod.py"],
                "symbols": ["aragora.legacy_mod:old_thing"],
                "evidence": "proposed removal, not yet binding in draft.",
            },
        ]
    )
    return payload


def test_multiline_removed_symbol_readd_reports_original_source_location(tmp_path: Path) -> None:
    charter_path = _write_charters(tmp_path, _charters_payload())
    diff_text = """diff --git a/pkg/worker.py b/pkg/worker.py
--- a/pkg/worker.py
+++ b/pkg/worker.py
@@ -9,0 +10,4 @@
+from aragora.queue import (
+    create_default_executor,
+)
+executor = create_default_executor()
"""

    result = checker.check_diff(diff_text, charter_path=charter_path)

    assert result.ok is False
    assert [violation.entry_id for violation in result.binding_violations] == ["CHR-P4A-004"]
    violation = result.binding_violations[0]
    assert violation.binding == "BINDING"
    assert violation.authority_ids == ["ARCH-015"]
    assert violation.path == "pkg/worker.py"
    assert violation.line_no == 10
    assert "create_default_executor" in violation.line
    assert result.proposed_violations == []


def test_multiline_removed_symbol_alias_and_comments_are_binding(tmp_path: Path) -> None:
    charter_path = _write_charters(tmp_path, _charters_payload())
    diff_text = """diff --git a/some.py b/some.py
--- a/some.py
+++ b/some.py
@@ -0,0 +1,5 @@
+from aragora.queue import (  # noqa: F401
+    QueueConfig,  # unrelated, kept on purpose
+    create_default_executor as build_executor,
+)  # end of import
+executor = build_executor()
"""

    result = checker.check_diff(diff_text, charter_path=charter_path)

    assert result.ok is False
    assert [violation.entry_id for violation in result.binding_violations] == ["CHR-P4A-004"]
    assert result.binding_violations[0].line_no == 1
    assert "create_default_executor" in result.binding_violations[0].line


def test_multiline_import_without_added_closer_still_detects_symbol(tmp_path: Path) -> None:
    charter_path = _write_charters(tmp_path, _charters_payload())
    diff_text = """diff --git a/some.py b/some.py
--- a/some.py
+++ b/some.py
@@ -1,1 +1,2 @@
-from aragora.queue import (QueueConfig,
+from aragora.queue import (
+    create_default_executor,
"""

    result = checker.check_diff(diff_text, charter_path=charter_path)

    assert result.ok is False
    assert [violation.entry_id for violation in result.binding_violations] == ["CHR-P4A-004"]
    assert result.binding_violations[0].line_no == 1


def test_multiline_kept_only_import_is_not_a_violation(tmp_path: Path) -> None:
    charter_path = _write_charters(tmp_path, _charters_payload())
    diff_text = """diff --git a/aragora/debate/team_selector.py b/aragora/debate/team_selector.py
--- a/aragora/debate/team_selector.py
+++ b/aragora/debate/team_selector.py
@@ -1,0 +2,5 @@
+from aragora.control_plane.registry import (
+    AgentRegistry,
+    AgentStatus,
+)
+registry = AgentRegistry()
"""

    result = checker.check_diff(diff_text, charter_path=charter_path)

    assert result.ok is True
    assert result.violations == []


def test_multiline_mixed_kept_and_parked_import_is_proposed(tmp_path: Path) -> None:
    charter_path = _write_charters(tmp_path, _charters_payload())
    diff_text = """diff --git a/aragora/debate/team_selector.py b/aragora/debate/team_selector.py
--- a/aragora/debate/team_selector.py
+++ b/aragora/debate/team_selector.py
@@ -1,0 +2,4 @@
+from aragora.control_plane.registry import (
+    AgentRegistry,
+    RegionalLoadBalancer,
+)
"""

    result = checker.check_diff(diff_text, charter_path=charter_path)

    assert result.ok is False
    assert result.binding_violations == []
    assert [violation.entry_id for violation in result.proposed_violations] == ["CHR-X-040"]
    assert result.proposed_violations[0].line_no == 2
    assert result.proposed_violations[0].authority_ids == ["ARCH-014"]


def test_multiline_mixed_kept_and_removed_symbol_flags_only_removed(tmp_path: Path) -> None:
    charter_path = _write_charters(tmp_path, _charters_payload_with_legacy_entries())
    diff_text = """diff --git a/some.py b/some.py
--- a/some.py
+++ b/some.py
@@ -0,0 +1,4 @@
+from aragora.queue.legacy import (
+    LegacyStatus,
+    legacy_executor,
+)
"""

    result = checker.check_diff(diff_text, charter_path=charter_path)

    assert result.ok is False
    assert [violation.entry_id for violation in result.binding_violations] == ["CHR-P4A-009"]
    assert result.binding_violations[0].authority_ids == ["ARCH-016"]
    assert "legacy_executor" in result.binding_violations[0].line
    assert result.proposed_violations == []

    kept_only = """diff --git a/some.py b/some.py
--- a/some.py
+++ b/some.py
@@ -0,0 +1,3 @@
+from aragora.queue.legacy import (
+    LegacyStatus,
+)
"""

    assert checker.check_diff(kept_only, charter_path=charter_path).violations == []


def test_multiline_proposed_symbol_readd_is_not_binding(tmp_path: Path) -> None:
    charter_path = _write_charters(tmp_path, _charters_payload_with_legacy_entries())
    diff_text = """diff --git a/some.py b/some.py
--- a/some.py
+++ b/some.py
@@ -0,0 +1,3 @@
+from aragora.legacy_mod import (
+    old_thing,
+)
"""

    result = checker.check_diff(diff_text, charter_path=charter_path)

    assert result.ok is False
    assert result.binding_violations == []
    assert [violation.entry_id for violation in result.proposed_violations] == ["CHR-X-051"]
    assert result.proposed_violations[0].binding == "PROPOSED"
    assert "old_thing" in result.proposed_violations[0].line


def test_multiline_import_is_not_joined_across_files(tmp_path: Path) -> None:
    charter_path = _write_charters(tmp_path, _charters_payload())
    diff_text = """diff --git a/first.py b/first.py
--- a/first.py
+++ b/first.py
@@ -4,0 +5,1 @@
+from aragora.queue import (
diff --git a/second.py b/second.py
--- a/second.py
+++ b/second.py
@@ -0,0 +1,2 @@
+    create_default_executor,
+)
"""

    assert checker.check_diff(diff_text, charter_path=charter_path).violations == []

    single_line_in_second = """diff --git a/first.py b/first.py
--- a/first.py
+++ b/first.py
@@ -4,0 +5,1 @@
+from aragora.queue import (
diff --git a/second.py b/second.py
--- a/second.py
+++ b/second.py
@@ -0,0 +1,1 @@
+from aragora.queue import create_default_executor
"""

    result = checker.check_diff(single_line_in_second, charter_path=charter_path)

    assert [violation.entry_id for violation in result.binding_violations] == ["CHR-P4A-004"]
    assert result.binding_violations[0].path == "second.py"
    assert result.binding_violations[0].line_no == 1


def test_multiline_import_is_not_joined_across_hunks(tmp_path: Path) -> None:
    charter_path = _write_charters(tmp_path, _charters_payload())
    diff_text = """diff --git a/some.py b/some.py
--- a/some.py
+++ b/some.py
@@ -0,0 +1,1 @@
+from aragora.queue import (
@@ -1,0 +2,2 @@
+    create_default_executor,
+)
"""

    assert checker.check_diff(diff_text, charter_path=charter_path).violations == []


def test_multiline_benign_import_passes(tmp_path: Path) -> None:
    charter_path = _write_charters(tmp_path, _charters_payload())
    diff_text = """diff --git a/some.py b/some.py
--- a/some.py
+++ b/some.py
@@ -0,0 +1,5 @@
+from os.path import (
+    join,
+    split as split_path,
+)
+target = join("a", "b")
"""

    result = checker.check_diff(diff_text, charter_path=charter_path)

    assert result.ok is True
    assert result.violations == []


def test_cli_text_multiline_reports_source_location_and_authority(
    tmp_path: Path, capsys: Any
) -> None:
    charter_path = _write_charters(tmp_path, _charters_payload())
    diff_path = tmp_path / "diff.patch"
    diff_path.write_text(
        """diff --git a/pkg/worker.py b/pkg/worker.py
--- a/pkg/worker.py
+++ b/pkg/worker.py
@@ -9,0 +10,3 @@
+from aragora.queue import (
+    create_default_executor,
+)
""",
        encoding="utf-8",
    )

    rc = checker.main(
        ["--charters", str(charter_path), "--diff-file", str(diff_path), "--format", "text"]
    )
    out = capsys.readouterr().out

    assert rc == 1
    assert "Charter compliance: FAIL" in out
    assert "BINDING CHR-P4A-004 [REMOVED] authorities=ARCH-015 pkg/worker.py:10:" in out
    assert "create_default_executor" in out


def test_cli_json_multiline_reports_source_location(tmp_path: Path, capsys: Any) -> None:
    charter_path = _write_charters(tmp_path, _charters_payload())
    diff_path = tmp_path / "diff.patch"
    diff_path.write_text(
        """diff --git a/pkg/worker.py b/pkg/worker.py
--- a/pkg/worker.py
+++ b/pkg/worker.py
@@ -9,0 +10,3 @@
+from aragora.queue import (
+    create_default_executor,
+)
""",
        encoding="utf-8",
    )

    rc = checker.main(
        ["--charters", str(charter_path), "--diff-file", str(diff_path), "--format", "json"]
    )
    payload = json.loads(capsys.readouterr().out)

    assert rc == 1
    assert payload["ok"] is False
    violation = payload["binding_violations"][0]
    assert violation["entry_id"] == "CHR-P4A-004"
    assert violation["authority_ids"] == ["ARCH-015"]
    assert violation["path"] == "pkg/worker.py"
    assert violation["line_no"] == 10
    assert "create_default_executor" in violation["line"]
    assert payload["proposed_violations"] == []
