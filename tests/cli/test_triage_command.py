"""Tests for the triage CLI command wiring."""

from __future__ import annotations

import argparse
import io
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from aragora.cli.commands import triage as triage_cmd
from aragora.inbox.triage_diagnostics import DiagnosticSeverity, record_triage_diagnostic
from aragora.inbox.trust_wedge import InboxWedgeAction, TriageDecision
from aragora.storage.gmail_token_store import (
    EncryptionError,
    GmailUserState,
    InMemoryGmailTokenStore,
    SQLiteGmailTokenStore,
    reset_gmail_token_store,
    set_gmail_token_store,
)


def test_add_triage_parser_supports_auth_and_dry_run():
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command")
    triage_cmd.add_triage_parser(subparsers)

    run_args = parser.parse_args(
        ["triage", "run", "--batch", "3", "--dry-run", "--page-token", "next-123"]
    )
    auth_args = parser.parse_args(["triage", "auth"])

    assert run_args.triage_command == "run"
    assert run_args.batch == 3
    assert run_args.dry_run is True
    assert run_args.page_token == "next-123"
    assert auth_args.triage_command == "auth"


@pytest.mark.asyncio
async def test_run_triage_uses_receipt_review_loop(tmp_path, monkeypatch):
    decision = TriageDecision.create(
        final_action="ignore",
        confidence=0.4,
        dissent_summary="",
        receipt_id="receipt-1",
    )
    monkeypatch.setenv("ARAGORA_TRIAGE_DIAGNOSTICS_DIR", str(tmp_path / "triage-runs"))
    fake_runner = SimpleNamespace(run_triage=AsyncMock(return_value=[decision]))
    fake_service = SimpleNamespace(review_receipt=object())
    captured: dict[str, object] = {}

    class _FakeLoop:
        def __init__(self, **kwargs):
            captured.update(kwargs)

        def review_batch(self, decisions):
            captured["decisions"] = decisions
            return []

    with (
        patch.object(triage_cmd, "_get_gmail_connector", return_value=object()),
        patch(
            "aragora.inbox.triage_runner.InboxTriageRunner",
            return_value=fake_runner,
        ),
        patch(
            "aragora.inbox.trust_wedge.get_inbox_trust_wedge_service",
            return_value=fake_service,
        ),
        patch(
            "aragora.inbox.cli_review.CLIReviewLoop",
            _FakeLoop,
        ),
    ):
        await triage_cmd._run_triage(batch_size=1, auto_approve=False)

    assert captured["review_fn"] is fake_service.review_receipt
    assert captured["decisions"] == [decision]


@pytest.mark.asyncio
async def test_run_triage_dry_run_disables_action_execution(capsys, tmp_path, monkeypatch):
    decision = TriageDecision.create(
        final_action="archive",
        confidence=0.92,
        dissent_summary="",
        receipt_id="receipt-2",
    )
    monkeypatch.setenv("ARAGORA_TRIAGE_DIAGNOSTICS_DIR", str(tmp_path / "triage-runs"))
    fake_runner = SimpleNamespace(
        run_triage=AsyncMock(return_value=[decision]),
        next_page_token="next-page-xyz",
    )
    fake_service = SimpleNamespace(review_receipt=object())

    with (
        patch.object(triage_cmd, "_get_gmail_connector", return_value=object()),
        patch(
            "aragora.inbox.triage_runner.InboxTriageRunner",
            return_value=fake_runner,
        ),
        patch(
            "aragora.inbox.trust_wedge.get_inbox_trust_wedge_service",
            return_value=fake_service,
        ),
    ):
        await triage_cmd._run_triage(
            batch_size=2,
            auto_approve=True,
            dry_run=True,
            page_token="cursor-2",
        )

    fake_runner.run_triage.assert_awaited_once_with(
        batch_size=2,
        auto_approve=False,
        page_token="cursor-2",
    )
    out = capsys.readouterr().out
    assert "[DRY RUN] Fetching up to 2 unread messages" in out
    assert "[DRY RUN] Proposed triage decisions" in out
    assert "archive" in out
    assert "Run summary:" in out
    assert "Inspect inbox receipts:" in out
    assert "aragora inbox-wedge show receipt-2" in out
    assert "Review inbox receipts:" in out
    assert "aragora inbox-wedge review receipt-2 --choice <approve|reject|edit|skip>" in out
    assert "Next page token: next-page-xyz" in out


@pytest.mark.asyncio
async def test_run_triage_defaults_to_staged_profile(tmp_path, monkeypatch):
    decision = TriageDecision.create(
        final_action="archive",
        confidence=0.92,
        dissent_summary="",
        receipt_id="receipt-default-profile",
    )
    monkeypatch.setenv("ARAGORA_TRIAGE_DIAGNOSTICS_DIR", str(tmp_path / "triage-runs"))
    monkeypatch.delenv("ARAGORA_TRIAGE_PROFILE", raising=False)
    fake_runner = SimpleNamespace(
        run_triage=AsyncMock(return_value=[decision]), next_page_token=None
    )
    fake_service = SimpleNamespace(review_receipt=object())
    captured: dict[str, object] = {}

    def _runner_factory(**kwargs):
        captured.update(kwargs)
        return fake_runner

    with (
        patch.object(triage_cmd, "_get_gmail_connector", return_value=object()),
        patch("aragora.inbox.triage_runner.InboxTriageRunner", side_effect=_runner_factory),
        patch(
            "aragora.inbox.trust_wedge.get_inbox_trust_wedge_service",
            return_value=fake_service,
        ),
    ):
        await triage_cmd._run_triage(batch_size=1, auto_approve=False, dry_run=True)

    assert captured["profile"] == "staged_v1"


@pytest.mark.asyncio
async def test_run_triage_syncs_connector_state_before_execution(tmp_path, monkeypatch):
    decision = TriageDecision.create(
        final_action="archive",
        confidence=0.92,
        dissent_summary="",
        receipt_id="receipt-auth-sync",
    )
    gmail = SimpleNamespace(_refresh_token="refresh-token", user_id="me")
    monkeypatch.setenv("ARAGORA_TRIAGE_DIAGNOSTICS_DIR", str(tmp_path / "triage-runs"))
    fake_runner = SimpleNamespace(
        run_triage=AsyncMock(return_value=[decision]), next_page_token=None
    )
    fake_service = SimpleNamespace(review_receipt=object())

    with (
        patch.object(triage_cmd, "_get_gmail_connector", return_value=gmail),
        patch.object(
            triage_cmd,
            "_sync_gmail_connector_to_token_store",
            AsyncMock(),
        ) as sync_token_store,
        patch("aragora.inbox.triage_runner.InboxTriageRunner", return_value=fake_runner),
        patch(
            "aragora.inbox.trust_wedge.get_inbox_trust_wedge_service",
            return_value=fake_service,
        ),
    ):
        await triage_cmd._run_triage(batch_size=1, auto_approve=False, dry_run=True)

    sync_token_store.assert_awaited_once_with(gmail)


@pytest.mark.asyncio
async def test_run_triage_footer_shows_diagnostics_path(capsys, tmp_path, monkeypatch):
    decision = TriageDecision.create(
        final_action="archive",
        confidence=0.92,
        dissent_summary="",
        receipt_id="receipt-3",
    )
    monkeypatch.setenv("ARAGORA_TRIAGE_DIAGNOSTICS_DIR", str(tmp_path / "triage-runs"))

    async def _run_triage(*, batch_size, auto_approve, page_token=None):
        record_triage_diagnostic(
            code="provider_fallback",
            severity=DiagnosticSeverity.DEGRADED,
            logger_name="aragora.server.research_phase",
            summary="Fallback to OpenRouter",
            tier="baseline",
        )
        return [decision]

    fake_runner = SimpleNamespace(
        run_triage=AsyncMock(side_effect=_run_triage),
        next_page_token=None,
    )
    fake_service = SimpleNamespace(review_receipt=object())

    with (
        patch.object(triage_cmd, "_get_gmail_connector", return_value=object()),
        patch("aragora.inbox.triage_runner.InboxTriageRunner", return_value=fake_runner),
        patch(
            "aragora.inbox.trust_wedge.get_inbox_trust_wedge_service",
            return_value=fake_service,
        ),
    ):
        await triage_cmd._run_triage(batch_size=1, auto_approve=True, dry_run=True)

    out = capsys.readouterr().out
    assert "Run summary:" in out
    assert "suppressed=0" in out
    assert "global_diag=" in out
    assert "Diagnostics:" in out
    diag_root = tmp_path / "triage-runs"
    meta_files = list(diag_root.glob("*/meta.json"))
    assert len(meta_files) == 1
    meta = json.loads(meta_files[0].read_text())
    assert meta["severity_counts"]["degraded"] == 1


@pytest.mark.asyncio
async def test_sync_gmail_connector_to_token_store_saves_connector_tokens():
    store = InMemoryGmailTokenStore()
    connector = SimpleNamespace(
        user_id="me",
        _refresh_token="refresh-token-123",
        _access_token="access-token-456",
        _token_expiry="expiry-marker",
    )
    set_gmail_token_store(store)
    try:
        await triage_cmd._sync_gmail_connector_to_token_store(connector)
        state = await store.get("me")
    finally:
        reset_gmail_token_store()

    assert state is not None
    assert state.refresh_token == "refresh-token-123"
    assert state.access_token == "access-token-456"
    assert state.token_expiry == "expiry-marker"


@pytest.mark.asyncio
async def test_sync_gmail_connector_to_token_store_ignores_encryption_errors(tmp_path):
    store = SQLiteGmailTokenStore(tmp_path / "gmail_tokens.db")
    connector = SimpleNamespace(
        user_id="me",
        _refresh_token="refresh-token-123",
        _access_token="access-token-456",
    )
    set_gmail_token_store(store)
    try:
        with (
            patch(
                "aragora.storage.gmail_token_store.is_encryption_required",
                return_value=True,
            ),
            patch(
                "aragora.storage.gmail_token_store.get_encryption_service",
                side_effect=RuntimeError("kms offline"),
            ),
        ):
            with pytest.raises(EncryptionError):
                await store.save(GmailUserState(user_id="me", refresh_token="refresh-token-123"))

            await triage_cmd._sync_gmail_connector_to_token_store(connector)
            state = await store.get("me")
    finally:
        reset_gmail_token_store()
        await store.close()

    assert state is None


def test_print_decisions_formats_enum_values(capsys):
    decision = TriageDecision.create(
        final_action=InboxWedgeAction.IGNORE,
        confidence=0.4,
        dissent_summary="",
        receipt_id="receipt-1",
    )
    decision.intent = SimpleNamespace(_subject="Subject line")

    triage_cmd._print_decisions([decision])

    out = capsys.readouterr().out
    assert "ignore" in out
    assert "InboxWedgeAction" not in out
    assert "created" in out
    assert "aragora receipt show receipt-1" in out


def test_print_decisions_shows_blocked_status_for_truthful_stop(capsys):
    decision = TriageDecision.create(
        final_action=InboxWedgeAction.IGNORE,
        confidence=0.0,
        dissent_summary="Debate quorum failed.",
        receipt_id="receipt-blocked",
        blocked_by_policy=True,
    )
    decision.intent = SimpleNamespace(_subject="Blocked subject")

    triage_cmd._print_decisions([decision])

    out = capsys.readouterr().out
    assert "blocked" in out
    assert "Blocked subject" in out


@pytest.mark.asyncio
async def test_initialize_triage_storage_bootstraps_shared_pool():
    with patch(
        "aragora.server.startup.database.init_postgres_pool",
        AsyncMock(return_value={"enabled": True}),
    ) as mocked:
        await triage_cmd._initialize_triage_storage()

    mocked.assert_awaited_once()


@pytest.mark.asyncio
async def test_shutdown_triage_storage_closes_http_pool_and_resets_singletons():
    with (
        patch(
            "aragora.server.startup.database.close_postgres_pool",
            AsyncMock(),
        ) as close_postgres_pool,
        patch(
            "aragora.observability.http_client_pool.close_http_pool",
            AsyncMock(),
        ) as close_http_pool,
        patch(
            "aragora.agents.api_agents.common.close_shared_connector",
            AsyncMock(),
        ) as close_shared_connector,
        patch(
            "aragora.storage.connection_factory.close_all_pools",
            AsyncMock(),
        ) as close_all_pools,
        patch(
            "aragora.events.dispatcher.shutdown_dispatcher",
        ) as shutdown_dispatcher,
        patch(
            "aragora.storage.webhook_config_store.reset_webhook_config_store",
        ) as reset_webhook_config_store,
        patch(
            "aragora.inbox.trust_wedge.reset_inbox_trust_wedge_service",
        ) as reset_inbox_trust_wedge_service,
        patch(
            "aragora.inbox.trust_wedge.reset_inbox_trust_wedge_store",
        ) as reset_inbox_trust_wedge_store,
        patch("aragora.cli.commands.triage.asyncio.sleep", AsyncMock()) as sleep,
    ):
        await triage_cmd._shutdown_triage_storage()

    close_postgres_pool.assert_awaited_once()
    close_http_pool.assert_awaited_once()
    close_shared_connector.assert_awaited_once()
    close_all_pools.assert_awaited_once()
    shutdown_dispatcher.assert_called_once_with(wait=True)
    reset_webhook_config_store.assert_called_once()
    reset_inbox_trust_wedge_service.assert_called_once()
    reset_inbox_trust_wedge_store.assert_called_once()
    sleep.assert_awaited_once_with(0.05)


def test_get_gmail_connector_loads_refresh_token_from_home_file(tmp_path, monkeypatch):
    class _FakeConnector:
        def __init__(self):
            self._refresh_token = None

    token_dir = Path(tmp_path) / ".aragora"
    token_dir.mkdir()
    (token_dir / "gmail_refresh_token").write_text("refresh-from-file\n")

    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("GMAIL_CLIENT_ID", "client-id")
    monkeypatch.setenv("GMAIL_CLIENT_SECRET", "client-secret")
    monkeypatch.delenv("GMAIL_REFRESH_TOKEN", raising=False)

    with (
        patch.object(triage_cmd, "_get_secret_fallback", return_value=""),
        patch.object(triage_cmd, "_load_local_dotenv"),
        patch(
            "aragora.connectors.enterprise.communication.gmail.GmailConnector",
            _FakeConnector,
        ),
    ):
        connector = triage_cmd._get_gmail_connector()

    assert connector is not None
    assert connector._refresh_token == "refresh-from-file"


def test_resolve_gmail_oauth_credentials_skips_remote_secret_fallback_by_default(monkeypatch):
    monkeypatch.delenv("ARAGORA_ENV", raising=False)
    monkeypatch.delenv("ARAGORA_USE_SECRETS_MANAGER", raising=False)
    monkeypatch.delenv("GMAIL_CLIENT_ID", raising=False)
    monkeypatch.delenv("GMAIL_CLIENT_SECRET", raising=False)

    with (
        patch.object(
            triage_cmd,
            "_get_secret_fallback",
            side_effect=AssertionError("remote fallback should stay disabled for local runs"),
        ),
        patch.object(triage_cmd, "_load_local_dotenv"),
    ):
        client_id, client_secret = triage_cmd._resolve_gmail_oauth_credentials()

    assert client_id == ""
    assert client_secret == ""


def test_get_gmail_connector_uses_secret_fallback_for_credentials(tmp_path, monkeypatch):
    class _FakeConnector:
        def __init__(self):
            self._refresh_token = None

    token_dir = Path(tmp_path) / ".aragora"
    token_dir.mkdir()
    (token_dir / "gmail_refresh_token").write_text("refresh-from-file\n")

    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("ARAGORA_ENV", "production")
    monkeypatch.setenv("ARAGORA_USE_SECRETS_MANAGER", "1")
    monkeypatch.delenv("GMAIL_CLIENT_ID", raising=False)
    monkeypatch.delenv("GMAIL_CLIENT_SECRET", raising=False)

    with (
        patch.object(
            triage_cmd,
            "_get_secret_fallback",
            side_effect=lambda name: {
                "GMAIL_CLIENT_ID": "secret-client-id",
                "GMAIL_CLIENT_SECRET": "secret-client-secret",
            }.get(name, ""),
        ),
        patch.object(triage_cmd, "_load_local_dotenv"),
        patch(
            "aragora.connectors.enterprise.communication.gmail.GmailConnector",
            _FakeConnector,
        ),
    ):
        connector = triage_cmd._get_gmail_connector()

    assert connector is not None
    assert connector._refresh_token == "refresh-from-file"


def test_get_secret_fallback_returns_empty_on_secret_not_found(monkeypatch):
    """Strict-mode SecretNotFoundError must degrade to '' (read-only diagnostics)."""
    from aragora.config.secrets import SecretNotFoundError

    def _raise(name, *args, **kwargs):
        raise SecretNotFoundError(name)

    monkeypatch.setattr("aragora.config.secrets.get_secret", _raise)

    assert triage_cmd._get_secret_fallback("OPENROUTER_API_KEY") == ""


def test_show_status_survives_strict_secrets(tmp_path, monkeypatch, capsys):
    """`triage status` must not crash when critical secrets are absent in strict mode."""
    from aragora.config.secrets import SecretNotFoundError

    token_dir = Path(tmp_path) / ".aragora"
    token_dir.mkdir()
    (token_dir / "signing.key").write_text("dummy-signing-key")

    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.delenv("GMAIL_CLIENT_ID", raising=False)
    monkeypatch.delenv("GMAIL_CLIENT_SECRET", raising=False)
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)

    def _raise(name, *args, **kwargs):
        raise SecretNotFoundError(name)

    with (
        patch("aragora.config.secrets.get_secret", _raise),
        patch.object(triage_cmd, "_load_local_dotenv"),
    ):
        triage_cmd._show_status()

    out = capsys.readouterr().out
    assert "OpenRouter fallback:  NO" in out
    assert "Durable signing key:  yes" in out


def test_show_status_reports_refresh_token(tmp_path, monkeypatch, capsys):
    token_dir = Path(tmp_path) / ".aragora"
    token_dir.mkdir()
    (token_dir / "gmail_refresh_token").write_text("refresh-from-file\n")
    (token_dir / "signing.key").write_text("dummy-signing-key")

    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("GMAIL_CLIENT_ID", "client-id")
    monkeypatch.delenv("GMAIL_CLIENT_SECRET", raising=False)
    monkeypatch.setenv("OPENROUTER_API_KEY", "or-key")

    with (
        patch.object(triage_cmd, "_get_secret_fallback", return_value=""),
        patch.object(triage_cmd, "_load_local_dotenv"),  # Prevent repo .env leaking keys
    ):
        triage_cmd._show_status()

    out = capsys.readouterr().out
    assert "Gmail configured:     NO" in out
    assert "Durable signing key:  yes" in out
    assert "Gmail refresh token:  yes" in out
    assert "OpenRouter fallback:  yes" in out


def test_show_status_reports_gmail_from_secret_fallback(tmp_path, monkeypatch, capsys):
    token_dir = Path(tmp_path) / ".aragora"
    token_dir.mkdir()
    (token_dir / "gmail_refresh_token").write_text("refresh-from-file\n")
    (token_dir / "signing.key").write_text("dummy-signing-key")

    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("ARAGORA_ENV", "production")
    monkeypatch.setenv("ARAGORA_USE_SECRETS_MANAGER", "1")
    monkeypatch.delenv("GMAIL_CLIENT_ID", raising=False)
    monkeypatch.delenv("GMAIL_CLIENT_SECRET", raising=False)

    with (
        patch.object(
            triage_cmd,
            "_get_secret_fallback",
            side_effect=lambda name: {
                "GMAIL_CLIENT_ID": "secret-client-id",
                "GMAIL_CLIENT_SECRET": "secret-client-secret",
            }.get(name, ""),
        ),
        patch.object(triage_cmd, "_load_local_dotenv"),
    ):
        triage_cmd._show_status()

    out = capsys.readouterr().out
    assert "Gmail configured:     yes" in out
    assert "Durable signing key:  yes" in out
    assert "Gmail refresh token:  yes" in out


@pytest.mark.asyncio
async def test_run_gmail_auth_fails_fast_without_remote_secret_fallback(monkeypatch, capsys):
    monkeypatch.delenv("ARAGORA_ENV", raising=False)
    monkeypatch.delenv("ARAGORA_USE_SECRETS_MANAGER", raising=False)
    monkeypatch.delenv("GMAIL_CLIENT_ID", raising=False)
    monkeypatch.delenv("GMAIL_CLIENT_SECRET", raising=False)

    with (
        patch.object(
            triage_cmd,
            "_get_secret_fallback",
            side_effect=AssertionError("triage auth should not hit remote secrets for local runs"),
        ),
        patch.object(triage_cmd, "_load_local_dotenv"),
    ):
        with pytest.raises(SystemExit) as excinfo:
            await triage_cmd._run_gmail_auth()

    assert excinfo.value.code == 1
    err = capsys.readouterr().err
    assert "Set GMAIL_CLIENT_ID and GMAIL_CLIENT_SECRET environment" in err


@pytest.mark.asyncio
async def test_run_gmail_auth_saves_refresh_token(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("GMAIL_CLIENT_ID", "client-id")
    monkeypatch.setenv("GMAIL_CLIENT_SECRET", "client-secret")

    opened_urls: list[str] = []

    class _FakeConnector:
        def __init__(self):
            self._refresh_token = "refresh-token-123"

        def get_oauth_url(self, redirect_uri: str) -> str:
            assert redirect_uri == "http://localhost:8089/callback"
            return "https://accounts.google.test/oauth"

        async def authenticate(self, *, code: str, redirect_uri: str) -> bool:
            assert code == "oauth-code"
            assert redirect_uri == "http://localhost:8089/callback"
            return True

    class _FakeHTTPServer:
        def __init__(self, server_address, handler_cls):
            self.server_address = server_address
            self.handler_cls = handler_cls

        def handle_request(self):
            handler = object.__new__(self.handler_cls)
            handler.path = "/callback?code=oauth-code"
            handler.wfile = io.BytesIO()
            handler.send_response = lambda _code: None
            handler.send_header = lambda *_args, **_kwargs: None
            handler.end_headers = lambda: None
            self.handler_cls.do_GET(handler)

        def server_close(self):
            return None

    with (
        patch(
            "aragora.connectors.enterprise.communication.gmail.GmailConnector",
            _FakeConnector,
        ),
        patch.object(
            triage_cmd,
            "_sync_gmail_connector_to_token_store",
            AsyncMock(),
        ) as sync_token_store,
        patch("webbrowser.open", side_effect=opened_urls.append),
        patch("http.server.HTTPServer", _FakeHTTPServer),
    ):
        await triage_cmd._run_gmail_auth()

    token_path = Path(tmp_path) / ".aragora" / "gmail_refresh_token"
    assert token_path.read_text() == "refresh-token-123"
    assert token_path.stat().st_mode & 0o777 == 0o600
    assert opened_urls == ["https://accounts.google.test/oauth"]

    out = capsys.readouterr().out
    assert "Opening browser for Gmail authorization..." in out
    assert "Gmail authenticated successfully!" in out
    assert str(token_path) in out
    sync_token_store.assert_awaited_once()
