"""External invariants for scripts/regenerate_metrics.py.

The drift check in the script itself compares the live ground truth
against the committed docs/METRICS.md. That is a useful
staleness check, but it is self-referential: if the committed doc was
wrong to begin with, the check would happily keep reproducing the
same wrong numbers as long as the ground truth also didn't move.

This test suite holds external lower-bound invariants on the metrics
the script produces. They encode facts about the codebase that are
obviously true (aragora has more than 100 Python files, more than
100,000 test definitions, etc.) and would catch:

  * A counting function silently returning 0 (e.g. ripgrep not
    available, a path typo returning an empty directory).
  * A counting function producing a number orders of magnitude off
    from reality (e.g. xargs/wc batching bug returning only the
    last chunk's total).

The bounds are intentionally loose: they exist to catch catastrophic
regressions, not to enforce specific values (those are the script's
job). Keep the bounds well below current values so this suite almost
never needs updating.
"""

from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "regenerate_metrics.py"


def _load_module():
    # Register in sys.modules before exec so @dataclass decorators
    # can resolve the module (otherwise cls.__module__ -> None).
    spec = importlib.util.spec_from_file_location("regenerate_metrics", str(SCRIPT))
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["regenerate_metrics"] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def snapshot():
    mod = _load_module()
    return {m.key: m for m in mod.gather_metrics().metrics}


# Lower-bound invariants. Pick bounds ~20-50% below the current live
# value so normal repo growth never breaks the test but a catastrophic
# undercount (e.g. 0, or an off-by-1000 from xargs batching) does.

MIN_BOUNDS = {
    "python_files": 1000,  # actual ~4000
    "python_loc": 500_000,  # actual ~1.9M
    "top_level_modules": 50,  # actual ~136
    "test_files": 1000,  # actual ~5000
    "test_functions": 100_000,  # actual ~215K
    "parametrize_decorators": 100,
    "cli_command_modules": 20,  # actual ~60
    "openapi_paths": 1000,  # actual ~2800
    "openapi_operations": 1000,  # actual ~3200
    "rbac_permission_calls": 500,
    "rbac_unique_permissions": 100,
    "python_sdk_modules": 50,
    "typescript_sdk_modules": 50,
    "allowed_agent_types": 10,
    "knowledge_mound_adapter_specs": 20,
    "knowledge_mound_adapter_files": 20,
    "doc_files": 100,
    "ci_workflows": 20,
}


@pytest.mark.parametrize("metric_key,min_value", list(MIN_BOUNDS.items()))
def test_metric_above_lower_bound(snapshot, metric_key, min_value):
    """Every counted metric must exceed a sanity lower bound.

    If this fails for a real reason (aragora shrank a lot), lower the
    bound in MIN_BOUNDS above. If it fails because the counter returned
    0 or a much-lower number than expected, there is a bug in
    scripts/regenerate_metrics.py.
    """
    assert metric_key in snapshot, (
        f"metric {metric_key!r} missing from snapshot; did it get renamed?"
    )
    metric = snapshot[metric_key]
    assert isinstance(metric.value, int), (
        f"metric {metric_key!r} has non-int value {metric.value!r}"
    )
    assert metric.value > min_value, (
        f"metric {metric_key!r} = {metric.value} is below sanity "
        f"lower bound {min_value}. Either the codebase genuinely "
        f"shrank (lower the bound) or the counter is buggy."
    )


def test_rbac_permission_calls_command_reproduces_value(snapshot):
    """The printed reproduction command must count the generator's file set.

    Every METRICS.md row promises a cold auditor can reproduce the value by
    running the row's command. For rbac_permission_calls the generator counts
    tracked ``.py`` files only (decorator calls cannot exist elsewhere; README
    and YAML mentions are not calls), so the printed command must apply the
    same restriction or the auditor gets a different number.
    """
    metric = snapshot["rbac_permission_calls"]
    result = subprocess.run(
        ["bash", "-c", metric.command],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=True,
    )
    reproduced = int(result.stdout.strip())
    assert reproduced == metric.value, (
        f"printed command reproduces {reproduced} but the generator computed "
        f"{metric.value}; the command's file set must match "
        f"_count_line_matches' file set"
    )


def test_markdown_has_no_timestamp_or_sha(snapshot):
    """Canonical doc must not embed generation timestamp or git SHA.

    Embedding either into a tracked file guarantees merge conflicts
    whenever two branches regenerate the doc. The authoritative
    timestamp and SHA live in --json output instead.
    """
    mod = _load_module()
    rendered = mod.render_markdown(
        mod.MetricsSnapshot(
            generated_at="1970-01-01T00:00:00+00:00",
            git_sha="deadbeef",
            metrics=list(snapshot.values()),
        )
    )
    assert "1970-01-01" not in rendered, "generation timestamp leaked into rendered markdown"
    assert "deadbeef" not in rendered, "git sha leaked into rendered markdown"


def test_loc_count_matches_python_sum():
    """LOC metric must match an independent git-tracked file sum.

    Guards against xargs/wc batching bugs: if the script ever
    reintroduces shell-pipe counting, this test catches it by
    computing the sum a second way. It intentionally uses git-tracked
    files, not Path.rglob, so ignored local artifacts cannot pollute
    canonical metrics.
    """
    mod = _load_module()
    snap = {m.key: m for m in mod.gather_metrics().metrics}
    naive_total = 0
    tracked_files = subprocess.check_output(
        ["git", "ls-files", "--", "aragora"],
        cwd=REPO_ROOT,
        text=True,
    ).splitlines()
    for rel_path in tracked_files:
        if not rel_path.endswith(".py"):
            continue
        p = REPO_ROOT / rel_path
        try:
            with p.open(encoding="utf-8", errors="replace") as f:
                naive_total += sum(1 for _ in f)
        except OSError:
            pass
    assert snap["python_loc"].value == naive_total, (
        f"python_loc metric {snap['python_loc'].value} disagrees with "
        f"independent Python sum {naive_total}"
    )


def test_counts_are_tracked_content_not_local_filesystem_noise(snapshot):
    """Canonical counts must ignore ignored/untracked local artifacts.

    Developer machines often have ignored scratch files such as CLAUDE.md,
    benchmark output, or generated reports under counted directories. The
    public metrics must describe repository content, not machine state.
    """
    tracked_aragora = subprocess.check_output(
        ["git", "ls-files", "--", "aragora"],
        cwd=REPO_ROOT,
        text=True,
    ).splitlines()
    tracked_docs = subprocess.check_output(
        ["git", "ls-files", "--", "docs"],
        cwd=REPO_ROOT,
        text=True,
    ).splitlines()

    expected_top_modules = len(
        {Path(p).parts[1] for p in tracked_aragora if len(Path(p).parts) > 2}
    )
    expected_doc_files = sum(1 for p in tracked_docs if p.endswith(".md"))

    assert snapshot["top_level_modules"].value == expected_top_modules
    assert snapshot["doc_files"].value == expected_doc_files


def test_check_mode_is_idempotent(tmp_path, monkeypatch):
    """Running regenerate twice in a row must report no drift.

    This is the core invariant the drift CI depends on.
    """
    mod = _load_module()
    snapshot_a = mod.gather_metrics()
    monkeypatch.setattr(mod, "METRICS_DOC", tmp_path / "METRICS.md")
    md = mod.render_markdown(snapshot_a)
    (tmp_path / "METRICS.md").write_text(md)

    snapshot_b = mod.gather_metrics()
    drifted, drifts = mod.check_drift(snapshot_b)
    assert not drifted, f"drift detected between two back-to-back regenerations: {drifts}"


# ---------------------------------------------------------------------------
# Base attribution (merge-commit-accurate PR drift check)
#
# PR runs of the Metrics Drift workflow execute on the synthetic merge
# commit, so live counts include main-side changes the PR did not make.
# check_drift accepts base_live (metric key -> live value at the base ref)
# and base_doc (metric label -> doc value at the base ref); drift fully
# explained by the base is reported as INHERITED and must not block.
# ---------------------------------------------------------------------------

PARAM_LABEL = "@pytest.mark.parametrize decorators"


def _synthetic_module_with_doc(tmp_path, monkeypatch, doc_value: int):
    """Load the module with METRICS_DOC pointing at a one-metric doc."""
    mod = _load_module()
    doc_metric = mod.Metric(
        key="parametrize_decorators",
        label=PARAM_LABEL,
        value=doc_value,
        command="cmd",
        source="tests/",
    )
    doc = mod.render_markdown(
        mod.MetricsSnapshot(generated_at="t", git_sha="s", metrics=[doc_metric])
    )
    doc_path = tmp_path / "METRICS.md"
    doc_path.write_text(doc)
    monkeypatch.setattr(mod, "METRICS_DOC", doc_path)
    return mod


def _snapshot_with_value(mod, value: int):
    return mod.MetricsSnapshot(
        generated_at="t",
        git_sha="s",
        metrics=[
            mod.Metric(
                key="parametrize_decorators",
                label=PARAM_LABEL,
                value=value,
                command="cmd",
                source="tests/",
            )
        ],
    )


def test_main_side_drift_is_inherited_not_blocking(tmp_path, monkeypatch):
    """Reproduces run 29947133317: doc=901, merge truth=909, all main-side.

    The PR added nothing; the 8 extra decorators were already on main at the
    base ref. The check must warn (INHERITED) but pass.
    """
    mod = _synthetic_module_with_doc(tmp_path, monkeypatch, doc_value=901)
    snapshot = _snapshot_with_value(mod, 909)
    drifted, drifts = mod.check_drift(
        snapshot,
        base_live={"parametrize_decorators": 909},
        base_doc={PARAM_LABEL: 901},
    )
    assert not drifted, f"main-side drift wrongly blocked the PR: {drifts}"
    assert any(d.startswith("INHERITED:") for d in drifts)


def test_pr_attributable_drift_still_fails(tmp_path, monkeypatch):
    """A PR that adds >threshold to a metric without regenerating must fail."""
    mod = _synthetic_module_with_doc(tmp_path, monkeypatch, doc_value=901)
    snapshot = _snapshot_with_value(mod, 909)
    drifted, drifts = mod.check_drift(
        snapshot,
        base_live={"parametrize_decorators": 901},  # base == doc: PR added all 8
        base_doc={PARAM_LABEL: 901},
    )
    assert drifted, "PR-attributable drift (0.9%) must block"
    assert any(d.startswith("DRIFT:") for d in drifts)


def test_sub_threshold_pr_contribution_on_stale_main_passes(tmp_path, monkeypatch):
    """Reproduces PR #9439: doc=879, merge=895; PR added only 4 (0.46%).

    Combined drift is 1.8% but the PR's own contribution is under the
    threshold; the pre-existing 12 belong to main.
    """
    mod = _synthetic_module_with_doc(tmp_path, monkeypatch, doc_value=879)
    snapshot = _snapshot_with_value(mod, 895)
    drifted, drifts = mod.check_drift(
        snapshot,
        base_live={"parametrize_decorators": 891},  # main already at 891
        base_doc={PARAM_LABEL: 879},
    )
    assert not drifted, f"sub-threshold PR contribution wrongly blocked: {drifts}"


def test_pr_that_regenerated_stays_green_as_main_advances(tmp_path, monkeypatch):
    """A PR that regenerated for its own changes must not fail when main
    later adds more (that was the restack treadmill in #9317)."""
    # PR branched when the count was 901, added 8, regenerated doc to 909.
    # Main meanwhile moved to 906 (doc on main still 901); merge truth 914.
    mod = _synthetic_module_with_doc(tmp_path, monkeypatch, doc_value=909)
    snapshot = _snapshot_with_value(mod, 914)
    drifted, drifts = mod.check_drift(
        snapshot,
        base_live={"parametrize_decorators": 906},
        base_doc={PARAM_LABEL: 901},
    )
    assert not drifted, f"regenerated PR wrongly blocked by main advance: {drifts}"


def test_strict_mode_without_base_data_unchanged(tmp_path, monkeypatch):
    """Scheduled/dispatch runs pass no base data and must stay strict."""
    mod = _synthetic_module_with_doc(tmp_path, monkeypatch, doc_value=901)
    snapshot = _snapshot_with_value(mod, 909)
    drifted, drifts = mod.check_drift(snapshot)
    assert drifted
    assert any(d.startswith("DRIFT:") for d in drifts)


def test_new_metric_always_blocks_even_with_base_data(tmp_path, monkeypatch):
    """A metric absent from the doc means the counter set changed; never
    attributed to the base."""
    mod = _synthetic_module_with_doc(tmp_path, monkeypatch, doc_value=901)
    snapshot = mod.MetricsSnapshot(
        generated_at="t",
        git_sha="s",
        metrics=[
            mod.Metric(
                key="parametrize_decorators",
                label=PARAM_LABEL,
                value=901,
                command="cmd",
                source="tests/",
            ),
            mod.Metric(
                key="brand_new",
                label="Brand new metric",
                value=42,
                command="cmd",
                source="x/",
            ),
        ],
    )
    drifted, drifts = mod.check_drift(
        snapshot,
        base_live={"parametrize_decorators": 901, "brand_new": 42},
        base_doc={PARAM_LABEL: 901},
    )
    assert drifted
    assert any(d.startswith("NEW:") for d in drifts)


def test_missing_base_entry_falls_back_to_strict(tmp_path, monkeypatch):
    """If the base snapshot lacks the metric, do not attribute — fail closed."""
    mod = _synthetic_module_with_doc(tmp_path, monkeypatch, doc_value=901)
    snapshot = _snapshot_with_value(mod, 909)
    drifted, _ = mod.check_drift(snapshot, base_live={}, base_doc={})
    assert drifted


def test_check_cli_with_base_attribution_files(tmp_path, monkeypatch):
    """End-to-end: main(['--check', '--base-json', ..., '--base-doc', ...])
    passes on inherited drift and fails without the base files."""
    import json as _json

    mod = _synthetic_module_with_doc(tmp_path, monkeypatch, doc_value=901)
    snapshot = _snapshot_with_value(mod, 909)
    monkeypatch.setattr(mod, "gather_metrics", lambda: snapshot)

    base_json = tmp_path / "base-live.json"
    base_json.write_text(
        _json.dumps({"metrics": [{"key": "parametrize_decorators", "value": 909}]})
    )
    base_doc = tmp_path / "base-doc.md"
    base_doc.write_text((tmp_path / "METRICS.md").read_text())

    assert mod.main(["--check"]) == 1
    assert mod.main(["--check", "--base-json", str(base_json), "--base-doc", str(base_doc)]) == 0


def test_check_cli_unreadable_base_files_fall_back_to_strict(tmp_path, monkeypatch):
    """Corrupt/missing base data must degrade to the strict check, not crash."""
    mod = _synthetic_module_with_doc(tmp_path, monkeypatch, doc_value=901)
    snapshot = _snapshot_with_value(mod, 909)
    monkeypatch.setattr(mod, "gather_metrics", lambda: snapshot)

    bad_json = tmp_path / "bad.json"
    bad_json.write_text("{not json")
    base_doc = tmp_path / "base-doc.md"
    base_doc.write_text((tmp_path / "METRICS.md").read_text())

    assert mod.main(["--check", "--base-json", str(bad_json), "--base-doc", str(base_doc)]) == 1
