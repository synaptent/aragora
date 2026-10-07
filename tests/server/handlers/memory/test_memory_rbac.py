"""
RBAC Verification Tests for Memory Handlers.

Ensures all memory handler endpoints are protected with appropriate permissions.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest


# Memory handler module paths
MEMORY_HANDLER_DIR = (
    Path(__file__).parent.parent.parent.parent.parent / "aragora" / "server" / "handlers" / "memory"
)

# These relocated handlers retain their existing entrypoint-level RBAC contracts.
# The package-native handlers below still require SecureHandler and memory:*.
RELOCATED_HANDLERS = {
    "checkpoints.py": ("CheckpointHandler", {"handle": "checkpoints:read"}),
    "consensus.py": (
        "ConsensusHandler",
        {"handle": "consensus:write", "handle_post": "consensus:write"},
    ),
    "memory_unified.py": (
        "MemoryUnifiedHandler",
        {"handle_get": "memory:read", "handle_post": "memory:write"},
    ),
}


def _native_handler_files() -> list[Path]:
    return [
        path
        for path in MEMORY_HANDLER_DIR.glob("*.py")
        if not path.name.startswith("_") and path.name not in RELOCATED_HANDLERS
    ]


@pytest.mark.parametrize("filename", RELOCATED_HANDLERS)
def test_relocated_handlers_retain_entrypoint_permissions(filename: str) -> None:
    """Moving a handler must not remove its existing permission checks."""
    class_name, permissions = RELOCATED_HANDLERS[filename]
    tree = ast.parse((MEMORY_HANDLER_DIR / filename).read_text())
    handler = next(
        node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == class_name
    )
    assert any(isinstance(base, ast.Name) and base.id == "BaseHandler" for base in handler.bases)
    methods = {
        node.name: node
        for node in handler.body
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef)
    }
    for method, permission in permissions.items():
        calls = [node for node in ast.walk(methods[method]) if isinstance(node, ast.Call)]
        assert any(
            (
                isinstance(call.func, ast.Name)
                and call.func.id == "require_permission"
                or isinstance(call.func, ast.Attribute)
                and call.func.attr == "require_permission_or_error"
            )
            and any(isinstance(arg, ast.Constant) and arg.value == permission for arg in call.args)
            for call in calls
        ), f"{class_name}.{method} must retain {permission}"


class TestMemoryHandlerRBACCoverage:
    """Verify all memory handlers have RBAC protection."""

    def test_all_handlers_extend_secure_handler(self) -> None:
        """All memory handlers should extend SecureHandler."""
        for py_file in _native_handler_files():
            if py_file.name.startswith("_") or py_file.name == "__init__.py":
                continue

            source = py_file.read_text()
            tree = ast.parse(source, filename=str(py_file))

            # Find handler classes
            for node in ast.walk(tree):
                if isinstance(node, ast.ClassDef) and node.name.endswith("Handler"):
                    # Check if it extends SecureHandler
                    base_names = []
                    for base in node.bases:
                        if isinstance(base, ast.Name):
                            base_names.append(base.id)
                        elif isinstance(base, ast.Attribute):
                            base_names.append(base.attr)

                    assert "SecureHandler" in base_names, (
                        f"{py_file.name}:{node.lineno} - {node.name} should extend SecureHandler"
                    )

    def test_handlers_import_require_permission(self) -> None:
        """All memory handlers should import require_permission decorator."""
        for py_file in _native_handler_files():
            if py_file.name.startswith("_") or py_file.name == "__init__.py":
                continue

            source = py_file.read_text()

            assert "require_permission" in source, (
                f"{py_file.name} should import require_permission decorator"
            )

    def test_handlers_define_permission_constants(self) -> None:
        """All memory handlers should define permission constants."""
        for py_file in _native_handler_files():
            if py_file.name.startswith("_") or py_file.name == "__init__.py":
                continue

            source = py_file.read_text()

            # Should have at least a read permission
            assert "PERMISSION" in source or '"memory:' in source or "'memory:" in source, (
                f"{py_file.name} should define permission constants"
            )

    def test_endpoint_methods_have_require_permission(self) -> None:
        """Endpoint methods that access data should have @require_permission."""
        endpoint_prefixes = ("get_", "retrieve_", "list_", "search_")

        for py_file in _native_handler_files():
            if py_file.name.startswith("_") or py_file.name == "__init__.py":
                continue

            source = py_file.read_text()
            tree = ast.parse(source, filename=str(py_file))

            for node in ast.walk(tree):
                if isinstance(node, ast.ClassDef) and node.name.endswith("Handler"):
                    for child in node.body:
                        if isinstance(child, ast.FunctionDef | ast.AsyncFunctionDef):
                            # Check if it's a data-accessing method
                            is_data_method = any(
                                child.name.startswith(prefix) for prefix in endpoint_prefixes
                            )
                            if is_data_method:
                                # Check for @require_permission decorator
                                has_permission_decorator = any(
                                    self._is_require_permission_decorator(d)
                                    for d in child.decorator_list
                                )
                                assert has_permission_decorator, (
                                    f"{py_file.name}:{child.lineno} - "
                                    f"{node.name}.{child.name}() needs @require_permission"
                                )

    def _is_require_permission_decorator(self, decorator: ast.expr) -> bool:
        """Check if a decorator is @require_permission."""
        if isinstance(decorator, ast.Name):
            return decorator.id == "require_permission"
        if isinstance(decorator, ast.Call):
            if isinstance(decorator.func, ast.Name):
                return decorator.func.id == "require_permission"
            if isinstance(decorator.func, ast.Attribute):
                return decorator.func.attr == "require_permission"
        return False


class TestMemoryPermissionConsistency:
    """Verify consistent permission naming across memory handlers."""

    def test_memory_read_permission_consistent(self) -> None:
        """memory:read permission should be used consistently."""
        for py_file in _native_handler_files():
            if py_file.name.startswith("_") or py_file.name == "__init__.py":
                continue

            source = py_file.read_text()

            # Should use "memory:read" not variations
            if "memory:" in source and "read" in source.lower():
                assert (
                    '"memory:read"' in source
                    or "'memory:read'" in source
                    or "MEMORY_READ" in source
                ), f"{py_file.name} should use consistent memory:read permission"

    def test_memory_write_permission_consistent(self) -> None:
        """memory:write permission should be used consistently for mutations."""
        # Only check files that have actual mutation endpoints (DELETE, POST that modifies)
        # Look for specific patterns like "DELETE /" or "def delete_" that indicate mutations
        mutation_patterns = [
            "delete /",  # DELETE endpoint
            "def delete_",  # Delete method
            "/consolidate",  # Consolidation endpoint
            "/cleanup",  # Cleanup endpoint
        ]

        for py_file in _native_handler_files():
            if py_file.name.startswith("_") or py_file.name == "__init__.py":
                continue

            source = py_file.read_text().lower()

            # If file has mutation endpoints, should have write permission
            has_mutations = any(pattern in source for pattern in mutation_patterns)
            if has_mutations:
                assert "memory:write" in source or "memory_write" in source, (
                    f"{py_file.name} has mutation endpoints but no memory:write permission"
                )
