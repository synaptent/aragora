"""
CalibrationTracker - Track prediction accuracy for agent calibration.

Records prediction confidence vs actual outcomes to compute:
- Brier scores (mean squared error of predictions)
- Expected Calibration Error (ECE)
- Calibration curves per agent and domain
- Temperature scaling for auto-tuning

Well-calibrated agents have confidence that matches their accuracy:
- 80% confidence predictions should be correct 80% of the time

Auto-tuning features:
- Temperature scaling: learns optimal T where adjusted = sigmoid(logit(conf) / T)
- Recency weighting: recent predictions weighted more heavily
- Domain-specific calibration: separate parameters per domain
- Rolling window: auto-recomputes optimal parameters periodically
"""

__all__ = [
    "temperature_scale",
    "TemperatureParams",
    "CalibrationBucket",
    "CalibrationSummary",
    "adjust_agent_confidence",
    "CalibrationTracker",
    "integrate_with_position_ledger",
]

import logging
import math
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)

from aragora.config import DB_TIMEOUT_SECONDS
from aragora.persistence.db_config import DatabaseType, get_db_path
from aragora.storage.base_store import SQLiteStore
from aragora.storage.schema import safe_add_column

# Schema version for CalibrationTracker migrations
CALIBRATION_SCHEMA_VERSION = 2  # Added temperature scaling columns

# Default auto-tuning parameters
DEFAULT_TEMPERATURE = 1.0  # No scaling
MIN_TEMPERATURE = 0.5  # Maximum confidence compression
MAX_TEMPERATURE = 2.0  # Maximum confidence expansion
RECENCY_DECAY_DAYS = 30  # Half-life for exponential decay
MIN_PREDICTIONS_FOR_TUNING = 20  # Minimum predictions before auto-tuning


def _logit(p: float) -> float:
    """Convert probability to log-odds, with clamping for numerical stability."""
    p = max(1e-7, min(1 - 1e-7, p))
    return math.log(p / (1 - p))


def _sigmoid(x: float) -> float:
    """Convert log-odds to probability."""
    if x > 20:
        return 1.0 - 1e-9
    if x < -20:
        return 1e-9
    return 1 / (1 + math.exp(-x))


def temperature_scale(confidence: float, temperature: float) -> float:
    """Apply temperature scaling to a confidence value.

    Temperature scaling adjusts confidence by dividing log-odds by T:
    - T < 1: Increases confidence spread (more extreme values)
    - T = 1: No change
    - T > 1: Decreases confidence spread (closer to 0.5)

    Args:
        confidence: Raw confidence (0-1)
        temperature: Temperature parameter (0.5-2.0 typical)

    Returns:
        Temperature-scaled confidence, clamped to [0.05, 0.95]
    """
    if temperature <= 0:
        temperature = DEFAULT_TEMPERATURE

    logit = _logit(confidence)
    scaled_logit = logit / temperature
    scaled = _sigmoid(scaled_logit)

    return max(0.05, min(0.95, scaled))


@dataclass
class TemperatureParams:
    """Learned temperature scaling parameters for an agent."""

    temperature: float = DEFAULT_TEMPERATURE
    domain_temperatures: dict[str, float] = field(default_factory=dict)
    last_tuned: datetime | None = None
    predictions_at_tune: int = 0

    def get_temperature(self, domain: str | None = None) -> float:
        """Get temperature for a specific domain, falling back to global."""
        if domain and domain in self.domain_temperatures:
            return self.domain_temperatures[domain]
        return self.temperature

    def is_stale(self, current_predictions: int, max_age_hours: int = 24) -> bool:
        """Check if parameters need retuning."""
        if self.last_tuned is None:
            return True
        # Retune if 50% more predictions accumulated
        if current_predictions > self.predictions_at_tune * 1.5:
            return True
        # Retune if older than max_age
        age = datetime.now() - self.last_tuned
        return age > timedelta(hours=max_age_hours)


@dataclass
class CalibrationBucket:
    """Stats for a confidence range (e.g., 0.7-0.8)."""

    range_start: float
    range_end: float
    total_predictions: int = 0
    correct_predictions: int = 0
    brier_sum: float = 0.0

    @property
    def accuracy(self) -> float:
        """Actual accuracy in this bucket."""
        if self.total_predictions == 0:
            return 0.0
        return self.correct_predictions / self.total_predictions

    @property
    def expected_accuracy(self) -> float:
        """Expected accuracy (midpoint of bucket)."""
        return (self.range_start + self.range_end) / 2

    @property
    def calibration_error(self) -> float:
        """Absolute difference between expected and actual accuracy."""
        return abs(self.accuracy - self.expected_accuracy)

    @property
    def brier_score(self) -> float:
        """Average Brier score for this bucket."""
        if self.total_predictions == 0:
            return 0.0
        return self.brier_sum / self.total_predictions


@dataclass
class CalibrationSummary:
    """Summary of an agent's calibration performance."""

    agent: str
    total_predictions: int = 0
    total_correct: int = 0
    brier_score: float = 0.0
    ece: float = 0.0  # Expected Calibration Error
    buckets: list[CalibrationBucket] = field(default_factory=list)
    temperature_params: TemperatureParams = field(default_factory=TemperatureParams)

    @property
    def accuracy(self) -> float:
        """Overall prediction accuracy."""
        if self.total_predictions == 0:
            return 0.0
        return self.total_correct / self.total_predictions

    @property
    def is_overconfident(self) -> bool:
        """True if agent's confidence exceeds accuracy."""
        if not self.buckets:
            return False
        high_conf = [b for b in self.buckets if b.range_start >= 0.7]
        if not high_conf:
            return False
        active = [b for b in high_conf if b.total_predictions > 0]
        if not active:
            return False
        avg_error = sum(b.expected_accuracy - b.accuracy for b in active) / len(active)
        return avg_error > 0.1

    @property
    def is_underconfident(self) -> bool:
        """True if agent's accuracy exceeds confidence."""
        if not self.buckets:
            return False
        low_conf = [b for b in self.buckets if b.range_end <= 0.5]
        if not low_conf:
            return False
        active = [b for b in low_conf if b.total_predictions > 0]
        if not active:
            return False
        avg_error = sum(b.accuracy - b.expected_accuracy for b in active) / len(active)
        return avg_error > 0.1

    @property
    def bias_direction(self) -> str:
        """Human-readable description of calibration bias.

        Returns:
            'overconfident', 'underconfident', or 'well-calibrated'
        """
        if self.is_overconfident:
            return "overconfident"
        elif self.is_underconfident:
            return "underconfident"
        return "well-calibrated"

    def get_confidence_adjustment(self) -> float:
        """Calculate confidence adjustment factor based on calibration history.

        Returns a multiplier to apply to agent confidence values:
        - Overconfident: < 1.0 (reduce confidence)
        - Underconfident: > 1.0 (boost confidence)
        - Well-calibrated: 1.0 (no change)

        The adjustment is proportional to the Expected Calibration Error (ECE).
        """
        if self.total_predictions < 10:
            return 1.0  # Not enough data

        # Base adjustment on ECE - larger errors mean larger adjustments
        max_adjustment = 0.3  # Maximum 30% adjustment
        adjustment_magnitude = min(self.ece, 0.2) / 0.2 * max_adjustment

        if self.is_overconfident:
            return 1.0 - adjustment_magnitude  # Scale down (e.g., 0.7 * confidence)
        elif self.is_underconfident:
            return 1.0 + adjustment_magnitude  # Scale up (e.g., 1.3 * confidence)
        return 1.0

    def adjust_confidence(
        self, raw_confidence: float, domain: str | None = None, use_temperature: bool = True
    ) -> float:
        """Adjust a confidence value based on calibration history.

        Uses temperature scaling if available and sufficient data exists,
        otherwise falls back to the linear adjustment method.

        Args:
            raw_confidence: The agent's stated confidence (0-1)
            domain: Optional domain for domain-specific adjustment
            use_temperature: If True, prefer temperature scaling

        Returns:
            Calibration-adjusted confidence, clamped to [0.05, 0.95]
        """
        # Check if we should use temperature scaling
        has_global_temp = self.temperature_params.temperature != DEFAULT_TEMPERATURE
        has_domain_temp = (
            domain is not None and domain in self.temperature_params.domain_temperatures
        )

        # Prefer temperature scaling if we have enough data and tuned params
        if (
            use_temperature
            and (has_global_temp or has_domain_temp)
            and self.total_predictions >= MIN_PREDICTIONS_FOR_TUNING
        ):
            temp = self.temperature_params.get_temperature(domain)
            return temperature_scale(raw_confidence, temp)

        # Fall back to linear adjustment
        adjustment = self.get_confidence_adjustment()
        adjusted = raw_confidence * adjustment

        # Clamp to reasonable bounds
        return max(0.05, min(0.95, adjusted))


def adjust_agent_confidence(
    confidence: float,
    calibration_summary: Optional["CalibrationSummary"],
    domain: str | None = None,
) -> float:
    """Utility function to adjust agent confidence based on calibration.

    Uses temperature scaling if available and sufficient data,
    otherwise falls back to linear adjustment.

    Args:
        confidence: Raw confidence value (0-1)
        calibration_summary: Agent's calibration summary, or None
        domain: Optional domain for domain-specific adjustment

    Returns:
        Adjusted confidence value
    """
    if calibration_summary is None:
        return confidence
    return calibration_summary.adjust_confidence(confidence, domain=domain)


class CalibrationTracker(SQLiteStore):
    """
    Track prediction calibration for agents.

    Records confidence → outcome pairs and computes calibration metrics.
    Stores data in SQLite for persistence across sessions.
    """

    SCHEMA_NAME = "calibration"
    SCHEMA_VERSION = CALIBRATION_SCHEMA_VERSION

    INITIAL_SCHEMA = """
        CREATE TABLE IF NOT EXISTS predictions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            agent TEXT NOT NULL,
            confidence REAL NOT NULL,
            correct INTEGER NOT NULL,
            domain TEXT DEFAULT 'general',
            debate_id TEXT,
            position_id TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        );

        CREATE INDEX IF NOT EXISTS idx_pred_agent ON predictions(agent);
        CREATE INDEX IF NOT EXISTS idx_pred_domain ON predictions(domain);
        CREATE INDEX IF NOT EXISTS idx_pred_confidence ON predictions(confidence);
        CREATE INDEX IF NOT EXISTS idx_pred_created ON predictions(created_at);

        CREATE TABLE IF NOT EXISTS temperature_params (
            agent TEXT PRIMARY KEY,
            temperature REAL DEFAULT 1.0,
            domain_temperatures TEXT DEFAULT '{}',
            last_tuned TEXT,
            predictions_at_tune INTEGER DEFAULT 0
        );
    """

    MIGRATIONS = {
        2: """
            CREATE INDEX IF NOT EXISTS idx_pred_created ON predictions(created_at);

            CREATE TABLE IF NOT EXISTS temperature_params (
                agent TEXT PRIMARY KEY,
                temperature REAL DEFAULT 1.0,
                domain_temperatures TEXT DEFAULT '{}',
                last_tuned TEXT,
                predictions_at_tune INTEGER DEFAULT 0
            );
        """,
    }

    def __init__(self, db_path: str | Path | None = None):
        if db_path is None:
            db_path = get_db_path(DatabaseType.CALIBRATION)
        super().__init__(db_path, timeout=DB_TIMEOUT_SECONDS)
        self._ensure_temperature_params_table()
        self._ensure_predictions_schema()

    def _ensure_temperature_params_table(self) -> None:
        """Ensure temperature_params table exists (defensive migration).

        This handles the case where the database was created with an older schema
        that didn't include this table, or where migrations didn't run properly.
        Uses pooled connection from parent class to avoid WAL mutex contention.
        """
        try:
            with self.connection() as conn:
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS temperature_params (
                        agent TEXT PRIMARY KEY,
                        temperature REAL DEFAULT 1.0,
                        domain_temperatures TEXT DEFAULT '{}',
                        last_tuned TEXT,
                        predictions_at_tune INTEGER DEFAULT 0
                    )
                    """)
                conn.commit()
        except (OSError, sqlite3.Error) as e:
            # Log but don't fail - the table might already exist or be created elsewhere
            logging.getLogger(__name__).warning("Failed to ensure temperature_params table: %s", e)

    def _ensure_predictions_schema(self) -> None:
        """Ensure predictions table has required columns for calibration tracking.

        This is defensive against older schemas or consolidated DBs where a
        different predictions table may already exist without the expected columns.
        """
        try:
            with self.connection() as conn:
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS predictions (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        agent TEXT NOT NULL,
                        confidence REAL NOT NULL,
                        correct INTEGER NOT NULL,
                        domain TEXT DEFAULT 'general',
                        debate_id TEXT,
                        position_id TEXT,
                        created_at TEXT DEFAULT CURRENT_TIMESTAMP
                    )
                """)
                conn.commit()

                safe_add_column(conn, "predictions", "agent", "TEXT", "''")
                safe_add_column(conn, "predictions", "confidence", "REAL", "0.0")
                safe_add_column(conn, "predictions", "correct", "INTEGER", "0")
                safe_add_column(conn, "predictions", "domain", "TEXT", "'general'")
                safe_add_column(conn, "predictions", "debate_id", "TEXT", "NULL")
                safe_add_column(conn, "predictions", "position_id", "TEXT", "NULL")
                safe_add_column(conn, "predictions", "created_at", "TEXT", "CURRENT_TIMESTAMP")
        except (OSError, sqlite3.Error) as e:
            logging.getLogger(__name__).warning("Failed to ensure predictions schema: %s", e)

    def record_prediction(
        self,
        agent: str,
        confidence: float,
        correct: bool,
        domain: str = "general",
        debate_id: str | None = None,
        position_id: str | None = None,
        prediction_type: str | None = None,
    ) -> int:
        """
        Record a prediction and its outcome.

        Args:
            agent: Agent name
            confidence: Expressed confidence (0.0-1.0)
            correct: Whether the prediction was correct
            domain: Problem domain (e.g., "security", "performance")
            debate_id: Optional debate reference
            position_id: Optional position reference
            prediction_type: Optional prediction category metadata. Accepted
                for protocol compatibility with callers that tag prediction
                source, but currently not persisted.

        Returns:
            ID of the recorded prediction
        """
        confidence = max(0.0, min(1.0, confidence))

        with self.connection() as conn:
            cursor = conn.execute(
                """
                INSERT INTO predictions (agent, confidence, correct, domain, debate_id, position_id, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    agent,
                    confidence,
                    1 if correct else 0,
                    domain,
                    debate_id or "",
                    position_id or "",
                    datetime.now().isoformat(),
                ),
            )
            pred_id = cursor.lastrowid
            conn.commit()

        return pred_id or 0

    def get_calibration_curve(
        self,
        agent: str,
        num_buckets: int = 10,
        domain: str | None = None,
    ) -> list[CalibrationBucket]:
        """
        Get calibration curve (expected vs actual accuracy per bucket).

        Args:
            agent: Agent name
            num_buckets: Number of confidence buckets (default 10)
            domain: Optional domain filter

        Returns:
            List of CalibrationBucket objects ordered by confidence range
        """
        bucket_size = 1.0 / num_buckets
        buckets = []

        with self.connection() as conn:
            for i in range(num_buckets):
                range_start = i * bucket_size
                range_end = (i + 1) * bucket_size

                # Last bucket uses <= to include 1.0 exactly
                if i == num_buckets - 1:
                    query = """
                        SELECT COUNT(*), SUM(correct)
                        FROM predictions
                        WHERE agent = ? AND confidence >= ? AND confidence <= ?
                    """
                else:
                    query = """
                        SELECT COUNT(*), SUM(correct)
                        FROM predictions
                        WHERE agent = ? AND confidence >= ? AND confidence < ?
                    """
                params: list = [agent, range_start, range_end]

                if domain:
                    query += " AND domain = ?"
                    params.append(domain)

                cursor = conn.execute(query, params)
                row = cursor.fetchone()

                total = row[0] or 0
                correct = row[1] or 0

                # Compute Brier sum for this bucket (last bucket uses <= to include 1.0)
                if i == num_buckets - 1:
                    brier_query = """
                        SELECT SUM((confidence - correct) * (confidence - correct))
                        FROM predictions
                        WHERE agent = ? AND confidence >= ? AND confidence <= ?
                    """
                else:
                    brier_query = """
                        SELECT SUM((confidence - correct) * (confidence - correct))
                        FROM predictions
                        WHERE agent = ? AND confidence >= ? AND confidence < ?
                    """
                if domain:
                    brier_query += " AND domain = ?"

                cursor = conn.execute(brier_query, params)
                brier_row = cursor.fetchone()
                brier_sum = brier_row[0] or 0.0

                buckets.append(
                    CalibrationBucket(
                        range_start=range_start,
                        range_end=range_end,
                        total_predictions=total,
                        correct_predictions=correct,
                        brier_sum=brier_sum,
                    )
                )

        return buckets

    def get_brier_score(self, agent: str, domain: str | None = None) -> float:
        """
        Compute Brier score for an agent.

        Brier score = mean((confidence - outcome)^2)
        Lower is better. 0 = perfect, 0.25 = random at 50% confidence.

        Args:
            agent: Agent name
            domain: Optional domain filter

        Returns:
            Brier score (0.0 to 1.0)
        """
        with self.connection() as conn:
            query = """
                SELECT AVG((confidence - correct) * (confidence - correct))
                FROM predictions
                WHERE agent = ?
            """
            params: list = [agent]

            if domain:
                query += " AND domain = ?"
                params.append(domain)

            cursor = conn.execute(query, params)
            row = cursor.fetchone()

        return row[0] if row[0] is not None else 0.0

    def get_expected_calibration_error(
        self,
        agent: str,
        num_buckets: int = 10,
        domain: str | None = None,
    ) -> float:
        """
        Compute Expected Calibration Error (ECE).

        ECE = weighted average of |accuracy - confidence| per bucket,
        weighted by number of predictions in each bucket.

        Args:
            agent: Agent name
            num_buckets: Number of confidence buckets
            domain: Optional domain filter

        Returns:
            ECE (0.0 to 1.0, lower is better)
        """
        buckets = self.get_calibration_curve(agent, num_buckets, domain)

        total_predictions = sum(b.total_predictions for b in buckets)
        if total_predictions == 0:
            return 0.0

        ece = sum(
            (b.total_predictions / total_predictions) * b.calibration_error
            for b in buckets
            if b.total_predictions > 0
        )

        return ece

    def get_calibration_summary(
        self,
        agent: str,
        domain: str | None = None,
        include_temperature: bool = True,
    ) -> CalibrationSummary:
        """
        Get comprehensive calibration summary for an agent.

        Args:
            agent: Agent name
            domain: Optional domain filter
            include_temperature: If True, include temperature params

        Returns:
            CalibrationSummary with all metrics
        """
        buckets = self.get_calibration_curve(agent, domain=domain)

        total_predictions = sum(b.total_predictions for b in buckets)
        total_correct = sum(b.correct_predictions for b in buckets)
        brier_score = self.get_brier_score(agent, domain)
        ece = self.get_expected_calibration_error(agent, domain=domain)

        temp_params = (
            self.get_temperature_params(agent) if include_temperature else TemperatureParams()
        )

        return CalibrationSummary(
            agent=agent,
            total_predictions=total_predictions,
            total_correct=total_correct,
            brier_score=brier_score,
            ece=ece,
            buckets=buckets,
            temperature_params=temp_params,
        )

    def get_calibration(self, agent: str) -> dict[str, Any] | None:
        """
        Get calibration data for an agent.

        Implements CalibrationTrackerProtocol.get_calibration.

        Args:
            agent: Agent name

        Returns:
            Dict with calibration metrics, or None if no data
        """
        try:
            summary = self.get_calibration_summary(agent, include_temperature=True)
            if summary.total_predictions == 0:
                return None
            return {
                "agent": summary.agent,
                "total_predictions": summary.total_predictions,
                "total_correct": summary.total_correct,
                "accuracy": summary.total_correct / summary.total_predictions
                if summary.total_predictions > 0
                else 0.0,
                "brier_score": summary.brier_score,
                "ece": summary.ece,
                "temperature": summary.temperature_params.temperature
                if summary.temperature_params
                else 1.0,
            }
        except (KeyError, ValueError, sqlite3.Error) as e:
            logger.debug("Failed to get calibration export for %s: %s", agent, e)
            return None

    def get_domain_breakdown(self, agent: str) -> dict[str, CalibrationSummary]:
        """
        Get calibration breakdown by domain for an agent.

        Returns:
            Dict mapping domain name to CalibrationSummary
        """
        with self.connection() as conn:
            cursor = conn.execute(
                "SELECT DISTINCT domain FROM predictions WHERE agent = ?",
                (agent,),
            )
            domains = [row[0] for row in cursor.fetchall()]

        return {domain: self.get_calibration_summary(agent, domain) for domain in domains}

    def get_all_agents(self) -> list[str]:
        """Get list of all agents with recorded predictions."""
        with self.connection() as conn:
            cursor = conn.execute("SELECT DISTINCT agent FROM predictions ORDER BY agent")
            agents = [row[0] for row in cursor.fetchall()]
        return agents

    def get_leaderboard(
        self,
        metric: str = "brier",
        limit: int = 10,
    ) -> list[tuple[str, float]]:
        """
        Get agents ranked by calibration metric.

        Args:
            metric: "brier" (lower is better), "ece" (lower is better),
                   or "accuracy" (higher is better)
            limit: Max number of agents to return

        Returns:
            List of (agent_name, metric_value) tuples, sorted by performance
        """
        agents = self.get_all_agents()

        results = []
        for agent in agents:
            summary = self.get_calibration_summary(agent)
            if summary.total_predictions < 5:
                continue  # Skip agents with too few predictions

            if metric == "brier":
                results.append((agent, summary.brier_score))
            elif metric == "ece":
                results.append((agent, summary.ece))
            elif metric == "accuracy":
                results.append((agent, summary.accuracy))
            else:
                results.append((agent, summary.brier_score))

        # Sort: lower is better for brier/ece, higher for accuracy
        reverse = metric == "accuracy"
        results.sort(key=lambda x: x[1], reverse=reverse)

        return results[:limit]

    def delete_agent_data(self, agent: str) -> int:
        """
        Delete all predictions for an agent.

        Returns:
            Number of records deleted
        """
        with self.connection() as conn:
            cursor = conn.execute("DELETE FROM predictions WHERE agent = ?", (agent,))
            deleted = cursor.rowcount
            conn.execute("DELETE FROM temperature_params WHERE agent = ?", (agent,))
            conn.commit()
        return deleted

    def get_recency_weighted_predictions(
        self,
        agent: str,
        domain: str | None = None,
        decay_days: float = RECENCY_DECAY_DAYS,
        limit: int = 1000,
    ) -> list[tuple[float, bool, float]]:
        """Get predictions with recency weights (exponential decay).

        Args:
            agent: Agent name
            domain: Optional domain filter
            decay_days: Half-life in days for exponential decay
            limit: Maximum predictions to retrieve

        Returns:
            List of (confidence, correct, weight) tuples
        """
        now = datetime.now()

        with self.connection() as conn:
            query = """
                SELECT confidence, correct, created_at
                FROM predictions
                WHERE agent = ?
            """
            params: list = [agent]

            if domain:
                query += " AND domain = ?"
                params.append(domain)

            query += " ORDER BY created_at DESC LIMIT ?"
            params.append(limit)

            cursor = conn.execute(query, params)
            rows = cursor.fetchall()

        result = []
        for confidence, correct, created_at_str in rows:
            created_at = datetime.fromisoformat(created_at_str)
            age_days = (now - created_at).total_seconds() / 86400
            weight = math.exp(-math.log(2) * age_days / decay_days)
            result.append((confidence, bool(correct), weight))

        return result

    def compute_optimal_temperature(
        self,
        agent: str,
        domain: str | None = None,
        use_recency_weighting: bool = True,
    ) -> float:
        """Compute optimal temperature via grid search on Brier score.

        Searches over temperature values to find the one that minimizes
        the (weighted) Brier score when applied to historical predictions.

        Args:
            agent: Agent name
            domain: Optional domain filter
            use_recency_weighting: Weight recent predictions more heavily

        Returns:
            Optimal temperature value (0.5-2.0)
        """
        if use_recency_weighting:
            predictions = self.get_recency_weighted_predictions(agent, domain)
            if len(predictions) < MIN_PREDICTIONS_FOR_TUNING:
                return DEFAULT_TEMPERATURE

            def weighted_brier(temp: float) -> float:
                total_weight = sum(w for _, _, w in predictions)
                if total_weight == 0:
                    return 1.0
                brier_sum = 0.0
                for conf, correct, weight in predictions:
                    scaled = temperature_scale(conf, temp)
                    outcome = 1.0 if correct else 0.0
                    brier_sum += weight * (scaled - outcome) ** 2
                return brier_sum / total_weight

            objective = weighted_brier
        else:
            # Unweighted - use stored predictions directly
            buckets = self.get_calibration_curve(agent, num_buckets=10, domain=domain)
            total_predictions = sum(b.total_predictions for b in buckets)
            if total_predictions < MIN_PREDICTIONS_FOR_TUNING:
                return DEFAULT_TEMPERATURE

            # For unweighted, we approximate by bucket midpoints
            with self.connection() as conn:
                query = "SELECT confidence, correct FROM predictions WHERE agent = ?"
                params: list = [agent]
                if domain:
                    query += " AND domain = ?"
                    params.append(domain)
                cursor = conn.execute(query, params)
                rows = cursor.fetchall()

            if len(rows) < MIN_PREDICTIONS_FOR_TUNING:
                return DEFAULT_TEMPERATURE

            def unweighted_brier(temp: float) -> float:
                brier_sum = 0.0
                for conf, correct in rows:
                    scaled = temperature_scale(conf, temp)
                    outcome = 1.0 if correct else 0.0
                    brier_sum += (scaled - outcome) ** 2
                return brier_sum / len(rows)

            objective = unweighted_brier

        # Grid search over temperature values
        best_temp = DEFAULT_TEMPERATURE
        best_brier = objective(DEFAULT_TEMPERATURE)

        for temp_tenths in range(5, 21):  # 0.5 to 2.0 in 0.1 increments
            temp = temp_tenths / 10.0
            brier = objective(temp)
            if brier < best_brier:
                best_brier = brier
                best_temp = temp

        return best_temp

    def auto_tune_agent(
        self,
        agent: str,
        force: bool = False,
        tune_domains: bool = True,
    ) -> TemperatureParams:
        """Auto-tune temperature parameters for an agent.

        Computes optimal temperature using historical predictions and
        optionally tunes domain-specific temperatures.

        Args:
            agent: Agent name
            force: If True, tune even if not stale
            tune_domains: If True, also compute per-domain temperatures

        Returns:
            Updated TemperatureParams
        """
        # Load current params
        params = self.get_temperature_params(agent)
        summary = self.get_calibration_summary(agent)

        # Check if tuning needed
        if not force and not params.is_stale(summary.total_predictions):
            return params

        # Compute global optimal temperature
        params.temperature = self.compute_optimal_temperature(agent)

        # Compute domain-specific temperatures
        if tune_domains:
            domain_breakdown = self.get_domain_breakdown(agent)
            for domain, domain_summary in domain_breakdown.items():
                if domain_summary.total_predictions >= MIN_PREDICTIONS_FOR_TUNING:
                    params.domain_temperatures[domain] = self.compute_optimal_temperature(
                        agent, domain=domain
                    )

        # Update metadata
        params.last_tuned = datetime.now()
        params.predictions_at_tune = summary.total_predictions

        # Save params
        self.save_temperature_params(agent, params)

        return params

    def get_temperature_params(self, agent: str) -> TemperatureParams:
        """Get stored temperature parameters for an agent."""
        import json

        with self.connection() as conn:
            cursor = conn.execute(
                """
                SELECT temperature, domain_temperatures, last_tuned, predictions_at_tune
                FROM temperature_params
                WHERE agent = ?
                """,
                (agent,),
            )
            row = cursor.fetchone()

        if not row:
            return TemperatureParams()

        temp, domain_temps_json, last_tuned_str, pred_at_tune = row
        domain_temps = json.loads(domain_temps_json) if domain_temps_json else {}
        last_tuned = datetime.fromisoformat(last_tuned_str) if last_tuned_str else None

        return TemperatureParams(
            temperature=temp or DEFAULT_TEMPERATURE,
            domain_temperatures=domain_temps,
            last_tuned=last_tuned,
            predictions_at_tune=pred_at_tune or 0,
        )

    def save_temperature_params(self, agent: str, params: TemperatureParams) -> None:
        """Save temperature parameters for an agent."""
        import json

        domain_temps_json = json.dumps(params.domain_temperatures)
        last_tuned_str = params.last_tuned.isoformat() if params.last_tuned else None

        with self.connection() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO temperature_params
                (agent, temperature, domain_temperatures, last_tuned, predictions_at_tune)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    agent,
                    params.temperature,
                    domain_temps_json,
                    last_tuned_str,
                    params.predictions_at_tune,
                ),
            )
            conn.commit()


def integrate_with_position_ledger(
    calibration_tracker: CalibrationTracker,
    position_ledger: "Any",  # PositionLedger from grounded.py (avoid circular import)
    agent: str,
) -> int:
    """
    Sync resolved positions from PositionLedger to CalibrationTracker.

    Call this periodically to import position outcomes as calibration data.

    Returns:
        Number of predictions imported
    """
    positions = position_ledger.get_agent_positions(agent, limit=1000, outcome_filter=None)

    imported = 0
    for pos in positions:
        if pos.outcome in ("correct", "incorrect"):
            calibration_tracker.record_prediction(
                agent=pos.agent_name,
                confidence=pos.confidence,
                correct=(pos.outcome == "correct"),
                domain=pos.domain or "general",
                debate_id=pos.debate_id,
                position_id=pos.id,
            )
            imported += 1

    return imported
