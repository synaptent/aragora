"""Focused guards for the Contract Drift measurement-authority Tier-4 constants.

The historical PR-scope regressions intentionally require a full Git checkout of
the default-branch history. Their purpose is to authenticate immutable
before/squash objects, so missing objects are a failed proof rather than a reason
to skip a maintained exact-name governance test.
"""

from __future__ import annotations

import ast
import os
import subprocess
import sys
from types import ModuleType
from pathlib import Path

import pytest

from aragora.cli.commands import review_queue
from scripts import generate_contract_drift_inventory
from scripts import tier4_merge_train


EXPECTED_AUTHORITY_PREFIXES = (
    "scripts/check_contract_drift_ratchet.py",
    "scripts/generate_contract_drift_inventory.py",
    "scripts/baselines/contract_drift_inventory.json",
    "scripts/sdk_path_normalize.py",
    "scripts/baselines/internal_route_prefixes.json",
    "scripts/baselines/contract_drift_program.json",
    "scripts/check_sdk_parity.py",
    "scripts/validate_openapi_routes.py",
)

EXECUTABLE_AUTHORITY_DEPENDENCIES = (
    "scripts/contract_drift_report.py",
    "scripts/generate_contract_drift_backlog.py",
    "scripts/generate_contract_drift_issue_plan.py",
    "scripts/check_cross_sdk_parity.py",
    "scripts/tier4_merge_train.py",
)

UNRELATED_SIBLING_PATHS = (
    "scripts/sdk_parity_audit.py",
    "scripts/baselines/validate_openapi_routes.json",
    "scripts/baselines/check_sdk_parity.json",
)

FILE_ROOT_SUFFIXES = (".bak", ".old", ".pyx", "/child", "x")

CLASSIFIER_BASE = "bf4e49c60b357b80f2bee5956f84570d0f9b140a"
CLASSIFIER_MERGE = "ee686e9d116c704ede146a6ec69dfe013b6c32be"
CLASSIFIER_TREE = "0d50965a26df2b88b8cb9bc29b70156e2d9ce006"
MATCHER_BASE = "6137552e4419862b895b096eef1ae36ff8ad210a"
MATCHER_MERGE = "e8a0d165242737d3226b6d3360aa9e8ec014fd75"
MATCHER_TREE = "65c567a51ed4d19d411b9f874163e8a39675d396"
STAGE1_MERGE = "9482fc2dffdb6425d2405389c13f46d5954ac467"


def _assignment_node(source: str, assignment_name: str) -> ast.Assign | ast.AnnAssign:
    tree = ast.parse(source)
    for node in tree.body:
        if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            if node.target.id == assignment_name:
                return node
        if (
            isinstance(node, ast.Assign)
            and len(node.targets) == 1
            and isinstance(node.targets[0], ast.Name)
            and node.targets[0].id == assignment_name
        ):
            return node
    raise AssertionError(f"{assignment_name} assignment not found")


def _assigned_string_literals(source_path: Path, assignment_name: str) -> tuple[str, ...]:
    source = source_path.read_text(encoding="utf-8")
    return _assigned_string_literals_from_source(source, assignment_name)


def _assigned_string_literals_from_source(source: str, assignment_name: str) -> tuple[str, ...]:
    node = _assignment_node(source, assignment_name)
    if not isinstance(node.value, ast.Tuple):
        raise AssertionError(f"{assignment_name} must be a literal tuple")
    values = tuple(
        element.value
        for element in node.value.elts
        if isinstance(element, ast.Constant) and isinstance(element.value, str)
    )
    if len(values) != len(node.value.elts):
        raise AssertionError(f"{assignment_name} must contain only string literals")
    return values


def _assignment_line_span(source_path: Path, assignment_name: str) -> int:
    source = source_path.read_text(encoding="utf-8")
    return _assignment_line_span_from_source(source, assignment_name)


def _assignment_line_span_from_source(source: str, assignment_name: str) -> int:
    node = _assignment_node(source, assignment_name)
    assert node.end_lineno is not None
    return node.end_lineno - node.lineno


def _assignment_source(source: str, assignment_name: str) -> str:
    node = _assignment_node(source, assignment_name)
    segment = ast.get_source_segment(source, node)
    if segment is None:
        raise AssertionError(f"{assignment_name} source segment unavailable")
    return segment


def _top_level_assignment_name(node: ast.stmt) -> str | None:
    if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
        return node.target.id
    if (
        isinstance(node, ast.Assign)
        and len(node.targets) == 1
        and isinstance(node.targets[0], ast.Name)
    ):
        return node.targets[0].id
    return None


def _assert_only_assignments_changed(
    base_source: str,
    head_source: str,
    expected_changed_assignments: set[str],
) -> None:
    base_tree = ast.parse(base_source)
    head_tree = ast.parse(head_source)
    base_assignments = {
        name: ast.dump(node, include_attributes=False)
        for node in base_tree.body
        if (name := _top_level_assignment_name(node)) is not None
    }
    head_assignments = {
        name: ast.dump(node, include_attributes=False)
        for node in head_tree.body
        if (name := _top_level_assignment_name(node)) is not None
    }
    changed_assignments = {
        name
        for name in base_assignments.keys() | head_assignments.keys()
        if base_assignments.get(name) != head_assignments.get(name)
    }
    assert changed_assignments == expected_changed_assignments

    base_tree.body = [
        node
        for node in base_tree.body
        if _top_level_assignment_name(node) not in expected_changed_assignments
    ]
    head_tree.body = [
        node
        for node in head_tree.body
        if _top_level_assignment_name(node) not in expected_changed_assignments
    ]
    assert ast.dump(base_tree, include_attributes=False) == ast.dump(
        head_tree, include_attributes=False
    )


def _without_top_level_functions(source: str, function_names: set[str]) -> str:
    tree = ast.parse(source)
    tree.body = [
        node
        for node in tree.body
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        or node.name not in function_names
    ]
    return ast.dump(tree, include_attributes=False)


def _function_dump(source: str, function_name: str) -> str:
    tree = ast.parse(source)
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == function_name:
            return ast.dump(node, include_attributes=False)
    raise AssertionError(f"{function_name} function not found")


def _git_text(repo_root: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=repo_root,
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, (
        "immutable-history governance proof requires the repository's full Git objects: "
        f"git {' '.join(args)} failed with {result.stderr.strip()!r}"
    )
    return result.stdout


def _source_at_ref(repo_root: Path, ref: str, path: str) -> str:
    return _git_text(repo_root, "show", f"{ref}:{path}")


def _changed_files(repo_root: Path, base: str, head: str) -> set[str]:
    return set(_git_text(repo_root, "diff", "--name-only", base, head).splitlines())


def _canonical_matched_rule(path: str) -> str | None:
    for prefix in review_queue.TIER_4_PREFIXES:
        if review_queue._matches_prefix(path, (prefix,)):
            return prefix
    return None


def test_authority_roots_are_tier4() -> None:
    assert review_queue.CONTRACT_DRIFT_AUTHORITY_PREFIXES == EXPECTED_AUTHORITY_PREFIXES
    assert review_queue.CONTRACT_DRIFT_AUTHORITY_TIER == 4
    for path in EXPECTED_AUTHORITY_PREFIXES:
        tier, name, _reason = review_queue._classify_model_review_tier([path])
        assert tier == 4, path
        assert name == "tier_4_preapproval_required", path


def test_classifier_and_merge_train_constants_match() -> None:
    assert tier4_merge_train.CONTRACT_DRIFT_AUTHORITY_PREFIXES == EXPECTED_AUTHORITY_PREFIXES
    assert (
        tier4_merge_train.CONTRACT_DRIFT_AUTHORITY_POLICY_VERSION
        == review_queue.CONTRACT_DRIFT_AUTHORITY_POLICY_VERSION
    )
    assert (
        tier4_merge_train.CONTRACT_DRIFT_AUTHORITY_TIER
        == review_queue.CONTRACT_DRIFT_AUTHORITY_TIER
        == 4
    )
    assert (
        tier4_merge_train.CONTRACT_DRIFT_AUTHORITY_CANONICAL_SOURCE
        == "aragora.cli.commands.review_queue.CONTRACT_DRIFT_AUTHORITY_PREFIXES"
    )
    assert tier4_merge_train.SERIALIZED_TIER4_PREFIXES == review_queue.TIER_4_PREFIXES
    assert (
        tier4_merge_train.CONTRACT_DRIFT_AUTHORITY_DEPENDENCY_PREFIXES
        == review_queue.CONTRACT_DRIFT_AUTHORITY_DEPENDENCY_PREFIXES
    )
    successor_builder = "scripts/build_contract_drift_historical_backfill.py"
    assert successor_builder in review_queue.CONTRACT_DRIFT_AUTHORITY_DEPENDENCY_PREFIXES
    assert review_queue._classify_model_review_tier([successor_builder])[0] == 4
    assert tier4_merge_train.matches_serialized_path(successor_builder) == successor_builder


@pytest.mark.parametrize("path", EXPECTED_AUTHORITY_PREFIXES)
def test_merge_train_matches_each_authority_root(path: str) -> None:
    assert tier4_merge_train.matches_serialized_path(path) == path


@pytest.mark.parametrize(
    ("path", "expected_rule"),
    [
        *((root, root) for root in review_queue.TIER_4_PREFIXES),
        *(
            (f"{root}{suffix}", None)
            for root in review_queue.TIER_4_PREFIXES
            if not root.endswith("/")
            for suffix in FILE_ROOT_SUFFIXES
        ),
        *(
            (f"{root}nested/authority.txt", root)
            for root in review_queue.TIER_4_PREFIXES
            if root.endswith("/")
        ),
    ],
)
def test_canonical_and_merge_train_boundary_matrix_match(
    path: str, expected_rule: str | None
) -> None:
    assert _canonical_matched_rule(path) == expected_rule
    assert tier4_merge_train.matches_serialized_path(path) == expected_rule
    tier, _name, _reason = review_queue._classify_model_review_tier([path])
    assert (tier == 4) == (expected_rule is not None)


@pytest.mark.parametrize(
    "path",
    [root.rstrip("/") for root in review_queue.TIER_4_PREFIXES if root.endswith("/")],
)
def test_directory_authority_requires_slash_boundary(path: str) -> None:
    assert _canonical_matched_rule(path) is None
    assert tier4_merge_train.matches_serialized_path(path) is None


@pytest.mark.parametrize(
    "path",
    (
        "aragora/knowledge/mound/metrics.py",
        "aragora/knowledge/mound/metrics_health_bridge.py",
    ),
)
def test_existing_tier2_metric_stem_paths_remain_tier2(path: str) -> None:
    tier, name, _reason = review_queue._classify_model_review_tier([path])
    assert tier == 2
    assert name == "tier_2_live_automation"


def test_tier2_metric_stem_matches_when_checked_as_single_rule() -> None:
    prefix = "aragora/knowledge/mound/metrics"
    assert review_queue._matches_prefix(f"{prefix}_health_bridge.py", (prefix,))


@pytest.mark.parametrize("path", EXECUTABLE_AUTHORITY_DEPENDENCIES)
def test_executable_authority_dependencies_are_tier4(path: str) -> None:
    tier, _name, _reason = review_queue._classify_model_review_tier([path])
    assert tier == 4, path
    assert tier4_merge_train.matches_serialized_path(path) == path
    assert path not in review_queue.CONTRACT_DRIFT_AUTHORITY_PREFIXES


def test_quorum_evidence_module_imports_do_not_resolve_below_tier4(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo_root = Path(__file__).resolve().parents[2]
    tree = _git_text(repo_root, "write-tree").strip()
    commit_env = {
        **os.environ,
        "GIT_AUTHOR_EMAIL": "cdg-test@example.invalid",
        "GIT_AUTHOR_NAME": "cdg-test",
        "GIT_COMMITTER_EMAIL": "cdg-test@example.invalid",
        "GIT_COMMITTER_NAME": "cdg-test",
    }
    ref = subprocess.run(
        [
            "git",
            "-C",
            str(repo_root),
            "commit-tree",
            tree,
            "-p",
            _git_text(repo_root, "rev-parse", "HEAD").strip(),
        ],
        input="temporary complete authority closure fixture\n",
        capture_output=True,
        check=True,
        text=True,
        env=commit_env,
    ).stdout.strip()
    monkeypatch.setattr(
        generate_contract_drift_inventory,
        "_resolve_full_commit",
        lambda _repo_root, candidate: candidate,
    )
    manifest_scratch = tmp_path / "manifest-scratch"
    manifest_scratch.mkdir()
    manifest = generate_contract_drift_inventory.build_authority_manifest(
        repo_root,
        ref,
        scratch_root=manifest_scratch,
    )
    closure = {item["path"]: item for item in manifest["repo_files"]}
    extraction_root = tmp_path / "exact-ref"
    generate_contract_drift_inventory._extract_exact_ref(
        repo_root,
        ref,
        extraction_root,
    )
    module_imports = sorted(
        {
            (source_path, imported_path)
            for source_path in closure
            if Path(source_path).suffix == ".py"
            for imported_path, _kind in generate_contract_drift_inventory._python_import_edges(
                extraction_root,
                source_path,
                include_function_bodies=False,
            )
            if imported_path != source_path
        }
    )

    missing_from_closure = [
        (source_path, imported_path)
        for source_path, imported_path in module_imports
        if imported_path not in closure
    ]
    assert missing_from_closure == []
    below_tier4 = [
        (source_path, imported_path)
        for source_path, imported_path in module_imports
        if closure[imported_path]["tier"] != 4
        or closure[imported_path]["matched_rule"]
        != closure[imported_path]["merge_train_matched_rule"]
    ]
    assert below_tier4 == []


def _install_fake_claude_vibeproxy_transport(
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[list[tuple[str, dict[str, object]]], object]:
    calls: list[tuple[str, dict[str, object]]] = []
    result = object()
    transport = ModuleType("aragora.agents.transports.claude_vibeproxy")

    def fake_run(prompt: str, **kwargs: object) -> object:
        calls.append((prompt, kwargs))
        return result

    setattr(transport, "run_claude_vibeproxy", fake_run)
    monkeypatch.setitem(
        sys.modules,
        "aragora.agents.transports.claude_vibeproxy",
        transport,
    )
    return calls, result


def test_quorum_evidence_lazy_delegate_omits_unset_model_keyword(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from aragora.swarm import quorum_evidence

    calls, expected_result = _install_fake_claude_vibeproxy_transport(monkeypatch)
    policy = object()

    result = quorum_evidence.run_claude_vibeproxy(
        "review prompt",
        reviewer_timeout=17.5,
        policy=policy,
    )

    assert result is expected_result
    assert calls == [
        (
            "review prompt",
            {
                "reviewer_timeout": 17.5,
                "policy": policy,
            },
        )
    ]


def test_quorum_evidence_lazy_delegate_forwards_explicit_model_unchanged(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from aragora.swarm import quorum_evidence

    calls, expected_result = _install_fake_claude_vibeproxy_transport(monkeypatch)
    policy = object()
    explicit_model = "claude-opus-4-8/custom:exact"

    result = quorum_evidence.run_claude_vibeproxy(
        "review prompt",
        reviewer_timeout=23.25,
        model=explicit_model,
        policy=policy,
    )

    assert result is expected_result
    assert calls == [
        (
            "review prompt",
            {
                "reviewer_timeout": 23.25,
                "model": explicit_model,
                "policy": policy,
            },
        )
    ]


@pytest.mark.parametrize("path", UNRELATED_SIBLING_PATHS)
def test_unrelated_siblings_remain_below_tier4(path: str) -> None:
    tier, _name, _reason = review_queue._classify_model_review_tier([path])
    assert tier == 2, path
    assert tier4_merge_train.matches_serialized_path(path) is None
    assert path not in review_queue.CONTRACT_DRIFT_AUTHORITY_PREFIXES


def test_authority_constants_and_tuple_shape_remain_exact() -> None:
    repo_root = Path(__file__).resolve().parents[2]
    review_queue_path = repo_root / "aragora/cli/commands/review_queue.py"
    merge_train_path = repo_root / "scripts/tier4_merge_train.py"

    assert (
        _assigned_string_literals(review_queue_path, "CONTRACT_DRIFT_AUTHORITY_PREFIXES")
        == EXPECTED_AUTHORITY_PREFIXES
    )
    assert (
        _assigned_string_literals(merge_train_path, "CONTRACT_DRIFT_AUTHORITY_PREFIXES")
        == EXPECTED_AUTHORITY_PREFIXES
    )
    assert _assignment_line_span(review_queue_path, "CONTRACT_DRIFT_AUTHORITY_PREFIXES") == 0


def test_classifier_pr_changes_are_constants_only() -> None:
    repo_root = Path(__file__).resolve().parents[2]
    review_queue_path = "aragora/cli/commands/review_queue.py"
    merge_train_path = "scripts/tier4_merge_train.py"

    assert _changed_files(repo_root, CLASSIFIER_BASE, CLASSIFIER_MERGE) == {
        review_queue_path,
        merge_train_path,
        "tests/governance/test_contract_drift_measurement_authority_tier.py",
    }
    _git_text(
        repo_root,
        "merge-base",
        "--is-ancestor",
        CLASSIFIER_BASE,
        CLASSIFIER_MERGE,
    )
    assert (
        _git_text(repo_root, "show", "-s", "--format=%P", CLASSIFIER_MERGE).strip()
        == CLASSIFIER_BASE
    )
    assert (
        _git_text(repo_root, "rev-parse", f"{CLASSIFIER_MERGE}^{{tree}}").strip() == CLASSIFIER_TREE
    )

    review_base = _source_at_ref(repo_root, CLASSIFIER_BASE, review_queue_path)
    review_head = _source_at_ref(repo_root, CLASSIFIER_MERGE, review_queue_path)
    _assert_only_assignments_changed(
        review_base,
        review_head,
        {
            "CONTRACT_DRIFT_AUTHORITY_POLICY_VERSION",
            "CONTRACT_DRIFT_AUTHORITY_TIER",
            "CONTRACT_DRIFT_AUTHORITY_PREFIXES",
            "TIER_4_PREFIXES",
        },
    )
    assert (
        _assigned_string_literals_from_source(review_head, "CONTRACT_DRIFT_AUTHORITY_PREFIXES")
        == EXPECTED_AUTHORITY_PREFIXES
    )

    train_base = _source_at_ref(repo_root, CLASSIFIER_BASE, merge_train_path)
    train_head = _source_at_ref(repo_root, CLASSIFIER_MERGE, merge_train_path)
    _assert_only_assignments_changed(
        train_base,
        train_head,
        {
            "CONTRACT_DRIFT_AUTHORITY_POLICY_VERSION",
            "CONTRACT_DRIFT_AUTHORITY_TIER",
            "CONTRACT_DRIFT_AUTHORITY_CANONICAL_SOURCE",
            "CONTRACT_DRIFT_AUTHORITY_PREFIXES",
            "SERIALIZED_TIER4_PREFIXES",
        },
    )
    assert (
        _assigned_string_literals_from_source(train_head, "CONTRACT_DRIFT_AUTHORITY_PREFIXES")
        == EXPECTED_AUTHORITY_PREFIXES
    )


def test_matcher_repair_preserves_eight_constants_and_single_line_authority_tuple() -> None:
    repo_root = Path(__file__).resolve().parents[2]
    authority_assignment = "CONTRACT_DRIFT_AUTHORITY_PREFIXES"
    paths = (
        "aragora/cli/commands/review_queue.py",
        "scripts/tier4_merge_train.py",
    )
    refs = (MATCHER_BASE, MATCHER_MERGE, STAGE1_MERGE)

    _git_text(repo_root, "merge-base", "--is-ancestor", CLASSIFIER_MERGE, MATCHER_BASE)
    _git_text(repo_root, "merge-base", "--is-ancestor", MATCHER_MERGE, STAGE1_MERGE)
    assert _git_text(repo_root, "show", "-s", "--format=%P", MATCHER_MERGE).strip() == MATCHER_BASE
    assert _git_text(repo_root, "rev-parse", f"{MATCHER_MERGE}^{{tree}}").strip() == MATCHER_TREE

    for path in paths:
        sources = {ref: _source_at_ref(repo_root, ref, path) for ref in refs}
        assignments = {
            ref: _assignment_source(source, authority_assignment) for ref, source in sources.items()
        }
        assert len(set(assignments.values())) == 1
        for source in sources.values():
            assert (
                _assigned_string_literals_from_source(source, authority_assignment)
                == EXPECTED_AUTHORITY_PREFIXES
            )

    canonical_sources = {
        ref: _source_at_ref(
            repo_root,
            ref,
            "aragora/cli/commands/review_queue.py",
        )
        for ref in refs
    }
    assert all(
        _assignment_line_span_from_source(source, authority_assignment) == 0
        for source in canonical_sources.values()
    )


def test_matcher_repair_has_no_parser_dispatch_handler_or_settlement_scope() -> None:
    repo_root = Path(__file__).resolve().parents[2]
    review_queue_path = "aragora/cli/commands/review_queue.py"
    merge_train_path = "scripts/tier4_merge_train.py"
    parser_path = "aragora/cli/parser.py"

    assert _changed_files(repo_root, MATCHER_BASE, MATCHER_MERGE) == {
        review_queue_path,
        "tests/governance/test_contract_drift_measurement_authority_tier.py",
        "tests/scripts/test_tier4_merge_train.py",
    }
    _git_text(repo_root, "merge-base", "--is-ancestor", MATCHER_BASE, MATCHER_MERGE)
    _git_text(repo_root, "merge-base", "--is-ancestor", CLASSIFIER_MERGE, MATCHER_BASE)
    _git_text(repo_root, "merge-base", "--is-ancestor", MATCHER_MERGE, STAGE1_MERGE)
    assert _git_text(repo_root, "show", "-s", "--format=%P", MATCHER_MERGE).strip() == MATCHER_BASE
    assert _git_text(repo_root, "rev-parse", f"{MATCHER_MERGE}^{{tree}}").strip() == MATCHER_TREE

    review_base = _source_at_ref(repo_root, MATCHER_BASE, review_queue_path)
    review_head = _source_at_ref(repo_root, MATCHER_MERGE, review_queue_path)
    assert _without_top_level_functions(
        review_base, {"_matches_prefix"}
    ) == _without_top_level_functions(review_head, {"_matches_prefix"})
    assert _function_dump(review_base, "_matches_prefix") != _function_dump(
        review_head, "_matches_prefix"
    )
    assert _source_at_ref(repo_root, MATCHER_BASE, merge_train_path) == _source_at_ref(
        repo_root, MATCHER_MERGE, merge_train_path
    )
    assert _source_at_ref(repo_root, MATCHER_BASE, parser_path) == _source_at_ref(
        repo_root, MATCHER_MERGE, parser_path
    )


@pytest.mark.parametrize(
    "command_name",
    ("classify-tier", "authority-manifest", "boundary-validator"),
)
def test_review_queue_parser_rejects_unapproved_authority_commands(command_name: str) -> None:
    from aragora.cli.parser import build_parser

    parser = build_parser()
    with pytest.raises(SystemExit) as exc_info:
        parser.parse_args(["review-queue", command_name])
    assert exc_info.value.code == 2
