"""generate_pipeline_receipt reads graph nodes only for the graph's owner org."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from aragora.canvas.stages import PipelineStage
from aragora.pipeline.graph_store import GraphStore
from aragora.pipeline.receipt_generator import generate_pipeline_receipt
from aragora.pipeline.universal_node import UniversalGraph, UniversalNode

GRAPH = "pipe-shared-name"


@pytest.fixture
def graphs(tmp_path: Path):
    store = GraphStore(db_path=str(tmp_path / "graphs.db"))
    graph = UniversalGraph(id=GRAPH, name="A graph")
    for node_id, stage, label in (
        ("idea-1", PipelineStage.IDEAS, "A secret idea"),
        ("goal-1", PipelineStage.GOALS, "A secret goal"),
    ):
        graph.nodes[node_id] = UniversalNode(
            id=node_id, stage=stage, node_subtype="concept", label=label
        )
    store.create(graph, org_id="org-a", created_by="user-a")
    store.create(UniversalGraph(id="pipe-unowned", name="legacy"))
    with (
        patch("aragora.pipeline.graph_store.get_graph_store", return_value=store),
        patch("aragora.knowledge.mound.adapters.receipt_adapter.ReceiptAdapter"),
    ):
        yield store


def _labels(receipt: dict) -> list[str]:
    return [node["label"] for nodes in receipt["provenance"].values() for node in nodes]


@pytest.mark.asyncio
async def test_owner_receipt_carries_the_graph_provenance(graphs) -> None:
    receipt = await generate_pipeline_receipt(GRAPH, {"status": "completed"}, org_id="org-a")

    assert sorted(_labels(receipt)) == ["A secret goal", "A secret idea"]
    assert receipt["summary"]["total_ideas"] == 1
    assert receipt["summary"]["total_goals"] == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("org_id", ["org-b", "", None])
async def test_other_org_receipt_has_no_provenance(graphs, org_id) -> None:
    receipt = await generate_pipeline_receipt(GRAPH, {"status": "completed"}, org_id=org_id)

    assert _labels(receipt) == []
    assert "A secret" not in str(receipt)
    assert receipt["summary"] == {
        "total_ideas": 0,
        "total_goals": 0,
        "total_actions": 0,
        "total_orchestration_nodes": 0,
    }
    assert receipt["execution"]["status"] == "completed"


@pytest.mark.asyncio
async def test_unowned_graph_gives_no_provenance(graphs) -> None:
    receipt = await generate_pipeline_receipt("pipe-unowned", {}, org_id="org-a")

    assert _labels(receipt) == []
