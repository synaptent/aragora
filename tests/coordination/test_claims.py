"""Tests for the advisory file claim protocol."""

from __future__ import annotations

import json
import time

import pytest

from aragora.coordination.claims import ClaimManager, ClaimStatus, FileClaim


class TestFileClaim:
    def test_roundtrip(self):
        claim = FileClaim(
            claim_id="abc",
            session_id="claude-1",
            paths=["aragora/server/auth.py"],
            intent="OIDC refactor",
            claimed_at=time.time(),
        )
        data = claim.to_dict()
        restored = FileClaim.from_dict(data)
        assert restored.claim_id == "abc"
        assert restored.paths == ["aragora/server/auth.py"]
        assert restored.intent == "OIDC refactor"

    def test_is_active(self):
        claim = FileClaim(
            claim_id="x",
            session_id="s",
            paths=[],
            intent="",
            claimed_at=time.time(),
            ttl_minutes=30,
        )
        assert claim.is_active is True
        assert claim.is_expired is False

    def test_is_expired(self):
        claim = FileClaim(
            claim_id="x",
            session_id="s",
            paths=[],
            intent="",
            claimed_at=time.time() - 3600,
            ttl_minutes=1,
        )
        assert claim.is_expired is True
        assert claim.is_active is False

    def test_released_not_active(self):
        claim = FileClaim(
            claim_id="x",
            session_id="s",
            paths=[],
            intent="",
            claimed_at=time.time(),
            released=True,
        )
        assert claim.is_active is False


class TestClaimManager:
    def test_claim_granted_no_overlap(self, tmp_path):
        mgr = ClaimManager(repo_path=tmp_path)
        result = mgr.claim(
            ["aragora/server/auth.py"],
            session_id="claude-1",
            intent="OIDC refactor",
        )
        assert result.status == ClaimStatus.GRANTED
        assert result.claim.session_id == "claude-1"
        assert result.contested_by == []

    def test_claim_contested_overlap(self, tmp_path):
        mgr = ClaimManager(repo_path=tmp_path)
        mgr.claim(["aragora/server/auth.py"], session_id="claude-1")
        result = mgr.claim(["aragora/server/auth.py"], session_id="codex-2")

        assert result.status == ClaimStatus.CONTESTED
        assert len(result.contested_by) == 1
        assert result.contested_by[0].session_id == "claude-1"
        assert "aragora/server/auth.py" in result.contested_paths

    def test_same_session_not_contested(self, tmp_path):
        mgr = ClaimManager(repo_path=tmp_path)
        mgr.claim(["file.py"], session_id="claude-1")
        result = mgr.claim(["file.py"], session_id="claude-1")
        assert result.status == ClaimStatus.GRANTED

    def test_claim_with_glob_overlap(self, tmp_path):
        mgr = ClaimManager(repo_path=tmp_path)
        mgr.claim(["sdk/**"], session_id="claude-1")
        result = mgr.claim(["sdk/python/client.py"], session_id="codex-2")

        # fnmatch("sdk/python/client.py", "sdk/**") checks for match
        assert result.status == ClaimStatus.CONTESTED

    def test_release_removes_claims(self, tmp_path):
        mgr = ClaimManager(repo_path=tmp_path)
        mgr.claim(["file1.py"], session_id="claude-1")
        mgr.claim(["file2.py"], session_id="claude-1")

        released = mgr.release("claude-1")
        assert released == 2

        # New claim should be uncontested
        result = mgr.claim(["file1.py"], session_id="codex-2")
        assert result.status == ClaimStatus.GRANTED

    def test_release_nonexistent(self, tmp_path):
        mgr = ClaimManager(repo_path=tmp_path)
        assert mgr.release("nonexistent") == 0

    def test_expired_claims_auto_cleaned(self, tmp_path):
        mgr = ClaimManager(repo_path=tmp_path)

        # Manually write an expired claim
        claims_dir = tmp_path / ".aragora_coordination" / "claims"
        claims_dir.mkdir(parents=True)
        expired = {
            "claim_id": "old1",
            "session_id": "old-session",
            "paths": ["file.py"],
            "intent": "",
            "claimed_at": time.time() - 7200,
            "ttl_minutes": 30,
            "released": False,
        }
        (claims_dir / "old1.json").write_text(json.dumps(expired))

        result = mgr.claim(["file.py"], session_id="new-session")
        assert result.status == ClaimStatus.GRANTED

    def test_check_returns_holders(self, tmp_path):
        mgr = ClaimManager(repo_path=tmp_path)
        mgr.claim(["file.py"], session_id="claude-1")

        holders = mgr.check(["file.py"])
        assert len(holders) == 1
        assert holders[0].session_id == "claude-1"

    def test_check_no_holders(self, tmp_path):
        mgr = ClaimManager(repo_path=tmp_path)
        assert mgr.check(["unclaimed.py"]) == []

    def test_list_all(self, tmp_path):
        mgr = ClaimManager(repo_path=tmp_path)
        mgr.claim(["a.py"], session_id="s1")
        mgr.claim(["b.py"], session_id="s2")

        all_claims = mgr.list_all()
        assert len(all_claims) == 2

    def test_custom_ttl(self, tmp_path):
        mgr = ClaimManager(repo_path=tmp_path)
        result = mgr.claim(["file.py"], session_id="s1", ttl_minutes=5)
        assert result.claim.ttl_minutes == 5

    def test_claim_always_granted_advisory(self, tmp_path):
        """Claims are advisory — even contested claims are stored."""
        mgr = ClaimManager(repo_path=tmp_path)
        mgr.claim(["file.py"], session_id="s1")
        result = mgr.claim(["file.py"], session_id="s2")

        # Contested but claim still exists
        assert result.status == ClaimStatus.CONTESTED
        all_claims = mgr.list_all()
        assert len(all_claims) == 2
