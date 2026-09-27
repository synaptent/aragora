"""Field-drift guard for docs/GITHUB_ACTION_SETUP.md's receipt-emission section.

The doc hand-transcribes action.yml input/output names and a "uses:" target into
prose and YAML snippets. Nothing enforces that transcription stays accurate as
action.yml evolves, so this test re-derives the doc's claims from the doc text
itself and checks them against the actual root action.yml (and the nested
composite actions, which must NOT claim receipt support).
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import yaml

from aragora.gauntlet.odr_verify import verify_odr_document

DOC_PATH = Path("docs/GITHUB_ACTION_SETUP.md")
README_PATH = Path("README.md")
NESTED_REVIEW_GUIDE_PATH = Path("docs/guides/github-actions-review.md")
ROOT_ACTION_PATH = Path("action.yml")
EXAMPLE_RECEIPT_PATH = Path("docs/specs/examples/example-merge-quorum-receipt.odr.json")
RECEIPT_WORKFLOW_EXAMPLE_PATH = Path("examples/github-action/receipt.yml")
PINNED_ROOT_ACTION_REF = "synaptent/aragora@1837e4b3cf26bd5f4a8acafded3e05475dcb0c6d"

_BACKTICK_TABLE_FIELD_RE = re.compile(r"^\|\s*`([a-zA-Z0-9_-]+)`\s*\|", re.MULTILINE)


def _load_yaml(path: Path) -> dict[str, Any]:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def _section(text: str, heading_line: str) -> str:
    """Return the body of a markdown section, stopping at the next heading of
    equal-or-higher level (so nested subsections are included, not treated as
    a boundary)."""
    level = len(heading_line) - len(heading_line.lstrip("#"))
    start = text.index(heading_line) + len(heading_line)
    rest = text[start:]
    stop = re.search(rf"^#{{1,{level}}}\s", rest, re.MULTILINE)
    return rest[: stop.start()] if stop else rest


def _table_field_names(section_text: str) -> list[str]:
    return _BACKTICK_TABLE_FIELD_RE.findall(section_text)


def _fenced_blocks(section_text: str, lang: str) -> list[str]:
    return re.findall(rf"```{lang}\n(.*?)```", section_text, re.DOTALL)


def _first_uses_step(steps: list[dict[str, Any]], prefix: str) -> dict[str, Any]:
    for step in steps:
        if str(step.get("uses", "")).startswith(prefix):
            return step
    raise AssertionError(f"no step with uses starting with {prefix!r} in {steps!r}")


def _comment_permission_blocks(path: Path) -> list[tuple[str, dict[str, Any]]]:
    blocks = []
    for block in _fenced_blocks(path.read_text(encoding="utf-8"), "yaml"):
        if "pull-requests: write" not in block:
            continue
        workflow = yaml.safe_load(block)
        if not isinstance(workflow, dict) or "jobs" not in workflow:
            continue
        blocks.append((block, workflow))
    return blocks


def _workflow_permission_sets(workflow: dict[str, Any]) -> list[dict[str, Any]]:
    permission_sets = []
    top_level = workflow.get("permissions")
    if isinstance(top_level, dict):
        permission_sets.append(top_level)
    for job in workflow.get("jobs", {}).values():
        if isinstance(job, dict) and isinstance(job.get("permissions"), dict):
            permission_sets.append(job["permissions"])
    return permission_sets


def test_comment_posting_workflow_snippets_grant_issue_comment_permission() -> None:
    """`gh pr comment` writes issue comments, so snippets that post PR comments
    need `issues: write` in addition to `pull-requests: write`."""
    for path in (README_PATH, DOC_PATH, NESTED_REVIEW_GUIDE_PATH):
        blocks = _comment_permission_blocks(path)
        assert blocks, f"expected at least one comment-posting workflow block in {path}"
        for block, workflow in blocks:
            permission_sets = _workflow_permission_sets(workflow)
            assert permission_sets, f"workflow block in {path} has no permissions: {block}"
            assert any(
                permissions.get("pull-requests") == "write" and permissions.get("issues") == "write"
                for permissions in permission_sets
            ), f"workflow block in {path} must grant issues: write with pull-requests: write"


def test_documented_input_names_match_action_yml_exactly() -> None:
    """Exact-parity guard (not a subset check): the doc's Action Inputs table
    must document every action.yml input and no others, so a future field
    added to (or removed from) action.yml without a matching doc update fails
    this test immediately instead of silently drifting."""
    action = _load_yaml(ROOT_ACTION_PATH)
    action_inputs = set(action["inputs"].keys())

    doc = DOC_PATH.read_text(encoding="utf-8")
    documented = set(_table_field_names(_section(doc, "### Action Inputs")))

    phantom = documented - action_inputs
    missing = action_inputs - documented
    assert documented == action_inputs, (
        f"doc Action Inputs table is out of parity with action.yml -- "
        f"phantom (documented but not in action.yml): {phantom or None}; "
        f"missing (in action.yml but not documented): {missing or None}"
    )


def test_documented_output_names_match_action_yml_exactly() -> None:
    """Exact-parity guard (not a subset check): the doc's Action Outputs table
    must document every action.yml output and no others, so a future field
    added to (or removed from) action.yml without a matching doc update fails
    this test immediately instead of silently drifting."""
    action = _load_yaml(ROOT_ACTION_PATH)
    action_outputs = set(action["outputs"].keys())

    doc = DOC_PATH.read_text(encoding="utf-8")
    documented = set(_table_field_names(_section(doc, "### Action Outputs")))

    phantom = documented - action_outputs
    missing = action_outputs - documented
    assert documented == action_outputs, (
        f"doc Action Outputs table is out of parity with action.yml -- "
        f"phantom (documented but not in action.yml): {phantom or None}; "
        f"missing (in action.yml but not documented): {missing or None}"
    )


def test_emit_receipt_input_exists_only_on_root_action() -> None:
    root = _load_yaml(ROOT_ACTION_PATH)
    assert "emit-receipt" in root["inputs"]

    for nested in ("aragora-code-review", "aragora-review"):
        nested_action = _load_yaml(Path(f".github/actions/{nested}/action.yml"))
        assert "emit-receipt" not in nested_action.get("inputs", {}), (
            f".github/actions/{nested}/action.yml unexpectedly has emit-receipt; "
            "the doc's 'root action only' claim would be false"
        )


def test_minimal_receipt_snippet_is_valid_yaml_and_wires_emit_receipt() -> None:
    doc = DOC_PATH.read_text(encoding="utf-8")
    section = _section(doc, "## Emitting a Verifiable Decision Receipt")

    yaml_blocks = _fenced_blocks(section, "yaml")
    assert len(yaml_blocks) == 1, "expected exactly one yaml snippet in the receipt section"
    workflow = yaml.safe_load(yaml_blocks[0])

    # PyYAML's (YAML 1.1) resolver coerces the bare "on:" trigger key to the
    # boolean True -- a well-known GitHub Actions/YAML quirk, not a doc defect.
    assert True in workflow or "on" in workflow
    assert "jobs" in workflow
    steps = next(iter(workflow["jobs"].values()))["steps"]

    checkout = _first_uses_step(steps, "actions/checkout@")
    assert checkout["uses"] == "actions/checkout@v4"

    aragora_step = _first_uses_step(steps, "synaptent/aragora@")
    assert "/.github/actions/" not in aragora_step["uses"], (
        "the receipt snippet must point at the ROOT action, not a nested composite"
    )
    assert aragora_step["with"]["emit-receipt"] == "true"
    assert "anthropic-api-key" in aragora_step["with"]
    assert "openai-api-key" in aragora_step["with"]

    upload_step = _first_uses_step(steps, "actions/upload-artifact@")
    assert "receipt-path" in upload_step["with"]["path"]

    verify_steps = [s for s in steps if "aragora-verify" in s.get("run", "")]
    assert verify_steps, "expected an optional aragora-verify step in the snippet"


def test_doc_points_to_receipt_workflow_example() -> None:
    doc = DOC_PATH.read_text(encoding="utf-8")
    assert str(RECEIPT_WORKFLOW_EXAMPLE_PATH) in doc, (
        "doc should point at the receipt-emitting example workflow file"
    )


def test_receipt_workflow_example_is_valid_yaml_and_wires_emit_receipt() -> None:
    workflow = _load_yaml(RECEIPT_WORKFLOW_EXAMPLE_PATH)

    assert "jobs" in workflow
    steps = next(iter(workflow["jobs"].values()))["steps"]

    aragora_step = _first_uses_step(steps, "synaptent/aragora@")
    assert "/.github/actions/" not in aragora_step["uses"], (
        "the receipt example must point at the ROOT action, not a nested composite"
    )
    assert aragora_step["with"]["emit-receipt"] == "true"

    upload_step = _first_uses_step(steps, "actions/upload-artifact@")
    assert "receipt-path" in upload_step["with"]["path"]


def test_docs_do_not_recommend_mutable_main_action_ref() -> None:
    for path in (README_PATH, DOC_PATH):
        assert "synaptent/aragora@main" not in path.read_text(encoding="utf-8")


def test_readme_wedge_snippet_is_valid_yaml_and_uses_pinned_root_action() -> None:
    readme = README_PATH.read_text(encoding="utf-8")
    yaml_blocks = _fenced_blocks(readme, "yaml")
    wedge_blocks = [b for b in yaml_blocks if "synaptent/aragora" in b]
    assert wedge_blocks, "expected a synaptent/aragora workflow snippet in README.md"
    workflow = yaml.safe_load(wedge_blocks[0])

    steps = next(iter(workflow["jobs"].values()))["steps"]
    aragora_step = _first_uses_step(steps, "synaptent/aragora@")

    assert aragora_step["uses"] == PINNED_ROOT_ACTION_REF, (
        "README wedge example should use an immutable root action ref that "
        "includes newer action.yml capabilities like emit-receipt"
    )
    assert aragora_step["with"]["emit-receipt"] == "true"


def test_example_merge_quorum_receipt_verifies_with_sufficient_diversity() -> None:
    import json

    doc_text = DOC_PATH.read_text(encoding="utf-8")
    assert str(EXAMPLE_RECEIPT_PATH) in doc_text, "doc should reference the committed example"

    receipt = json.loads(EXAMPLE_RECEIPT_PATH.read_text(encoding="utf-8"))
    result = verify_odr_document(receipt)

    assert result.ok is True, [(c.name, c.status, c.detail) for c in result.checks]
    assert receipt["quorum"]["independence"]["distinct_model_families"] >= 2
