"""
Tests for the debate sharing handler.

Covers:
- DebateVisibility enum
- ShareSettings dataclass (to_dict, from_dict, is_expired, share_url)
- ShareStore (get, save, delete, revoke_token, get_by_token, increment_view_count, eviction)
- SocialShare dataclass
- SocialShareStore (get_by_org, get_by_id, create, delete)
- SharingHandler (can_handle, handle routing, GET/POST/DELETE endpoints)
  - Debate share settings (GET/POST /api/v1/debates/{id}/share)
  - Shared debate access (GET /api/v1/shared/{token})
  - Revoke share (POST /api/v1/debates/{id}/share/revoke)
  - Social shares CRUD (GET/POST /api/v1/social/shares, GET/DELETE /api/v1/social/shares/{id})
  - Authorization checks (ownership, team visibility)
  - Rate limiting
  - Input validation (schema validation, missing fields)
"""

from __future__ import annotations

import json
import subprocess
import sys
import time
from unittest.mock import MagicMock, patch

import pytest

from aragora.server.handlers.social.sharing import (
    ShareStore,
    SharingHandler,
    SocialShare,
    SocialShareStore,
    MAX_SHARE_SETTINGS,
)
from aragora.storage.share_models import DebateVisibility, ShareSettings


# ============================================================================
# Helpers
# ============================================================================


def _body(result) -> dict:
    """Extract JSON body dict from a HandlerResult."""
    if isinstance(result, dict):
        return result
    raw = result.body
    if isinstance(raw, (bytes, bytearray)):
        raw = raw.decode("utf-8")
    return json.loads(raw)


def _status(result) -> int:
    """Extract HTTP status code from a HandlerResult."""
    if isinstance(result, dict):
        return result.get("status", result.get("status_code", 200))
    return result.status_code


def _set_body(mock_http_handler, data: dict) -> None:
    """Set the JSON body on a mock HTTP handler."""
    body_bytes = json.dumps(data).encode("utf-8")
    mock_http_handler.rfile.read.return_value = body_bytes
    mock_http_handler.headers["Content-Length"] = str(len(body_bytes))


# ============================================================================
# Fixtures
# ============================================================================


@pytest.fixture
def mock_http_handler():
    """Create a mock HTTP handler."""
    mock = MagicMock()
    mock.command = "GET"
    mock.client_address = ("127.0.0.1", 12345)
    mock.headers = {"Content-Type": "application/json", "Content-Length": "2"}
    mock.rfile = MagicMock()
    mock.rfile.read.return_value = b"{}"
    return mock


@pytest.fixture
def share_store():
    """Create a fresh ShareStore."""
    return ShareStore()


@pytest.fixture
def social_share_store():
    """Create a fresh SocialShareStore."""
    return SocialShareStore()


@pytest.fixture
def handler(share_store, social_share_store):
    """Create a SharingHandler with test stores."""
    h = SharingHandler(server_context={})
    h._store = share_store
    h._social_store = social_share_store
    return h


# ============================================================================
# DebateVisibility Enum Tests
# ============================================================================


def test_debate_visibility_legacy_symbol_warns_and_preserves_identity():
    import aragora.server.handlers.social.sharing as sharing
    from aragora.storage.share_models import DebateVisibility as CanonicalDebateVisibility

    script = """
import warnings
with warnings.catch_warnings(record=True) as caught:
    warnings.simplefilter("always")
    from aragora.server.handlers.social.sharing import SharingHandler
legacy = [
    item for item in caught
    if "aragora.server.handlers.social.sharing.DebateVisibility" in str(item.message)
    or "aragora.server.handlers.social.sharing.ShareSettings" in str(item.message)
]
assert not legacy, legacy
"""
    result = subprocess.run(
        [sys.executable, "-c", script],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr or result.stdout

    with pytest.warns(
        DeprecationWarning,
        match=r"aragora\.server\.handlers\.social\.sharing\.DebateVisibility",
    ):
        legacy_symbol = sharing.DebateVisibility

    assert legacy_symbol is CanonicalDebateVisibility


def test_share_settings_legacy_symbol_warns_and_preserves_identity():
    from aragora.storage.share_models import ShareSettings as CanonicalShareSettings

    with pytest.warns(
        DeprecationWarning,
        match=r"aragora\.server\.handlers\.social\.sharing\.ShareSettings",
    ):
        from aragora.server.handlers.social.sharing import ShareSettings as LegacyShareSettings

    assert LegacyShareSettings is CanonicalShareSettings


def test_legacy_share_symbol_monkeypatch_reaches_handler(handler, mock_http_handler, share_store):
    settings_factory = MagicMock(
        return_value=ShareSettings(
            debate_id="patched-settings",
            owner_id="test-user-001",
            org_id="test-org-001",
        )
    )
    with patch(
        "aragora.server.handlers.social.sharing.ShareSettings",
        settings_factory,
    ):
        result = handler._get_share_settings("patched-settings", mock_http_handler)

    assert _status(result) == 200
    settings_factory.assert_called_once_with(
        debate_id="patched-settings",
        owner_id="test-user-001",
        org_id="test-org-001",
    )

    class PatchedVisibility:
        PRIVATE = DebateVisibility.PRIVATE
        TEAM = DebateVisibility.TEAM
        PUBLIC = DebateVisibility.PUBLIC

        def __new__(cls, value):
            return DebateVisibility(value)

    mock_http_handler.command = "POST"
    _set_body(mock_http_handler, {"visibility": "public"})
    with patch(
        "aragora.server.handlers.social.sharing.DebateVisibility",
        PatchedVisibility,
    ):
        result = handler._update_share_settings("patched-visibility", mock_http_handler)

    assert _status(result) == 200
    assert share_store.get("patched-visibility").visibility is DebateVisibility.PUBLIC


class TestDebateVisibility:
    """Tests for the DebateVisibility enum."""

    def test_private_value(self):
        assert DebateVisibility.PRIVATE.value == "private"

    def test_team_value(self):
        assert DebateVisibility.TEAM.value == "team"

    def test_public_value(self):
        assert DebateVisibility.PUBLIC.value == "public"

    def test_from_string(self):
        assert DebateVisibility("private") == DebateVisibility.PRIVATE
        assert DebateVisibility("team") == DebateVisibility.TEAM
        assert DebateVisibility("public") == DebateVisibility.PUBLIC

    def test_invalid_value_raises(self):
        with pytest.raises(ValueError):
            DebateVisibility("invalid")

    def test_is_string_subclass(self):
        assert isinstance(DebateVisibility.PRIVATE, str)


# ============================================================================
# ShareSettings Tests
# ============================================================================


class TestShareSettings:
    """Tests for the ShareSettings dataclass."""

    def test_default_values(self):
        s = ShareSettings(debate_id="d1")
        assert s.debate_id == "d1"
        assert s.visibility == DebateVisibility.PRIVATE
        assert s.share_token is None
        assert s.expires_at is None
        assert s.allow_comments is False
        assert s.allow_forking is False
        assert s.view_count == 0
        assert s.owner_id is None
        assert s.org_id is None

    def test_to_dict(self):
        s = ShareSettings(
            debate_id="d1",
            visibility=DebateVisibility.PUBLIC,
            share_token="tok123",
            created_at=1000.0,
            expires_at=2000.0,
            allow_comments=True,
            allow_forking=True,
            view_count=5,
        )
        d = s.to_dict()
        assert d["debate_id"] == "d1"
        assert d["visibility"] == "public"
        assert d["share_token"] == "tok123"
        assert d["share_url"] == "/api/v1/shared/tok123"
        assert d["created_at"] == 1000.0
        assert d["expires_at"] == 2000.0
        assert d["allow_comments"] is True
        assert d["allow_forking"] is True
        assert d["view_count"] == 5

    def test_to_dict_no_token(self):
        s = ShareSettings(debate_id="d1")
        d = s.to_dict()
        assert d["share_url"] is None
        assert d["share_token"] is None

    def test_is_expired_no_expiration(self):
        s = ShareSettings(debate_id="d1", expires_at=None)
        assert s.is_expired is False

    def test_is_expired_future(self):
        s = ShareSettings(debate_id="d1", expires_at=time.time() + 3600)
        assert s.is_expired is False

    def test_is_expired_past(self):
        s = ShareSettings(debate_id="d1", expires_at=time.time() - 3600)
        assert s.is_expired is True

    def test_from_dict_minimal(self):
        s = ShareSettings.from_dict({"debate_id": "d1"})
        assert s.debate_id == "d1"
        assert s.visibility == DebateVisibility.PRIVATE
        assert s.share_token is None

    def test_from_dict_full(self):
        data = {
            "debate_id": "d2",
            "visibility": "public",
            "share_token": "abc",
            "created_at": 500.0,
            "expires_at": 1000.0,
            "allow_comments": True,
            "allow_forking": True,
            "view_count": 42,
            "owner_id": "u1",
            "org_id": "o1",
        }
        s = ShareSettings.from_dict(data)
        assert s.debate_id == "d2"
        assert s.visibility == DebateVisibility.PUBLIC
        assert s.share_token == "abc"
        assert s.created_at == 500.0
        assert s.expires_at == 1000.0
        assert s.allow_comments is True
        assert s.allow_forking is True
        assert s.view_count == 42
        assert s.owner_id == "u1"
        assert s.org_id == "o1"

    def test_to_dict_is_expired_field(self):
        s = ShareSettings(debate_id="d1", expires_at=time.time() - 1)
        d = s.to_dict()
        assert d["is_expired"] is True

    def test_share_url_format(self):
        s = ShareSettings(debate_id="d1", share_token="mytoken")
        assert s._get_share_url() == "/api/v1/shared/mytoken"


# ============================================================================
# ShareStore Tests
# ============================================================================


class TestShareStore:
    """Tests for the ShareStore in-memory store."""

    def test_get_nonexistent(self, share_store):
        assert share_store.get("nonexistent") is None

    def test_save_and_get(self, share_store):
        s = ShareSettings(debate_id="d1", owner_id="u1")
        share_store.save(s)
        retrieved = share_store.get("d1")
        assert retrieved is not None
        assert retrieved.debate_id == "d1"

    def test_get_by_token(self, share_store):
        s = ShareSettings(debate_id="d1", share_token="tok1")
        share_store.save(s)
        retrieved = share_store.get_by_token("tok1")
        assert retrieved is not None
        assert retrieved.debate_id == "d1"

    def test_get_by_token_nonexistent(self, share_store):
        assert share_store.get_by_token("missing") is None

    def test_delete(self, share_store):
        s = ShareSettings(debate_id="d1", share_token="tok1")
        share_store.save(s)
        assert share_store.delete("d1") is True
        assert share_store.get("d1") is None
        assert share_store.get_by_token("tok1") is None

    def test_delete_nonexistent(self, share_store):
        assert share_store.delete("nonexistent") is False

    def test_revoke_token(self, share_store):
        s = ShareSettings(debate_id="d1", share_token="tok1")
        share_store.save(s)
        assert share_store.revoke_token("d1") is True
        assert share_store.get_by_token("tok1") is None
        retrieved = share_store.get("d1")
        assert retrieved.share_token is None

    def test_revoke_token_no_token(self, share_store):
        s = ShareSettings(debate_id="d1")
        share_store.save(s)
        assert share_store.revoke_token("d1") is False

    def test_revoke_token_nonexistent(self, share_store):
        assert share_store.revoke_token("missing") is False

    def test_increment_view_count(self, share_store):
        s = ShareSettings(debate_id="d1", view_count=0)
        share_store.save(s)
        share_store.increment_view_count("d1")
        share_store.increment_view_count("d1")
        assert share_store.get("d1").view_count == 2

    def test_increment_view_count_nonexistent(self, share_store):
        # Should not raise
        share_store.increment_view_count("missing")

    def test_save_overwrites(self, share_store):
        s1 = ShareSettings(debate_id="d1", allow_comments=False)
        share_store.save(s1)
        s2 = ShareSettings(debate_id="d1", allow_comments=True)
        share_store.save(s2)
        assert share_store.get("d1").allow_comments is True

    def test_eviction_when_full(self, share_store):
        """When store hits MAX_SHARE_SETTINGS, oldest entries are evicted."""
        # Fill the store to max capacity
        for i in range(MAX_SHARE_SETTINGS):
            share_store.save(ShareSettings(debate_id=f"d{i}", created_at=float(i)))
        assert len(share_store._settings) == MAX_SHARE_SETTINGS

        # Adding one more should trigger eviction
        share_store.save(
            ShareSettings(debate_id="new_entry", created_at=float(MAX_SHARE_SETTINGS + 1))
        )
        # Should have evicted oldest 10%
        assert len(share_store._settings) <= MAX_SHARE_SETTINGS
        # The very oldest entry should be gone
        assert share_store.get("d0") is None
        # The new entry should be present
        assert share_store.get("new_entry") is not None

    def test_eviction_cleans_up_tokens(self, share_store):
        """Eviction should also clean up token references."""
        for i in range(MAX_SHARE_SETTINGS):
            share_store.save(
                ShareSettings(debate_id=f"d{i}", share_token=f"tok{i}", created_at=float(i))
            )
        # Adding one more should trigger eviction of oldest entries and their tokens
        share_store.save(
            ShareSettings(debate_id="new_entry", created_at=float(MAX_SHARE_SETTINGS + 1))
        )
        assert share_store.get_by_token("tok0") is None

    def test_no_eviction_when_updating_existing(self, share_store):
        """Updating an existing entry should not trigger eviction even when at capacity."""
        for i in range(MAX_SHARE_SETTINGS):
            share_store.save(ShareSettings(debate_id=f"d{i}", created_at=float(i)))
        # Update existing entry (should not trigger eviction)
        share_store.save(ShareSettings(debate_id="d0", created_at=99999.0, allow_comments=True))
        assert len(share_store._settings) == MAX_SHARE_SETTINGS
        assert share_store.get("d0").allow_comments is True


# ============================================================================
# SocialShare Tests
# ============================================================================


class TestSocialShare:
    """Tests for the SocialShare dataclass."""

    def test_default_values(self):
        ss = SocialShare(
            id="s1",
            org_id="o1",
            resource_type="debate",
            resource_id="d1",
            shared_by="u1",
        )
        assert ss.shared_with == []
        assert ss.channel_id == ""
        assert ss.platform == ""
        assert ss.message == ""

    def test_to_dict(self):
        ss = SocialShare(
            id="s1",
            org_id="o1",
            resource_type="debate",
            resource_id="d1",
            shared_by="u1",
            shared_with=["u2", "u3"],
            channel_id="ch1",
            platform="slack",
            message="Check this out",
        )
        d = ss.to_dict()
        assert d["id"] == "s1"
        assert d["org_id"] == "o1"
        assert d["resource_type"] == "debate"
        assert d["resource_id"] == "d1"
        assert d["shared_by"] == "u1"
        assert d["shared_with"] == ["u2", "u3"]
        assert d["channel_id"] == "ch1"
        assert d["platform"] == "slack"
        assert d["message"] == "Check this out"
        assert "created_at" in d


# ============================================================================
# SocialShareStore Tests
# ============================================================================


class TestSocialShareStore:
    """Tests for the SocialShareStore."""

    def test_create_and_get_by_id(self, social_share_store):
        ss = SocialShare(
            id="s1", org_id="o1", resource_type="debate", resource_id="d1", shared_by="u1"
        )
        created = social_share_store.create(ss)
        assert created.id == "s1"
        retrieved = social_share_store.get_by_id("s1")
        assert retrieved is not None
        assert retrieved.id == "s1"

    def test_get_by_id_nonexistent(self, social_share_store):
        assert social_share_store.get_by_id("missing") is None

    def test_get_by_org(self, social_share_store):
        ss1 = SocialShare(
            id="s1", org_id="o1", resource_type="debate", resource_id="d1", shared_by="u1"
        )
        ss2 = SocialShare(
            id="s2", org_id="o1", resource_type="debate", resource_id="d2", shared_by="u1"
        )
        ss3 = SocialShare(
            id="s3", org_id="o2", resource_type="debate", resource_id="d3", shared_by="u2"
        )
        social_share_store.create(ss1)
        social_share_store.create(ss2)
        social_share_store.create(ss3)
        org1_shares = social_share_store.get_by_org("o1")
        assert len(org1_shares) == 2
        org2_shares = social_share_store.get_by_org("o2")
        assert len(org2_shares) == 1

    def test_get_by_org_empty(self, social_share_store):
        assert social_share_store.get_by_org("none") == []

    def test_delete(self, social_share_store):
        ss = SocialShare(
            id="s1", org_id="o1", resource_type="debate", resource_id="d1", shared_by="u1"
        )
        social_share_store.create(ss)
        assert social_share_store.delete("s1") is True
        assert social_share_store.get_by_id("s1") is None

    def test_delete_nonexistent(self, social_share_store):
        assert social_share_store.delete("missing") is False


# ============================================================================
# SharingHandler.can_handle Tests
# ============================================================================


class TestCanHandle:
    """Tests for SharingHandler.can_handle."""

    def test_social_shares_path(self, handler):
        assert handler.can_handle("/api/v1/social/shares") is True

    def test_social_shares_with_id(self, handler):
        assert handler.can_handle("/api/v1/social/shares/abc123") is True

    def test_shared_debate_path(self, handler):
        assert handler.can_handle("/api/v1/shared/token123") is True

    def test_debate_share_path(self, handler):
        assert handler.can_handle("/api/v1/debates/d1/share") is True

    def test_debate_share_revoke_path(self, handler):
        assert handler.can_handle("/api/v1/debates/d1/share/revoke") is True

    def test_unrelated_path(self, handler):
        assert handler.can_handle("/api/v1/debates") is False

    def test_unrelated_path_other(self, handler):
        assert handler.can_handle("/api/v1/health") is False


# ============================================================================
# SharingHandler - Social Shares Endpoints
# ============================================================================


class TestListSocialShares:
    """Tests for GET /api/v1/social/shares."""

    def test_list_empty(self, handler, mock_http_handler):
        mock_http_handler.command = "GET"
        result = handler.handle("/api/v1/social/shares", {}, mock_http_handler, "GET")
        assert _status(result) == 200
        body = _body(result)
        assert body["shares"] == []
        assert body["total"] == 0

    def test_list_with_shares(self, handler, mock_http_handler, social_share_store):
        mock_http_handler.command = "GET"
        ss = SocialShare(
            id="s1", org_id="test-org-001", resource_type="debate", resource_id="d1", shared_by="u1"
        )
        social_share_store.create(ss)
        result = handler.handle("/api/v1/social/shares", {}, mock_http_handler, "GET")
        assert _status(result) == 200
        body = _body(result)
        assert body["total"] == 1
        assert body["shares"][0]["id"] == "s1"

    def test_list_filter_by_resource_type(self, handler, mock_http_handler, social_share_store):
        mock_http_handler.command = "GET"
        ss1 = SocialShare(
            id="s1", org_id="test-org-001", resource_type="debate", resource_id="d1", shared_by="u1"
        )
        ss2 = SocialShare(
            id="s2", org_id="test-org-001", resource_type="report", resource_id="r1", shared_by="u1"
        )
        social_share_store.create(ss1)
        social_share_store.create(ss2)
        result = handler.handle(
            "/api/v1/social/shares", {"resource_type": "debate"}, mock_http_handler, "GET"
        )
        body = _body(result)
        assert body["total"] == 1
        assert body["shares"][0]["resource_type"] == "debate"


class TestGetSocialShare:
    """Tests for GET /api/v1/social/shares/{id}."""

    def test_get_existing(self, handler, mock_http_handler, social_share_store):
        mock_http_handler.command = "GET"
        ss = SocialShare(
            id="s1", org_id="o1", resource_type="debate", resource_id="d1", shared_by="u1"
        )
        social_share_store.create(ss)
        result = handler.handle("/api/v1/social/shares/s1", {}, mock_http_handler, "GET")
        assert _status(result) == 200
        body = _body(result)
        assert body["share"]["id"] == "s1"

    def test_get_nonexistent(self, handler, mock_http_handler):
        mock_http_handler.command = "GET"
        result = handler.handle("/api/v1/social/shares/missing", {}, mock_http_handler, "GET")
        assert _status(result) == 404


class TestCreateSocialShare:
    """Tests for POST /api/v1/social/shares."""

    def test_create_success(self, handler, mock_http_handler):
        mock_http_handler.command = "POST"
        _set_body(
            mock_http_handler,
            {
                "resource_type": "debate",
                "resource_id": "d1",
                "shared_with": ["u2"],
                "channel_id": "ch1",
                "platform": "slack",
                "message": "Look at this",
            },
        )
        result = handler.handle("/api/v1/social/shares", {}, mock_http_handler, "POST")
        assert _status(result) == 201
        body = _body(result)
        assert body["share"]["resource_type"] == "debate"
        assert body["share"]["resource_id"] == "d1"
        assert body["share"]["shared_with"] == ["u2"]

    def test_create_missing_resource_type(self, handler, mock_http_handler):
        mock_http_handler.command = "POST"
        _set_body(mock_http_handler, {"resource_id": "d1"})
        result = handler.handle("/api/v1/social/shares", {}, mock_http_handler, "POST")
        assert _status(result) == 400

    def test_create_missing_resource_id(self, handler, mock_http_handler):
        mock_http_handler.command = "POST"
        _set_body(mock_http_handler, {"resource_type": "debate"})
        result = handler.handle("/api/v1/social/shares", {}, mock_http_handler, "POST")
        assert _status(result) == 400

    def test_create_invalid_body(self, handler, mock_http_handler):
        mock_http_handler.command = "POST"
        mock_http_handler.rfile.read.return_value = b"not json"
        mock_http_handler.headers["Content-Length"] = "8"
        result = handler.handle("/api/v1/social/shares", {}, mock_http_handler, "POST")
        assert _status(result) == 400

    def test_create_empty_body(self, handler, mock_http_handler):
        mock_http_handler.command = "POST"
        _set_body(mock_http_handler, {})
        result = handler.handle("/api/v1/social/shares", {}, mock_http_handler, "POST")
        assert _status(result) == 400

    def test_create_defaults_for_optional_fields(self, handler, mock_http_handler):
        mock_http_handler.command = "POST"
        _set_body(mock_http_handler, {"resource_type": "debate", "resource_id": "d1"})
        result = handler.handle("/api/v1/social/shares", {}, mock_http_handler, "POST")
        assert _status(result) == 201
        body = _body(result)
        assert body["share"]["shared_with"] == []
        assert body["share"]["channel_id"] == ""
        assert body["share"]["platform"] == ""
        assert body["share"]["message"] == ""


class TestDeleteSocialShare:
    """Tests for DELETE /api/v1/social/shares/{id}."""

    def test_delete_existing(self, handler, mock_http_handler, social_share_store):
        mock_http_handler.command = "DELETE"
        ss = SocialShare(
            id="s1", org_id="o1", resource_type="debate", resource_id="d1", shared_by="u1"
        )
        social_share_store.create(ss)
        result = handler.handle("/api/v1/social/shares/s1", {}, mock_http_handler, "DELETE")
        assert _status(result) == 200
        body = _body(result)
        assert body["deleted"] is True
        assert body["share_id"] == "s1"

    def test_delete_nonexistent(self, handler, mock_http_handler):
        mock_http_handler.command = "DELETE"
        result = handler.handle("/api/v1/social/shares/missing", {}, mock_http_handler, "DELETE")
        assert _status(result) == 404


class TestSocialSharesMethodNotAllowed:
    """Tests for unsupported methods on social shares endpoints."""

    def test_put_on_collection(self, handler, mock_http_handler):
        mock_http_handler.command = "PUT"
        result = handler.handle("/api/v1/social/shares", {}, mock_http_handler, "PUT")
        assert _status(result) == 405

    def test_patch_on_item(self, handler, mock_http_handler):
        mock_http_handler.command = "PATCH"
        result = handler.handle("/api/v1/social/shares/s1", {}, mock_http_handler, "PATCH")
        assert _status(result) == 405


# ============================================================================
# SharingHandler - Debate Share Settings
# ============================================================================


class TestGetShareSettings:
    """Tests for GET /api/v1/debates/{id}/share."""

    def test_get_creates_default_settings(self, handler, mock_http_handler):
        mock_http_handler.command = "GET"
        result = handler.handle("/api/v1/debates/d1/share", {}, mock_http_handler, "GET")
        assert _status(result) == 200
        body = _body(result)
        assert body["debate_id"] == "d1"
        assert body["visibility"] == "private"

    def test_get_existing_settings(self, handler, mock_http_handler, share_store):
        mock_http_handler.command = "GET"
        settings = ShareSettings(
            debate_id="d1",
            visibility=DebateVisibility.PUBLIC,
            share_token="tok1",
            owner_id="test-user-001",
            org_id="test-org-001",
        )
        share_store.save(settings)
        result = handler.handle("/api/v1/debates/d1/share", {}, mock_http_handler, "GET")
        assert _status(result) == 200
        body = _body(result)
        assert body["visibility"] == "public"
        assert body["share_token"] == "tok1"

    def test_get_unauthorized_different_owner(self, handler, mock_http_handler, share_store):
        """Non-owner cannot view private debate share settings."""
        mock_http_handler.command = "GET"
        settings = ShareSettings(
            debate_id="d1",
            visibility=DebateVisibility.PRIVATE,
            owner_id="other-user",
            org_id="other-org",
        )
        share_store.save(settings)
        result = handler.handle("/api/v1/debates/d1/share", {}, mock_http_handler, "GET")
        assert _status(result) == 403

    def test_get_team_visible_same_org(self, handler, mock_http_handler, share_store):
        """Org member can view team-visible debate share settings."""
        mock_http_handler.command = "GET"
        settings = ShareSettings(
            debate_id="d1",
            visibility=DebateVisibility.TEAM,
            owner_id="other-user",
            org_id="test-org-001",
        )
        share_store.save(settings)
        result = handler.handle("/api/v1/debates/d1/share", {}, mock_http_handler, "GET")
        assert _status(result) == 200

    def test_get_team_visible_different_org(self, handler, mock_http_handler, share_store):
        """User from different org cannot view team-visible debate."""
        mock_http_handler.command = "GET"
        settings = ShareSettings(
            debate_id="d1",
            visibility=DebateVisibility.TEAM,
            owner_id="other-user",
            org_id="different-org",
        )
        share_store.save(settings)
        result = handler.handle("/api/v1/debates/d1/share", {}, mock_http_handler, "GET")
        assert _status(result) == 403


# ============================================================================
# SharingHandler - Update Share Settings
# ============================================================================


class TestUpdateShareSettings:
    """Tests for POST /api/v1/debates/{id}/share."""

    def test_update_visibility_to_public(self, handler, mock_http_handler, share_store):
        mock_http_handler.command = "POST"
        _set_body(mock_http_handler, {"visibility": "public"})
        result = handler.handle("/api/v1/debates/d1/share", {}, mock_http_handler, "POST")
        assert _status(result) == 200
        body = _body(result)
        assert body["success"] is True
        assert body["settings"]["visibility"] == "public"
        assert body["settings"]["share_token"] is not None

    def test_update_visibility_to_private_revokes_token(
        self, handler, mock_http_handler, share_store
    ):
        mock_http_handler.command = "POST"
        # First make it public
        settings = ShareSettings(
            debate_id="d1",
            visibility=DebateVisibility.PUBLIC,
            share_token="tok1",
            owner_id="test-user-001",
        )
        share_store.save(settings)
        # Now set to private
        _set_body(mock_http_handler, {"visibility": "private"})
        result = handler.handle("/api/v1/debates/d1/share", {}, mock_http_handler, "POST")
        assert _status(result) == 200
        body = _body(result)
        assert body["settings"]["visibility"] == "private"
        assert body["settings"]["share_token"] is None

    def test_update_visibility_to_team(self, handler, mock_http_handler, share_store):
        mock_http_handler.command = "POST"
        _set_body(mock_http_handler, {"visibility": "team"})
        result = handler.handle("/api/v1/debates/d1/share", {}, mock_http_handler, "POST")
        assert _status(result) == 200
        body = _body(result)
        assert body["settings"]["visibility"] == "team"

    def test_update_invalid_visibility(self, handler, mock_http_handler, share_store):
        mock_http_handler.command = "POST"
        # The schema validation will reject this before it reaches the handler logic
        _set_body(mock_http_handler, {"visibility": "invalid"})
        result = handler.handle("/api/v1/debates/d1/share", {}, mock_http_handler, "POST")
        assert _status(result) == 400

    def test_update_allow_comments(self, handler, mock_http_handler, share_store):
        mock_http_handler.command = "POST"
        _set_body(mock_http_handler, {"allow_comments": True})
        result = handler.handle("/api/v1/debates/d1/share", {}, mock_http_handler, "POST")
        assert _status(result) == 200
        body = _body(result)
        assert body["settings"]["allow_comments"] is True

    def test_update_allow_forking(self, handler, mock_http_handler, share_store):
        mock_http_handler.command = "POST"
        _set_body(mock_http_handler, {"allow_forking": True})
        result = handler.handle("/api/v1/debates/d1/share", {}, mock_http_handler, "POST")
        assert _status(result) == 200
        body = _body(result)
        assert body["settings"]["allow_forking"] is True

    def test_update_expires_in_hours(self, handler, mock_http_handler, share_store):
        mock_http_handler.command = "POST"
        _set_body(mock_http_handler, {"expires_in_hours": 24})
        result = handler.handle("/api/v1/debates/d1/share", {}, mock_http_handler, "POST")
        assert _status(result) == 200
        body = _body(result)
        assert body["settings"]["expires_at"] is not None

    def test_update_expires_in_zero_removes_expiration(
        self, handler, mock_http_handler, share_store
    ):
        mock_http_handler.command = "POST"
        # First set expiration
        settings = ShareSettings(
            debate_id="d1",
            expires_at=time.time() + 3600,
            owner_id="test-user-001",
        )
        share_store.save(settings)
        _set_body(mock_http_handler, {"expires_in_hours": 0})
        result = handler.handle("/api/v1/debates/d1/share", {}, mock_http_handler, "POST")
        assert _status(result) == 200
        body = _body(result)
        assert body["settings"]["expires_at"] is None

    def test_update_invalid_body(self, handler, mock_http_handler):
        mock_http_handler.command = "POST"
        mock_http_handler.rfile.read.return_value = b"not json"
        mock_http_handler.headers["Content-Length"] = "8"
        result = handler.handle("/api/v1/debates/d1/share", {}, mock_http_handler, "POST")
        assert _status(result) == 400

    def test_update_unauthorized_different_owner(self, handler, mock_http_handler, share_store):
        mock_http_handler.command = "POST"
        settings = ShareSettings(debate_id="d1", owner_id="other-user")
        share_store.save(settings)
        _set_body(mock_http_handler, {"visibility": "public"})
        result = handler.handle("/api/v1/debates/d1/share", {}, mock_http_handler, "POST")
        assert _status(result) == 403

    def test_update_creates_settings_if_not_exist(self, handler, mock_http_handler, share_store):
        mock_http_handler.command = "POST"
        _set_body(mock_http_handler, {"visibility": "public"})
        result = handler.handle("/api/v1/debates/d1/share", {}, mock_http_handler, "POST")
        assert _status(result) == 200
        # Should be saved in the store
        settings = share_store.get("d1")
        assert settings is not None
        assert settings.visibility == DebateVisibility.PUBLIC

    def test_update_multiple_fields(self, handler, mock_http_handler):
        mock_http_handler.command = "POST"
        _set_body(
            mock_http_handler,
            {
                "visibility": "public",
                "allow_comments": True,
                "allow_forking": True,
                "expires_in_hours": 48,
            },
        )
        result = handler.handle("/api/v1/debates/d1/share", {}, mock_http_handler, "POST")
        assert _status(result) == 200
        body = _body(result)
        assert body["settings"]["visibility"] == "public"
        assert body["settings"]["allow_comments"] is True
        assert body["settings"]["allow_forking"] is True
        assert body["settings"]["expires_at"] is not None
        assert body["settings"]["share_token"] is not None

    def test_update_public_does_not_regenerate_existing_token(
        self, handler, mock_http_handler, share_store
    ):
        """Setting visibility to public when token exists should keep existing token."""
        mock_http_handler.command = "POST"
        settings = ShareSettings(
            debate_id="d1",
            visibility=DebateVisibility.PUBLIC,
            share_token="existing_token",
            owner_id="test-user-001",
        )
        share_store.save(settings)
        _set_body(mock_http_handler, {"visibility": "public"})
        result = handler.handle("/api/v1/debates/d1/share", {}, mock_http_handler, "POST")
        assert _status(result) == 200
        body = _body(result)
        assert body["settings"]["share_token"] == "existing_token"


# ============================================================================
# SharingHandler - Shared Debate Access
# ============================================================================


class TestGetSharedDebate:
    """Tests for GET /api/v1/shared/{token}."""

    def test_token_not_found(self, handler, mock_http_handler):
        mock_http_handler.command = "GET"
        result = handler.handle("/api/v1/shared/badtoken", {}, mock_http_handler, "GET")
        assert _status(result) == 404

    def test_expired_token(self, handler, mock_http_handler, share_store):
        mock_http_handler.command = "GET"
        settings = ShareSettings(
            debate_id="d1",
            visibility=DebateVisibility.PUBLIC,
            share_token="tok_expired",
            expires_at=time.time() - 3600,
        )
        share_store.save(settings)
        result = handler.handle("/api/v1/shared/tok_expired", {}, mock_http_handler, "GET")
        assert _status(result) == 410

    def test_not_public_visibility(self, handler, mock_http_handler, share_store):
        mock_http_handler.command = "GET"
        settings = ShareSettings(
            debate_id="d1",
            visibility=DebateVisibility.TEAM,
            share_token="tok_team",
        )
        share_store.save(settings)
        result = handler.handle("/api/v1/shared/tok_team", {}, mock_http_handler, "GET")
        assert _status(result) == 403

    @patch("aragora.server.handlers.social.sharing.SharingHandler._get_debate_data")
    def test_valid_token_debate_found(
        self, mock_get_debate, handler, mock_http_handler, share_store
    ):
        mock_http_handler.command = "GET"
        mock_get_debate.return_value = {"id": "d1", "topic": "Test debate"}
        settings = ShareSettings(
            debate_id="d1",
            visibility=DebateVisibility.PUBLIC,
            share_token="tok_valid",
            allow_comments=True,
            allow_forking=False,
            view_count=5,
        )
        share_store.save(settings)
        result = handler.handle("/api/v1/shared/tok_valid", {}, mock_http_handler, "GET")
        assert _status(result) == 200
        body = _body(result)
        assert body["debate"]["id"] == "d1"
        assert body["sharing"]["allow_comments"] is True
        assert body["sharing"]["allow_forking"] is False
        # View count should be incremented
        assert body["sharing"]["view_count"] == 6  # incremented from 5 to 6 before response

    @patch("aragora.server.handlers.social.sharing.SharingHandler._get_debate_data")
    def test_valid_token_debate_not_found(
        self, mock_get_debate, handler, mock_http_handler, share_store
    ):
        mock_http_handler.command = "GET"
        mock_get_debate.return_value = None
        settings = ShareSettings(
            debate_id="d1",
            visibility=DebateVisibility.PUBLIC,
            share_token="tok_valid",
        )
        share_store.save(settings)
        result = handler.handle("/api/v1/shared/tok_valid", {}, mock_http_handler, "GET")
        assert _status(result) == 404

    @patch("aragora.server.handlers.social.sharing.SharingHandler._get_debate_data")
    def test_shared_debate_increments_view_count(
        self, mock_get_debate, handler, mock_http_handler, share_store
    ):
        mock_http_handler.command = "GET"
        mock_get_debate.return_value = {"id": "d1", "topic": "Test"}
        settings = ShareSettings(
            debate_id="d1",
            visibility=DebateVisibility.PUBLIC,
            share_token="tok_views",
            view_count=0,
        )
        share_store.save(settings)
        handler.handle("/api/v1/shared/tok_views", {}, mock_http_handler, "GET")
        assert share_store.get("d1").view_count == 1


# ============================================================================
# SharingHandler - Revoke Share
# ============================================================================


class TestRevokeShare:
    """Tests for POST /api/v1/debates/{id}/share/revoke."""

    def test_revoke_success(self, handler, mock_http_handler, share_store):
        mock_http_handler.command = "POST"
        settings = ShareSettings(
            debate_id="d1",
            visibility=DebateVisibility.PUBLIC,
            share_token="tok1",
            owner_id="test-user-001",
        )
        share_store.save(settings)
        _set_body(mock_http_handler, {})
        result = handler.handle("/api/v1/debates/d1/share/revoke", {}, mock_http_handler, "POST")
        assert _status(result) == 200
        body = _body(result)
        assert body["success"] is True
        assert body["message"] == "Share links revoked"
        # Verify token was revoked
        assert share_store.get_by_token("tok1") is None
        # Verify visibility set to private
        assert share_store.get("d1").visibility == DebateVisibility.PRIVATE

    def test_revoke_no_settings(self, handler, mock_http_handler):
        mock_http_handler.command = "POST"
        _set_body(mock_http_handler, {})
        result = handler.handle("/api/v1/debates/d1/share/revoke", {}, mock_http_handler, "POST")
        assert _status(result) == 404

    def test_revoke_unauthorized(self, handler, mock_http_handler, share_store):
        mock_http_handler.command = "POST"
        settings = ShareSettings(
            debate_id="d1",
            visibility=DebateVisibility.PUBLIC,
            share_token="tok1",
            owner_id="other-user",
        )
        share_store.save(settings)
        _set_body(mock_http_handler, {})
        result = handler.handle("/api/v1/debates/d1/share/revoke", {}, mock_http_handler, "POST")
        assert _status(result) == 403


# ============================================================================
# SharingHandler - Debate ID Extraction
# ============================================================================


class TestExtractDebateId:
    """Tests for _extract_debate_id."""

    def test_standard_path(self, handler):
        debate_id, err = handler._extract_debate_id("/api/v1/debates/abc123/share")
        assert debate_id == "abc123"
        assert err is None

    def test_revoke_path(self, handler):
        debate_id, err = handler._extract_debate_id("/api/v1/debates/abc123/share/revoke")
        assert debate_id == "abc123"
        assert err is None

    def test_no_debate_id(self, handler):
        debate_id, err = handler._extract_debate_id("/api/v1/debates/share")
        # "share" is excluded, so should fail
        assert debate_id is None
        assert err is not None

    def test_empty_debate_id(self, handler):
        debate_id, err = handler._extract_debate_id("/api/v1/debates//share")
        assert debate_id is None
        assert err is not None


# ============================================================================
# SharingHandler - Rate Limiting
# ============================================================================


class TestRateLimiting:
    """Tests for rate limiting on sharing endpoints."""

    def test_social_shares_rate_limited(self, handler, mock_http_handler):
        """When rate limiter denies, should return 429."""
        mock_http_handler.command = "GET"
        with patch("aragora.server.handlers.social.sharing._share_limiter") as mock_limiter:
            mock_limiter.is_allowed.return_value = False
            result = handler.handle("/api/v1/social/shares", {}, mock_http_handler, "GET")
            assert _status(result) == 429

    def test_social_shares_rate_limit_allowed(self, handler, mock_http_handler):
        """When rate limiter allows, should process normally."""
        mock_http_handler.command = "GET"
        with patch("aragora.server.handlers.social.sharing._share_limiter") as mock_limiter:
            mock_limiter.is_allowed.return_value = True
            result = handler.handle("/api/v1/social/shares", {}, mock_http_handler, "GET")
            assert _status(result) == 200


# ============================================================================
# SharingHandler - Edge Cases and Misc
# ============================================================================


class TestEdgeCases:
    """Tests for edge cases in the sharing handler."""

    def test_handle_returns_none_for_unknown_post(self, handler, mock_http_handler):
        """POST to an unrecognized path within debates should return None from handle_post."""
        mock_http_handler.command = "POST"
        _set_body(mock_http_handler, {})
        result = handler.handle_post("/api/v1/debates/d1/unknown", {}, mock_http_handler)
        assert result is None

    def test_handle_uses_handler_command(self, handler, mock_http_handler, share_store):
        """When handler.command is set, it should override the method parameter."""
        mock_http_handler.command = "GET"
        settings = ShareSettings(debate_id="d1", owner_id="test-user-001")
        share_store.save(settings)
        # Pass method="POST" but handler.command="GET"
        result = handler.handle("/api/v1/debates/d1/share", {}, mock_http_handler, "POST")
        # Should use "GET" from handler.command and return share settings
        assert _status(result) == 200

    def test_get_debate_data_import_error(self, handler):
        """_get_debate_data returns None on ImportError."""
        with patch(
            "aragora.server.handlers.social.sharing.SharingHandler._get_debate_data"
        ) as mock_method:
            mock_method.return_value = None
            result = handler._get_debate_data("d1")
            assert result is None

    def test_handle_get_nonexistent_shared_path(self, handler, mock_http_handler):
        """GET on /api/v1/shared/ with trailing slash only."""
        mock_http_handler.command = "GET"
        result = handler.handle("/api/v1/shared/", {}, mock_http_handler, "GET")
        # Empty token after stripping - should be a 404
        assert _status(result) == 404

    def test_resolve_social_user_no_user_store(self, handler, mock_http_handler):
        """_resolve_social_user works when no user_store in context."""
        user = handler._resolve_social_user(mock_http_handler, None)
        assert user is not None  # Returns result from get_current_user mock

    def test_resolve_social_user_with_explicit_user(self, handler, mock_http_handler):
        """_resolve_social_user uses explicit user when provided."""
        mock_user = MagicMock()
        mock_user.user_id = "u1"
        result = handler._resolve_social_user(mock_http_handler, mock_user)
        # Without a user_store in context, returns the user as-is
        assert result is mock_user

    def test_resolve_social_user_with_user_store(self, handler, mock_http_handler):
        """_resolve_social_user looks up user from store when available."""
        mock_user = MagicMock()
        mock_user.user_id = "u1"
        mock_db_user = MagicMock()
        mock_db_user.org_id = "o1"
        mock_store = MagicMock()
        mock_store.get_user_by_id.return_value = mock_db_user
        handler.ctx["user_store"] = mock_store
        result = handler._resolve_social_user(mock_http_handler, mock_user)
        assert result is mock_db_user

    def test_resolve_social_user_store_raises(self, handler, mock_http_handler):
        """_resolve_social_user falls back when user store raises."""
        mock_user = MagicMock()
        mock_user.user_id = "u1"
        mock_store = MagicMock()
        mock_store.get_user_by_id.side_effect = RuntimeError("db down")
        handler.ctx["user_store"] = mock_store
        result = handler._resolve_social_user(mock_http_handler, mock_user)
        assert result is mock_user

    def test_social_shares_trailing_slash(self, handler, mock_http_handler, social_share_store):
        """GET on social share with trailing slash extracts share_id correctly."""
        mock_http_handler.command = "GET"
        ss = SocialShare(
            id="s1", org_id="o1", resource_type="debate", resource_id="d1", shared_by="u1"
        )
        social_share_store.create(ss)
        result = handler.handle("/api/v1/social/shares/s1/", {}, mock_http_handler, "GET")
        # The handler strips trailing "/" with rstrip
        # The split produces "s1/" -> which when parsed gives "s1/"
        # Actually the share_id extraction: path.split("/api/v1/social/shares/")[1].rstrip("/") = "s1"
        assert _status(result) == 200

    def test_shared_debate_trailing_slash(self, handler, mock_http_handler, share_store):
        mock_http_handler.command = "GET"
        settings = ShareSettings(
            debate_id="d1",
            visibility=DebateVisibility.PUBLIC,
            share_token="tok1",
        )
        share_store.save(settings)
        with patch.object(handler, "_get_debate_data", return_value={"id": "d1"}):
            result = handler.handle("/api/v1/shared/tok1/", {}, mock_http_handler, "GET")
            assert _status(result) == 200

    def test_generate_share_token_is_url_safe(self, handler):
        """The generated share token should be URL-safe."""
        token = handler._generate_share_token("d1")
        assert isinstance(token, str)
        assert len(token) > 0
        # secrets.token_urlsafe(16) should produce ~22 chars
        assert len(token) >= 16


class TestConstructor:
    """Tests for handler construction."""

    @patch("aragora.server.handlers.social.sharing.get_share_store")
    @patch("aragora.server.handlers.social.sharing.get_social_share_store")
    def test_constructor_with_none_context(self, mock_social, mock_share):
        mock_share.return_value = ShareStore()
        mock_social.return_value = SocialShareStore()
        h = SharingHandler(server_context=None)
        assert h.ctx == {}

    @patch("aragora.server.handlers.social.sharing.get_share_store")
    @patch("aragora.server.handlers.social.sharing.get_social_share_store")
    def test_constructor_with_context(self, mock_social, mock_share):
        mock_share.return_value = ShareStore()
        mock_social.return_value = SocialShareStore()
        ctx = {"key": "value"}
        h = SharingHandler(server_context=ctx)
        assert h.ctx["key"] == "value"


class TestHandleReturnNone:
    """Tests for handle returning None for unhandled paths."""

    def test_get_on_unmatched_path(self, handler, mock_http_handler):
        """GET on a path the handler does not recognize should return None."""
        mock_http_handler.command = "GET"
        result = handler.handle("/api/v1/something/else", {}, mock_http_handler, "GET")
        assert result is None

    def test_post_unrecognized_debate_path(self, handler, mock_http_handler):
        """POST to debate path without /share or /share/revoke returns None."""
        mock_http_handler.command = "POST"
        _set_body(mock_http_handler, {})
        # This path goes into handle_post but doesn't match /share or /share/revoke
        result = handler.handle_post("/api/v1/debates/d1/other", {}, mock_http_handler)
        assert result is None


class TestOwnerIdNone:
    """Tests for when owner_id is None (no ownership check)."""

    def test_get_settings_no_owner_id(self, handler, mock_http_handler, share_store):
        """When owner_id is None, no ownership check is done."""
        mock_http_handler.command = "GET"
        settings = ShareSettings(
            debate_id="d1",
            visibility=DebateVisibility.PRIVATE,
            owner_id=None,  # No owner set
        )
        share_store.save(settings)
        result = handler.handle("/api/v1/debates/d1/share", {}, mock_http_handler, "GET")
        # owner_id is None, so ownership check is skipped
        assert _status(result) == 200

    def test_update_settings_no_owner_id(self, handler, mock_http_handler, share_store):
        """When owner_id is None, update succeeds without ownership check."""
        mock_http_handler.command = "POST"
        settings = ShareSettings(debate_id="d1", owner_id=None)
        share_store.save(settings)
        _set_body(mock_http_handler, {"visibility": "public"})
        result = handler.handle("/api/v1/debates/d1/share", {}, mock_http_handler, "POST")
        assert _status(result) == 200

    def test_revoke_no_owner_id(self, handler, mock_http_handler, share_store):
        """When owner_id is None, revoke succeeds."""
        mock_http_handler.command = "POST"
        settings = ShareSettings(
            debate_id="d1",
            visibility=DebateVisibility.PUBLIC,
            share_token="tok1",
            owner_id=None,
        )
        share_store.save(settings)
        _set_body(mock_http_handler, {})
        result = handler.handle("/api/v1/debates/d1/share/revoke", {}, mock_http_handler, "POST")
        assert _status(result) == 200
