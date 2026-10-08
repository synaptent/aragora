"""Autouse fixture that opens knowledge fact routes for route-body tests.

Loaded as a plugin via ``pytest_plugins`` in ``tests/conftest.py``. Knowledge
fact routes answer 403 to every caller until org scoping exists; handler tests
that exercise route bodies need them open.
"""

import pytest


@pytest.fixture(autouse=True)
def _open_knowledge_fact_routes(request, monkeypatch):
    """Let knowledge route-body tests reach the routes the org-scoping closure shuts.

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
