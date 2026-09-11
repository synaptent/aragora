"""Tests for ``scripts/build_disagreement_atlas.py`` (#9950).

Every test runs against the committed fixture in
``tests/scripts/fixtures/disagreement_atlas`` — three real PRs from the
reviewer-failure taxonomy (#8824 diff-blind grounding, #8802 out-of-scope
carousel, #8811 control) with comment bodies stripped to the lines the gate
parsers read. Nothing here touches ``gh`` or the network.
"""

from __future__ import annotations

import importlib.util
import json
import shutil
import sys
from pathlib import Path
from typing import Any

import pytest

HERE = Path(__file__).resolve()
REPO_ROOT = HERE.parents[2]
FIXTURE = HERE.parent / "fixtures" / "disagreement_atlas"
SCHEMA = REPO_ROOT / "docs" / "atlas" / "schema.json"


def _load_module(script_name: str) -> Any:
    script_path = REPO_ROOT / "scripts" / script_name
    spec = importlib.util.spec_from_file_location(f"{script_name}_under_test", script_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"could not load spec for {script_path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


atlas = _load_module("build_disagreement_atlas.py")


def _build(root: Path, cache: Path = FIXTURE) -> tuple[list[dict[str, Any]], dict[str, Any], Path]:
    out_dir = root / "docs" / "atlas"
    out_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy(SCHEMA, out_dir / "schema.json")
    out = out_dir / "atlas-v1.jsonl"
    rc = atlas.main(
        [
            "build",
            "--cache-dir",
            str(cache),
            "--out",
            str(out),
            "--schema",
            str(out_dir / "schema.json"),
            "--repo-root",
            str(root),
            "--eval-fixture",
            str(FIXTURE / "eval_cases.json"),
            "--receipt-dirs",
        ]
    )
    assert rc == 0
    records = atlas.read_jsonl(out)
    manifest = json.loads((out_dir / "manifest.json").read_text(encoding="utf-8"))
    return records, manifest, out


@pytest.fixture(scope="module")
def built(
    tmp_path_factory: pytest.TempPathFactory,
) -> tuple[list[dict[str, Any]], dict[str, Any], Path]:
    return _build(tmp_path_factory.mktemp("atlas"))


def _find(records: list[dict[str, Any]], pr: int, head7: str, family: str) -> dict[str, Any]:
    matches = [
        r
        for r in records
        if r["pr"]["number"] == pr
        and r["head_sha_short"] == head7
        and r["reviewer"]["family"] == family
    ]
    assert len(matches) == 1, f"expected one record for {pr}/{head7}/{family}, got {len(matches)}"
    return matches[0]


# ---------------------------------------------------------------------------
# Schema conformance and controlled vocabularies
# ---------------------------------------------------------------------------


def test_every_record_conforms_to_schema(built) -> None:
    jsonschema = pytest.importorskip("jsonschema")
    records, _manifest, _out = built
    assert records, "fixture must yield records"
    validator = jsonschema.Draft202012Validator(json.loads(SCHEMA.read_text(encoding="utf-8")))
    for record in records:
        errors = sorted(validator.iter_errors(record), key=lambda e: list(e.path))
        assert not errors, f"{record['record_id']}: {[e.message for e in errors][:3]}"


def test_record_ids_are_unique_and_vocabularies_controlled(built) -> None:
    records, _manifest, _out = built
    ids = [r["record_id"] for r in records]
    assert len(ids) == len(set(ids))
    for record in records:
        assert record["adjudication"]["mechanism"] in atlas.RESOLUTION_MECHANISMS
        for mechanism in record["adjudication"]["mechanisms_secondary"]:
            assert mechanism in atlas.RESOLUTION_MECHANISMS
        for klass in record["taxonomy_classes"]:
            assert klass in atlas.FAILURE_CLASSES
        assert record["verdict"] in atlas.VERDICTS
        assert record["verdict_basis"] in atlas.VERDICT_BASES
        assert record["source"] in atlas.SOURCES
        if record["source"] == "eval_fixture":
            assert record["verdict_basis"] == "fixture"
        if record["verdict"] == "changes_requested":
            assert record["dissent_text"] == record["body"]
        else:
            assert record["dissent_text"] == ""


def test_covers_the_three_taxonomy_prs(built) -> None:
    records, manifest, _out = built
    assert {r["pr"]["number"] for r in records} == {8802, 8811, 8824}
    assert manifest["dataset"]["record_count"] == len(records)
    assert manifest["dataset"]["pr_count"] == 3
    assert manifest["source"]["prs_scanned"] == 3
    assert manifest["source"]["prs_with_verdicts"] == 3


# ---------------------------------------------------------------------------
# Determinism
# ---------------------------------------------------------------------------


def test_build_is_byte_deterministic_under_input_reordering(tmp_path: Path) -> None:
    _records_a, manifest_a, out_a = _build(tmp_path / "a")

    shuffled = tmp_path / "shuffled-cache"
    shutil.copytree(FIXTURE, shuffled)
    for comments_path in shuffled.glob("prs/*/comments.json"):
        comments = json.loads(comments_path.read_text(encoding="utf-8"))
        comments.reverse()
        comments_path.write_text(json.dumps(comments), encoding="utf-8")
    _records_b, manifest_b, out_b = _build(tmp_path / "b", cache=shuffled)

    assert out_a.read_bytes() == out_b.read_bytes()
    assert manifest_a == manifest_b
    assert manifest_a["content_digest"]["value"] == manifest_b["content_digest"]["value"]


def test_records_are_sorted_by_pr_round_head_family(built) -> None:
    records, _manifest, _out = built
    keys = [atlas._sort_key(r) for r in records]
    assert keys == sorted(keys)


# ---------------------------------------------------------------------------
# Ground truth, adjudication, rounds
# ---------------------------------------------------------------------------


def test_out_of_scope_carousel_is_labelled_and_refiled(built) -> None:
    records, _manifest, _out = built
    openai = _find(records, 8802, "21a4ac4", "openai")
    assert openai["verdict"] == "changes_requested"
    assert openai["taxonomy_classes"] == ["out_of_scope_carousel"]
    assert openai["adjudication"]["source"] == "labeled"
    assert openai["adjudication"]["mechanism"] == "re_filing"
    assert "operator_adjudication" in openai["adjudication"]["mechanisms_secondary"]
    assert 8810 in openai["follow_up_issues"]
    assert openai["adjudication"]["ground_truth"]["findings_valid"] is True
    assert openai["highest_blocking_severity"] is None  # [P2]-only: advisory under the gate
    assert openai["findings"] and openai["findings"][0]["severity"] == "P2"
    claude = _find(records, 8802, "21a4ac4", "claude")
    assert claude["verdict"] == "pass"
    assert claude["adjudication"]["mechanism"] == "none_required"


def test_diff_blind_grounding_prepare_only_bodies_come_from_fixture(built) -> None:
    records, _manifest, _out = built
    claude = _find(records, 8824, "1bbf572", "claude")
    assert claude["source"] == "eval_fixture"
    assert claude["posted_to_thread"] is False
    assert claude["taxonomy_classes"] == ["diff_blind_grounding"]
    assert claude["highest_blocking_severity"] == "P1"
    assert claude["adjudication"]["mechanism"] == "evidence_post"
    assert "grounding_fix" in claude["adjudication"]["mechanisms_secondary"]
    assert 8825 in claude["follow_up_issues"]
    assert claude["adjudication"]["ground_truth"]["findings_valid"] is False
    # The publicly posted openai PASS at 7e18207 is a pr_comment record.
    openai_pass = _find(records, 8824, "7e18207", "openai")
    assert openai_pass["source"] == "pr_comment"
    assert openai_pass["verdict"] == "pass"
    assert openai_pass["head_resolution"] == "comment_full"
    assert openai_pass["reviewer"]["harness"] == "Codex CLI OpenAI harness"


def test_control_pr_converges_to_clean_pass(built) -> None:
    records, _manifest, _out = built
    r1 = _find(records, 8811, "4aeba63", "claude")
    assert r1["taxonomy_classes"] == ["control"]
    assert r1["adjudication"]["mechanism"] == "revision"
    assert r1["round"] == 1
    for family in ("claude", "openai"):
        final = _find(records, 8811, "15e87b1", family)
        assert final["verdict"] == "pass"
        assert final["round"] == 2
        assert final["pr"]["outcome"] == "merged"
        assert final["pr"]["tier"] == 4


def test_rounds_to_clean_pass_and_split_rounds(built) -> None:
    records, _manifest, _out = built
    reached, never = atlas.rounds_to_clean_pass(records)
    assert never == 0
    assert sorted(reached) == [2, 3, 4]  # #8811, #8824, #8802
    splits = atlas.split_rounds(records)
    by_head = {(s["pr"], s["head"][:7]): s for s in splits}
    carousel = by_head[(8802, "21a4ac4")]
    assert carousel["minority_side"] == "changes_requested"
    assert carousel["minority_families"] == ["openai"]
    assert carousel["vindicated"] is True  # head advanced before merge
    assert (8811, "15e87b1") not in by_head  # 2-0 PASS is not a split


# ---------------------------------------------------------------------------
# Manifest, verify, summary
# ---------------------------------------------------------------------------


def test_manifest_digest_is_jcs_sha256_and_verify_detects_tampering(built, tmp_path: Path) -> None:
    records, manifest, out = built
    payload = {k: v for k, v in manifest.items() if k not in {"content_digest", "signatures"}}
    expected = atlas._sha256(atlas.jcs_canonicalize(payload))
    assert manifest["content_digest"] == {"alg": "sha-256", "value": expected}
    assert manifest["dataset"]["sha256"] == atlas._sha256(out.read_bytes())
    assert manifest["signatures"] == []

    root = out.parents[2]
    ok, lines = atlas.verify_manifest(out.parent / "manifest.json", base=root)
    assert ok, lines

    tampered_root = tmp_path / "tampered"
    shutil.copytree(root, tampered_root)
    tampered = tampered_root / "docs" / "atlas" / "atlas-v1.jsonl"
    tampered.write_bytes(
        tampered.read_bytes().replace(b'"verdict":"pass"', b'"verdict":"unknown"', 1)
    )
    ok, lines = atlas.verify_manifest(
        tampered_root / "docs" / "atlas" / "manifest.json", base=tampered_root
    )
    assert not ok
    assert any("dataset sha256 mismatch" in line for line in lines)


def test_signed_manifest_round_trips(built, tmp_path: Path) -> None:
    pytest.importorskip("cryptography")
    from aragora.gauntlet.odr_signing import generate_signing_key, public_key_pem, sign_odr_receipt

    _records, manifest, out = built
    key = generate_signing_key()
    signed = sign_odr_receipt(manifest, key)
    root = tmp_path / "signed"
    shutil.copytree(out.parents[2], root)
    (root / "docs" / "atlas" / "manifest.json").write_text(json.dumps(signed), encoding="utf-8")
    public = tmp_path / "public.pem"
    public.write_text(public_key_pem(key), encoding="utf-8")
    ok, lines = atlas.verify_manifest(
        root / "docs" / "atlas" / "manifest.json", base=root, public_key_path=public
    )
    assert ok, lines
    assert any("signature" in line and "valid" in line for line in lines)


def test_summary_numbers_regenerate_from_records(built, tmp_path: Path) -> None:
    records, manifest, out = built
    summary_path = tmp_path / "summary.md"
    rc = atlas.main(
        [
            "summary",
            "--dataset",
            str(out),
            "--manifest",
            str(out.parent / "manifest.json"),
            "--out",
            str(summary_path),
        ]
    )
    assert rc == 0
    text = summary_path.read_text(encoding="utf-8")
    assert f"| Records (one per PR × head × family × source verdict) | {len(records)} |" in text
    assert "| PRs with ≥1 posted reviewer verdict | 3 |" in text
    assert "| Median rounds to clean pass | 3 |" in text
    assert manifest["dataset"]["sha256"] in text
    for heading in (
        "## 1. Split verdicts",
        "## 2. False negatives by taxonomy class and family",
        "## 3. Rounds to a clean pass",
        "## Coverage",
        "## Definitions",
    ):
        assert heading in text


# ---------------------------------------------------------------------------
# Parser reuse on a synthetic evidence comment
# ---------------------------------------------------------------------------


def test_record_from_comment_reuses_gate_parsers() -> None:
    from collections import Counter

    from aragora.swarm.quorum_evidence import compose_evidence_comment

    head = "0123456789abcdef0123456789abcdef01234567"
    body = compose_evidence_comment(
        family="codex",
        head_sha=head,
        head_committed_at="2026-07-10T10:00:00Z",
        pr=4242,
        reviewer_text="Verdict: CHANGES-REQUESTED\n\n[P1] `x.py:3` - unguarded None deref.\n[P3] nit.",
        harness="Codex CLI OpenAI harness",
    )
    comment = {
        "id": 1,
        "user": {"login": "someone"},
        "created_at": "2026-07-10T10:05:00Z",
        "html_url": "https://github.com/synaptent/aragora/pull/4242#issuecomment-1",
        "body": body,
    }
    stats: Counter = Counter()
    record = atlas.record_from_comment(comment, {}, stats)
    assert record is not None
    assert record["reviewer_family"] == "openai"  # codex alias collapses to the openai family
    assert record["verdict"] == "changes_requested"
    assert record["verdict_basis"] == "verdict_line"
    assert record["head_sha"] == head
    assert record["head_committed_at"] == "2026-07-10T10:00:00Z"
    assert record["head_resolution"] == "comment_full"
    assert record["harness"] == "Codex CLI OpenAI harness"
    findings = atlas._findings(body)
    assert [f["severity"] for f in findings] == ["P1", "P3"]
    assert atlas.highest_blocking_severity(body) == "P1"

    # Pre-gate phrasing: the gate reads "Verdict: approve" as a non-negative signal.
    approve_body = body.replace("Verdict: CHANGES-REQUESTED", "Verdict: approve").replace(
        "[P1] `x.py:3` - unguarded None deref.", ""
    )
    approved = atlas.record_from_comment(dict(comment, body=approve_body), {}, stats)
    assert approved is not None
    assert (approved["verdict"], approved["verdict_basis"]) == ("pass", "non_negative_signal")

    bot = dict(comment, user={"login": "github-actions[bot]"})
    assert atlas.record_from_comment(bot, {}, stats) is None
    assert stats["skipped_bot_comments"] == 1


def test_head_extraction_resolves_prefixes_against_commit_list() -> None:
    full = "abcdef0123456789abcdef0123456789abcdef01"
    index = {full: "2026-07-01T00:00:00Z"}
    assert atlas.extract_head("reviewed at head abcdef0 carefully", index) == (
        full,
        "2026-07-01T00:00:00Z",
        "commits_list",
    )
    assert atlas.extract_head("Head: abcdef0 (" + full + ")", {}) == (full, "", "comment_full")
    assert atlas.extract_head("Head: 1234567", {})[2] == "prefix_only"
    assert atlas.extract_head("no sha here", {}) == ("", "", "unresolved")


def test_mechanism_text_maps_onto_controlled_vocabulary() -> None:
    assert atlas.map_mechanism_text(
        "evidence-post (machine refutation in-thread) + grounding-blind-spot filed as #8825"
    ) == ["evidence_post", "grounding_fix"]
    assert atlas.map_mechanism_text(
        "re-filing (finding preserved as #8810) + operator advisory settlement"
    ) == [
        "re_filing",
        "operator_adjudication",
    ]
    assert atlas.map_mechanism_text("fix + re-review (converged to 2-0 PASS)") == ["revision"]
    assert atlas.map_mechanism_text("") == []


def test_readme_names_release_tag_atlas_v1() -> None:
    readme = (REPO_ROOT / "docs" / "atlas" / "README.md").read_text(encoding="utf-8")
    assert "`atlas-v1`" in readme
    assert "disagreement-atlas-v1.0.0" not in readme
    gitignore = (REPO_ROOT / "docs" / "atlas" / ".gitignore").read_text(encoding="utf-8")
    assert "atlas-v1.jsonl" in gitignore.splitlines()


def test_collect_caches_reviews_when_verdicts_exist_only_as_review_objects(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cache = tmp_path / "cache"
    (cache / "prs" / "42").mkdir(parents=True)
    (cache / "index.json").write_text(
        json.dumps(
            {
                "repo": "o/r",
                "since": "2026-01-01T00:00:00Z",
                "since_basis": "x",
                "prs": [
                    {
                        "number": 42,
                        "closed_at": "2026-02-01T00:00:00Z",
                        "merged_at": None,
                        "head_sha": "a" * 40,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    (cache / "prs" / "42" / "pr.json").write_text(
        json.dumps({"number": 42, "head": {"sha": "a" * 40}}), encoding="utf-8"
    )
    review_body = (
        "## Codex review\n\nHead: aaaaaaa\nModel family: openai\n\nVerdict: CHANGES-REQUESTED\n"
    )
    payloads = {
        "meta/since_pr_8638.json": {"merged_at": "2026-01-01T00:00:00Z"},
        "prs/42/comments.json": [{"id": 1, "body": "Thanks, looks good."}],
        "prs/42/reviews.json": [{"id": 7, "body": review_body, "state": "CHANGES_REQUESTED"}],
        "prs/42/commits.json": [],
        f"statuses/{'a' * 40}.json": [],
    }
    fetched: list[str] = []

    class FakeClient:
        def __init__(self, cache_dir: Path, *, refresh: bool = False) -> None:
            self.cache_dir = cache_dir
            self.calls = 0

        def cached(self, rel: str, path: str, *, paginate: bool = False) -> Any:
            fetched.append(rel)
            payload = payloads[rel]
            target = self.cache_dir / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(json.dumps(payload), encoding="utf-8")
            return payload

        def total_logged_calls(self) -> int:
            return 0

    monkeypatch.setattr(atlas, "GitHubClient", FakeClient)
    rc = atlas.main(["collect", "--cache-dir", str(cache), "--repo", "o/r"])
    assert rc == 0
    assert "prs/42/reviews.json" in fetched
    assert "prs/42/commits.json" in fetched, "review-only verdict threads must be fully cached"
    assert (cache / "prs" / "42" / "reviews.json").exists()


def test_failure_classes_attach_only_to_the_dissenting_verdict(built) -> None:
    records, _manifest, _out = built
    claude_pass = _find(records, 8802, "21a4ac4", "claude")
    assert claude_pass["verdict"] == "pass"
    assert claude_pass["adjudication"]["source"] == "labeled"
    assert claude_pass["taxonomy_classes"] == []
    assert claude_pass["adjudication"]["ground_truth"]["taxonomy_classes"] == [
        "out_of_scope_carousel"
    ]
    for r in records:
        if r["verdict"] == "pass":
            assert set(r["taxonomy_classes"]) <= {"control"}, r["record_id"]


def test_source_window_covers_every_scanned_pr(tmp_path: Path) -> None:
    cache = tmp_path / "cache"
    shutil.copytree(FIXTURE, cache)
    index = json.loads((cache / "index.json").read_text(encoding="utf-8"))
    index["prs"].append(
        {
            "number": 9999,
            "closed_at": "2026-08-30T00:00:00Z",
            "merged_at": None,
            "head_sha": "f" * 40,
        }
    )
    (cache / "index.json").write_text(json.dumps(index), encoding="utf-8")
    (cache / "prs" / "9999").mkdir()
    (cache / "prs" / "9999" / "pr.json").write_text(
        json.dumps(
            {"number": 9999, "head": {"sha": "f" * 40}, "closed_at": "2026-08-30T00:00:00Z"}
        ),
        encoding="utf-8",
    )
    _records, manifest, _out = _build(tmp_path / "root", cache=cache)
    assert manifest["source"]["prs_scanned"] == 4
    assert manifest["source"]["until"] == "2026-08-30T00:00:00Z"


def test_verify_skips_an_absent_dataset_when_the_sample_is_present(built, tmp_path: Path) -> None:
    _records, manifest, out = built
    root = tmp_path / "checkout"
    shutil.copytree(out.parents[2], root)
    manifest_path = root / "docs" / "atlas" / "manifest.json"
    if not manifest.get("sample"):
        rc = atlas.main(
            [
                "build",
                "--cache-dir",
                str(FIXTURE),
                "--out",
                str(root / "docs" / "atlas" / "atlas-v1.jsonl"),
                "--schema",
                str(root / "docs" / "atlas" / "schema.json"),
                "--repo-root",
                str(root),
                "--eval-fixture",
                str(FIXTURE / "eval_cases.json"),
                "--receipt-dirs",
                "--force-sample",
            ]
        )
        assert rc == 0
    (root / "docs" / "atlas" / "atlas-v1.jsonl").unlink()
    ok, lines = atlas.verify_manifest(manifest_path, base=root)
    assert ok, lines
    assert any(line.startswith("dataset SKIPPED") for line in lines)
    assert any("sample sha256 ok" in line for line in lines)
    (root / "docs" / "atlas" / "atlas-v1.sample.jsonl").unlink()
    ok, lines = atlas.verify_manifest(manifest_path, base=root)
    assert not ok
    assert any("sample missing" in line for line in lines)


def _cache_with_index(tmp_path: Path, mutate: Any) -> Path:
    cache = tmp_path / "cache"
    shutil.copytree(FIXTURE, cache)
    index_path = cache / "index.json"
    index = json.loads(index_path.read_text(encoding="utf-8"))
    mutate(index)
    index_path.write_text(json.dumps(index), encoding="utf-8")
    return cache


def test_records_carry_the_repo_from_the_cache_index(tmp_path: Path) -> None:
    def rename(index: dict[str, Any]) -> None:
        index["repo"] = "example/other"

    cache = _cache_with_index(tmp_path, rename)
    records, manifest, _out = _build(tmp_path / "root", cache=cache)
    assert records
    assert {r["repo"] for r in records} == {"example/other"}
    assert manifest["source"]["repo"] == "example/other"


def test_build_ignores_cached_pr_dirs_absent_from_the_index(tmp_path: Path) -> None:
    cache = _cache_with_index(tmp_path, lambda index: None)
    stray = cache / "prs" / "999"
    shutil.copytree(cache / "prs" / "8811", stray)
    pr = json.loads((stray / "pr.json").read_text(encoding="utf-8"))
    pr["number"] = 999
    (stray / "pr.json").write_text(json.dumps(pr), encoding="utf-8")
    records, manifest, _out = _build(tmp_path / "root", cache=cache)
    assert 999 not in {r["pr"]["number"] for r in records}
    assert manifest["source"]["prs_scanned"] == 3
    assert manifest["dataset"]["pr_count"] == 3


def test_build_fails_when_an_indexed_pr_is_missing_from_the_cache(tmp_path: Path) -> None:
    def add_missing(index: dict[str, Any]) -> None:
        index["prs"].append(
            {
                "number": 4242,
                "closed_at": "2026-08-30T00:00:00Z",
                "merged_at": None,
                "head_sha": "e" * 40,
            }
        )

    cache = _cache_with_index(tmp_path, add_missing)
    with pytest.raises(RuntimeError, match=r"PR #4242 .*collect --cache-dir .*--refresh"):
        _build(tmp_path / "root", cache=cache)


def test_manifest_pins_receipt_files_and_verify_flags_an_edited_one(tmp_path: Path) -> None:
    root = tmp_path / "root"
    receipt_dir = root / "docs" / "receipts"
    receipt_dir.mkdir(parents=True)
    receipt = receipt_dir / "settlement-8811.json"
    receipt.write_text(json.dumps({"pr": 8811, "note": "settled"}), encoding="utf-8")
    out_dir = root / "docs" / "atlas"
    out_dir.mkdir(parents=True)
    shutil.copy(SCHEMA, out_dir / "schema.json")
    argv = [
        "build",
        "--cache-dir",
        str(FIXTURE),
        "--out",
        str(out_dir / "atlas-v1.jsonl"),
        "--schema",
        str(out_dir / "schema.json"),
        "--repo-root",
        str(root),
        "--eval-fixture",
        str(FIXTURE / "eval_cases.json"),
        "--receipt-dirs",
        "docs/receipts",
    ]
    assert atlas.main(argv) == 0
    manifest = json.loads((out_dir / "manifest.json").read_text(encoding="utf-8"))
    records = atlas.read_jsonl(out_dir / "atlas-v1.jsonl")
    assert all(
        r["receipt_refs"] == ["docs/receipts/settlement-8811.json"]
        for r in records
        if r["pr"]["number"] == 8811
    )
    assert manifest["receipt_inputs"]["dirs"] == ["docs/receipts"]
    assert manifest["receipt_inputs"]["files"] == {
        "docs/receipts/settlement-8811.json": atlas._sha256(receipt.read_bytes())
    }
    ok, lines = atlas.verify_manifest(out_dir / "manifest.json", base=root)
    assert ok, lines
    assert any(line.startswith("receipt inputs sha256 ok") for line in lines)

    receipt.write_text(json.dumps({"pr": 8811, "note": "edited"}), encoding="utf-8")
    ok, lines = atlas.verify_manifest(out_dir / "manifest.json", base=root)
    assert not ok
    assert "receipt input sha256 mismatch: docs/receipts/settlement-8811.json" in lines
    assert not any("dataset sha256 mismatch" in line for line in lines)

    # A mirrored tree holding only the atlas files skips the receipt check.
    mirror = tmp_path / "mirror"
    shutil.copytree(out_dir, mirror / "docs" / "atlas")
    ok, lines = atlas.verify_manifest(mirror / "docs" / "atlas" / "manifest.json", base=mirror)
    assert ok, lines
    assert any(line.startswith("receipt inputs SKIPPED") for line in lines)


def test_manifest_canonicalization_string_reproduces_the_digest(built) -> None:
    _records, manifest, _out = built
    assert (
        manifest["canonicalization"] == "RFC 8785 (JCS); content_digest = "
        "SHA-256(JCS(manifest minus content_digest and signatures))"
    )
    unsigned = {k: v for k, v in manifest.items() if k not in {"content_digest", "signatures"}}
    assert atlas._sha256(atlas.jcs_canonicalize(unsigned)) == manifest["content_digest"]["value"]


def test_verify_recomputes_the_ground_truth_fixture_hash(tmp_path: Path) -> None:
    root = tmp_path / "root"
    fixture_dir = root / "tests" / "fixtures"
    fixture_dir.mkdir(parents=True)
    fixture = fixture_dir / "eval_cases.json"
    shutil.copy(FIXTURE / "eval_cases.json", fixture)
    out_dir = root / "docs" / "atlas"
    out_dir.mkdir(parents=True)
    shutil.copy(SCHEMA, out_dir / "schema.json")
    argv = [
        "build",
        "--cache-dir",
        str(FIXTURE),
        "--out",
        str(out_dir / "atlas-v1.jsonl"),
        "--schema",
        str(out_dir / "schema.json"),
        "--repo-root",
        str(root),
        "--eval-fixture",
        str(fixture),
        "--receipt-dirs",
    ]
    assert atlas.main(argv) == 0
    manifest = json.loads((out_dir / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["ground_truth_fixture"]["path"] == "tests/fixtures/eval_cases.json"
    ok, lines = atlas.verify_manifest(out_dir / "manifest.json", base=root)
    assert ok, lines
    assert "ground_truth_fixture sha256 ok" in lines

    fixture.write_text(fixture.read_text(encoding="utf-8") + "\n", encoding="utf-8")
    ok, lines = atlas.verify_manifest(out_dir / "manifest.json", base=root)
    assert not ok
    assert "ground_truth_fixture sha256 mismatch" in lines
