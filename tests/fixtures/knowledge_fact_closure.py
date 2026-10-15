"""Autouse fixture that opens v1 knowledge chunk search for route-body tests.

Loaded as a plugin via ``pytest_plugins`` in ``tests/conftest.py``. Every v1
fact route is organization-scoped; GET /api/v1/knowledge/search is not yet
and answers 403 to every caller, so handler tests that exercise its route
body need it open.
"""

import pytest


@pytest.fixture(autouse=True)
def _open_knowledge_fact_routes(request, monkeypatch):
    """Let knowledge route-body tests reach the search route the closure still shuts.

    Modules that pin the closure itself set ``EXERCISES_FACT_CLOSURE = True``.
    """
    module = request.module
    if (
        "handlers" not in request.path.parts
        or "knowledge" not in module.__name__
        or getattr(module, "EXERCISES_FACT_CLOSURE", False)
    ):
        return
    monkeypatch.setattr(
        "aragora.server.handlers.knowledge_base.handler._is_fact_access_closed",
        lambda path, method: False,
    )
