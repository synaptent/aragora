"""Tests for scripts/doc_stats.py.

Updated to the delimited-block contract for #8792: doc_stats.py rewrites
only ``<!-- metrics:begin <key> -->`` ... ``<!-- metrics:end -->`` blocks,
sourcing values from docs/METRICS.md (plus the version from pyproject.toml),
and fails closed on missing rows, unknown keys, or malformed delimiters.
The old per-line regex search/replace machinery was deleted in the same
change, so its tests were replaced rather than weakened.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "doc_stats.py"

METRICS_TABLE = "\n".join(
    [
        "| Metric | Value | Source | Command |",
        "|---|---|---|---|",
        "| Python files under aragora/ | `4219` | `aragora/` | `cmd` |",
        "| Python lines of code under aragora/ | `1972052` | `aragora/` | `cmd` |",
        "| Top-level modules under aragora/ | `144` | `aragora/` | `cmd` |",
        "| Test files (test_*.py under tests/) | `5402` | `tests/` | `cmd` |",
        "| Test functions (class + module level) | `222659` | `tests/` | `cmd` |",
        "| OpenAPI paths | `2870` | `docs/api/openapi.json` | `cmd` |",
        "| OpenAPI operations (HTTP verbs) | `3297` | `docs/api/openapi.json` | `cmd` |",
        "| Allowlisted agent types | `35` | `aragora/config/settings.py` | `cmd` |",
        "| Knowledge Mound adapter specs | `41` | `aragora/knowledge/mound/adapters/factory.py` | `cmd` |",
        "| Knowledge Mound adapter files | `46` | `aragora/knowledge/mound/adapters/` | `cmd` |",
    ]
)

PYPROJECT = 'name = "aragora"\nversion = "2.9.0"\n'


def _load_module():
    spec = importlib.util.spec_from_file_location("doc_stats_under_test", str(SCRIPT))
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _block(key: str, body: str) -> str:
    return f"<!-- metrics:begin {key} -->\n{body}\n<!-- metrics:end -->"


def _make_root(tmp_path: Path, metrics_table: str = METRICS_TABLE) -> Path:
    root = tmp_path
    (root / "docs").mkdir(exist_ok=True)
    (root / "docs" / "METRICS.md").write_text(metrics_table, encoding="utf-8")
    (root / "pyproject.toml").write_text(PYPROJECT, encoding="utf-8")
    return root


def test_metrics_doc_values_parse_exact_generated_metrics(tmp_path, monkeypatch):
    mod = _load_module()
    root = _make_root(tmp_path)

    monkeypatch.setattr(mod, "ROOT", root)

    values = mod._metrics_doc_values()

    assert values["python_files"].value == 4219
    assert values["python_lines"].value == 1972052
    assert values["top_level_modules"].value == 144
    assert values["test_files"].value == 5402
    assert values["tests"].value == 222659
    assert values["api_paths"].value == 2870
    assert values["api_operations"].value == 3297
    assert values["allowlisted_agent_types"].value == 35
    assert values["adapter_specs"].value == 41
    assert values["adapter_files"].value == 46


def test_rewrite_metric_blocks_rewrites_only_delimited_blocks(tmp_path, monkeypatch):
    mod = _load_module()
    root = _make_root(tmp_path)

    claude_static = "\n".join(
        [
            "Aragora orchestrates 46 agent types.",
            "**Codebase metrics:** See `docs/METRICS.md` for canonical generated counts.",
            "**Test suite metrics:** See `docs/METRICS.md` for canonical generated counts.",
        ]
    )
    (root / "CLAUDE.md").write_text(claude_static, encoding="utf-8")
    (root / "docs" / "EXTENDED_README.md").write_text(
        _block("extended-readme-scale", "stale"),
        encoding="utf-8",
    )
    (root / "docs" / "CANONICAL_GOALS.md").write_text(
        _block("canonical-goals-metrics", "| stale | table |"),
        encoding="utf-8",
    )
    (root / "README.md").write_text(
        _block("readme-scale", "> stale quote"),
        encoding="utf-8",
    )

    monkeypatch.setattr(mod, "ROOT", root)
    updated = mod.rewrite_metric_blocks(write=True)
    assert updated == 3

    claude = (root / "CLAUDE.md").read_text(encoding="utf-8")
    assert claude == claude_static

    extended = (root / "docs" / "EXTENDED_README.md").read_text(encoding="utf-8")
    assert (
        "**Scale:** 4,219 tracked Python files | 144 top-level modules | "
        "222,659 test functions across 5,402 test files | "
        "canonical counts in [METRICS.md](METRICS.md)"
    ) in extended

    goals = (root / "docs" / "CANONICAL_GOALS.md").read_text(encoding="utf-8")
    assert "| Version | 2.9.0 | `pyproject.toml` |" in goals
    assert "| Python files under `aragora/` | 4,219 | `docs/METRICS.md` |" in goals
    assert "| Python modules | 144 top-level package directories | `docs/METRICS.md` |" in goals
    assert "| Lines of code under `aragora/` | 1,972,052 | `docs/METRICS.md` |" in goals
    assert "| Automated tests | 222,659 test functions | `docs/METRICS.md` |" in goals
    assert "| API operations | 3,297 across 2,870 paths | `docs/METRICS.md` |" in goals
    assert (
        "| Knowledge Mound adapters | 46 adapter files / 41 registered specs "
        "| `docs/METRICS.md` |" in goals
    )

    readme = (root / "README.md").read_text(encoding="utf-8")
    assert "> **~4,200 Python files · ~1.9M LOC · 140+ top-level modules · 200,000+ test" in readme
    assert "> functions across ~5,400 files · 3,297 API operations across 2,870 paths ·" in readme
    assert "> 35+ allowlisted agent types across 12+ providers · 41 Knowledge Mound" in readme
    assert "v2.9.0.**" in readme


def test_rewrite_metric_blocks_is_idempotent(tmp_path, monkeypatch):
    mod = _load_module()
    root = _make_root(tmp_path)
    (root / "docs" / "EXTENDED_README.md").write_text(
        _block("extended-readme-scale", "stale"),
        encoding="utf-8",
    )

    monkeypatch.setattr(mod, "ROOT", root)
    assert mod.rewrite_metric_blocks(write=True) == 1
    first = (root / "docs" / "EXTENDED_README.md").read_text(encoding="utf-8")
    assert mod.rewrite_metric_blocks(write=True) == 0
    assert (root / "docs" / "EXTENDED_README.md").read_text(encoding="utf-8") == first


def test_rewrite_metric_blocks_reports_without_writing_when_write_is_false(tmp_path, monkeypatch):
    mod = _load_module()
    root = _make_root(tmp_path)
    original = _block("extended-readme-scale", "stale")
    target = root / "docs" / "EXTENDED_README.md"
    target.write_text(original, encoding="utf-8")

    monkeypatch.setattr(mod, "ROOT", root)
    assert mod.rewrite_metric_blocks(write=False) == 1
    assert target.read_text(encoding="utf-8") == original


def test_rewrite_metric_blocks_fails_closed_when_metrics_doc_is_partial(tmp_path, monkeypatch):
    mod = _load_module()
    partial = "\n".join(
        [
            "| Metric | Value | Source | Command |",
            "|---|---|---|---|",
            "| Python files under aragora/ | `4219` | `aragora/` | `cmd` |",
            "| OpenAPI operations (HTTP verbs) | `3297` | `docs/api/openapi.json` | `cmd` |",
        ]
    )
    root = _make_root(tmp_path, metrics_table=partial)
    original = _block("extended-readme-scale", "stale but preserved")
    target = root / "docs" / "EXTENDED_README.md"
    target.write_text(original, encoding="utf-8")

    monkeypatch.setattr(mod, "ROOT", root)
    with pytest.raises(RuntimeError, match="docs/METRICS.md is missing rows"):
        mod.rewrite_metric_blocks(write=True)
    assert target.read_text(encoding="utf-8") == original


def test_rewrite_metric_blocks_fails_closed_on_missing_version(tmp_path, monkeypatch):
    mod = _load_module()
    root = _make_root(tmp_path)
    (root / "pyproject.toml").unlink()
    original = _block("extended-readme-scale", "stale but preserved")
    target = root / "docs" / "EXTENDED_README.md"
    target.write_text(original, encoding="utf-8")

    monkeypatch.setattr(mod, "ROOT", root)
    with pytest.raises(RuntimeError, match="version"):
        mod.rewrite_metric_blocks(write=True)
    assert target.read_text(encoding="utf-8") == original


def test_rewrite_metric_blocks_fails_closed_on_unknown_key(tmp_path, monkeypatch):
    mod = _load_module()
    root = _make_root(tmp_path)
    known = _block("extended-readme-scale", "stale but preserved")
    target = root / "docs" / "EXTENDED_README.md"
    target.write_text(known, encoding="utf-8")
    unknown = _block("no-such-renderer", "body")
    (root / "docs" / "OTHER.md").write_text(unknown, encoding="utf-8")

    monkeypatch.setattr(mod, "ROOT", root)
    with pytest.raises(RuntimeError, match="unknown metrics block key"):
        mod.rewrite_metric_blocks(write=True)
    # Fail-closed: nothing is written, not even valid blocks in other files.
    assert target.read_text(encoding="utf-8") == known
    assert (root / "docs" / "OTHER.md").read_text(encoding="utf-8") == unknown


def test_rewrite_metric_blocks_fails_closed_on_unterminated_block(tmp_path, monkeypatch):
    mod = _load_module()
    root = _make_root(tmp_path)
    (root / "docs" / "EXTENDED_README.md").write_text(
        "<!-- metrics:begin extended-readme-scale -->\nno end marker\n",
        encoding="utf-8",
    )

    monkeypatch.setattr(mod, "ROOT", root)
    with pytest.raises(RuntimeError, match="well-formed"):
        mod.rewrite_metric_blocks(write=True)


def test_rewrite_metric_blocks_excludes_docs_site_mirrors(tmp_path, monkeypatch):
    mod = _load_module()
    root = _make_root(tmp_path)
    mirror_dir = root / "docs-site" / "docs" / "contributing"
    mirror_dir.mkdir(parents=True)
    mirror = _block("extended-readme-scale", "mirror body owned by sync-docs.js")
    (mirror_dir / "claude.md").write_text(mirror, encoding="utf-8")

    monkeypatch.setattr(mod, "ROOT", root)
    assert mod.rewrite_metric_blocks(write=True) == 0
    assert (mirror_dir / "claude.md").read_text(encoding="utf-8") == mirror


@pytest.mark.parametrize("removed_key", ["claude-codebase-scale", "claude-test-suite"])
def test_rewrite_metric_blocks_rejects_removed_claude_keys(tmp_path, monkeypatch, removed_key):
    mod = _load_module()
    root = _make_root(tmp_path)
    original = _block(removed_key, "stale generated content")
    (root / "CLAUDE.md").write_text(original, encoding="utf-8")

    monkeypatch.setattr(mod, "ROOT", root)
    with pytest.raises(RuntimeError, match="unknown metrics block key"):
        mod.rewrite_metric_blocks(write=True)
    assert (root / "CLAUDE.md").read_text(encoding="utf-8") == original


def test_every_renderer_is_covered_by_required_metric_keys(tmp_path, monkeypatch):
    """Rendering every block with only REQUIRED_METRIC_KEYS present must work."""
    mod = _load_module()
    root = _make_root(tmp_path)
    monkeypatch.setattr(mod, "ROOT", root)

    metrics = mod._metrics_doc_values()
    assert set(metrics) == set(mod.REQUIRED_METRIC_KEYS)
    ctx = mod.RenderContext(metrics=metrics, version="9.9.9")
    for key, renderer in mod.RENDERERS.items():
        rendered = renderer(ctx)
        assert rendered.strip(), key
        assert "<!--" not in rendered, key
