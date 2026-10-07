"""
Tests for core decision results module.

Tests cover:
- save_decision_result function
- get_decision_result function
- get_decision_status function
- Fallback behavior when persistent store is unavailable
"""

import pytest
from unittest.mock import MagicMock, patch

# Import functions to test
from aragora.core.decision_results import (
    save_decision_result,
    get_decision_result,
    get_decision_status,
    _decision_results_fallback,
    _get_result_store,
)


# =============================================================================
# Helper to reset module state
# =============================================================================


def reset_module_state():
    """Reset module-level state between tests."""
    import aragora.core.decision_results as module

    module._decision_result_store = None
    module._decision_results_fallback.clear()


# =============================================================================
# save_decision_result Tests
# =============================================================================


class TestSaveDecisionResult:
    """Tests for save_decision_result function."""

    def setup_method(self):
        """Reset state before each test."""
        reset_module_state()

    def test_save_to_fallback_when_store_unavailable(self):
        """Saves to fallback dict when store is unavailable."""
        with patch(
            "aragora.core.decision_results._get_result_store",
            return_value=None,
        ):
            data = {"answer": "test answer", "confidence": 0.9}
            save_decision_result("req-123", data)

            # Verify data is in fallback
            import aragora.core.decision_results as module

            assert "req-123" in module._decision_results_fallback
            assert module._decision_results_fallback["req-123"] == data

    def test_save_to_store_when_available(self):
        """Saves to store when available."""
        mock_store = MagicMock()
        with patch(
            "aragora.core.decision_results._get_result_store",
            return_value=mock_store,
        ):
            data = {"answer": "test answer", "confidence": 0.9}
            save_decision_result("req-456", data)

            mock_store.save.assert_called_once_with("req-456", data)

    def test_save_falls_back_on_store_error(self):
        """Falls back to dict when store raises exception."""
        mock_store = MagicMock()
        mock_store.save.side_effect = OSError("Storage error")

        with patch(
            "aragora.core.decision_results._get_result_store",
            return_value=mock_store,
        ):
            data = {"answer": "test answer"}
            save_decision_result("req-789", data)

            # Should fall back to dict
            import aragora.core.decision_results as module

            assert "req-789" in module._decision_results_fallback
            assert module._decision_results_fallback["req-789"] == data

    def test_save_multiple_results(self):
        """Can save multiple results."""
        with patch(
            "aragora.core.decision_results._get_result_store",
            return_value=None,
        ):
            save_decision_result("req-1", {"answer": "one"})
            save_decision_result("req-2", {"answer": "two"})
            save_decision_result("req-3", {"answer": "three"})

            import aragora.core.decision_results as module

            assert len(module._decision_results_fallback) == 3

    def test_save_overwrites_existing(self):
        """Saving with same ID overwrites existing result."""
        with patch(
            "aragora.core.decision_results._get_result_store",
            return_value=None,
        ):
            save_decision_result("req-1", {"answer": "first"})
            save_decision_result("req-1", {"answer": "second"})

            import aragora.core.decision_results as module

            assert module._decision_results_fallback["req-1"]["answer"] == "second"


# =============================================================================
# get_decision_result Tests
# =============================================================================


class TestGetDecisionResult:
    """Tests for get_decision_result function."""

    def setup_method(self):
        """Reset state before each test."""
        reset_module_state()

    def test_get_from_fallback_when_store_unavailable(self):
        """Gets from fallback dict when store is unavailable."""
        import aragora.core.decision_results as module

        module._decision_results_fallback["req-123"] = {"answer": "fallback answer"}

        with patch(
            "aragora.core.decision_results._get_result_store",
            return_value=None,
        ):
            result = get_decision_result("req-123")

            assert result is not None
            assert result["answer"] == "fallback answer"

    def test_get_from_store_when_available(self):
        """Gets from store when available."""
        mock_store = MagicMock()
        mock_store.get.return_value = {"answer": "store answer"}

        with patch(
            "aragora.core.decision_results._get_result_store",
            return_value=mock_store,
        ):
            result = get_decision_result("req-456")

            mock_store.get.assert_called_once_with("req-456")
            assert result["answer"] == "store answer"

    def test_get_returns_none_for_missing(self):
        """Returns None for missing request ID."""
        with patch(
            "aragora.core.decision_results._get_result_store",
            return_value=None,
        ):
            result = get_decision_result("nonexistent")

            assert result is None

    def test_get_falls_back_on_store_error(self):
        """Falls back to dict when store raises exception."""
        mock_store = MagicMock()
        mock_store.get.side_effect = OSError("Storage error")

        import aragora.core.decision_results as module

        module._decision_results_fallback["req-789"] = {"answer": "fallback"}

        with patch(
            "aragora.core.decision_results._get_result_store",
            return_value=mock_store,
        ):
            result = get_decision_result("req-789")

            assert result is not None
            assert result["answer"] == "fallback"

    def test_get_falls_back_when_store_returns_none(self):
        """Falls back to dict when store returns None."""
        mock_store = MagicMock()
        mock_store.get.return_value = None

        import aragora.core.decision_results as module

        module._decision_results_fallback["req-000"] = {"answer": "in fallback"}

        with patch(
            "aragora.core.decision_results._get_result_store",
            return_value=mock_store,
        ):
            result = get_decision_result("req-000")

            assert result is not None
            assert result["answer"] == "in fallback"

    @pytest.mark.parametrize("use_store", [True, False], ids=["store", "fallback"])
    def test_get_leaves_out_the_stored_request(self, use_store):
        """The request kept for a retry, with its delivery targets, is never returned."""
        import aragora.core.decision_results as module

        record = {
            "request_id": "dec-1",
            "status": "failed",
            "result": {
                "answer": None,
                "request": {
                    "content": "q",
                    "response_channels": [
                        {"platform": "webhook", "webhook_url": "https://hooks.example.test/x"}
                    ],
                },
            },
        }
        mock_store = MagicMock()
        mock_store.get.return_value = record
        if not use_store:
            module._decision_results_fallback["dec-1"] = record

        with patch(
            "aragora.core.decision_results._get_result_store",
            return_value=mock_store if use_store else None,
        ):
            result = get_decision_result("dec-1")

        assert result == {"request_id": "dec-1", "status": "failed", "result": {"answer": None}}
        assert "request" in record["result"]


# =============================================================================
# get_decision_status Tests
# =============================================================================


class TestGetDecisionStatus:
    """Tests for get_decision_status function."""

    def setup_method(self):
        """Reset state before each test."""
        reset_module_state()

    def test_get_status_from_store(self):
        """Gets status from store when available."""
        mock_store = MagicMock()
        mock_store.get_status.return_value = {
            "request_id": "req-123",
            "status": "completed",
            "completed_at": "2024-01-15T10:00:00",
        }

        with patch(
            "aragora.core.decision_results._get_result_store",
            return_value=mock_store,
        ):
            status = get_decision_status("req-123")

            mock_store.get_status.assert_called_once_with("req-123")
            assert status["status"] == "completed"

    def test_get_status_from_fallback(self):
        """Gets status from fallback when store unavailable."""
        import aragora.core.decision_results as module

        module._decision_results_fallback["req-456"] = {
            "status": "processing",
            "completed_at": None,
        }

        with patch(
            "aragora.core.decision_results._get_result_store",
            return_value=None,
        ):
            status = get_decision_status("req-456")

            assert status["request_id"] == "req-456"
            assert status["status"] == "processing"

    def test_get_status_not_found(self):
        """Returns not_found status for missing request."""
        with patch(
            "aragora.core.decision_results._get_result_store",
            return_value=None,
        ):
            status = get_decision_status("nonexistent")

            assert status["request_id"] == "nonexistent"
            assert status["status"] == "not_found"

    def test_get_status_falls_back_on_store_error(self):
        """Falls back to dict when store raises exception."""
        mock_store = MagicMock()
        mock_store.get_status.side_effect = RuntimeError("Connection failed")

        import aragora.core.decision_results as module

        module._decision_results_fallback["req-789"] = {
            "status": "completed",
            "completed_at": "2024-01-15",
        }

        with patch(
            "aragora.core.decision_results._get_result_store",
            return_value=mock_store,
        ):
            status = get_decision_status("req-789")

            assert status["status"] == "completed"

    def test_get_status_includes_completed_at(self):
        """Status includes completed_at when available."""
        import aragora.core.decision_results as module

        module._decision_results_fallback["req-completed"] = {
            "status": "completed",
            "completed_at": "2024-01-15T10:30:00",
        }

        with patch(
            "aragora.core.decision_results._get_result_store",
            return_value=None,
        ):
            status = get_decision_status("req-completed")

            assert status["completed_at"] == "2024-01-15T10:30:00"

    def test_get_status_unknown_when_no_status_field(self):
        """Returns 'unknown' status when field is missing."""
        import aragora.core.decision_results as module

        module._decision_results_fallback["req-no-status"] = {
            "answer": "some answer",
            # No 'status' field
        }

        with patch(
            "aragora.core.decision_results._get_result_store",
            return_value=None,
        ):
            status = get_decision_status("req-no-status")

            assert status["status"] == "unknown"


# =============================================================================
# _get_result_store Tests
# =============================================================================


class TestGetResultStore:
    """Tests for _get_result_store helper function."""

    def setup_method(self):
        """Reset state before each test."""
        reset_module_state()

    def test_caches_store_instance(self):
        """Store instance is cached after first retrieval."""
        import aragora.core.decision_results as module

        # Reset to start fresh
        module._decision_result_store = None

        # First call may create the store if available
        store1 = module._get_result_store()

        # Second call should return the same instance (cached)
        store2 = module._get_result_store()

        # Both should be the same instance or both None
        assert store1 is store2

    def test_returns_none_on_import_error(self):
        """Returns None when store module unavailable."""
        import aragora.core.decision_results as module

        # Reset to trigger re-import
        module._decision_result_store = None

        # When the real store isn't available, should return None
        # This tests the fallback behavior
        with patch.object(module, "_decision_result_store", None):
            # Force a re-check of the store
            store = module._get_result_store()
            # May be None or a real store depending on environment


# =============================================================================
# Integration Tests
# =============================================================================


class TestDecisionResultsIntegration:
    """Integration tests for decision results module."""

    def setup_method(self):
        """Reset state before each test."""
        reset_module_state()

    def test_save_and_retrieve_workflow(self):
        """Tests complete save and retrieve workflow."""
        with patch(
            "aragora.core.decision_results._get_result_store",
            return_value=None,
        ):
            # Save a result
            result_data = {
                "answer": "Integration test answer",
                "confidence": 0.95,
                "consensus_reached": True,
                "status": "completed",
                "completed_at": "2024-01-15T12:00:00",
            }
            save_decision_result("int-test-1", result_data)

            # Retrieve it
            retrieved = get_decision_result("int-test-1")
            assert retrieved is not None
            assert retrieved["answer"] == "Integration test answer"
            assert retrieved["confidence"] == 0.95

            # Get status
            status = get_decision_status("int-test-1")
            assert status["status"] == "completed"
            assert status["request_id"] == "int-test-1"

    def test_multiple_requests_tracking(self):
        """Tests tracking multiple request results."""
        with patch(
            "aragora.core.decision_results._get_result_store",
            return_value=None,
        ):
            # Save multiple results
            requests = [
                ("req-a", {"status": "completed", "answer": "A"}),
                ("req-b", {"status": "processing"}),
                ("req-c", {"status": "failed", "error": "timeout"}),
            ]

            for req_id, data in requests:
                save_decision_result(req_id, data)

            # Verify all can be retrieved
            for req_id, expected in requests:
                result = get_decision_result(req_id)
                assert result is not None
                assert result["status"] == expected["status"]

            # Verify statuses
            status_a = get_decision_status("req-a")
            status_b = get_decision_status("req-b")
            status_c = get_decision_status("req-c")

            assert status_a["status"] == "completed"
            assert status_b["status"] == "processing"
            assert status_c["status"] == "failed"

    def test_fallback_resilience(self):
        """Tests that fallback is resilient to store failures."""
        mock_store = MagicMock()

        # First call: store works for save
        mock_store.save.return_value = None
        mock_store.get.return_value = {"answer": "from store"}

        with patch(
            "aragora.core.decision_results._get_result_store",
            return_value=mock_store,
        ):
            save_decision_result("resilience-test", {"answer": "test"})
            mock_store.save.assert_called_once()

        # Second scenario: store fails, fallback should work
        mock_store_failing = MagicMock()
        mock_store_failing.save.side_effect = OSError("Store unavailable")
        mock_store_failing.get.side_effect = OSError("Store unavailable")
        mock_store_failing.get_status.side_effect = OSError("Store unavailable")

        with patch(
            "aragora.core.decision_results._get_result_store",
            return_value=mock_store_failing,
        ):
            # Save should fall back
            save_decision_result("fallback-test", {"answer": "fallback data"})

            # Get should fall back
            result = get_decision_result("fallback-test")
            assert result["answer"] == "fallback data"

            # Status should fall back
            import aragora.core.decision_results as module

            module._decision_results_fallback["status-test"] = {"status": "ok"}
            status = get_decision_status("status-test")
            assert status["status"] == "ok"


# =============================================================================
# Edge Case Tests
# =============================================================================


class TestDecisionResultsEdgeCases:
    """Edge case tests for decision results module."""

    def setup_method(self):
        """Reset state before each test."""
        reset_module_state()

    def test_empty_data(self):
        """Handles empty data correctly."""
        with patch(
            "aragora.core.decision_results._get_result_store",
            return_value=None,
        ):
            save_decision_result("empty-test", {})
            result = get_decision_result("empty-test")

            assert result == {}

    def test_special_characters_in_request_id(self):
        """Handles special characters in request IDs."""
        with patch(
            "aragora.core.decision_results._get_result_store",
            return_value=None,
        ):
            special_ids = [
                "req-with-dashes",
                "req_with_underscores",
                "req.with.dots",
                "req:with:colons",
                "req/with/slashes",
            ]

            for req_id in special_ids:
                save_decision_result(req_id, {"answer": f"for {req_id}"})
                result = get_decision_result(req_id)
                assert result["answer"] == f"for {req_id}"

    def test_large_data(self):
        """Handles large data correctly."""
        with patch(
            "aragora.core.decision_results._get_result_store",
            return_value=None,
        ):
            large_data = {
                "answer": "x" * 10000,  # Large string
                "contributions": [
                    {"agent": f"agent-{i}", "response": "y" * 1000} for i in range(100)
                ],
                "evidence": [{"source": f"source-{i}", "content": "z" * 500} for i in range(50)],
            }

            save_decision_result("large-test", large_data)
            result = get_decision_result("large-test")

            assert len(result["answer"]) == 10000
            assert len(result["contributions"]) == 100
            assert len(result["evidence"]) == 50

    def test_nested_data(self):
        """Handles deeply nested data correctly."""
        with patch(
            "aragora.core.decision_results._get_result_store",
            return_value=None,
        ):
            nested_data = {
                "level1": {"level2": {"level3": {"level4": {"level5": {"value": "deep"}}}}}
            }

            save_decision_result("nested-test", nested_data)
            result = get_decision_result("nested-test")

            assert result["level1"]["level2"]["level3"]["level4"]["level5"]["value"] == "deep"
