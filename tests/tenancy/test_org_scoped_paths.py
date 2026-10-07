"""The org-scoped route matcher used by the pre-handler static-token denial."""

from __future__ import annotations

import pytest

from aragora.tenancy.record_scope import ORG_REQUIRED, is_org_scoped_path, static_token_denial

STATIC_TOKEN = "org-scoped-paths-static-token-0123456789"

# One concrete path per route family (isolation inventory sections A-E plus
# the decision workspace), written without a version prefix.
FAMILY_PATHS = [
    "/api/plans",
    "/api/plans/plan-1/execute",
    "/api/decisions",
    "/api/decisions/plans/plan-1/approve",
    "/api/runs",
    "/api/runs/run-1",
    "/api/documents",
    "/api/documents/doc-1/chunks",
    "/api/documents/batch/job-1/results",
    "/api/knowledge/jobs",
    "/api/knowledge/jobs/job-1",
    "/api/receipts",
    "/api/receipts/rcpt-1/share",
    "/api/receipts/rcpt-1/verify",
    "/api/receipts/verify-batch",
    "/api/receipts/deliveries",
    "/api/gauntlet",
    "/api/gauntlet/receipts",
    "/api/gauntlet/run-1/receipt",
    "/api/gauntlet/run-1",
    "/api/debates",
    "/api/debates/batch",
    "/api/debates/batch/",
    "/api/debates/deb-1",
    "/api/debates/deb-1/messages",
    "/api/debates/deb-1/share",
    "/api/debate",
    "/api/debate-this",
    "/api/search",
    "/api/graph-debates/g-1",
    "/api/matrix-debates",
    "/api/pipeline",
    "/api/pipeline/pipe-1/execute",
    "/api/pipeline/transitions",
    "/api/pipeline/dag/d-1",
    "/api/canvas/pipeline",
    "/api/canvas/pipeline/p-1/graph",
    "/api/workspace",
    "/api/workspace/decisions/dec-1/actions",
    "/api/checkpoints",
    "/api/checkpoints/resumable",
    "/api/checkpoints/cp-1/intervention",
]

PUBLIC_PATHS = [
    "/api/receipts/share/tok-123",
    "/api/receipts/signing-key",
    "/api/receipts/verify",
    "/api/debates/public",
    "/api/debates/public/deb-1",
    "/api/debates/public/deb-1/og",
    "/api/debates/deb-1/spectate/public",
    "/api/gauntlet/personas",
]

OTHER_PATHS = [
    "/api/auth/login",
    "/api/auth/me",
    "/api/health",
    "/api/agents",
    "/api/memory/stats",
    "/api/workspaces",
    "/api/workspaces/ws-1",
    "/api/canvas",
    "/api/canvas/c-1",
    "/api/knowledge",
    "/api/knowledge/search",
    "/api/playground/debate",
    "/api/spectate/recent",
    "/api/plansx",
    "/api/debatesx",
    "/api/debate-thisx",
    "/api/searches",
    "/api/checkpointsx",
    "/.well-known/aragora-odr-signing-key",
    "/healthz",
    "/",
    "",
    "/api",
    "/api/",
]


def _versions(path: str) -> list[str]:
    rest = path.removeprefix("/api")
    return [path, f"/api/v1{rest}", f"/api/v2{rest}", f"/api/v9{rest}"]


class TestIsOrgScopedPath:
    @pytest.mark.parametrize("path", [v for p in FAMILY_PATHS for v in _versions(p)])
    def test_every_family_matches_under_every_version_alias(self, path):
        assert is_org_scoped_path(path) is True

    @pytest.mark.parametrize("path", [v for p in PUBLIC_PATHS for v in _versions(p)])
    def test_public_by_design_paths_are_excluded(self, path):
        assert is_org_scoped_path(path) is False

    @pytest.mark.parametrize("path", OTHER_PATHS)
    def test_other_paths_and_near_misses_are_not_matched(self, path):
        assert is_org_scoped_path(path) is False

    def test_versioned_forms_of_other_paths_are_not_matched(self):
        assert is_org_scoped_path("/api/v1/workspaces") is False
        assert is_org_scoped_path("/api/v1/memory/stats") is False
        assert is_org_scoped_path("/api/vx/plans") is False

    @pytest.mark.parametrize("value", [None, 42, b"/api/plans"])
    def test_non_string_is_not_matched(self, value):
        assert is_org_scoped_path(value) is False  # type: ignore[arg-type]


def _install_api_token(monkeypatch: pytest.MonkeyPatch, value: str | None):
    from aragora.server import auth as server_auth

    if value is None:
        monkeypatch.delenv("ARAGORA_API_TOKEN", raising=False)
    else:
        monkeypatch.setenv("ARAGORA_API_TOKEN", value)
    config = server_auth.AuthConfig()
    config.configure_from_env()
    monkeypatch.setattr(server_auth, "auth_config", config, raising=False)
    return config


class TestStaticTokenDenial:
    def test_static_token_on_org_scoped_path_is_org_required(self, monkeypatch):
        _install_api_token(monkeypatch, STATIC_TOKEN)
        headers = {"Authorization": f"Bearer {STATIC_TOKEN}"}

        assert static_token_denial("/api/v1/plans", headers) is ORG_REQUIRED
        assert static_token_denial("/api/v2/receipts", headers) is ORG_REQUIRED

    def test_token_signed_with_static_token_counts(self, monkeypatch):
        config = _install_api_token(monkeypatch, STATIC_TOKEN)
        signed = config.generate_token("loop-1", expires_in=600)

        assert static_token_denial("/api/v1/documents", {"Authorization": f"Bearer {signed}"}) is (
            ORG_REQUIRED
        )

    @pytest.mark.parametrize(
        "headers",
        [{}, {"Authorization": "Bearer wrong-token"}, {"Authorization": STATIC_TOKEN}],
    )
    def test_missing_or_invalid_credential_gets_no_denial(self, monkeypatch, headers):
        _install_api_token(monkeypatch, STATIC_TOKEN)

        assert static_token_denial("/api/v1/plans", headers) is None

    def test_paths_outside_the_matcher_get_no_denial(self, monkeypatch):
        _install_api_token(monkeypatch, STATIC_TOKEN)
        headers = {"Authorization": f"Bearer {STATIC_TOKEN}"}

        assert static_token_denial("/api/v1/memory/stats", headers) is None
        assert static_token_denial("/api/v2/receipts/share/tok-1", headers) is None

    def test_no_denial_when_no_static_token_is_configured(self, monkeypatch):
        _install_api_token(monkeypatch, None)

        assert static_token_denial("/api/v1/plans", {"Authorization": "Bearer anything"}) is None
