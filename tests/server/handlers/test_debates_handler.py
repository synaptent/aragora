"""
Tests for the DebatesHandler module.
Tests cover:
- Handler routing for all debate endpoints
- can_handle method
- ROUTES attribute
- AUTH_REQUIRED_ENDPOINTS attribute
- Response formatting
- Error handling
"""

import pytest
from unittest.mock import MagicMock, patch


class TestDebatesHandlerImport:
    """Tests for importing DebatesHandler."""

    def test_can_import_handler(self):
        """DebatesHandler can be imported."""
        from aragora.server.handlers.debates.handler import DebatesHandler

        assert DebatesHandler is not None

    def test_can_import_from_debates_module(self):
        """DebatesHandler can be imported from debates module."""
        from aragora.server.handlers.debates import handler

        assert hasattr(handler, "DebatesHandler")


class TestDebatesHandlerRoutes:
    """Tests for DebatesHandler ROUTES attribute."""

    @pytest.fixture
    def handler(self):
        """Create handler instance."""
        from aragora.server.handlers.debates.handler import DebatesHandler

        return DebatesHandler(server_context={})

    def test_routes_is_list(self, handler):
        """ROUTES is a list."""
        assert isinstance(handler.ROUTES, list)

    def test_routes_not_empty(self, handler):
        """ROUTES is not empty."""
        assert len(handler.ROUTES) > 0

    def test_debates_list_route_in_routes(self, handler):
        """Debates list route is in ROUTES."""
        assert "/api/v1/debates" in handler.ROUTES

    def test_debate_post_route_in_routes(self, handler):
        """Legacy debate POST route is in ROUTES."""
        assert "/api/v1/debate" in handler.ROUTES

    def test_batch_route_in_routes(self, handler):
        """Batch route is in ROUTES."""
        assert "/api/v1/debates/batch" in handler.ROUTES

    def test_search_route_in_routes(self, handler):
        """Search route is in ROUTES."""
        assert "/api/v1/search" in handler.ROUTES

    def test_impasse_route_pattern_in_routes(self, handler):
        """Impasse route pattern is in ROUTES."""
        assert "/api/v1/debates/*/impasse" in handler.ROUTES

    def test_convergence_route_pattern_in_routes(self, handler):
        """Convergence route pattern is in ROUTES."""
        assert "/api/v1/debates/*/convergence" in handler.ROUTES

    def test_citations_route_pattern_in_routes(self, handler):
        """Citations route pattern is in ROUTES."""
        assert "/api/v1/debates/*/citations" in handler.ROUTES

    def test_fork_route_pattern_in_routes(self, handler):
        """Fork route pattern is in ROUTES."""
        assert "/api/v1/debates/*/fork" in handler.ROUTES

    def test_messages_route_pattern_in_routes(self, handler):
        """Messages route pattern is in ROUTES."""
        assert "/api/v1/debates/*/messages" in handler.ROUTES

    def test_decision_integrity_route_pattern_in_routes(self, handler):
        """Decision integrity route pattern is in ROUTES."""
        assert "/api/v1/debates/*/decision-integrity" in handler.ROUTES


class TestDebatesHandlerAuthRequiredEndpoints:
    """Tests for AUTH_REQUIRED_ENDPOINTS attribute."""

    @pytest.fixture
    def handler(self):
        """Create handler instance."""
        from aragora.server.handlers.debates.handler import DebatesHandler

        return DebatesHandler(server_context={})

    def test_auth_required_is_list(self, handler):
        """AUTH_REQUIRED_ENDPOINTS is a list."""
        assert isinstance(handler.AUTH_REQUIRED_ENDPOINTS, list)

    def test_debates_list_is_public(self, handler):
        """Debates list endpoint is public (not in AUTH_REQUIRED_ENDPOINTS)."""
        assert "/api/v1/debates" not in handler.AUTH_REQUIRED_ENDPOINTS

    def test_batch_requires_auth(self, handler):
        """Batch endpoint requires auth."""
        assert "/api/v1/debates/batch" in handler.AUTH_REQUIRED_ENDPOINTS

    def test_export_requires_auth(self, handler):
        """Export endpoint requires auth."""
        assert "/export/" in handler.AUTH_REQUIRED_ENDPOINTS

    def test_fork_requires_auth(self, handler):
        """Fork endpoint requires auth."""
        assert "/fork" in handler.AUTH_REQUIRED_ENDPOINTS

    def test_decision_integrity_requires_auth(self, handler):
        """Decision integrity endpoint requires auth."""
        assert "/decision-integrity" in handler.AUTH_REQUIRED_ENDPOINTS


class TestDebatesHandlerCanHandle:
    """Tests for can_handle method."""

    @pytest.fixture
    def handler(self):
        """Create handler instance."""
        from aragora.server.handlers.debates.handler import DebatesHandler

        return DebatesHandler(server_context={})

    def test_can_handle_debates_list(self, handler):
        """Handler can handle /api/debates."""
        assert handler.can_handle("/api/v1/debates") is True

    def test_can_handle_debate_post(self, handler):
        """Handler can handle /api/debate (legacy POST)."""
        assert handler.can_handle("/api/v1/debate") is True

    def test_can_handle_search(self, handler):
        """Handler can handle /api/search."""
        assert handler.can_handle("/api/v1/search") is True

    def test_can_handle_debate_by_id(self, handler):
        """Handler can handle /api/debates/{id}."""
        assert handler.can_handle("/api/v1/debates/debate_123") is True

    def test_can_handle_debate_impasse(self, handler):
        """Handler can handle impasse endpoint."""
        assert handler.can_handle("/api/v1/debates/debate_123/impasse") is True

    def test_can_handle_debate_convergence(self, handler):
        """Handler can handle convergence endpoint."""
        assert handler.can_handle("/api/v1/debates/debate_123/convergence") is True

    def test_can_handle_debate_citations(self, handler):
        """Handler can handle citations endpoint."""
        assert handler.can_handle("/api/v1/debates/debate_123/citations") is True

    def test_can_handle_debate_messages(self, handler):
        """Handler can handle messages endpoint."""
        assert handler.can_handle("/api/v1/debates/debate_123/messages") is True

    def test_can_handle_debate_fork(self, handler):
        """Handler can handle fork endpoint."""
        assert handler.can_handle("/api/v1/debates/debate_123/fork") is True

    def test_can_handle_decision_integrity(self, handler):
        """Handler can handle decision integrity endpoint."""
        assert handler.can_handle("/api/v1/debates/debate_123/decision-integrity") is True

    def test_can_handle_meta_critique(self, handler):
        """Handler can handle meta-critique endpoint."""
        assert handler.can_handle("/api/v1/debate/debate_123/meta-critique") is True

    def test_can_handle_graph_stats(self, handler):
        """Handler can handle graph stats endpoint."""
        assert handler.can_handle("/api/v1/debate/debate_123/graph/stats") is True

    def test_cannot_handle_unrelated_path(self, handler):
        """Handler does not handle unrelated paths."""
        assert handler.can_handle("/api/v1/agents") is False

    def test_cannot_handle_partial_path(self, handler):
        """Handler does not handle partial paths."""
        assert handler.can_handle("/api/v1/debat") is False


class TestDebatesHandlerRequiresAuth:
    """Tests for _requires_auth method."""

    @pytest.fixture
    def handler(self):
        """Create handler instance."""
        from aragora.server.handlers.debates.handler import DebatesHandler

        return DebatesHandler(server_context={})

    def test_debates_list_is_public(self, handler):
        """Debates list path is public (no auth required)."""
        assert handler._requires_auth("/api/v1/debates") is False

    def test_batch_requires_auth(self, handler):
        """Batch path requires auth."""
        assert handler._requires_auth("/api/v1/debates/batch") is True

    def test_export_requires_auth(self, handler):
        """Export path requires auth."""
        assert handler._requires_auth("/api/v1/debates/123/export/json") is True

    def test_fork_requires_auth(self, handler):
        """Fork path requires auth."""
        assert handler._requires_auth("/api/v1/debates/123/fork") is True

    def test_impasse_path_is_public(self, handler):
        """Impasse is a public read endpoint (not in AUTH_REQUIRED_ENDPOINTS)."""
        result = handler._requires_auth("/api/v1/debates/123/impasse")
        assert result is False


class TestDebatesHandlerAllowedFormats:
    """Tests for allowed export formats."""

    @pytest.fixture
    def handler(self):
        """Create handler instance."""
        from aragora.server.handlers.debates.handler import DebatesHandler

        return DebatesHandler(server_context={})

    def test_allowed_formats_is_set(self, handler):
        """ALLOWED_EXPORT_FORMATS is a set."""
        assert isinstance(handler.ALLOWED_EXPORT_FORMATS, set)

    def test_json_is_allowed(self, handler):
        """JSON format is allowed."""
        assert "json" in handler.ALLOWED_EXPORT_FORMATS

    def test_csv_is_allowed(self, handler):
        """CSV format is allowed."""
        assert "csv" in handler.ALLOWED_EXPORT_FORMATS

    def test_html_is_allowed(self, handler):
        """HTML format is allowed."""
        assert "html" in handler.ALLOWED_EXPORT_FORMATS

    def test_md_is_allowed(self, handler):
        """Markdown format is allowed."""
        assert "md" in handler.ALLOWED_EXPORT_FORMATS


class TestDebatesHandlerAllowedTables:
    """Tests for allowed export tables."""

    @pytest.fixture
    def handler(self):
        """Create handler instance."""
        from aragora.server.handlers.debates.handler import DebatesHandler

        return DebatesHandler(server_context={})

    def test_allowed_tables_is_set(self, handler):
        """ALLOWED_EXPORT_TABLES is a set."""
        assert isinstance(handler.ALLOWED_EXPORT_TABLES, set)

    def test_summary_is_allowed(self, handler):
        """Summary table is allowed."""
        assert "summary" in handler.ALLOWED_EXPORT_TABLES

    def test_messages_is_allowed(self, handler):
        """Messages table is allowed."""
        assert "messages" in handler.ALLOWED_EXPORT_TABLES

    def test_critiques_is_allowed(self, handler):
        """Critiques table is allowed."""
        assert "critiques" in handler.ALLOWED_EXPORT_TABLES

    def test_votes_is_allowed(self, handler):
        """Votes table is allowed."""
        assert "votes" in handler.ALLOWED_EXPORT_TABLES


class TestDebatesHandlerSuffixRoutes:
    """Tests for SUFFIX_ROUTES dispatch table."""

    @pytest.fixture
    def handler(self):
        """Create handler instance."""
        from aragora.server.handlers.debates.handler import DebatesHandler

        return DebatesHandler(server_context={})

    def test_suffix_routes_is_list(self, handler):
        """SUFFIX_ROUTES is a list."""
        assert isinstance(handler.SUFFIX_ROUTES, list)

    def test_suffix_routes_not_empty(self, handler):
        """SUFFIX_ROUTES is not empty."""
        assert len(handler.SUFFIX_ROUTES) > 0

    def test_suffix_routes_are_tuples(self, handler):
        """SUFFIX_ROUTES entries are tuples."""
        for route in handler.SUFFIX_ROUTES:
            assert isinstance(route, tuple)
            assert len(route) == 4  # (suffix, method_name, needs_id, extra_params)

    def test_impasse_suffix_route_exists(self, handler):
        """Impasse suffix route exists."""
        suffixes = [r[0] for r in handler.SUFFIX_ROUTES]
        assert "/impasse" in suffixes

    def test_convergence_suffix_route_exists(self, handler):
        """Convergence suffix route exists."""
        suffixes = [r[0] for r in handler.SUFFIX_ROUTES]
        assert "/convergence" in suffixes

    def test_citations_suffix_route_exists(self, handler):
        """Citations suffix route exists."""
        suffixes = [r[0] for r in handler.SUFFIX_ROUTES]
        assert "/citations" in suffixes


class TestDebatesHandlerCheckAuth:
    """Tests for _check_auth method."""

    @pytest.fixture
    def handler(self):
        """Create handler instance."""
        from aragora.server.handlers.debates.handler import DebatesHandler

        return DebatesHandler(server_context={})

    def test_check_auth_with_none_handler(self, handler):
        """Returns None for None handler."""
        result = handler._check_auth(None)
        assert result is None

    @patch("aragora.server.auth.auth_config")
    def test_check_auth_disabled_returns_none(self, mock_auth_config, handler):
        """Returns None when auth is disabled."""
        mock_auth_config.enabled = False

        mock_http = MagicMock()
        result = handler._check_auth(mock_http)

        assert result is None

    @patch("aragora.server.auth.auth_config")
    def test_check_auth_no_token_configured_returns_none(self, mock_auth_config, handler):
        """Returns None when no API token configured."""
        mock_auth_config.enabled = True
        mock_auth_config.api_token = None

        mock_http = MagicMock()
        mock_http.headers = {}
        result = handler._check_auth(mock_http)

        assert result is None

    @patch("aragora.server.auth.auth_config")
    def test_check_auth_invalid_token_returns_401(self, mock_auth_config, handler):
        """Returns 401 for invalid token."""
        mock_auth_config.enabled = True
        mock_auth_config.api_token = "valid_token"
        mock_auth_config.validate_token = MagicMock(return_value=False)

        mock_http = MagicMock()
        mock_http.headers = {"Authorization": "Bearer invalid_token"}
        result = handler._check_auth(mock_http)

        assert result is not None
        assert result.status_code == 401

    @patch("aragora.server.auth.auth_config")
    def test_check_auth_valid_token_returns_none(self, mock_auth_config, handler):
        """Returns None for valid token."""
        mock_auth_config.enabled = True
        mock_auth_config.api_token = "valid_token"
        mock_auth_config.validate_token = MagicMock(return_value=True)

        mock_http = MagicMock()
        mock_http.headers = {"Authorization": "Bearer valid_token"}
        result = handler._check_auth(mock_http)

        assert result is None


class TestDebatesHandlerInheritance:
    """Tests for handler inheritance."""

    def test_inherits_from_base_handler(self):
        """DebatesHandler inherits from BaseHandler."""
        from aragora.server.handlers.debates.handler import DebatesHandler
        from aragora.server.handlers.base import BaseHandler

        assert issubclass(DebatesHandler, BaseHandler)

    def test_inherits_from_analysis_mixin(self):
        """DebatesHandler inherits from AnalysisOperationsMixin."""
        from aragora.server.handlers.debates.handler import DebatesHandler
        from aragora.server.handlers.debates.analysis import AnalysisOperationsMixin

        assert issubclass(DebatesHandler, AnalysisOperationsMixin)

    def test_inherits_from_export_mixin(self):
        """DebatesHandler inherits from ExportOperationsMixin."""
        from aragora.server.handlers.debates.handler import DebatesHandler
        from aragora.server.handlers.debates.export import ExportOperationsMixin

        assert issubclass(DebatesHandler, ExportOperationsMixin)

    def test_inherits_from_fork_mixin(self):
        """DebatesHandler inherits from ForkOperationsMixin."""
        from aragora.server.handlers.debates.handler import DebatesHandler
        from aragora.server.handlers.debates.fork import ForkOperationsMixin

        assert issubclass(DebatesHandler, ForkOperationsMixin)

    def test_inherits_from_search_mixin(self):
        """DebatesHandler inherits from SearchOperationsMixin."""
        from aragora.server.handlers.debates.handler import DebatesHandler
        from aragora.server.handlers.debates.search import SearchOperationsMixin

        assert issubclass(DebatesHandler, SearchOperationsMixin)

    def test_inherits_from_batch_mixin(self):
        """DebatesHandler inherits from BatchOperationsMixin."""
        from aragora.server.handlers.debates.handler import DebatesHandler
        from aragora.server.handlers.debates.batch import BatchOperationsMixin

        assert issubclass(DebatesHandler, BatchOperationsMixin)


class TestDebatesHandlerArtifactEndpoints:
    """Tests for ARTIFACT_ENDPOINTS attribute."""

    @pytest.fixture
    def handler(self):
        """Create handler instance."""
        from aragora.server.handlers.debates.handler import DebatesHandler

        return DebatesHandler(server_context={})

    def test_artifact_endpoints_is_set(self, handler):
        """ARTIFACT_ENDPOINTS is a set."""
        assert isinstance(handler.ARTIFACT_ENDPOINTS, set)

    def test_messages_is_artifact(self, handler):
        """Messages endpoint is an artifact."""
        assert "/messages" in handler.ARTIFACT_ENDPOINTS

    def test_evidence_is_artifact(self, handler):
        """Evidence endpoint is an artifact."""
        assert "/evidence" in handler.ARTIFACT_ENDPOINTS

    def test_verification_report_is_artifact(self, handler):
        """Verification report endpoint is an artifact."""
        assert "/verification-report" in handler.ARTIFACT_ENDPOINTS


class TestDebatesHandlerDispatchSuffixRoute:
    """Tests for _dispatch_suffix_route method."""

    @pytest.fixture
    def handler(self):
        """Create handler instance with mock storage."""
        from aragora.server.handlers.debates.handler import DebatesHandler

        mock_storage = MagicMock()
        mock_storage.is_public = MagicMock(return_value=True)
        mock_storage.get_read_access = MagicMock(side_effect=lambda ref: (ref, "org-1", True))
        return DebatesHandler(server_context={"storage": mock_storage})

    def test_dispatch_returns_none_for_unknown_suffix(self, handler):
        """Returns None for unknown suffix."""
        result = handler._dispatch_suffix_route(
            "/api/v1/debates/123/unknown",
            {},
            MagicMock(),
        )
        assert result is None

    def test_dispatch_calls_impasse_method(self, handler):
        """Dispatches to _get_impasse for impasse suffix."""
        with patch.object(handler, "_get_impasse") as mock_method:
            mock_method.return_value = MagicMock()
            with patch.object(handler, "_extract_debate_id") as mock_extract:
                mock_extract.return_value = ("debate_123", None)
                handler._dispatch_suffix_route(
                    "/api/v1/debates/debate_123/impasse",
                    {},
                    MagicMock(),
                )
                mock_method.assert_called_once()
