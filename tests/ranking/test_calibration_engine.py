"""Tests for calibration engine - tournament prediction scoring."""

import pytest
import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock, PropertyMock
from datetime import datetime

from aragora.ranking.calibration_engine import (
    CalibrationPrediction,
    BucketStats,
    CalibrationEngine,
    DomainCalibrationEngine,
)


class TestCalibrationPrediction:
    """Test CalibrationPrediction dataclass."""

    def test_create_prediction(self):
        """Test creating a calibration prediction."""
        pred = CalibrationPrediction(
            tournament_id="t1",
            predictor_agent="claude",
            predicted_winner="gemini",
            confidence=0.7,
        )
        assert pred.tournament_id == "t1"
        assert pred.predictor_agent == "claude"
        assert pred.predicted_winner == "gemini"
        assert pred.confidence == 0.7
        assert pred.created_at is None

    def test_create_prediction_with_timestamp(self):
        """Test creating a prediction with timestamp."""
        pred = CalibrationPrediction(
            tournament_id="t1",
            predictor_agent="claude",
            predicted_winner="gemini",
            confidence=0.8,
            created_at="2025-01-01T12:00:00",
        )
        assert pred.created_at == "2025-01-01T12:00:00"

    def test_confidence_range(self):
        """Test prediction with various confidence values."""
        for conf in [0.0, 0.5, 1.0]:
            pred = CalibrationPrediction(
                tournament_id="t1",
                predictor_agent="claude",
                predicted_winner="gemini",
                confidence=conf,
            )
            assert pred.confidence == conf


class TestBucketStats:
    """Test BucketStats dataclass."""

    def test_create_bucket_stats(self):
        """Test creating bucket statistics."""
        stats = BucketStats(
            bucket_key="0.7-0.8",
            bucket_start=0.7,
            bucket_end=0.8,
            predictions=100,
            correct=75,
            accuracy=0.75,
            expected_accuracy=0.75,
            brier_score=0.05,
        )
        assert stats.bucket_key == "0.7-0.8"
        assert stats.bucket_start == 0.7
        assert stats.bucket_end == 0.8
        assert stats.predictions == 100
        assert stats.correct == 75
        assert stats.accuracy == 0.75
        assert stats.expected_accuracy == 0.75
        assert stats.brier_score == 0.05

    def test_bucket_with_zero_predictions(self):
        """Test bucket with no predictions."""
        stats = BucketStats(
            bucket_key="0.9-1.0",
            bucket_start=0.9,
            bucket_end=1.0,
            predictions=0,
            correct=0,
            accuracy=0.0,
            expected_accuracy=0.95,
            brier_score=1.0,
        )
        assert stats.predictions == 0
        assert stats.brier_score == 1.0


class TestCalibrationEngine:
    """Test CalibrationEngine class."""

    @pytest.fixture
    def temp_db(self):
        """Create a temporary database."""
        with tempfile.TemporaryDirectory() as tmpdir:
            yield Path(tmpdir) / "test_calibration.db"

    @pytest.fixture
    def mock_db(self):
        """Create a mock database."""
        mock = MagicMock()
        mock.connection.return_value.__enter__ = MagicMock()
        mock.connection.return_value.__exit__ = MagicMock()
        return mock

    def test_init_without_elo_system(self, temp_db):
        """Test initialization without ELO system."""
        with patch("aragora.ranking.calibration_engine.CalibrationDatabase"):
            engine = CalibrationEngine(temp_db)
            assert engine.db_path == temp_db
            assert engine.elo_system is None

    def test_init_with_elo_system(self, temp_db):
        """Test initialization with ELO system."""
        mock_elo = MagicMock()
        with patch("aragora.ranking.calibration_engine.CalibrationDatabase"):
            engine = CalibrationEngine(temp_db, elo_system=mock_elo)
            assert engine.elo_system is mock_elo

    def test_record_winner_prediction(self, temp_db):
        """Test recording a winner prediction."""
        with patch("aragora.ranking.calibration_engine.CalibrationDatabase") as MockDB:
            mock_conn = MagicMock()
            mock_cursor = MagicMock()
            mock_conn.__enter__ = MagicMock(return_value=mock_conn)
            mock_conn.__exit__ = MagicMock(return_value=None)
            mock_conn.cursor.return_value = mock_cursor
            MockDB.return_value.connection.return_value = mock_conn

            engine = CalibrationEngine(temp_db)
            engine.record_winner_prediction("t1", "claude", "gemini", 0.7)

            mock_cursor.execute.assert_called_once()
            args = mock_cursor.execute.call_args[0]
            assert "INSERT OR REPLACE INTO calibration_predictions" in args[0]
            assert args[1] == ("t1", "claude", "gemini", 0.7)

    def test_record_prediction_clamps_confidence(self, temp_db):
        """Test that confidence is clamped to [0, 1]."""
        with patch("aragora.ranking.calibration_engine.CalibrationDatabase") as MockDB:
            mock_conn = MagicMock()
            mock_cursor = MagicMock()
            mock_conn.__enter__ = MagicMock(return_value=mock_conn)
            mock_conn.__exit__ = MagicMock(return_value=None)
            mock_conn.cursor.return_value = mock_cursor
            MockDB.return_value.connection.return_value = mock_conn

            engine = CalibrationEngine(temp_db)

            # Test confidence > 1
            engine.record_winner_prediction("t1", "claude", "gemini", 1.5)
            args = mock_cursor.execute.call_args[0][1]
            assert args[3] == 1.0  # Clamped to 1.0

            # Test confidence < 0
            engine.record_winner_prediction("t2", "claude", "gemini", -0.5)
            args = mock_cursor.execute.call_args[0][1]
            assert args[3] == 0.0  # Clamped to 0.0

    def test_resolve_tournament_no_predictions(self, temp_db):
        """Test resolving tournament with no predictions."""
        with patch("aragora.ranking.calibration_engine.CalibrationDatabase") as MockDB:
            mock_conn = MagicMock()
            mock_cursor = MagicMock()
            mock_conn.__enter__ = MagicMock(return_value=mock_conn)
            mock_conn.__exit__ = MagicMock(return_value=None)
            mock_conn.cursor.return_value = mock_cursor
            mock_cursor.fetchall.return_value = []
            MockDB.return_value.connection.return_value = mock_conn

            engine = CalibrationEngine(temp_db)
            scores = engine.resolve_tournament("t1", "gemini")
            assert scores == {}

    def test_resolve_tournament_without_elo(self, temp_db):
        """Test resolving tournament without ELO system."""
        with patch("aragora.ranking.calibration_engine.CalibrationDatabase") as MockDB:
            mock_conn = MagicMock()
            mock_cursor = MagicMock()
            mock_conn.__enter__ = MagicMock(return_value=mock_conn)
            mock_conn.__exit__ = MagicMock(return_value=None)
            mock_conn.cursor.return_value = mock_cursor
            # (predictor, predicted_winner, confidence)
            mock_cursor.fetchall.return_value = [
                ("claude", "gemini", 0.8),
                ("gpt", "codex", 0.6),
            ]
            MockDB.return_value.connection.return_value = mock_conn

            engine = CalibrationEngine(temp_db)
            scores = engine.resolve_tournament("t1", "gemini")

            # claude predicted gemini with 0.8 confidence, gemini won
            # Brier = (0.8 - 1.0)^2 = 0.04
            assert abs(scores["claude"] - 0.04) < 0.001

            # gpt predicted codex with 0.6 confidence, gemini won
            # Brier = (0.6 - 0.0)^2 = 0.36
            assert abs(scores["gpt"] - 0.36) < 0.001

    def test_resolve_tournament_with_elo(self, temp_db):
        """Test resolving tournament with ELO system."""
        with patch("aragora.ranking.calibration_engine.CalibrationDatabase") as MockDB:
            mock_conn = MagicMock()
            mock_cursor = MagicMock()
            mock_conn.__enter__ = MagicMock(return_value=mock_conn)
            mock_conn.__exit__ = MagicMock(return_value=None)
            mock_conn.cursor.return_value = mock_cursor
            mock_cursor.fetchall.return_value = [
                ("claude", "gemini", 0.9),
            ]
            MockDB.return_value.connection.return_value = mock_conn

            mock_elo = MagicMock()
            mock_rating = MagicMock()
            mock_rating.calibration_total = 0
            mock_rating.calibration_correct = 0
            mock_rating.calibration_brier_sum = 0.0
            mock_elo.get_ratings_batch.return_value = {"claude": mock_rating}

            engine = CalibrationEngine(temp_db, elo_system=mock_elo)
            scores = engine.resolve_tournament("t1", "gemini")

            # Should have updated the rating
            assert mock_rating.calibration_total == 1
            assert mock_rating.calibration_correct == 1
            mock_elo._save_ratings_batch.assert_called_once()

    def test_get_leaderboard_no_elo(self, temp_db):
        """Test getting leaderboard without ELO system."""
        with patch("aragora.ranking.calibration_engine.CalibrationDatabase"):
            engine = CalibrationEngine(temp_db)
            result = engine.get_leaderboard()
            assert result == []

    def test_get_leaderboard_with_elo(self, temp_db):
        """Test getting leaderboard with ELO system."""
        with patch("aragora.ranking.calibration_engine.CalibrationDatabase"):
            mock_elo = MagicMock()
            mock_elo.get_calibration_leaderboard.return_value = ["agent1", "agent2"]

            engine = CalibrationEngine(temp_db, elo_system=mock_elo)
            result = engine.get_leaderboard(limit=10)

            mock_elo.get_calibration_leaderboard.assert_called_once_with(10)
            assert result == ["agent1", "agent2"]

    def test_get_agent_history(self, temp_db):
        """Test getting agent prediction history."""
        with patch("aragora.ranking.calibration_engine.CalibrationDatabase") as MockDB:
            mock_conn = MagicMock()
            mock_cursor = MagicMock()
            mock_conn.__enter__ = MagicMock(return_value=mock_conn)
            mock_conn.__exit__ = MagicMock(return_value=None)
            mock_conn.cursor.return_value = mock_cursor
            mock_cursor.fetchall.return_value = [
                ("t1", "claude", "gemini", 0.7, "2025-01-01"),
                ("t2", "claude", "codex", 0.8, "2025-01-02"),
            ]
            MockDB.return_value.connection.return_value = mock_conn

            engine = CalibrationEngine(temp_db)
            history = engine.get_agent_history("claude", limit=10)

            assert len(history) == 2
            assert isinstance(history[0], CalibrationPrediction)
            assert history[0].tournament_id == "t1"
            assert history[0].predicted_winner == "gemini"
            assert history[1].confidence == 0.8

    def test_get_agent_history_empty(self, temp_db):
        """Test getting agent history with no predictions."""
        with patch("aragora.ranking.calibration_engine.CalibrationDatabase") as MockDB:
            mock_conn = MagicMock()
            mock_cursor = MagicMock()
            mock_conn.__enter__ = MagicMock(return_value=mock_conn)
            mock_conn.__exit__ = MagicMock(return_value=None)
            mock_conn.cursor.return_value = mock_cursor
            mock_cursor.fetchall.return_value = []
            MockDB.return_value.connection.return_value = mock_conn

            engine = CalibrationEngine(temp_db)
            history = engine.get_agent_history("unknown_agent")

            assert history == []

    def test_calculate_brier_score_correct(self, temp_db):
        """Test Brier score for correct prediction."""
        with patch("aragora.ranking.calibration_engine.CalibrationDatabase"):
            engine = CalibrationEngine(temp_db)

            # Perfect prediction (confidence 1.0, correct)
            score = engine.calculate_brier_score(1.0, correct=True)
            assert score == 0.0

            # High confidence, correct
            score = engine.calculate_brier_score(0.8, correct=True)
            assert abs(score - 0.04) < 0.001

    def test_calculate_brier_score_incorrect(self, temp_db):
        """Test Brier score for incorrect prediction."""
        with patch("aragora.ranking.calibration_engine.CalibrationDatabase"):
            engine = CalibrationEngine(temp_db)

            # High confidence, wrong
            score = engine.calculate_brier_score(0.9, correct=False)
            assert abs(score - 0.81) < 0.001

            # Low confidence, wrong
            score = engine.calculate_brier_score(0.3, correct=False)
            assert abs(score - 0.09) < 0.001

    def test_calculate_brier_score_uncertain(self, temp_db):
        """Test Brier score for uncertain prediction."""
        with patch("aragora.ranking.calibration_engine.CalibrationDatabase"):
            engine = CalibrationEngine(temp_db)

            # 50% confidence, correct
            score = engine.calculate_brier_score(0.5, correct=True)
            assert abs(score - 0.25) < 0.001

            # 50% confidence, wrong
            score = engine.calculate_brier_score(0.5, correct=False)
            assert abs(score - 0.25) < 0.001


class TestDomainCalibrationEngine:
    """Test DomainCalibrationEngine class."""

    @pytest.fixture
    def temp_db(self):
        """Create a temporary database."""
        with tempfile.TemporaryDirectory() as tmpdir:
            yield Path(tmpdir) / "test_domain_calibration.db"

    def test_init_without_elo(self, temp_db):
        """Test initialization without ELO system."""
        with patch("aragora.ranking.calibration_engine.CalibrationDatabase"):
            engine = DomainCalibrationEngine(temp_db)
            assert engine.db_path == temp_db
            assert engine.elo_system is None

    def test_init_with_elo(self, temp_db):
        """Test initialization with ELO system."""
        mock_elo = MagicMock()
        with patch("aragora.ranking.calibration_engine.CalibrationDatabase"):
            engine = DomainCalibrationEngine(temp_db, elo_system=mock_elo)
            assert engine.elo_system is mock_elo

    def test_get_bucket_key(self):
        """Test bucket key generation."""
        assert DomainCalibrationEngine.get_bucket_key(0.0) == "0.0-0.1"
        assert DomainCalibrationEngine.get_bucket_key(0.05) == "0.0-0.1"
        assert DomainCalibrationEngine.get_bucket_key(0.15) == "0.1-0.2"
        assert DomainCalibrationEngine.get_bucket_key(0.5) == "0.5-0.6"
        assert DomainCalibrationEngine.get_bucket_key(0.75) == "0.7-0.8"
        assert DomainCalibrationEngine.get_bucket_key(0.95) == "0.9-1.0"
        assert DomainCalibrationEngine.get_bucket_key(1.0) == "1.0-1.0"

    def test_get_bucket_key_edge_cases(self):
        """Test bucket key for edge values."""
        assert DomainCalibrationEngine.get_bucket_key(0.1) == "0.1-0.2"
        assert DomainCalibrationEngine.get_bucket_key(0.2) == "0.2-0.3"
        assert DomainCalibrationEngine.get_bucket_key(0.99) == "0.9-1.0"

    def test_record_prediction(self, temp_db):
        """Test recording a domain prediction."""
        with patch("aragora.ranking.calibration_engine.CalibrationDatabase") as MockDB:
            mock_conn = MagicMock()
            mock_cursor = MagicMock()
            mock_conn.__enter__ = MagicMock(return_value=mock_conn)
            mock_conn.__exit__ = MagicMock(return_value=None)
            mock_conn.cursor.return_value = mock_cursor
            MockDB.return_value.connection.return_value = mock_conn

            engine = DomainCalibrationEngine(temp_db)
            engine.record_prediction("claude", "security", 0.8, correct=True)

            # Should have made 2 insert calls (domain_calibration and calibration_buckets)
            assert mock_cursor.execute.call_count == 2

    def test_record_prediction_with_elo(self, temp_db):
        """Test recording prediction updates ELO system."""
        with patch("aragora.ranking.calibration_engine.CalibrationDatabase") as MockDB:
            mock_conn = MagicMock()
            mock_cursor = MagicMock()
            mock_conn.__enter__ = MagicMock(return_value=mock_conn)
            mock_conn.__exit__ = MagicMock(return_value=None)
            mock_conn.cursor.return_value = mock_cursor
            MockDB.return_value.connection.return_value = mock_conn

            mock_elo = MagicMock()
            mock_rating = MagicMock()
            mock_rating.calibration_total = 0
            mock_rating.calibration_correct = 0
            mock_rating.calibration_brier_sum = 0.0
            mock_elo.get_rating.return_value = mock_rating

            engine = DomainCalibrationEngine(temp_db, elo_system=mock_elo)
            engine.record_prediction("claude", "security", 0.9, correct=True)

            # Should have updated calibration stats
            assert mock_rating.calibration_total == 1
            assert mock_rating.calibration_correct == 1
            mock_elo._save_rating.assert_called_once()

    def test_record_prediction_clamps_confidence(self, temp_db):
        """Test that confidence is clamped."""
        with patch("aragora.ranking.calibration_engine.CalibrationDatabase") as MockDB:
            mock_conn = MagicMock()
            mock_cursor = MagicMock()
            mock_conn.__enter__ = MagicMock(return_value=mock_conn)
            mock_conn.__exit__ = MagicMock(return_value=None)
            mock_conn.cursor.return_value = mock_cursor
            MockDB.return_value.connection.return_value = mock_conn

            engine = DomainCalibrationEngine(temp_db)

            # Test with value > 1
            engine.record_prediction("claude", "security", 1.5, correct=True)
            # Brier should be (1.0 - 1.0)^2 = 0.0 (clamped confidence)
            args = mock_cursor.execute.call_args_list[0][0][1]
            # Third value is correct (1 if True), fourth is brier
            assert args[3] == 0.0  # Brier score

    def test_get_domain_stats_no_data(self, temp_db):
        """Test getting stats with no data."""
        with patch("aragora.ranking.calibration_engine.CalibrationDatabase") as MockDB:
            mock_conn = MagicMock()
            mock_cursor = MagicMock()
            mock_conn.__enter__ = MagicMock(return_value=mock_conn)
            mock_conn.__exit__ = MagicMock(return_value=None)
            mock_conn.cursor.return_value = mock_cursor
            mock_cursor.fetchall.return_value = []
            MockDB.return_value.connection.return_value = mock_conn

            engine = DomainCalibrationEngine(temp_db)
            stats = engine.get_domain_stats("unknown_agent")

            assert stats["total"] == 0
            assert stats["correct"] == 0
            assert stats["accuracy"] == 0.0
            assert stats["brier_score"] == 1.0
            assert stats["domains"] == {}

    def test_get_domain_stats_with_data(self, temp_db):
        """Test getting stats with data."""
        with patch("aragora.ranking.calibration_engine.CalibrationDatabase") as MockDB:
            mock_conn = MagicMock()
            mock_cursor = MagicMock()
            mock_conn.__enter__ = MagicMock(return_value=mock_conn)
            mock_conn.__exit__ = MagicMock(return_value=None)
            mock_conn.cursor.return_value = mock_cursor
            # (domain, total_predictions, total_correct, brier_sum)
            mock_cursor.fetchall.return_value = [
                ("security", 100, 80, 10.0),
                ("performance", 50, 40, 5.0),
            ]
            MockDB.return_value.connection.return_value = mock_conn

            engine = DomainCalibrationEngine(temp_db)
            stats = engine.get_domain_stats("claude")

            assert stats["total"] == 150
            assert stats["correct"] == 120
            assert abs(stats["accuracy"] - 0.8) < 0.001
            assert abs(stats["brier_score"] - 0.1) < 0.001  # 15.0 / 150
            assert "security" in stats["domains"]
            assert "performance" in stats["domains"]
            assert stats["domains"]["security"]["predictions"] == 100

    def test_get_domain_stats_single_domain(self, temp_db):
        """Test getting stats for a single domain."""
        with patch("aragora.ranking.calibration_engine.CalibrationDatabase") as MockDB:
            mock_conn = MagicMock()
            mock_cursor = MagicMock()
            mock_conn.__enter__ = MagicMock(return_value=mock_conn)
            mock_conn.__exit__ = MagicMock(return_value=None)
            mock_conn.cursor.return_value = mock_cursor
            mock_cursor.fetchall.return_value = [
                ("security", 100, 80, 10.0),
            ]
            MockDB.return_value.connection.return_value = mock_conn

            engine = DomainCalibrationEngine(temp_db)
            stats = engine.get_domain_stats("claude", domain="security")

            assert stats["total"] == 100
            assert len(stats["domains"]) == 1

    def test_get_calibration_curve_empty(self, temp_db):
        """Test calibration curve with no data."""
        with patch("aragora.ranking.calibration_engine.CalibrationDatabase") as MockDB:
            mock_conn = MagicMock()
            mock_cursor = MagicMock()
            mock_conn.__enter__ = MagicMock(return_value=mock_conn)
            mock_conn.__exit__ = MagicMock(return_value=None)
            mock_conn.cursor.return_value = mock_cursor
            mock_cursor.fetchall.return_value = []
            MockDB.return_value.connection.return_value = mock_conn

            engine = DomainCalibrationEngine(temp_db)
            curve = engine.get_calibration_curve("claude")

            assert curve == []

    def test_get_calibration_curve_with_data(self, temp_db):
        """Test calibration curve with data."""
        with patch("aragora.ranking.calibration_engine.CalibrationDatabase") as MockDB:
            mock_conn = MagicMock()
            mock_cursor = MagicMock()
            mock_conn.__enter__ = MagicMock(return_value=mock_conn)
            mock_conn.__exit__ = MagicMock(return_value=None)
            mock_conn.cursor.return_value = mock_cursor
            # (bucket_key, predictions, correct, brier_sum)
            mock_cursor.fetchall.return_value = [
                ("0.5-0.6", 100, 55, 25.0),
                ("0.7-0.8", 80, 60, 12.0),
                ("0.9-1.0", 50, 48, 3.0),
            ]
            MockDB.return_value.connection.return_value = mock_conn

            engine = DomainCalibrationEngine(temp_db)
            curve = engine.get_calibration_curve("claude")

            assert len(curve) == 3
            assert isinstance(curve[0], BucketStats)
            assert curve[0].bucket_key == "0.5-0.6"
            assert curve[0].bucket_start == 0.5
            assert curve[0].bucket_end == 0.6
            assert curve[0].predictions == 100
            assert curve[0].correct == 55
            assert abs(curve[0].accuracy - 0.55) < 0.001
            assert abs(curve[0].expected_accuracy - 0.55) < 0.001

    def test_get_calibration_curve_malformed_bucket(self, temp_db):
        """Test calibration curve handles malformed bucket keys."""
        with patch("aragora.ranking.calibration_engine.CalibrationDatabase") as MockDB:
            mock_conn = MagicMock()
            mock_cursor = MagicMock()
            mock_conn.__enter__ = MagicMock(return_value=mock_conn)
            mock_conn.__exit__ = MagicMock(return_value=None)
            mock_conn.cursor.return_value = mock_cursor
            mock_cursor.fetchall.return_value = [
                ("invalid", 10, 5, 2.5),  # Malformed
                ("0.7-0.8", 80, 60, 12.0),  # Valid
            ]
            MockDB.return_value.connection.return_value = mock_conn

            engine = DomainCalibrationEngine(temp_db)
            curve = engine.get_calibration_curve("claude")

            # Should skip malformed bucket
            assert len(curve) == 1
            assert curve[0].bucket_key == "0.7-0.8"

    def test_get_expected_calibration_error_no_data(self, temp_db):
        """Test ECE with no data."""
        with patch("aragora.ranking.calibration_engine.CalibrationDatabase") as MockDB:
            mock_conn = MagicMock()
            mock_cursor = MagicMock()
            mock_conn.__enter__ = MagicMock(return_value=mock_conn)
            mock_conn.__exit__ = MagicMock(return_value=None)
            mock_conn.cursor.return_value = mock_cursor
            mock_cursor.fetchall.return_value = []
            MockDB.return_value.connection.return_value = mock_conn

            engine = DomainCalibrationEngine(temp_db)
            ece = engine.get_expected_calibration_error("claude")

            assert ece == 1.0

    def test_get_expected_calibration_error_perfect(self, temp_db):
        """Test ECE for perfectly calibrated agent."""
        with patch("aragora.ranking.calibration_engine.CalibrationDatabase") as MockDB:
            mock_conn = MagicMock()
            mock_cursor = MagicMock()
            mock_conn.__enter__ = MagicMock(return_value=mock_conn)
            mock_conn.__exit__ = MagicMock(return_value=None)
            mock_conn.cursor.return_value = mock_cursor
            # Perfect calibration: accuracy = expected
            mock_cursor.fetchall.return_value = [
                ("0.5-0.6", 100, 55, 25.0),  # 55% accuracy, 55% expected
                ("0.7-0.8", 100, 75, 19.0),  # 75% accuracy, 75% expected
            ]
            MockDB.return_value.connection.return_value = mock_conn

            engine = DomainCalibrationEngine(temp_db)
            ece = engine.get_expected_calibration_error("claude")

            # Should be 0 for perfect calibration
            assert abs(ece) < 0.001

    def test_get_expected_calibration_error_poor(self, temp_db):
        """Test ECE for poorly calibrated agent."""
        with patch("aragora.ranking.calibration_engine.CalibrationDatabase") as MockDB:
            mock_conn = MagicMock()
            mock_cursor = MagicMock()
            mock_conn.__enter__ = MagicMock(return_value=mock_conn)
            mock_conn.__exit__ = MagicMock(return_value=None)
            mock_conn.cursor.return_value = mock_cursor
            # Poor calibration: very different accuracy vs expected
            mock_cursor.fetchall.return_value = [
                ("0.9-1.0", 100, 50, 25.0),  # 50% accuracy, 95% expected
            ]
            MockDB.return_value.connection.return_value = mock_conn

            engine = DomainCalibrationEngine(temp_db)
            ece = engine.get_expected_calibration_error("claude")

            # Should be high (|0.50 - 0.95| = 0.45)
            assert abs(ece - 0.45) < 0.001

    def test_get_best_domains_no_data(self, temp_db):
        """Test getting best domains with no data."""
        with patch("aragora.ranking.calibration_engine.CalibrationDatabase") as MockDB:
            mock_conn = MagicMock()
            mock_cursor = MagicMock()
            mock_conn.__enter__ = MagicMock(return_value=mock_conn)
            mock_conn.__exit__ = MagicMock(return_value=None)
            mock_conn.cursor.return_value = mock_cursor
            mock_cursor.fetchall.return_value = []
            MockDB.return_value.connection.return_value = mock_conn

            engine = DomainCalibrationEngine(temp_db)
            domains = engine.get_best_domains("claude")

            assert domains == []

    def test_get_best_domains_with_data(self, temp_db):
        """Test getting best domains with data."""
        with patch("aragora.ranking.calibration_engine.CalibrationDatabase") as MockDB:
            mock_conn = MagicMock()
            mock_cursor = MagicMock()
            mock_conn.__enter__ = MagicMock(return_value=mock_conn)
            mock_conn.__exit__ = MagicMock(return_value=None)
            mock_conn.cursor.return_value = mock_cursor
            # Multiple domains with different Brier scores
            mock_cursor.fetchall.return_value = [
                ("security", 30, 27, 3.0),  # Brier = 0.1, good
                ("performance", 20, 10, 10.0),  # Brier = 0.5, poor
                ("networking", 10, 9, 1.0),  # Brier = 0.1, good but fewer predictions
                ("tiny", 3, 2, 0.5),  # Too few predictions
            ]
            MockDB.return_value.connection.return_value = mock_conn

            engine = DomainCalibrationEngine(temp_db)
            domains = engine.get_best_domains("claude", limit=3, min_predictions=5)

            # Should exclude "tiny" due to min_predictions
            assert len(domains) <= 3
            # Should be sorted by score descending
            if len(domains) >= 2:
                assert domains[0][1] >= domains[1][1]

    def test_get_best_domains_respects_limit(self, temp_db):
        """Test that limit is respected."""
        with patch("aragora.ranking.calibration_engine.CalibrationDatabase") as MockDB:
            mock_conn = MagicMock()
            mock_cursor = MagicMock()
            mock_conn.__enter__ = MagicMock(return_value=mock_conn)
            mock_conn.__exit__ = MagicMock(return_value=None)
            mock_conn.cursor.return_value = mock_cursor
            mock_cursor.fetchall.return_value = [
                ("d1", 100, 90, 10.0),
                ("d2", 100, 80, 20.0),
                ("d3", 100, 70, 30.0),
                ("d4", 100, 60, 40.0),
            ]
            MockDB.return_value.connection.return_value = mock_conn

            engine = DomainCalibrationEngine(temp_db)
            domains = engine.get_best_domains("claude", limit=2)

            assert len(domains) == 2


class TestCalibrationEngineIntegration:
    """Integration tests using real database."""

    @pytest.fixture
    def real_db(self):
        """Create a real temporary database with the production ELO schema."""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "integration_test.db"
            from aragora.ranking.database import EloDatabase

            EloDatabase(str(db_path))
            yield db_path

    def test_full_calibration_workflow(self, real_db):
        """Test full workflow: record, resolve, query."""
        engine = CalibrationEngine(real_db)

        # Record some predictions
        engine.record_winner_prediction("t1", "claude", "gemini", 0.7)
        engine.record_winner_prediction("t1", "gpt", "codex", 0.8)

        # Resolve the tournament
        scores = engine.resolve_tournament("t1", "gemini")

        assert "claude" in scores
        assert "gpt" in scores
        # Claude predicted correctly with 0.7 confidence
        assert scores["claude"] == (0.7 - 1.0) ** 2  # 0.09
        # GPT predicted incorrectly with 0.8 confidence
        assert scores["gpt"] == (0.8 - 0.0) ** 2  # 0.64

    def test_domain_calibration_workflow(self, real_db):
        """Test domain calibration workflow."""
        engine = DomainCalibrationEngine(real_db)

        # Record some domain predictions
        engine.record_prediction("claude", "security", 0.8, correct=True)
        engine.record_prediction("claude", "security", 0.7, correct=True)
        engine.record_prediction("claude", "security", 0.9, correct=False)
        engine.record_prediction("claude", "performance", 0.6, correct=True)

        # Get stats
        stats = engine.get_domain_stats("claude")
        assert stats["total"] == 4
        assert stats["correct"] == 3

        # Get calibration curve
        curve = engine.get_calibration_curve("claude")
        assert len(curve) > 0
