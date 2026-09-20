"""Static guards for deploy/Dockerfile.backend.

The runtime stage copies the builder's user-site packages to
``/home/aragora/.local`` while the runtime user's HOME is ``/app`` (issue
#9955). Python resolves the user site from HOME unless ``PYTHONUSERBASE`` is
set, so without it every entrypoint fails at import time. These tests pin
the invariant without needing Docker: the copied ``.local`` parent must be
what ``PYTHONUSERBASE`` points at, and its ``bin`` must be on PATH.
"""

from __future__ import annotations

import re
from pathlib import Path

DOCKERFILE = Path(__file__).resolve().parents[2] / "deploy" / "Dockerfile.backend"


def _dockerfile() -> str:
    return DOCKERFILE.read_text(encoding="utf-8")


def _copied_local_dir(text: str) -> str:
    match = re.search(r"^COPY --from=builder /root/\.local (\S+)$", text, re.MULTILINE)
    assert match, "runtime stage no longer copies the builder user site; update this test"
    return match.group(1)


def test_pythonuserbase_matches_copied_user_site() -> None:
    text = _dockerfile()
    local_dir = _copied_local_dir(text)
    match = re.search(r"^ENV PYTHONUSERBASE=(\S+)$", text, re.MULTILINE)
    assert match, "PYTHONUSERBASE must be set so the copied user site is importable (#9955)"
    assert match.group(1) == local_dir


def test_copied_user_site_bin_is_on_path() -> None:
    text = _dockerfile()
    local_dir = _copied_local_dir(text)
    assert re.search(rf"^ENV PATH={re.escape(local_dir)}/bin:\$PATH$", text, re.MULTILINE)


def test_runtime_user_home_differs_from_user_site_so_the_guard_is_needed() -> None:
    """Documents why PYTHONUSERBASE is required rather than incidental."""
    text = _dockerfile()
    match = re.search(
        r"^RUN groupadd -r aragora && useradd .*-d (\S+) .*aragora$", text, re.MULTILINE
    )
    assert match, "runtime user creation line changed; re-check the user-site assumption"
    home = match.group(1)
    local_dir = _copied_local_dir(text)
    if home == str(Path(local_dir).parent):
        # If HOME ever equals the copied tree's parent, PYTHONUSERBASE becomes
        # redundant; keep it anyway (harmless) but this assertion documents intent.
        return
    assert "ENV PYTHONUSERBASE=" in text
