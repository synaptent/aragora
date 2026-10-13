"""Structural regression tests for the webhook handler package."""

from __future__ import annotations

import ast
import json
import os
from pathlib import Path
import subprocess
import sys
import textwrap
import warnings


REPO_ROOT = Path(__file__).resolve().parents[2]
PACKAGE_NAME = "aragora.server.handlers.webhooks"
CANONICAL_MODULE_NAME = "aragora.server.handlers.webhook_management"

EXPECTED_SHIM_WARNING = (
    "aragora.server.handlers.webhooks is deprecated as the webhook management "
    "implementation home; import WebhookHandler from "
    "aragora.server.handlers.webhook_management instead."
)

EXPECTED_EXPORTS = [
    "GITHUB_APP_ROUTES",
    "handle_github_webhook",
    "WebhookHandler",
    "WebhookStore",
    "WebhookConfig",
    "get_webhook_store",
    "generate_signature",
    "verify_signature",
    "WEBHOOK_EVENTS",
    "RBAC_AVAILABLE",
    "check_permission",
    "validate_webhook_url",
]

# Only the package's canonical residents stay eagerly bound; the management
# re-exports resolve through the deprecation shim on attribute access.
EXPECTED_PUBLIC_NAMES = [
    "GITHUB_APP_ROUTES",
    "github_app",
    "handle_github_webhook",
    "importlib",
]

EXPECTED_ROUTES = [
    "POST /api/webhooks",
    "GET /api/webhooks",
    "GET /api/webhooks/events",
    "GET /api/webhooks/slo/status",
    "POST /api/webhooks/slo/test",
    "GET /api/webhooks/:id",
    "DELETE /api/webhooks/:id",
    "PATCH /api/webhooks/:id",
    "POST /api/webhooks/:id/test",
    "GET /api/webhooks/dead-letter",
    "GET /api/webhooks/dead-letter/:id",
    "POST /api/webhooks/dead-letter/:id/retry",
    "DELETE /api/webhooks/dead-letter/:id",
    "GET /api/webhooks/queue/stats",
]

EXPECTED_V1_ROUTES = [
    "/api/v1/webhooks",
    "/api/v1/webhooks/events",
    "/api/v1/webhooks/events/categories",
    "/api/v1/webhooks/slo/status",
    "/api/v1/webhooks/slo/test",
    "/api/v1/webhooks/dead-letter",
    "/api/v1/webhooks/queue/stats",
    "/api/v1/webhooks/bulk",
    "/api/v1/webhooks/pause-all",
    "/api/v1/webhooks/resume-all",
]


def _run_import_probe() -> dict[str, object]:
    script = textwrap.dedent(
        """
        import importlib
        import importlib.machinery
        import importlib.util
        import json
        from pathlib import Path
        import sys
        import warnings

        root = Path(sys.argv[1])
        legacy_file = root / "aragora/server/handlers/webhooks.py"
        canonical_file = root / "aragora/server/handlers/webhook_management.py"
        implementation_paths = {
            path.resolve() for path in (legacy_file, canonical_file) if path.exists()
        }
        execution_count = 0
        original_exec_module = importlib.machinery.SourceFileLoader.exec_module

        def counted_exec_module(loader, module):
            global execution_count
            if Path(loader.path).resolve() in implementation_paths:
                execution_count += 1
            return original_exec_module(loader, module)

        importlib.machinery.SourceFileLoader.exec_module = counted_exec_module
        legacy_module = None
        try:
            with warnings.catch_warnings(record=True) as caught:
                warnings.simplefilter("always", DeprecationWarning)
                if legacy_file.exists():
                    spec = importlib.util.spec_from_file_location(
                        "aragora.server.handlers.webhooks",
                        legacy_file,
                    )
                    assert spec is not None and spec.loader is not None
                    legacy_module = importlib.util.module_from_spec(spec)
                    spec.loader.exec_module(legacy_module)

                package = importlib.import_module("aragora.server.handlers.webhooks")
                try:
                    implementation = importlib.import_module(
                        "aragora.server.handlers.webhook_management"
                    )
                except ModuleNotFoundError:
                    implementation = package._webhooks_module
        finally:
            importlib.machinery.SourceFileLoader.exec_module = original_exec_module

        relevant_warnings = [
            str(item.message)
            for item in caught
            if issubclass(item.category, DeprecationWarning)
            and str(item.message).startswith(
                "aragora.server.handlers.webhooks"
            )
        ]
        print(json.dumps({
            "execution_count": execution_count,
            "handler_module": package.WebhookHandler.__module__,
            "implementation_name": implementation.__name__,
            "legacy_file_exists": legacy_file.exists(),
            "legacy_handler_is_package_handler": (
                None
                if legacy_module is None
                else legacy_module.WebhookHandler is package.WebhookHandler
            ),
            "package_handler_is_implementation": (
                package.WebhookHandler is implementation.WebhookHandler
            ),
            "compat_module_alias_is_implementation": (
                package._webhooks_module is implementation
            ),
            "relevant_warning_count": len(relevant_warnings),
            "webhooks_module_registered": "webhooks_module" in sys.modules,
        }, sort_keys=True))
        """
    )
    env = os.environ.copy()
    env.update(
        {
            "ARAGORA_SECRETS_STRICT": "false",
            "AWS_CONFIG_FILE": "/dev/null",
            "AWS_EC2_METADATA_DISABLED": "true",
            "AWS_SHARED_CREDENTIALS_FILE": "/dev/null",
            "PYTHONPATH": str(REPO_ROOT),
        }
    )
    result = subprocess.run(
        [sys.executable, "-c", script, str(REPO_ROOT)],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


def test_webhook_implementation_executes_once_under_canonical_identity() -> None:
    """The implementation has one source path, module identity, and class object."""
    probe = _run_import_probe()

    assert probe == {
        "compat_module_alias_is_implementation": True,
        "execution_count": 1,
        "handler_module": "aragora.server.handlers.webhook_management",
        "implementation_name": "aragora.server.handlers.webhook_management",
        "legacy_file_exists": False,
        "legacy_handler_is_package_handler": None,
        "package_handler_is_implementation": True,
        "relevant_warning_count": 0,
        "webhooks_module_registered": False,
    }


def test_lazy_handler_registry_resolves_webhook_handler_without_warnings() -> None:
    """The registry resolves WebhookHandler canonically without touching the shim."""
    script = textwrap.dedent(
        """
        import importlib
        import json
        import sys
        import warnings

        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always", DeprecationWarning)
            handlers = importlib.import_module("aragora.server.handlers")
            handler_cls = handlers.WebhookHandler

        relevant = [
            str(item.message)
            for item in caught
            if issubclass(item.category, DeprecationWarning)
            and str(item.message).startswith("aragora.server.handlers.webhooks")
        ]
        print(json.dumps({
            "handler_module": handler_cls.__module__,
            "registered_target": handlers.HANDLER_MODULES["WebhookHandler"],
            "relevant_warnings": relevant,
            "shim_imported": "aragora.server.handlers.webhooks" in sys.modules,
        }, sort_keys=True))
        """
    )
    env = os.environ.copy()
    env.update(
        {
            "ARAGORA_SECRETS_STRICT": "false",
            "AWS_CONFIG_FILE": "/dev/null",
            "AWS_EC2_METADATA_DISABLED": "true",
            "AWS_SHARED_CREDENTIALS_FILE": "/dev/null",
            "PYTHONPATH": str(REPO_ROOT),
        }
    )
    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == {
        "handler_module": CANONICAL_MODULE_NAME,
        "registered_target": CANONICAL_MODULE_NAME,
        "relevant_warnings": [],
        "shim_imported": False,
    }


def test_canonical_module_is_silent_and_package_shim_warns() -> None:
    """Canonical and package imports are silent; only retired attribute access warns."""
    script = textwrap.dedent(
        """
        import importlib
        import json
        import warnings

        with warnings.catch_warnings(record=True) as canonical_warnings:
            warnings.simplefilter("always", DeprecationWarning)
            canonical = importlib.import_module(
                "aragora.server.handlers.webhook_management"
            )
        with warnings.catch_warnings(record=True) as package_warnings:
            warnings.simplefilter("always", DeprecationWarning)
            github_app = importlib.import_module(
                "aragora.server.handlers.webhooks.github_app"
            )
            shim = importlib.import_module("aragora.server.handlers.webhooks")
        with warnings.catch_warnings(record=True) as attribute_warnings:
            warnings.simplefilter("always", DeprecationWarning)
            handler = shim.WebhookHandler

        def relevant(items):
            return [
                str(item.message)
                for item in items
                if issubclass(item.category, DeprecationWarning)
                and str(item.message).startswith("aragora.server.handlers.webhooks")
            ]

        print(json.dumps({
            "attribute_warnings": relevant(attribute_warnings),
            "canonical_warnings": relevant(canonical_warnings),
            "github_app_routes_exported": bool(github_app.GITHUB_APP_ROUTES),
            "package_warnings": relevant(package_warnings),
            "shim_handler_is_canonical": handler is canonical.WebhookHandler,
        }, sort_keys=True))
        """
    )
    env = os.environ.copy()
    env.update(
        {
            "ARAGORA_SECRETS_STRICT": "false",
            "AWS_CONFIG_FILE": "/dev/null",
            "AWS_EC2_METADATA_DISABLED": "true",
            "AWS_SHARED_CREDENTIALS_FILE": "/dev/null",
            "PYTHONPATH": str(REPO_ROOT),
        }
    )
    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == {
        "attribute_warnings": [EXPECTED_SHIM_WARNING],
        "canonical_warnings": [],
        "github_app_routes_exported": True,
        "package_warnings": [],
        "shim_handler_is_canonical": True,
    }


def test_webhook_routes_registration_and_public_surface_match_baseline() -> None:
    """The structural move preserves exports, route tables, and registration order."""
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", DeprecationWarning)
        module = __import__(PACKAGE_NAME, fromlist=["WebhookHandler"])
        webhook_handler_cls = module.WebhookHandler
        from aragora.server.handler_registry.admin import ADMIN_HANDLER_REGISTRY
        from aragora.server.handlers._lazy_imports import ALL_HANDLER_NAMES, HANDLER_MODULES

    assert module.__all__ == EXPECTED_EXPORTS
    assert (
        sorted(name for name in vars(module) if not name.startswith("_")) == EXPECTED_PUBLIC_NAMES
    )
    assert webhook_handler_cls.routes == EXPECTED_ROUTES
    assert webhook_handler_cls.ROUTES == EXPECTED_V1_ROUTES

    assert HANDLER_MODULES["WebhookHandler"] == CANONICAL_MODULE_NAME
    lazy_names = list(ALL_HANDLER_NAMES)
    lazy_index = lazy_names.index("WebhookHandler")
    assert lazy_names[lazy_index - 3 : lazy_index + 4] == [
        "FormalVerificationHandler",
        "SlackHandler",
        "EvidenceHandler",
        "WebhookHandler",
        "CodebaseAuditHandler",
        "AdminHandler",
        "SecurityHandler",
    ]

    registry_names = [name for name, _ in ADMIN_HANDLER_REGISTRY]
    registry_index = registry_names.index("_webhook_handler")
    assert registry_names[registry_index - 3 : registry_index + 4] == [
        "_integration_health_handler",
        "_automation_handler",
        "_workflow_handler",
        "_webhook_handler",
        "_queue_handler",
        "_workflow_templates_handler",
        "_workflow_patterns_handler",
    ]
    registry_entry = dict(ADMIN_HANDLER_REGISTRY)["_webhook_handler"]
    assert getattr(registry_entry, "resolve")() is webhook_handler_cls


def test_delivery_and_retry_consumers_import_canonically_without_warnings() -> None:
    """Delivery/retry consumer from-imports target the canonical module silently."""
    script = textwrap.dedent(
        """
        import ast
        import json
        from pathlib import Path
        import sys
        import warnings

        root = Path(sys.argv[1])
        consumer_files = json.loads(sys.argv[2])
        deprecated = "aragora.server.handlers.webhooks"
        canonical = "aragora.server.handlers.webhook_management"

        webhook_imports = []
        for rel_path in consumer_files:
            tree = ast.parse((root / rel_path).read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if isinstance(node, ast.ImportFrom) and node.module in {deprecated, canonical}:
                    webhook_imports.append(
                        (rel_path, node.module, [alias.name for alias in node.names])
                    )

        resolved_homes = set()
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always", DeprecationWarning)
            for _, module_name, names in webhook_imports:
                module = __import__(module_name, fromlist=names)
                for name in names:
                    resolved_homes.add(getattr(module, name).__module__)

        relevant = [
            str(item.message)
            for item in caught
            if issubclass(item.category, DeprecationWarning)
            and str(item.message).startswith(deprecated)
        ]
        print(json.dumps({
            "deprecated_import_sites": sorted(
                {path for path, module_name, _ in webhook_imports if module_name == deprecated}
            ),
            "import_site_count": len(webhook_imports),
            "relevant_warnings": relevant,
            "resolved_homes": sorted(resolved_homes),
            "shim_imported": deprecated in sys.modules,
        }, sort_keys=True))
        """
    )
    consumer_files = [
        "aragora/server/event_subscribers.py",
        "aragora/webhooks/retry_queue.py",
    ]
    env = os.environ.copy()
    env.update(
        {
            "ARAGORA_SECRETS_STRICT": "false",
            "AWS_CONFIG_FILE": "/dev/null",
            "AWS_EC2_METADATA_DISABLED": "true",
            "AWS_SHARED_CREDENTIALS_FILE": "/dev/null",
            "PYTHONPATH": str(REPO_ROOT),
        }
    )
    result = subprocess.run(
        [sys.executable, "-c", script, str(REPO_ROOT), json.dumps(consumer_files)],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    # The retry queue signs via aragora.security.webhook_signing (probed
    # separately below), so only the event-subscriber store import remains.
    assert json.loads(result.stdout) == {
        "deprecated_import_sites": [],
        "import_site_count": 1,
        "relevant_warnings": [],
        "resolved_homes": [CANONICAL_MODULE_NAME],
        "shim_imported": False,
    }


def test_type_checking_webhook_handler_import_targets_canonical_module() -> None:
    """The handlers package type-checking import names the real class home."""
    source = (REPO_ROOT / "aragora/server/handlers/__init__.py").read_text(encoding="utf-8")
    webhook_handler_imports = [
        node.module
        for node in ast.walk(ast.parse(source))
        if isinstance(node, ast.ImportFrom)
        and node.level == 1
        and any(alias.name == "WebhookHandler" for alias in node.names)
    ]
    assert webhook_handler_imports == ["webhook_management"]


def test_package_shim_has_no_dynamic_file_loader() -> None:
    """The compatibility package uses a normal canonical import, not exec loading."""
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", DeprecationWarning)
        package = __import__(PACKAGE_NAME, fromlist=["_webhooks_module"])

    module_file = package.__file__
    assert module_file is not None
    source = Path(module_file).read_text(encoding="utf-8")
    assert "spec_from_file_location" not in source
    assert "module_from_spec" not in source
    assert "exec_module" not in source
    assert package._webhooks_module.__name__ == "aragora.server.handlers.webhook_management"


def test_retry_queue_signs_via_security_layer_without_call_time_warnings() -> None:
    """Retry-queue signing resolves AND CALLS the security-layer signer silently.

    The webhook_management.generate_signature wrapper warns on every call, so a
    delivery path that imports it stays noisy even when the import itself is
    warning-free. This probe pins the retry queue's signer imports to the
    security layer and proves the resolved callable is silent at call time.
    """
    script = textwrap.dedent(
        """
        import ast
        import json
        from pathlib import Path
        import sys
        import warnings

        root = Path(sys.argv[1])
        rel_path = "aragora/webhooks/retry_queue.py"
        server_prefix = "aragora.server.handlers."

        signer_imports = []
        tree = ast.parse((root / rel_path).read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and any(
                alias.name == "generate_signature" for alias in node.names
            ):
                signer_imports.append(node.module)

        expected_signature = (
            "sha256=b82fcb791acec57859b989b430a826488ce2e479fdf92326bd0a2e8375a42ba4"
        )
        call_results = []
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always", DeprecationWarning)
            for module_name in signer_imports:
                module = __import__(module_name, fromlist=["generate_signature"])
                signer = getattr(module, "generate_signature")
                call_results.append(signer("payload", "secret") == expected_signature)

        relevant = [
            str(item.message)
            for item in caught
            if issubclass(item.category, DeprecationWarning)
        ]
        print(json.dumps({
            "call_results": call_results,
            "call_time_warnings": relevant,
            "server_modules_loaded": sorted(
                name for name in sys.modules if name.startswith(server_prefix)
            ),
            "signer_import_modules": sorted(set(signer_imports)),
            "signer_import_site_count": len(signer_imports),
        }, sort_keys=True))
        """
    )
    env = os.environ.copy()
    env.update(
        {
            "ARAGORA_SECRETS_STRICT": "false",
            "AWS_CONFIG_FILE": "/dev/null",
            "AWS_EC2_METADATA_DISABLED": "true",
            "AWS_SHARED_CREDENTIALS_FILE": "/dev/null",
            "PYTHONPATH": str(REPO_ROOT),
        }
    )
    result = subprocess.run(
        [sys.executable, "-c", script, str(REPO_ROOT)],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == {
        "call_results": [True, True],
        "call_time_warnings": [],
        "server_modules_loaded": [],
        "signer_import_modules": ["aragora.security.webhook_signing"],
        "signer_import_site_count": 2,
    }


def test_webhook_suite_patch_targets_bypass_the_deprecation_shim() -> None:
    """@patch targets in the handler test suite name the canonical module.

    Patching the shim package attribute is a decoy: the implementation reads
    its own module globals, so a shim-path patch never intercepts anything.
    """
    suite_path = REPO_ROOT / "tests/server/handlers/test_webhooks.py"
    tree = ast.parse(suite_path.read_text(encoding="utf-8"))

    patch_targets = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        func_name = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", None)
        if func_name != "patch":
            continue
        if (
            node.args
            and isinstance(node.args[0], ast.Constant)
            and isinstance(node.args[0].value, str)
        ):
            patch_targets.append(node.args[0].value)

    shim_targets = [
        target for target in patch_targets if target.startswith("aragora.server.handlers.webhooks.")
    ]
    canonical_targets = [
        target
        for target in patch_targets
        if target.startswith("aragora.server.handlers.webhook_management.")
    ]
    assert shim_targets == []
    assert len(canonical_targets) >= 8


_SHIM_PARENT_PACKAGE = "aragora.server.handlers"
_NATIVE_SUBMODULE = PACKAGE_NAME + ".github_app"


def _reaches_shim_module(target: str) -> bool:
    """True when a dotted path lands on the shim rather than the canonical
    github_app subpackage that happens to live inside it."""
    if target == PACKAGE_NAME:
        return True
    if not target.startswith(PACKAGE_NAME + "."):
        return False
    return target != _NATIVE_SUBMODULE and not target.startswith(_NATIVE_SUBMODULE + ".")


def _call_name(func: ast.expr) -> str | None:
    if isinstance(func, ast.Attribute):
        return func.attr
    if isinstance(func, ast.Name):
        return func.id
    return None


def _static_string_argument(node: ast.Call, keyword: str) -> str | None:
    """First positional argument, else the named keyword, when a string constant."""
    candidate: ast.expr | None = node.args[0] if node.args else None
    if candidate is None:
        candidate = next((kw.value for kw in node.keywords if kw.arg == keyword), None)
    if isinstance(candidate, ast.Constant) and isinstance(candidate.value, str):
        return candidate.value
    return None


def _shim_consumption_offenders(rel_path: str, source: str) -> list[str]:
    """Census one test source for static shim-path consumption records."""
    # Every catchable reach form spells the bare package name somewhere; the
    # full dotted path is too narrow a pre-filter (a parent-package binding
    # never contains it).
    if "webhooks" not in source:
        return []
    try:
        tree = ast.parse(source)
    except SyntaxError:
        # An unparseable file cannot import anything.
        return []
    offenders: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            if node.level != 0 or node.module is None:
                continue
            if _reaches_shim_module(node.module):
                offenders.append(f"{rel_path}:{node.lineno} from-import")
            elif node.module == _SHIM_PARENT_PACKAGE and any(
                alias.name == "webhooks" for alias in node.names
            ):
                offenders.append(f"{rel_path}:{node.lineno} parent-package from-import")
        elif isinstance(node, ast.Import):
            for alias in node.names:
                if _reaches_shim_module(alias.name):
                    offenders.append(f"{rel_path}:{node.lineno} import")
        elif isinstance(node, ast.Call):
            func_name = _call_name(node.func)
            if func_name == "patch":
                target = _static_string_argument(node, "target")
                if target is not None and _reaches_shim_module(target):
                    offenders.append(f"{rel_path}:{node.lineno} patch-target {target}")
            elif func_name == "import_module":
                module_name = _static_string_argument(node, "name")
                if module_name is not None and _reaches_shim_module(module_name):
                    offenders.append(f"{rel_path}:{node.lineno} import-module {module_name}")
    return offenders


def test_shim_path_consumption_is_confined_to_the_designated_shim_test() -> None:
    """Test-tree shim consumption stays intentional and singular.

    The deprecation shim exists for external callers; inside tests/ only this
    file exercises the legacy path (the explicit warn-and-delegate probe in
    test_canonical_module_is_silent_and_package_shim_warns), so any other
    static shim reach - imports (including parent-package bindings), string
    importlib.import_module calls, or patch targets naming the shim - is
    drift, not coverage. The github_app submodule is a canonical package
    resident, not shim surface.
    """
    designated_files = {"tests/handlers/test_webhooks_module_structure.py"}

    offenders: list[str] = []
    for path in sorted((REPO_ROOT / "tests").rglob("*.py")):
        rel_path = path.relative_to(REPO_ROOT).as_posix()
        if rel_path in designated_files:
            continue
        offenders.extend(_shim_consumption_offenders(rel_path, path.read_text(encoding="utf-8")))

    assert offenders == []


def test_census_matcher_flags_parent_package_shim_import() -> None:
    """Binding the shim from its parent package is shim consumption."""
    assert _shim_consumption_offenders(
        "tests/synthetic/test_case.py",
        "from aragora.server.handlers import webhooks\n",
    ) == ["tests/synthetic/test_case.py:1 parent-package from-import"]
    assert _shim_consumption_offenders(
        "tests/synthetic/test_case.py",
        "from aragora.server.handlers import webhooks as legacy_webhooks\n",
    ) == ["tests/synthetic/test_case.py:1 parent-package from-import"]


def test_census_matcher_flags_dynamic_import_module_of_shim() -> None:
    """importlib.import_module string reach of the shim is shim consumption."""
    assert _shim_consumption_offenders(
        "tests/synthetic/test_case.py",
        'import importlib\n\nimportlib.import_module("aragora.server.handlers.webhooks")\n',
    ) == [
        "tests/synthetic/test_case.py:3 import-module aragora.server.handlers.webhooks",
    ]
    assert _shim_consumption_offenders(
        "tests/synthetic/test_case.py",
        (
            "from importlib import import_module\n\n"
            'import_module("aragora.server.handlers.webhooks")\n'
        ),
    ) == [
        "tests/synthetic/test_case.py:3 import-module aragora.server.handlers.webhooks",
    ]


def test_census_matcher_flags_keyword_patch_target_on_shim() -> None:
    """patch(target=...) keyword spelling cannot bypass the census."""
    source = (
        "from unittest.mock import patch\n\n"
        'patch(target="aragora.server.handlers.webhooks.WebhookHandler")\n'
    )
    assert _shim_consumption_offenders("tests/synthetic/test_case.py", source) == [
        "tests/synthetic/test_case.py:3 patch-target "
        "aragora.server.handlers.webhooks.WebhookHandler",
    ]


def test_census_matcher_flags_whole_module_patch_target_of_shim() -> None:
    """Patching the shim module itself (no attribute suffix) is shim reach."""
    source = 'from unittest.mock import patch\n\npatch("aragora.server.handlers.webhooks")\n'
    assert _shim_consumption_offenders("tests/synthetic/test_case.py", source) == [
        "tests/synthetic/test_case.py:3 patch-target aragora.server.handlers.webhooks",
    ]


def test_census_matcher_exempts_suffixless_github_app_patch_target() -> None:
    """github_app is a real subpackage; a whole-module patch of it is not shim reach."""
    source = (
        'from unittest.mock import patch\n\npatch("aragora.server.handlers.webhooks.github_app")\n'
    )
    assert _shim_consumption_offenders("tests/synthetic/test_case.py", source) == []


def test_census_matcher_still_flags_direct_legacy_forms() -> None:
    """The pre-hardening catches stay caught."""
    assert _shim_consumption_offenders(
        "tests/synthetic/test_case.py",
        "import aragora.server.handlers.webhooks\n",
    ) == ["tests/synthetic/test_case.py:1 import"]
    assert _shim_consumption_offenders(
        "tests/synthetic/test_case.py",
        "from aragora.server.handlers.webhooks import WebhookHandler\n",
    ) == ["tests/synthetic/test_case.py:1 from-import"]
    assert _shim_consumption_offenders(
        "tests/synthetic/test_case.py",
        (
            "from unittest.mock import patch\n\n"
            'patch("aragora.server.handlers.webhooks.WebhookHandler")\n'
        ),
    ) == [
        "tests/synthetic/test_case.py:3 patch-target "
        "aragora.server.handlers.webhooks.WebhookHandler",
    ]


def test_census_matcher_exempts_canonical_and_github_app_reach() -> None:
    """Canonical-module and github_app-resident forms never trip the census."""
    for source in (
        "import aragora.server.handlers.webhook_management\n",
        "from aragora.server.handlers import webhook_management\n",
        "from aragora.server.handlers.webhooks.github_app import handle_github_webhook\n",
        "import aragora.server.handlers.webhooks.github_app\n",
        (
            "from unittest.mock import patch\n\n"
            'patch("aragora.server.handlers.webhooks.github_app.queue_code_review_debate")\n'
        ),
        'MESSAGE = "aragora.server.handlers.webhooks is deprecated"\n',
    ):
        assert _shim_consumption_offenders("tests/synthetic/test_case.py", source) == []
