from __future__ import annotations

import subprocess
import sys
import textwrap


def _run_isolated_python(code: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-c", textwrap.dedent(code)],
        capture_output=True,
        text=True,
        check=False,
        timeout=60,
    )


def test_normal_cli_registers_webhook_store_without_server_startup_package() -> None:
    proc = _run_isolated_python(
        """
        import importlib.abc
        import sys

        class Blocker(importlib.abc.MetaPathFinder):
            def find_spec(self, fullname, path=None, target=None):
                if fullname == "aragora.server.startup" or fullname.startswith(
                    "aragora.server.startup."
                ):
                    raise RuntimeError(f"blocked server startup import: {fullname}")
                return None

        sys.meta_path.insert(0, Blocker())

        import aragora.cli.main as main

        sys.argv = ["aragora", "--help"]
        try:
            main.main()
        except SystemExit as exc:
            assert exc.code in (0, None), exc.code

        import aragora.events.dispatcher as dispatcher
        from aragora.storage.webhook_config_store import get_webhook_config_store

        assert dispatcher._webhook_store_provider is get_webhook_config_store
        """
    )

    assert proc.returncode == 0, proc.stderr


def test_registration_helper_import_is_a_leaf() -> None:
    proc = _run_isolated_python(
        """
        import sys

        import aragora.server.webhook_store_registration as registration
        from aragora.server.startup import event_subscribers

        assert event_subscribers.register_webhook_store is registration.register_webhook_store
        """
    )
    assert proc.returncode == 0, proc.stderr

    proc = _run_isolated_python(
        """
        import sys

        import aragora.server.webhook_store_registration  # noqa: F401

        loaded = sorted(
            name
            for name in sys.modules
            if name.startswith(("aragora.server.startup", "aragora.events", "aragora.storage"))
        )
        assert loaded == [], loaded
        """
    )
    assert proc.returncode == 0, proc.stderr


def test_review_queue_fast_path_skips_webhook_registration_imports() -> None:
    proc = _run_isolated_python(
        """
        import importlib.abc
        import sys

        BLOCKED = (
            "aragora.server.startup",
            "aragora.server.webhook_store_registration",
            "aragora.storage.webhook_config_store",
        )

        class Blocker(importlib.abc.MetaPathFinder):
            def find_spec(self, fullname, path=None, target=None):
                if fullname.startswith(BLOCKED):
                    raise RuntimeError(f"blocked webhook registration import: {fullname}")
                return None

        sys.meta_path.insert(0, Blocker())

        import aragora.cli.main as main

        sys.argv = ["aragora", "review-queue", "merge-packet", "--help"]
        raise SystemExit(main.main())
        """
    )

    assert proc.returncode == 0, proc.stderr
    assert "merge-packet" in proc.stdout


def test_registration_leaf_is_a_tier4_authority_dependency_in_both_classifiers() -> None:
    """aragora/cli/main.py is an authority-closure member and imports this leaf
    statically, so the leaf joins the closure. The fail-closed closure build
    rejects any member classifying below Tier 4 and enforces per-member parity
    between the canonical classifier and the merge-train mirror, so the exact
    file path must be a dependency-prefix entry in both."""
    from aragora.cli.commands import review_queue
    from scripts import tier4_merge_train

    path = "aragora/server/webhook_store_registration.py"
    assert path in review_queue.CONTRACT_DRIFT_AUTHORITY_DEPENDENCY_PREFIXES
    assert path in tier4_merge_train.CONTRACT_DRIFT_AUTHORITY_DEPENDENCY_PREFIXES
    assert tier4_merge_train.matches_serialized_path(path) == path
    tier, name, _reason = review_queue._classify_model_review_tier([path])
    assert tier == 4
    assert name == "tier_4_preapproval_required"
