"""Generic, evidence-bearing MetaPlanner acceptance tests."""

from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path
from typing import Any

import pytest

from aragora.core_types import DebateResult
from aragora.nomic.context_builder import NomicContextBuilder
from aragora.nomic.meta_planner import MetaPlanner, MetaPlannerConfig
from aragora.nomic.repository_profile import RepositoryStateError, load_nomic_repository_profile


def git(repo: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout.strip()


@pytest.fixture
def planning_repository(tmp_path: Path) -> Path:
    git(tmp_path, "init")
    git(tmp_path, "config", "user.email", "planner@example.test")
    git(tmp_path, "config", "user.name", "Planner Test")
    git(tmp_path, "remote", "add", "origin", "git@github.com:example/acme-widgets.git")
    (tmp_path / ".gitignore").write_text(".nomic/\n", encoding="utf-8")
    (tmp_path / ".aragora.yaml").write_text(
        """nomic:
  repository:
    name: Acme Widgets
    id: example/acme-widgets
    remote_url: https://github.com/example/acme-widgets
  roadmap_paths:
    - planning/NEXT.md
  context_entry_files:
    - GUIDE.md
  evaluation_criteria:
    - id: leverage
      description: Unlocks measurable product progress
""",
        encoding="utf-8",
    )
    (tmp_path / "GUIDE.md").write_text("# Guide\nServe widget teams.\n", encoding="utf-8")
    planning = tmp_path / "planning"
    planning.mkdir()
    (planning / "NEXT.md").write_text("# Next\nImprove widget latency.\n", encoding="utf-8")
    source = tmp_path / "widget.py"
    source.write_text("def latency_budget():\n    return 100\n", encoding="utf-8")
    git(tmp_path, "add", ".")
    git(tmp_path, "commit", "-m", "initial")
    return tmp_path


def debate(answer: dict[str, Any], *, models: int = 2) -> DebateResult:
    identities = [f"provider-{index}:model-{index}" for index in range(models)]
    proposals = {
        f"agent-{index}": f"Substantive repository proposal {index} with concrete analysis."
        for index in range(max(models, 2))
    }
    return DebateResult(
        task="repository planning",
        final_answer=json.dumps(answer),
        confidence=0.9,
        consensus_reached=True,
        rounds_used=2,
        participants=list(proposals),
        proposals=proposals,
        metadata={"nomic_planning_models": identities},
    )


def goal(path: str, *, description: str = "Reduce widget latency") -> dict[str, Any]:
    return {
        "description": description,
        "rationale": "The roadmap identifies latency as the next measurable constraint.",
        "estimated_impact": "high",
        "criterion_scores": {"leverage": 0.9},
        "evidence_paths": [path],
    }


async def build_pack(repo: Path):
    return await NomicContextBuilder(repo, full_corpus=False).build_context_pack(
        "Improve the widget roadmap",
        profile=load_nomic_repository_profile(repo),
    )


def planner(repo: Path) -> MetaPlanner:
    instance = MetaPlanner(
        MetaPlannerConfig(
            repo_path=str(repo),
            enable_cross_cycle_learning=False,
            enable_metrics_collection=False,
        )
    )
    instance._ingest_receipt_to_km = lambda _receipt: None
    return instance


@pytest.mark.asyncio
async def test_full_coverage_emits_bound_schema_13_receipt(planning_repository: Path) -> None:
    pack = await build_pack(planning_repository)
    instance = planner(planning_repository)
    captured: dict[str, str] = {}

    async def run(prompt: str, _pack):
        captured["prompt"] = prompt
        return debate({"goals": [goal("planning/NEXT.md")]})

    instance._run_repository_planning_debate = run
    result = await instance.plan("Improve the widget roadmap", pack)

    assert result.status == "planned"
    assert result.receipt.verdict == "PASS"
    assert result.receipt.schema_version == "1.3"
    assert result.evidence_coverage == 1.0
    assert result.goals[0].criterion_scores == {"leverage": 0.9}
    assert result.goals[0].evidence_refs == [
        next(item.evidence_id for item in pack.evidence if item.path == "planning/NEXT.md")
    ]
    assert result.receipt.verify_integrity()
    assert result.receipt_json_path.is_file()
    assert result.receipt_markdown_path.is_file()
    stored = json.loads(result.receipt_json_path.read_text(encoding="utf-8"))
    assert stored == result.receipt.to_dict()
    assert "planning/NEXT.md" in result.receipt_markdown_path.read_text(encoding="utf-8")
    assert pack.reference == result.debate_result.metadata["nomic_context_pack"]

    prompt = captured["prompt"]
    assert "Acme Widgets" in prompt
    assert "planning/NEXT.md" in prompt
    assert "GUIDE.md" in prompt
    assert "leverage: Unlocks measurable product progress" in prompt
    assert "Aragora project" not in prompt
    assert "INTERESTING" not in prompt
    assert "POWERFUL" not in prompt

    input_material = {
        "objective": "Improve the widget roadmap",
        "repository_id": "example/acme-widgets",
        "commit_sha": pack.revision.commit_sha,
        "profile_hash": pack.profile_hash,
        "pack_id": pack.pack_id,
    }
    expected_hash = hashlib.sha256(
        json.dumps(input_material, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    assert result.receipt.input_hash == expected_hash


@pytest.mark.asyncio
async def test_partial_coverage_caps_pass_at_conditional(planning_repository: Path) -> None:
    pack = await build_pack(planning_repository)
    instance = planner(planning_repository)

    async def run(_prompt: str, _pack):
        return debate(
            {
                "goals": [
                    goal("planning/NEXT.md"),
                    goal("missing.md", description="Document widget ownership"),
                ]
            }
        )

    instance._run_repository_planning_debate = run
    result = await instance.plan("Improve the widget roadmap", pack)

    assert result.evidence_coverage == 0.5
    assert result.receipt.verdict == "CONDITIONAL"
    assert len(result.goals) == 2
    assert result.receipt.verify_integrity()


@pytest.mark.asyncio
async def test_zero_coverage_is_no_evidence(planning_repository: Path) -> None:
    pack = await build_pack(planning_repository)
    instance = planner(planning_repository)

    async def run(_prompt: str, _pack):
        return debate({"goals": [goal("missing.md")]})

    instance._run_repository_planning_debate = run
    result = await instance.plan("Improve the widget roadmap", pack)

    assert result.evidence_coverage == 0.0
    assert result.receipt.verdict == "NO_EVIDENCE"
    assert result.receipt.confidence == 0.0
    assert result.goals
    assert result.receipt.verify_integrity()


@pytest.mark.asyncio
async def test_single_model_has_no_settled_goals(planning_repository: Path) -> None:
    pack = await build_pack(planning_repository)
    instance = planner(planning_repository)

    async def run(_prompt: str, _pack):
        return debate({"goals": [goal("planning/NEXT.md")]}, models=1)

    instance._run_repository_planning_debate = run
    result = await instance.plan("Improve the widget roadmap", pack)

    assert result.substantive_debate is False
    assert result.goals == []
    assert result.receipt.verdict == "NO_EVIDENCE"
    assert result.receipt.decision_payload["goals"] == []


@pytest.mark.asyncio
async def test_invalid_structured_scores_do_not_settle(planning_repository: Path) -> None:
    pack = await build_pack(planning_repository)
    instance = planner(planning_repository)
    invalid = goal("planning/NEXT.md")
    invalid["criterion_scores"] = {"leverage": 1.5}

    async def run(_prompt: str, _pack):
        return debate({"goals": [invalid]})

    instance._run_repository_planning_debate = run
    result = await instance.plan("Improve the widget roadmap", pack)

    assert result.goals == []
    assert result.receipt.verdict == "NO_EVIDENCE"


@pytest.mark.asyncio
async def test_revision_drift_before_receipt_publish_fails_closed(
    planning_repository: Path,
) -> None:
    pack = await build_pack(planning_repository)
    instance = planner(planning_repository)

    async def run(_prompt: str, _pack):
        (planning_repository / "widget.py").write_text("dirty = True\n", encoding="utf-8")
        return debate({"goals": [goal("planning/NEXT.md")]})

    instance._run_repository_planning_debate = run
    with pytest.raises(RepositoryStateError, match="clean"):
        await instance.plan("Improve the widget roadmap", pack)

    assert not list(pack.pack_path.glob("decision-receipt-*"))
