from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

from aragora.server.fastapi.routes import knowledge_base


def _auth() -> Any:
    return SimpleNamespace(user_id="user-1", email="user@example.com", org_id="org-1")


def test_verify_fact_awaits_engine_in_async_route() -> None:
    class FakeDatasetQueryEngine:
        pass

    engine: Any = FakeDatasetQueryEngine()
    engine.verify_fact = AsyncMock(
        return_value=SimpleNamespace(
            to_dict=lambda: {
                "fact_id": "fact-1",
                "verified": True,
                "status": "completed",
                "message": "verified",
            }
        )
    )
    store = MagicMock()
    store.get_fact.return_value = SimpleNamespace(metadata={})

    with patch.object(knowledge_base, "DatasetQueryEngine", FakeDatasetQueryEngine):
        response = asyncio.run(
            knowledge_base.verify_fact(
                fact_id="fact-1",
                auth=_auth(),
                store=store,
                engine=engine,
            )
        )

    assert response.fact_id == "fact-1"
    assert response.verified is True
    engine.verify_fact.assert_awaited_once_with("fact-1")


def test_query_knowledge_base_awaits_engine_query() -> None:
    engine = MagicMock()
    engine.query = AsyncMock(
        return_value=SimpleNamespace(
            to_dict=lambda: {
                "answer": "Use the knowledge base directly.",
                "confidence": 0.81,
                "citations": [{"fact_id": "fact-1"}],
                "sources": [{"workspace_id": "default"}],
            }
        )
    )

    with patch(
        "aragora.server.http_utils.run_async",
        side_effect=AssertionError("sync bridge should not be used"),
    ):
        response = asyncio.run(
            knowledge_base.query_knowledge_base(
                body=knowledge_base.QueryRequest(
                    question="What should we use?",
                    workspace_id="default",
                    options={},
                ),
                auth=_auth(),
                engine=engine,
            )
        )

    assert response.answer == "Use the knowledge base directly."
    assert response.confidence == 0.81
    engine.query.assert_awaited_once()
    assert engine.query.await_args.kwargs == {"org_id": "org-1"}


def test_search_knowledge_base_awaits_engine_search() -> None:
    result = SimpleNamespace(
        to_dict=lambda: {
            "chunk_id": "chunk-1",
            "content": "Found result",
            "score": 0.9,
        }
    )
    engine = MagicMock()
    engine.search = AsyncMock(return_value=[result])

    with patch(
        "aragora.server.http_utils.run_async",
        side_effect=AssertionError("sync bridge should not be used"),
    ):
        response = asyncio.run(
            knowledge_base.search_knowledge_base(
                q="result",
                workspace_id="default",
                limit=5,
                auth=_auth(),
                engine=engine,
            )
        )

    assert response.count == 1
    assert response.results[0]["chunk_id"] == "chunk-1"
    engine.search.assert_awaited_once_with("result", "default", 5, org_id="org-1")
