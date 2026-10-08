"""Aragora's weaviate import sites must not mutate process-global warning filters.

weaviate-client's package ``__init__`` calls a bare ``warnings.simplefilter("default")``
(and its transitive imports register further filters), globally rewriting the ambient
warning policy of any process that imports it. Every aragora import site of weaviate
wraps the import in a scoped ``warnings.catch_warnings`` guard so that mutation is
confined to the import itself. These tests pin that invariant per import site.

Each check runs in a fresh subprocess because a package ``__init__`` executes only
once per process. The subprocess first loads the target module with weaviate blocked
(caching every non-weaviate prerequisite import and its own filter side effects),
then re-executes the module body with weaviate importable, so the measured filters
delta is exactly the weaviate-attributable contribution.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]

WEAVIATE_IMPORT_SITES = [
    "aragora.documents.indexing.weaviate_store",
    "aragora.knowledge.embeddings",
    "aragora.knowledge.vector_store",
    "aragora.knowledge.mound.vector_abstraction.weaviate",
]

_SITE_SCRIPT = """\
import importlib
import importlib.util
import sys
import warnings

mod_name = {mod!r}
spec_available = importlib.util.find_spec("weaviate") is not None

# Phase A: load the module with weaviate blocked so every non-weaviate
# prerequisite import (and any filter side effect it carries) is cached first.
sys.modules["weaviate"] = None
module = importlib.import_module(mod_name)
assert module.WEAVIATE_AVAILABLE is False, "weaviate import block did not take"
del sys.modules["weaviate"]
del sys.modules[mod_name]

# Phase B: re-execute the module body; the only fresh imports are weaviate and
# its transitive dependencies, so any filters delta is weaviate-attributable.
before = list(warnings.filters)
before_repr = repr(warnings.filters)
module = importlib.import_module(mod_name)
after = list(warnings.filters)
after_repr = repr(warnings.filters)

if spec_available and not module.WEAVIATE_AVAILABLE:
    print("AVAILABILITY_BROKEN")
    raise SystemExit(4)
if not spec_available:
    print("WEAVIATE_UNAVAILABLE")
    raise SystemExit(0)
if before == after and before_repr == after_repr:
    print("FILTERS_UNCHANGED")
    raise SystemExit(0)
print("FILTERS_MUTATED")
for entry in after:
    if entry not in before:
        print("leaked:", entry)
raise SystemExit(3)
"""

_BARE_IMPORT_SCRIPT = """\
import warnings

before = list(warnings.filters)
try:
    import weaviate  # noqa: F401
except ImportError:
    print("WEAVIATE_UNAVAILABLE")
    raise SystemExit(0)
after = list(warnings.filters)
if before == after:
    print("UPSTREAM_FIXED")
    raise SystemExit(0)
print("FILTERS_MUTATED")
raise SystemExit(3)
"""


def _run_isolated(code: str) -> subprocess.CompletedProcess[str]:
    env = dict(os.environ)
    env.update(
        {
            "PYTHONPATH": str(REPO_ROOT),
            # Importing aragora.server.* without AWS neutralization can trigger
            # botocore credential prompts on some machines.
            "AWS_CONFIG_FILE": "/dev/null",
            "AWS_SHARED_CREDENTIALS_FILE": "/dev/null",
            "AWS_EC2_METADATA_DISABLED": "true",
        }
    )
    return subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        timeout=180,
        env=env,
        cwd=REPO_ROOT,
    )


@pytest.mark.parametrize("site", WEAVIATE_IMPORT_SITES)
def test_import_site_leaves_global_warning_filters_byte_identical(site: str) -> None:
    """Importing an aragora weaviate module leaves warnings.filters untouched."""
    proc = _run_isolated(_SITE_SCRIPT.format(mod=site))
    assert proc.returncode == 0, (
        f"{site} leaked warning-filter mutations (exit {proc.returncode}):\n"
        f"{proc.stdout}{proc.stderr}"
    )
    assert ("FILTERS_UNCHANGED" in proc.stdout) or ("WEAVIATE_UNAVAILABLE" in proc.stdout), (
        f"unexpected subprocess output for {site}:\n{proc.stdout}{proc.stderr}"
    )


def test_bare_weaviate_import_mutates_filters_upstream_control() -> None:
    """Positive control pinning the upstream side effect the guards contain."""
    proc = _run_isolated(_BARE_IMPORT_SCRIPT)
    if "WEAVIATE_UNAVAILABLE" in proc.stdout or "UPSTREAM_FIXED" in proc.stdout:
        # Nothing to contain in this environment; the site guards are inert.
        return
    assert proc.returncode == 3 and "FILTERS_MUTATED" in proc.stdout, (
        f"unexpected bare-import behavior:\n{proc.stdout}{proc.stderr}"
    )
