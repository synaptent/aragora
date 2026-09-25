"""Catalog imports must not initialize the separate workflow template store."""

from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
import textwrap

import pytest


ROOT = Path(__file__).resolve().parents[2]

# An editable install of aragora and any cwd entry on sys.path can bind a fresh
# probe to a different checkout, which would silently grade the wrong tree.
_BIND_TO_TREE_UNDER_TEST = """
import importlib.util as _importlib_util
import os as _os
from pathlib import Path as _Path

_expected_root = _Path(_os.environ["ARAGORA_IMPORT_ROOT"]).resolve()
_spec = _importlib_util.find_spec("aragora")
assert _spec is not None and _spec.origin is not None, "aragora is not importable"
assert _Path(_spec.origin).resolve().parents[1] == _expected_root, _spec.origin
"""

HANDLERS = [
    ("playbooks", "PlaybookHandler", "analytics"),
    ("workflow_templates", "WorkflowTemplatesHandler", "admin"),
    ("workflow_templates", "WorkflowCategoriesHandler", "admin"),
    ("workflow_templates", "WorkflowPatternsHandler", "admin"),
    ("workflow_templates", "WorkflowPatternTemplatesHandler", "admin"),
    ("workflow_templates", "TemplateRecommendationsHandler", ""),
    ("workflow_templates", "SMEWorkflowsHandler", "admin"),
]


def _probe(tmp_path: Path, script: str, *args: str) -> dict:
    # No inherited credentials/configuration, and no repository .env discovery.
    env = {
        "HOME": str(tmp_path),
        "TMPDIR": str(tmp_path),
        "PATH": "/usr/bin:/bin",
        "PYTHONPATH": str(ROOT),
        "ARAGORA_IMPORT_ROOT": str(ROOT),
        "PYTHONDONTWRITEBYTECODE": "1",
        "ARAGORA_DATA_DIR": str(tmp_path),
        "ARAGORA_WORKFLOW_DB": str(tmp_path / "workflows.db"),
        "ARAGORA_STORAGE_BACKEND": "sqlite",
        "ARAGORA_ENV": "development",
        "ARAGORA_SECRETS_STRICT": "false",
        "ARAGORA_USE_SECRETS_MANAGER": "false",
        "AWS_CONFIG_FILE": "/dev/null",
        "AWS_SHARED_CREDENTIALS_FILE": "/dev/null",
        "AWS_EC2_METADATA_DISABLED": "true",
    }
    result = subprocess.run(
        [
            sys.executable,
            "-B",
            "-c",
            _BIND_TO_TREE_UNDER_TEST + textwrap.dedent(script),
            *args,
        ],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    return json.loads(result.stdout)


@pytest.mark.parametrize("module,name,registry", HANDLERS)
@pytest.mark.parametrize("entrypoint", ["canonical", "legacy", "public", "registry"])
def test_catalog_imports_are_store_inert(tmp_path, module, name, registry, entrypoint):
    result = _probe(
        tmp_path,
        """
        import importlib
        import json
        import os
        from pathlib import Path
        import sqlite3
        import sys
        import warnings

        module, name, registry, entrypoint = sys.argv[1:]
        db = Path(os.environ["ARAGORA_WORKFLOW_DB"])
        connect = sqlite3.connect
        connect(db).close()
        before = db.read_bytes()
        connections = []

        def readonly_connect(database, *args, **kwargs):
            # Only the disposable workflow DB may be opened by this probe.
            assert Path(database).resolve() == db.resolve(), database
            connections.append(str(database))
            kwargs["uri"] = True
            return connect(db.as_uri() + "?mode=ro", *args, **kwargs)

        sqlite3.connect = readonly_connect
        prefix = "aragora.server.handlers."
        canonical = prefix + "catalog." + module
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always", DeprecationWarning)
            handlers = importlib.import_module(prefix[:-1])
            if entrypoint == "canonical":
                target = importlib.import_module(handlers.HANDLER_MODULES[name])
                cls = getattr(target, name)
            elif entrypoint == "legacy":
                cls = getattr(importlib.import_module(prefix + module), name)
            elif entrypoint == "public":
                cls = getattr(handlers, name)
            else:
                if registry:
                    refs = importlib.import_module("aragora.server.handler_registry." + registry)
                    ref = getattr(refs, name)
                else:
                    # This public class has no dedicated registry row; the existing
                    # admin row of the same name belongs to template_marketplace.
                    from aragora.server.handler_registry.core import _safe_import
                    ref = _safe_import(handlers.HANDLER_MODULES[name], name)
                cls = ref.resolve()
        assert cls is not None
        assert cls.__module__ == canonical
        assert handlers.HANDLER_MODULES[name] == canonical
        assert cls is getattr(importlib.import_module(canonical), name)
        store = sys.modules.get("aragora.workflow.persistent_store")
        assert getattr(store, "_workflow_store_instance", None) is None
        assert prefix + "workflows" not in sys.modules
        assert connections == []
        assert db.read_bytes() == before
        relevant = [str(w.message) for w in caught
                    if issubclass(w.category, DeprecationWarning)
                    and str(w.message).startswith(prefix)]
        if entrypoint == "legacy":
            assert any(prefix + module in warning for warning in relevant), relevant
        else:
            assert relevant == [], relevant
        print(json.dumps({"name": cls.__name__, "connections": connections}))
        """,
        module,
        name,
        registry,
        entrypoint,
    )
    assert result == {"name": name, "connections": []}


def test_explicit_workflow_templates_initialize_writable_store(tmp_path):
    result = _probe(
        tmp_path,
        """
        import asyncio
        import json
        import os
        from pathlib import Path
        import sqlite3

        db = Path(os.environ["ARAGORA_WORKFLOW_DB"])
        assert not db.exists()
        from aragora.server.handlers.workflows import list_templates
        from aragora.workflow.persistent_store import get_workflow_store

        templates = asyncio.run(list_templates())
        builtin = {"template_contract_review", "template_code_review"}
        assert builtin <= {template["id"] for template in templates}
        assert get_workflow_store()._db_path.resolve() == db.resolve()
        with sqlite3.connect(db) as connection:
            persisted = {row[0] for row in connection.execute("SELECT id FROM workflow_templates")}
        assert builtin <= persisted
        print(json.dumps({"builtins": sorted(builtin), "persisted": len(persisted)}))
        """,
    )
    assert result["builtins"] == ["template_code_review", "template_contract_review"]
    assert result["persisted"] >= 2
