"""Response-status overrides for wired registration declarations."""

import ast
from pathlib import Path

import pytest

from aragora.server.openapi.endpoints import wired_registrations
from aragora.server.openapi.endpoints.wired_registrations import (
    WIRED_REGISTRATION_ENDPOINTS,
    _operation,
    _routes,
)


_MODULE_PATH = Path(wired_registrations.__file__)
_ENDPOINTS_NAME = "WIRED_REGISTRATION_ENDPOINTS"
# operationId preservation is not a response override; it is the only
# post-construction write the module may still perform.
_ALLOWED_POST_CONSTRUCTION_WRITES = {"WIRED_REGISTRATION_ENDPOINTS[_path][_method]['operationId']"}
_MUTATING_DICT_METHODS = {"clear", "pop", "popitem", "setdefault", "update", "__setitem__"}


def _json_response(description: str) -> dict:
    return {
        "description": description,
        "content": {"application/json": {"schema": {"type": "object"}}},
    }


def test_operation_emits_extra_success_statuses_after_primary_status() -> None:
    operation = _operation(
        "/api/v1/widgets/{widget_id}",
        "put",
        source="aragora/example.py",
        tag="Widgets",
        extra_success_statuses=("201",),
    )

    assert list(operation["responses"]) == ["200", "201"]
    assert operation["responses"]["200"] == _json_response("Success")
    assert operation["responses"]["201"] == _json_response("Created")
    assert (
        operation["responses"]["200"]["content"]["application/json"]["schema"]
        is not operation["responses"]["201"]["content"]["application/json"]["schema"]
    )


def test_operation_defaults_to_single_success_status() -> None:
    operation = _operation(
        "/api/v1/widgets", "post", source="aragora/example.py", tag="Widgets", success_status="201"
    )

    assert operation["responses"] == {"201": _json_response("Created")}


def test_routes_apply_extra_statuses_only_to_the_named_operation() -> None:
    routes = _routes(
        "aragora/example.py",
        "Widgets",
        (("/api/widgets/{type}", ("get", "put"), "200", False),),
        extra_success_statuses={("/api/widgets/{type}", "put"): ("201",)},
    )

    assert list(routes["/api/widgets/{type}"]["put"]["responses"]) == ["200", "201"]
    assert list(routes["/api/widgets/{type}"]["get"]["responses"]) == ["200"]


def test_routes_reject_extra_statuses_for_undeclared_operations() -> None:
    with pytest.raises(ValueError, match="/api/widgets/{type}"):
        _routes(
            "aragora/example.py",
            "Widgets",
            (("/api/widgets/{type}", ("get",), "200", False),),
            extra_success_statuses={("/api/widgets/{type}", "put"): ("201",)},
        )


def test_integration_put_documents_create_and_update_statuses() -> None:
    methods = WIRED_REGISTRATION_ENDPOINTS["/api/integrations/{type}"]

    assert list(methods["put"]["responses"]) == ["200", "201"]
    assert methods["put"]["responses"]["201"] == _json_response("Created")
    for method in ("delete", "get", "patch"):
        assert list(methods[method]["responses"]) == ["200"]


def _subscript_chain(node: ast.expr) -> tuple[ast.expr, list[ast.expr]]:
    keys: list[ast.expr] = []
    while isinstance(node, ast.Subscript):
        keys.append(node.slice)
        node = node.value
    return node, keys


def _post_construction_writes(tree: ast.Module) -> list[ast.expr]:
    """Subscript targets and dict-mutation receivers written outside function bodies."""
    writes: list[ast.expr] = []
    pending: list[ast.AST] = list(tree.body)
    while pending:
        node = pending.pop()
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda, ast.ClassDef)):
            continue
        if isinstance(node, (ast.Assign, ast.Delete)):
            writes.extend(t for t in node.targets if isinstance(t, ast.Subscript))
        elif isinstance(node, (ast.AugAssign, ast.AnnAssign)) and isinstance(
            node.target, ast.Subscript
        ):
            writes.append(node.target)
        elif (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr in _MUTATING_DICT_METHODS
            and isinstance(node.func.value, ast.Subscript)
        ):
            writes.append(node.func.value)
        pending.extend(ast.iter_child_nodes(node))
    return writes


def test_wired_registrations_has_no_post_construction_response_surgery() -> None:
    writes = _post_construction_writes(ast.parse(_MODULE_PATH.read_text()))

    response_surgery = [
        ast.unparse(target)
        for target in writes
        if any(
            isinstance(key, ast.Constant) and key.value == "responses"
            for key in _subscript_chain(target)[1]
        )
    ]
    assert response_surgery == [], (
        "declare response statuses through _routes(..., extra_success_statuses=...) "
        f"instead of mutating built operations: {response_surgery}"
    )

    endpoint_writes = {
        ast.unparse(target)
        for target in writes
        if isinstance(root := _subscript_chain(target)[0], ast.Name) and root.id == _ENDPOINTS_NAME
    }
    assert endpoint_writes <= _ALLOWED_POST_CONSTRUCTION_WRITES, (
        f"unexpected post-construction writes: {endpoint_writes - _ALLOWED_POST_CONSTRUCTION_WRITES}"
    )
