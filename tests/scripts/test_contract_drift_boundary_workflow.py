from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / ".github/workflows/contract-drift-boundary.yml"
TEXT = WORKFLOW.read_text(encoding="utf-8")
DOC = yaml.load(TEXT, Loader=yaml.BaseLoader)


def test_boundary_signer_is_manual_only_and_pins_attest_v4() -> None:
    assert set(DOC["on"]) == {"workflow_dispatch"}
    assert set(DOC["jobs"]) == {"attest"}
    assert "actions/attest@" in TEXT
    assert "# v4.2.1" in TEXT
    assert DOC["permissions"] == {
        "attestations": "write",
        "contents": "read",
        "id-token": "write",
    }


def test_boundary_signer_accepts_only_canonical_boundary_or_successor_tags() -> None:
    run = DOC["jobs"]["attest"]["steps"][0]["run"]
    assert (
        "^(cdg-(corrective_bootstrap|route_truth|core_sdk|extended_sdk|final_seal)|"
        "backfill-v2)-[0-9a-f]{40}$"
    ) in run
    assert 'test "refs/tags/$TAG" = "$GITHUB_REF"' in run
    assert 'test "$SOURCE_DIGEST" = "$GITHUB_SHA"' in run
    assert 'if [[ "$TAG" == backfill-v2-* ]]' in run
    assert 'test "${TAG##*-}" != "$GITHUB_SHA"' in run
    assert 'test "${TAG##*-}" = "$GITHUB_SHA"' in run
    assert "gh release download" in run
    assert "sha256sum --check --strict checksums.txt" in run


def test_boundary_signer_requires_an_exact_source_digest_input() -> None:
    inputs = DOC["on"]["workflow_dispatch"]["inputs"]
    assert inputs["source_digest"]["required"] == "true"
    assert inputs["source_digest"]["type"] == "string"
    assert DOC["jobs"]["attest"]["env"]["SOURCE_DIGEST"] == "${{ inputs.source_digest }}"


def test_boundary_signer_attests_exact_three_assets() -> None:
    attest = DOC["jobs"]["attest"]["steps"][1]
    assert attest["with"]["subject-path"].splitlines() == [
        "assets/manifest.json",
        "assets/payload.json",
        "assets/checksums.txt",
    ]
    run = DOC["jobs"]["attest"]["steps"][0]["run"]
    assert "find assets -mindepth 1 | wc -l" in run
    for name in ("manifest.json", "payload.json", "checksums.txt"):
        assert f"test -s assets/{name}" in run
