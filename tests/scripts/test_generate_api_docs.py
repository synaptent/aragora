from __future__ import annotations

import json
import re
from pathlib import Path

import scripts.generate_api_docs as generate_api_docs

REPO_ROOT = Path(__file__).resolve().parents[2]


def _discover(tmp_path: Path, modules: dict[str, str], operations: dict[str, list[str]]):
    for name, source in modules.items():
        (tmp_path / "handlers" / name).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / "handlers" / name).write_text(source, encoding="utf-8")
    paths = {
        route: {m: {"summary": route} for m in methods} for route, methods in operations.items()
    }
    (tmp_path / "openapi.json").write_text(json.dumps({"paths": paths}), encoding="utf-8")
    groups, omitted = generate_api_docs.discover_endpoints(
        tmp_path / "handlers", tmp_path / "openapi.json"
    )
    return [(e.method, e.path, e.description) for g in groups for e in g.endpoints], omitted


def test_nested_routes_are_found_statically_with_the_spec_verbs(tmp_path) -> None:
    source = (
        "import module_that_is_not_installed\n\n\nclass GustoHandler:\n"
        '    ROUTES = ["/api/v1/gusto/status", "/api/v1/gusto/connect", "/api/v1/gusto/x"]\n'
        '    POST_ROUTES = ["/api/v1/gusto/x"]\n'
    )
    hidden = 'class HiddenHandler:\n    ROUTES = ["/api/v1/gusto/status"]\n'
    listed, omitted = _discover(
        tmp_path,
        {"accounting/gusto.py": source, "accounting/_hidden.py": hidden},
        {"/api/v1/gusto/status": ["get"], "/api/v1/gusto/connect": ["post"]},
    )

    assert [(method, path) for method, path, _ in listed] == [
        ("GET", "/api/v1/gusto/status"),
        ("POST", "/api/v1/gusto/connect"),
    ]
    assert omitted == 1


def test_docstring_endpoints_keep_only_verbs_the_spec_serves(tmp_path) -> None:
    source = (
        '"""A2A handlers.\n\nEndpoints:\n- GET /api/v1/a2a/tasks/:id - Get task status\n'
        "- DELETE /api/v1/a2a/tasks/:id - Cancel task\n"
        '- GET /api/v1/a2a/tasks/:id/stream - Stream task\n"""\n'
    )
    listed, omitted = _discover(
        tmp_path, {"tasks/a2a.py": source}, {"/api/v1/a2a/tasks/{task_id}": ["get"]}
    )

    assert listed == [("GET", "/api/v1/a2a/tasks/:id", "Get task status")]
    assert omitted == 2


def test_committed_endpoint_docs_list_no_phantom_verbs() -> None:
    spec = json.loads((REPO_ROOT / "docs/api/openapi.json").read_text(encoding="utf-8"))
    normalize = generate_api_docs.normalize_path
    served = {(m.upper(), normalize(p)) for p, item in spec["paths"].items() for m in item}
    docs = (REPO_ROOT / "docs/API_ENDPOINTS.md").read_text(encoding="utf-8")
    listed = re.findall(r"^### `([A-Z]+)` `([^`]+)`", docs, re.MULTILINE)

    phantom = [f"{m} {p}" for m, p in listed if (m, normalize(p)) not in served]

    assert listed
    assert phantom == []
