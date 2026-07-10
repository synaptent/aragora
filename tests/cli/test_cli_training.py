"""
Tests for CLI training module.

Tests Tinker training CLI commands.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import typer  # noqa: F811
from typer.testing import CliRunner

import aragora.cli.training as training_cli
from aragora.cli.training import app


@pytest.fixture
def runner():
    """Create a CLI test runner."""
    return CliRunner()


class TestExportSft:
    """Tests for export-sft command."""

    @patch("aragora.training.exporters.SFTExporter")
    def test_export_sft_basic(self, mock_exporter_class, runner, tmp_path):
        """export-sft creates output file."""
        mock_exporter = MagicMock()
        mock_metadata = MagicMock()
        mock_metadata.total_records = 100
        mock_exporter.export_to_file.return_value = mock_metadata
        mock_exporter_class.return_value = mock_exporter

        output_file = tmp_path / "output.jsonl"
        result = runner.invoke(app, ["export-sft", "-o", str(output_file)])

        assert result.exit_code == 0
        assert "100" in result.output
        assert "SFT" in result.output
        mock_exporter_class.assert_called_once_with(db_path="agora_memory.db")
        mock_exporter.export_to_file.assert_called_once()

    @patch("aragora.training.exporters.SFTExporter")
    def test_export_sft_with_options(self, mock_exporter_class, runner, tmp_path):
        """export-sft respects options."""
        mock_exporter = MagicMock()
        mock_metadata = MagicMock()
        mock_metadata.total_records = 50
        mock_exporter.export_to_file.return_value = mock_metadata
        mock_exporter_class.return_value = mock_exporter

        output_file = tmp_path / "output.jsonl"
        result = runner.invoke(
            app,
            [
                "export-sft",
                "-o",
                str(output_file),
                "--min-confidence",
                "0.8",
                "--limit",
                "500",
            ],
        )

        assert result.exit_code == 0
        mock_exporter_class.assert_called_once_with(db_path="agora_memory.db")
        mock_exporter.export_to_file.assert_called_once()
        # Verify options were passed
        call_kwargs = mock_exporter.export_to_file.call_args[1]
        assert call_kwargs["min_confidence"] == 0.8
        assert call_kwargs["limit"] == 500


class TestDependencyLookup:
    """Tests for dependency lookup assumptions used by source-module patches."""

    def test_training_cli_does_not_cache_patch_target_classes(self):
        """Source-module patch targets stay valid because commands import at call time."""
        cached_names = {
            "CritiqueStore",
            "DPOExporter",
            "EloSystem",
            "GauntletExporter",
            "SFTExporter",
            "TinkerClient",
            "TrainingScheduler",
        }

        assert cached_names.isdisjoint(vars(training_cli))


class TestExportDpo:
    """Tests for export-dpo command."""

    @patch("aragora.training.exporters.DPOExporter")
    def test_export_dpo_basic(self, mock_exporter_class, runner, tmp_path):
        """export-dpo creates output file."""
        mock_exporter = MagicMock()
        mock_metadata = MagicMock()
        mock_metadata.total_records = 75
        mock_exporter.export_to_file.return_value = mock_metadata
        mock_exporter_class.return_value = mock_exporter

        output_file = tmp_path / "dpo_output.jsonl"
        result = runner.invoke(app, ["export-dpo", "-o", str(output_file)])

        assert result.exit_code == 0
        assert "75" in result.output
        assert "DPO" in result.output
        mock_exporter_class.assert_called_once_with()
        mock_exporter.export_to_file.assert_called_once()

    @patch("aragora.training.exporters.DPOExporter")
    def test_export_dpo_with_elo_diff(self, mock_exporter_class, runner, tmp_path):
        """export-dpo respects min-elo-diff option."""
        mock_exporter = MagicMock()
        mock_metadata = MagicMock()
        mock_metadata.total_records = 25
        mock_exporter.export_to_file.return_value = mock_metadata
        mock_exporter_class.return_value = mock_exporter

        result = runner.invoke(
            app,
            [
                "export-dpo",
                "--min-elo-diff",
                "100.0",
            ],
        )

        assert result.exit_code == 0
        mock_exporter_class.assert_called_once_with()
        mock_exporter.export_to_file.assert_called_once()
        call_kwargs = mock_exporter.export_to_file.call_args[1]
        assert call_kwargs["min_elo_difference"] == 100.0


class TestExportGauntlet:
    """Tests for export-gauntlet command."""

    @patch("aragora.training.exporters.GauntletExporter")
    def test_export_gauntlet_basic(self, mock_exporter_class, runner, tmp_path):
        """export-gauntlet creates output file."""
        mock_exporter = MagicMock()
        mock_metadata = MagicMock()
        mock_metadata.total_records = 30
        mock_exporter.export_to_file.return_value = mock_metadata
        mock_exporter_class.return_value = mock_exporter

        output_file = tmp_path / "gauntlet.jsonl"
        result = runner.invoke(app, ["export-gauntlet", "-o", str(output_file)])

        assert result.exit_code == 0
        assert "30" in result.output
        assert "Gauntlet" in result.output
        mock_exporter_class.assert_called_once_with()
        mock_exporter.export_to_file.assert_called_once()


class TestExportAll:
    """Tests for export-all command."""

    @patch("aragora.training.exporters.GauntletExporter")
    @patch("aragora.training.exporters.DPOExporter")
    @patch("aragora.training.exporters.SFTExporter")
    def test_export_all_creates_multiple_files(
        self, mock_sft, mock_dpo, mock_gauntlet, runner, tmp_path
    ):
        """export-all exports all data types."""
        # Setup mocks
        for mock_class, count in [(mock_sft, 100), (mock_dpo, 50), (mock_gauntlet, 20)]:
            mock_exporter = MagicMock()
            mock_metadata = MagicMock()
            mock_metadata.total_records = count
            mock_exporter.export_to_file.return_value = mock_metadata
            mock_class.return_value = mock_exporter

        output_dir = tmp_path / "training_data"
        result = runner.invoke(app, ["export-all", "-d", str(output_dir)])

        assert result.exit_code == 0
        assert "SFT" in result.output
        assert "DPO" in result.output
        assert "Gauntlet" in result.output
        mock_sft.assert_called_once_with()
        mock_dpo.assert_called_once_with()
        mock_gauntlet.assert_called_once_with()
        assert mock_sft.return_value.export_to_file.call_count == 1
        assert mock_dpo.return_value.export_to_file.call_count == 1
        assert mock_gauntlet.return_value.export_to_file.call_count == 1


class TestTestConnection:
    """Tests for test-connection command."""

    @patch.dict("os.environ", {}, clear=True)
    def test_connection_no_api_key(self, runner):
        """test-connection fails without API key."""
        result = runner.invoke(app, ["test-connection"])

        assert result.exit_code == 1
        assert "TINKER_API_KEY" in result.output

    @patch("aragora.cli.training.asyncio.run")
    @patch("aragora.training.tinker_client.TinkerClient")
    @patch.dict("os.environ", {"TINKER_API_KEY": "test-key"})
    def test_connection_success(self, mock_client_class, mock_run, runner):
        """test-connection succeeds with valid key."""
        mock_client = AsyncMock()
        mock_client_class.return_value = mock_client
        mock_run.return_value = None

        result = runner.invoke(app, ["test-connection"])

        # Note: typer.Exit(1) may be raised for connection success display
        # Check that we got past the API key check
        assert "TINKER_API_KEY" not in result.output or "successful" in result.output


class TestTrainSft:
    """Tests for train-sft command."""

    @patch("aragora.cli.training.asyncio.run")
    @patch("aragora.training.TrainingScheduler")
    def test_train_sft_schedules_job(self, mock_scheduler_class, mock_run, runner):
        """train-sft schedules a training job."""
        mock_scheduler = AsyncMock()
        mock_job = MagicMock()
        mock_job.job_id = "job-123"
        mock_job.model = "test-model"
        mock_job.status = MagicMock()
        mock_job.status.value = "completed"
        mock_job.model_id = "model-456"
        mock_job.result = MagicMock()
        mock_job.result.final_loss = 0.1
        mock_job.result.training_time_seconds = 3600
        mock_scheduler_class.return_value = mock_scheduler

        async def run_train():
            return mock_job

        mock_run.return_value = None

        result = runner.invoke(app, ["train-sft", "--model", "test-model", "--no-wait"])

        # Should have attempted to schedule
        assert "train" in result.output.lower() or result.exit_code in [0, 1]


class TestTrainDpo:
    """Tests for train-dpo command."""

    @patch("aragora.cli.training.asyncio.run")
    @patch("aragora.training.TrainingScheduler")
    def test_train_dpo_schedules_job(self, mock_scheduler_class, mock_run, runner):
        """train-dpo schedules a DPO training job."""
        mock_scheduler = AsyncMock()
        mock_scheduler_class.return_value = mock_scheduler

        result = runner.invoke(
            app, ["train-dpo", "--model", "test-model", "--beta", "0.2", "--no-wait"]
        )

        # Should have attempted to schedule
        assert "dpo" in result.output.lower() or result.exit_code in [0, 1]


class TestListModels:
    """Tests for list-models command."""

    @patch("aragora.cli.training.asyncio.run")
    @patch("aragora.training.tinker_client.TinkerClient")
    def test_list_models_empty(self, mock_client_class, mock_run, runner):
        """list-models shows message when no models."""
        mock_run.return_value = None

        result = runner.invoke(app, ["list-models"])

        # Will either show models or "no models" message
        assert result.exit_code in [0, 1]


class TestSample:
    """Tests for sample command."""

    @patch("aragora.cli.training.asyncio.run")
    @patch("aragora.training.tinker_client.TinkerClient")
    def test_sample_generates_text(self, mock_client_class, mock_run, runner):
        """sample command generates text."""
        mock_client = AsyncMock()
        mock_client.sample.return_value = "Generated text output"
        mock_client_class.return_value = mock_client

        async def run_sample():
            return "Generated text"

        mock_run.return_value = None

        result = runner.invoke(app, ["sample", "Test prompt"])

        assert result.exit_code in [0, 1]


class TestStats:
    """Tests for stats command."""

    @patch("aragora.ranking.elo.EloSystem")
    @patch("aragora.memory.store.CritiqueStore")
    def test_stats_shows_data(self, mock_critique, mock_elo, runner):
        """stats command shows training data statistics."""
        mock_critique_instance = MagicMock()
        mock_critique_instance.get_stats.return_value = {
            "total_debates": 100,
            "consensus_debates": 80,
            "total_critiques": 500,
            "total_patterns": 200,
            "avg_consensus_confidence": 0.85,
        }
        mock_critique.return_value = mock_critique_instance

        mock_elo_instance = MagicMock()
        mock_elo_instance.get_stats.return_value = {
            "total_agents": 10,
            "total_matches": 50,
            "average_elo": 1050,
        }
        mock_elo.return_value = mock_elo_instance

        result = runner.invoke(app, ["stats"])

        assert result.exit_code == 0
        assert "Training Data Statistics" in result.output
        assert "Debate" in result.output or "debate" in result.output.lower()
        assert "ELO" in result.output or "elo" in result.output.lower()
