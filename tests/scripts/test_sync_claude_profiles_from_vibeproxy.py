from __future__ import annotations

import datetime as _dt
import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

import pytest


def _load_module() -> Any:
    script = (
        Path(__file__).resolve().parents[2] / "scripts" / "sync_claude_profiles_from_vibeproxy.py"
    )
    spec = importlib.util.spec_from_file_location("sync_claude_profiles_under_test", script)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


sync = _load_module()

_VP = {
    "access_token": "vp-access",
    "refresh_token": "vp-refresh",
    "expired": "2099-01-01T00:00:00+00:00",  # far future so it is never "stale"
    "type": "claude",
    "disabled": False,
}


def _config(sync_target=None, native_only=None):
    return sync.SyncConfig(
        sync_target=sync_target or {"x@example.com": "max-99"},
        native_only=native_only or {},
    )


def _setup(monkeypatch, tmp_path, vp_payload=_VP, email="x@example.com"):
    vp_dir = tmp_path / "vp"
    vp_dir.mkdir()
    (vp_dir / f"claude-{email}.json").write_text(json.dumps(vp_payload), encoding="utf-8")
    prof_root = tmp_path / "profiles"
    monkeypatch.setattr(sync, "VIBEPROXY_AUTH_DIR", vp_dir)
    monkeypatch.setattr(sync, "ARAGORA_PROFILE_ROOT", prof_root)
    return prof_root


# --- translate_credential ---------------------------------------------------


def test_blank_refresh_makes_a_pure_consumer_credential() -> None:
    oauth = sync.translate_credential(_VP, None, blank_refresh=True)["claudeAiOauth"]
    assert oauth["accessToken"] == "vp-access"
    assert oauth["refreshToken"] == ""


def test_keep_refresh_carries_the_vibeproxy_refresh_token() -> None:
    oauth = sync.translate_credential(_VP, None, blank_refresh=False)["claudeAiOauth"]
    assert oauth["refreshToken"] == "vp-refresh"


def test_expiry_iso_offset_translated_to_epoch_ms() -> None:
    vp = dict(_VP, expired="2026-07-22T18:27:18-05:00")
    got = sync.translate_credential(vp, None, blank_refresh=True)["claudeAiOauth"]["expiresAt"]
    expected = int(_dt.datetime.fromisoformat("2026-07-22T18:27:18-05:00").timestamp() * 1000)
    assert got == expected


def test_expiry_z_suffix_and_naive_treated_as_utc() -> None:
    z = sync._iso_to_epoch_ms("2026-07-22T18:27:18Z")
    utc = sync._iso_to_epoch_ms("2026-07-22T18:27:18+00:00")
    naive = sync._iso_to_epoch_ms("2026-07-22T18:27:18")
    assert z == utc == naive


def test_plan_and_scope_metadata_preserved_from_existing() -> None:
    existing = {"scopes": ["s"], "subscriptionType": "team", "rateLimitTier": "t"}
    oauth = sync.translate_credential(_VP, existing, blank_refresh=True)["claudeAiOauth"]
    assert oauth["scopes"] == ["s"] and oauth["subscriptionType"] == "team"
    assert oauth["rateLimitTier"] == "t"


# --- config loading / 1:1 invariant ----------------------------------------


def test_load_config_missing_raises(tmp_path) -> None:
    with pytest.raises(sync.ConfigError, match="not found"):
        sync.load_config(tmp_path / "absent.json")


def test_load_config_empty_sync_target_raises(tmp_path) -> None:
    p = tmp_path / "c.json"
    p.write_text(json.dumps({"sync_target": {}}), encoding="utf-8")
    with pytest.raises(sync.ConfigError, match="empty"):
        sync.load_config(p)


def test_load_config_rejects_profile_both_synced_and_native(tmp_path) -> None:
    p = tmp_path / "c.json"
    p.write_text(
        json.dumps({"sync_target": {"a@e": "max-01"}, "native_only": {"max-01": "x"}}),
        encoding="utf-8",
    )
    with pytest.raises(sync.ConfigError, match="both synced and native"):
        sync.load_config(p)


def test_load_config_rejects_one_profile_from_two_emails(tmp_path) -> None:
    p = tmp_path / "c.json"
    p.write_text(json.dumps({"sync_target": {"a@e": "max-01", "b@e": "max-01"}}), encoding="utf-8")
    with pytest.raises(sync.ConfigError, match=">1 email"):
        sync.load_config(p)


def test_redact_email_masks_local_part() -> None:
    assert sync._redact_email("anomium@gmail.com") == "a***@gmail.com"
    assert sync._redact_email("") == ""
    assert sync._redact_email("noatsign") == "noatsign"


def test_profile_root_honors_env_override(monkeypatch) -> None:
    # A fresh import with CLAUDE_PROFILE_ROOT set must point the writer at the
    # same root the sibling readers use (load an isolated instance so the shared
    # module under test is untouched).
    monkeypatch.setenv("CLAUDE_PROFILE_ROOT", "/tmp/custom-root")
    fresh = _load_module()
    assert str(fresh.ARAGORA_PROFILE_ROOT) == "/tmp/custom-root"


def test_shipped_example_config_is_loadable() -> None:
    example = Path(__file__).resolve().parents[2] / "scripts" / "claude_profile_sync.json.example"
    cfg = sync.load_config(example)
    assert cfg.sync_target and not (set(cfg.sync_target.values()) & set(cfg.native_only))


# --- sync_profile behavior --------------------------------------------------


def test_native_only_profile_is_skipped() -> None:
    cfg = _config(native_only={"max-08": "distinct org"})
    r = sync.sync_profile("max-08", cfg, blank_refresh=True, apply=False)
    assert r.action == "skipped_native_only"


def test_no_source_when_vibeproxy_file_absent(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(sync, "VIBEPROXY_AUTH_DIR", tmp_path)  # empty
    r = sync.sync_profile("max-99", _config(), blank_refresh=True, apply=False)
    assert r.action == "skipped_no_source"


def test_stale_source_is_not_synced(monkeypatch, tmp_path) -> None:
    _setup(monkeypatch, tmp_path, vp_payload=dict(_VP, expired="2000-01-01T00:00:00+00:00"))
    r = sync.sync_profile("max-99", _config(), blank_refresh=True, apply=True)
    assert r.action == "skipped_stale_source"


def test_disabled_source_is_not_synced(monkeypatch, tmp_path) -> None:
    _setup(monkeypatch, tmp_path, vp_payload=dict(_VP, disabled=True))
    r = sync.sync_profile("max-99", _config(), blank_refresh=True, apply=False)
    assert r.action == "skipped_no_source"


def test_malformed_source_isolates_as_error(monkeypatch, tmp_path) -> None:
    _setup(monkeypatch, tmp_path, vp_payload=dict(_VP, expired="not-a-date"))
    r = sync.sync_profile("max-99", _config(), blank_refresh=True, apply=True)
    assert r.action == "error"


def test_idempotent_on_matching_access_token(monkeypatch, tmp_path) -> None:
    prof_root = _setup(monkeypatch, tmp_path)
    cred = prof_root / "max-99" / ".claude" / ".credentials.json"
    cred.parent.mkdir(parents=True)
    cred.write_text(json.dumps({"claudeAiOauth": {"accessToken": "vp-access"}}), encoding="utf-8")
    r = sync.sync_profile("max-99", _config(), blank_refresh=True, apply=True)
    assert r.action == "skipped_fresh"


@pytest.mark.parametrize("expires_at", [sync._now_ms() + 3_600_000, sync._now_ms() - 1])
def test_native_login_protected_regardless_of_access_token_liveness(
    monkeypatch, tmp_path, expires_at
) -> None:
    # Both a live native login AND an idle one (valid refresh, expired access)
    # must be protected — the refresh token is the thing worth preserving.
    prof_root = _setup(monkeypatch, tmp_path)
    cred = prof_root / "max-99" / ".claude" / ".credentials.json"
    cred.parent.mkdir(parents=True)
    cred.write_text(
        json.dumps(
            {"claudeAiOauth": {"accessToken": "n", "refreshToken": "real", "expiresAt": expires_at}}
        ),
        encoding="utf-8",
    )
    r = sync.sync_profile("max-99", _config(), blank_refresh=True, apply=True)
    assert r.action == "skipped_native_login"
    r2 = sync.sync_profile("max-99", _config(), blank_refresh=True, apply=True, force=True)
    assert r2.action == "synced"
    # --force backs up the native cred it is about to destroy.
    backup = cred.with_name(".credentials.json.bak")
    assert json.loads(backup.read_text())["claudeAiOauth"]["refreshToken"] == "real"


def test_writes_owner_only_credential_and_no_backup_for_our_own_cred(monkeypatch, tmp_path) -> None:
    # Re-syncing over our own blank-refresh cred writes owner-only and does NOT
    # create a backup (there is no native refresh token worth preserving, and a
    # backup here would overwrite an earlier real native backup).
    prof_root = _setup(monkeypatch, tmp_path)
    cred = prof_root / "max-99" / ".claude" / ".credentials.json"
    cred.parent.mkdir(parents=True)
    cred.write_text(
        json.dumps({"claudeAiOauth": {"accessToken": "old", "refreshToken": ""}}),
        encoding="utf-8",
    )
    r = sync.sync_profile("max-99", _config(), blank_refresh=True, apply=True)
    assert r.action == "synced"
    assert (cred.stat().st_mode & 0o777) == 0o600
    written = json.loads(cred.read_text())
    assert written["claudeAiOauth"]["accessToken"] == "vp-access"
    assert written["claudeAiOauth"]["refreshToken"] == ""
    assert not cred.with_name(".credentials.json.bak").exists()


def test_total_source_loss_exits_nonzero(monkeypatch, tmp_path) -> None:
    cfg_path = tmp_path / "c.json"
    cfg_path.write_text(json.dumps({"sync_target": {"a@e": "max-01"}}), encoding="utf-8")
    monkeypatch.setattr(sync, "VIBEPROXY_AUTH_DIR", tmp_path / "empty")
    rc = sync.main(["--config", str(cfg_path)])
    assert rc == 1


def test_native_login_with_matching_access_token_still_protected(monkeypatch, tmp_path) -> None:
    # openai P2: the native-login guard must run BEFORE the idempotency check, so
    # a native profile whose access token coincidentally equals VibeProxy's is
    # still protected (not classified skipped_fresh, which would leave its live
    # refresh token to race VibeProxy).
    prof_root = _setup(monkeypatch, tmp_path)
    cred = prof_root / "max-99" / ".claude" / ".credentials.json"
    cred.parent.mkdir(parents=True)
    cred.write_text(
        json.dumps({"claudeAiOauth": {"accessToken": "vp-access", "refreshToken": "real"}}),
        encoding="utf-8",
    )
    r = sync.sync_profile("max-99", _config(), blank_refresh=True, apply=True)
    assert r.action == "skipped_native_login"


def test_all_native_profiles_exit_nonzero_needing_bootstrap(monkeypatch, tmp_path, capsys) -> None:
    # A pool that still holds native/dead refresh tokens is a silent no-op state;
    # main() must exit non-zero and point at the one-time --force bootstrap.
    prof_root = _setup(monkeypatch, tmp_path)
    cred = prof_root / "max-01" / ".claude" / ".credentials.json"
    cred.parent.mkdir(parents=True)
    cred.write_text(
        json.dumps({"claudeAiOauth": {"accessToken": "x", "refreshToken": "revoked"}}),
        encoding="utf-8",
    )
    cfg_path = tmp_path / "c.json"
    cfg_path.write_text(json.dumps({"sync_target": {"x@example.com": "max-01"}}), encoding="utf-8")
    rc = sync.main(["--config", str(cfg_path), "--apply"])
    assert rc == 1
    assert "--force" in capsys.readouterr().err


def test_unreadable_existing_credential_fails_closed(monkeypatch, tmp_path) -> None:
    # A present-but-corrupt cred (e.g. a torn read) must fail closed, not be
    # treated as empty (which would bypass the guard/backup and destroy a token).
    prof_root = _setup(monkeypatch, tmp_path)
    cred = prof_root / "max-99" / ".claude" / ".credentials.json"
    cred.parent.mkdir(parents=True)
    cred.write_text("{ this is not json", encoding="utf-8")
    r = sync.sync_profile("max-99", _config(), blank_refresh=True, apply=True)
    assert r.action == "error"
    # The unreadable file was NOT overwritten.
    assert cred.read_text() == "{ this is not json"


def test_force_recovers_a_corrupt_credential(monkeypatch, tmp_path) -> None:
    # Without --force a corrupt cred fails closed; WITH --force it is backed up
    # to .bak.corrupt and rewritten, so a wedged profile can self-heal.
    prof_root = _setup(monkeypatch, tmp_path)
    cred = prof_root / "max-99" / ".claude" / ".credentials.json"
    cred.parent.mkdir(parents=True)
    cred.write_text("{ torn write", encoding="utf-8")
    assert sync.sync_profile("max-99", _config(), blank_refresh=True, apply=True).action == "error"
    r = sync.sync_profile("max-99", _config(), blank_refresh=True, apply=True, force=True)
    assert r.action == "synced"
    assert json.loads(cred.read_text())["claudeAiOauth"]["accessToken"] == "vp-access"
    corrupt_bak = cred.with_name(".credentials.json.bak.corrupt")
    assert corrupt_bak.exists() and corrupt_bak.read_text() == "{ torn write"


def test_non_object_json_credential_fails_closed(monkeypatch, tmp_path) -> None:
    prof_root = _setup(monkeypatch, tmp_path)
    cred = prof_root / "max-99" / ".claude" / ".credentials.json"
    cred.parent.mkdir(parents=True)
    cred.write_text("[]", encoding="utf-8")  # valid JSON, wrong shape
    assert sync.sync_profile("max-99", _config(), blank_refresh=True, apply=True).action == "error"


def test_partial_failure_exits_nonzero(monkeypatch, tmp_path) -> None:
    # One profile syncs, another has no source -> the stuck profile must not be
    # masked by the healthy one; the run fails.
    vp_dir = tmp_path / "vp"
    vp_dir.mkdir()
    (vp_dir / "claude-a@e.json").write_text(json.dumps(_VP), encoding="utf-8")  # b@e absent
    monkeypatch.setattr(sync, "VIBEPROXY_AUTH_DIR", vp_dir)
    monkeypatch.setattr(sync, "ARAGORA_PROFILE_ROOT", tmp_path / "profiles")
    cfg_path = tmp_path / "c.json"
    cfg_path.write_text(
        json.dumps({"sync_target": {"a@e": "max-01", "b@e": "max-02"}}), encoding="utf-8"
    )
    assert sync.main(["--config", str(cfg_path), "--apply"]) == 1


def test_all_sources_stale_exits_nonzero(monkeypatch, tmp_path) -> None:
    # A stopped/crashed proxy leaves files present with expired tokens; that is
    # a total source loss and must exit non-zero, not look healthy.
    vp_dir = tmp_path / "vp"
    vp_dir.mkdir()
    (vp_dir / "claude-a@e.json").write_text(
        json.dumps(dict(_VP, expired="2000-01-01T00:00:00+00:00")), encoding="utf-8"
    )
    monkeypatch.setattr(sync, "VIBEPROXY_AUTH_DIR", vp_dir)
    monkeypatch.setattr(sync, "ARAGORA_PROFILE_ROOT", tmp_path / "profiles")
    cfg_path = tmp_path / "c.json"
    cfg_path.write_text(json.dumps({"sync_target": {"a@e": "max-01"}}), encoding="utf-8")
    assert sync.main(["--config", str(cfg_path), "--apply"]) == 1
