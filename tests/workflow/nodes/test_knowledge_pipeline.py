"""
Tests for Knowledge Pipeline Step.

Tests cover:
- Pipeline initialization (config, defaults, validation)
- Step execution (sources, workspace_id, chunk strategy)
- Metrics collection (documents_processed, checkpoint/restore)
- Async execution (directory, file, URL, connector processing)
- Error handling (no sources, import errors, connector failures)
"""

import asyncio
import sys
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

CREATE_CONNECTOR = "aragora.workflow.nodes.knowledge_pipeline.create_connector"


# ============================================================================
# Helper Functions
# ============================================================================


def _make_context(inputs=None, state=None, step_outputs=None, current_step_config=None):
    """Create a WorkflowContext for testing."""
    from aragora.workflow.step import WorkflowContext

    return WorkflowContext(
        workflow_id="wf_test",
        definition_id="def_test",
        inputs=inputs or {},
        state=state or {},
        step_outputs=step_outputs or {},
        current_step_config=current_step_config or {},
    )


def _create_mock_pipeline_module():
    """Create a mock pipeline module for patching imports."""
    mock_module = MagicMock()
    mock_pipeline = MagicMock()
    mock_pipeline.start = AsyncMock()
    mock_pipeline.stop = AsyncMock()
    mock_pipeline.process_document = AsyncMock(return_value={"chunks_created": 2})
    mock_module.KnowledgePipeline = MagicMock(return_value=mock_pipeline)
    mock_module.PipelineConfig = MagicMock()
    return mock_module, mock_pipeline


def _create_mock_chunking_module():
    """Create a mock chunking module for patching imports."""
    mock_module = MagicMock()
    mock_module.ChunkingConfig = MagicMock()
    return mock_module


# ============================================================================
# Pipeline Initialization Tests
# ============================================================================


class TestKnowledgePipelineStepInit:
    """Tests for KnowledgePipelineStep initialization."""

    def test_basic_init(self):
        """Test basic KnowledgePipelineStep initialization."""
        from aragora.workflow.nodes.knowledge_pipeline import KnowledgePipelineStep

        step = KnowledgePipelineStep(
            name="Test Pipeline",
            config={"sources": ["/path/to/docs"], "workspace_id": "test"},
        )
        assert step.name == "Test Pipeline"
        assert step.config["sources"] == ["/path/to/docs"]
        assert step.config["workspace_id"] == "test"

    def test_init_with_default_config(self):
        """Test KnowledgePipelineStep with no config."""
        from aragora.workflow.nodes.knowledge_pipeline import KnowledgePipelineStep

        step = KnowledgePipelineStep(name="Empty Pipeline")
        assert step.config == {}
        assert step._documents_processed == 0
        assert step._pipeline is None

    def test_init_with_full_config(self):
        """Test KnowledgePipelineStep with comprehensive config."""
        from aragora.workflow.nodes.knowledge_pipeline import KnowledgePipelineStep

        step = KnowledgePipelineStep(
            name="Full Config Pipeline",
            config={
                "sources": ["/path/to/docs", "https://example.com"],
                "workspace_id": "legal",
                "chunk_strategy": "semantic",
                "chunk_size": 1024,
                "chunk_overlap": 128,
                "embedding_model": "text-embedding-3-large",
                "use_knowledge_mound": True,
                "extract_facts": True,
                "connector_type": "web",
                "connector_config": {"timeout": 60},
                "timeout_seconds": 300.0,
                "batch_size": 5,
            },
        )
        assert step.config["chunk_strategy"] == "semantic"
        assert step.config["chunk_size"] == 1024
        assert step.config["chunk_overlap"] == 128

    def test_chunk_strategies_constant(self):
        """Test that CHUNK_STRATEGIES constant is defined correctly."""
        from aragora.workflow.nodes.knowledge_pipeline import KnowledgePipelineStep

        assert "semantic" in KnowledgePipelineStep.CHUNK_STRATEGIES
        assert "sliding" in KnowledgePipelineStep.CHUNK_STRATEGIES
        assert "recursive" in KnowledgePipelineStep.CHUNK_STRATEGIES
        assert "sentence" in KnowledgePipelineStep.CHUNK_STRATEGIES

    def test_connector_types_constant(self):
        """Test that CONNECTOR_TYPES constant is defined correctly."""
        from aragora.workflow.nodes.knowledge_pipeline import KnowledgePipelineStep

        assert "local_docs" in KnowledgePipelineStep.CONNECTOR_TYPES
        assert "web" in KnowledgePipelineStep.CONNECTOR_TYPES
        assert "github" in KnowledgePipelineStep.CONNECTOR_TYPES
        assert "confluence" in KnowledgePipelineStep.CONNECTOR_TYPES
        assert "notion" in KnowledgePipelineStep.CONNECTOR_TYPES


# ============================================================================
# Configuration Validation Tests
# ============================================================================


class TestKnowledgePipelineValidation:
    """Tests for KnowledgePipelineStep configuration validation."""

    def test_validate_config_valid_strategy(self):
        """Test validation passes with valid chunk strategy."""
        from aragora.workflow.nodes.knowledge_pipeline import KnowledgePipelineStep

        step = KnowledgePipelineStep(
            name="Valid Strategy",
            config={"chunk_strategy": "semantic"},
        )
        assert step.validate_config() is True

    def test_validate_config_invalid_strategy(self):
        """Test validation fails with invalid chunk strategy."""
        from aragora.workflow.nodes.knowledge_pipeline import KnowledgePipelineStep

        step = KnowledgePipelineStep(
            name="Invalid Strategy",
            config={"chunk_strategy": "invalid_strategy"},
        )
        assert step.validate_config() is False

    def test_validate_config_default_strategy(self):
        """Test validation passes with default strategy when not specified."""
        from aragora.workflow.nodes.knowledge_pipeline import KnowledgePipelineStep

        step = KnowledgePipelineStep(
            name="Default Strategy",
            config={},
        )
        assert step.validate_config() is True


# ============================================================================
# Execution Tests - No Sources
# ============================================================================


class TestKnowledgePipelineNoSources:
    """Tests for KnowledgePipelineStep execution when no sources are provided."""

    @pytest.mark.asyncio
    async def test_execute_no_sources_returns_error(self):
        """Test that execution without sources returns an error result."""
        from aragora.workflow.nodes.knowledge_pipeline import KnowledgePipelineStep

        step = KnowledgePipelineStep(
            name="No Sources",
            config={"workspace_id": "test"},
        )
        ctx = _make_context()
        result = await step.execute(ctx)

        assert result["success"] is False
        assert result["error"] == "No sources specified"
        assert result["documents_processed"] == 0

    @pytest.mark.asyncio
    async def test_execute_empty_sources_list_returns_error(self):
        """Test that execution with empty sources list returns an error."""
        from aragora.workflow.nodes.knowledge_pipeline import KnowledgePipelineStep

        step = KnowledgePipelineStep(
            name="Empty Sources",
            config={"sources": [], "workspace_id": "test"},
        )
        ctx = _make_context()
        result = await step.execute(ctx)

        assert result["success"] is False
        assert result["error"] == "No sources specified"


# ============================================================================
# Execution Tests - Sources from Context
# ============================================================================


class TestKnowledgePipelineSourcesFromContext:
    """Tests for KnowledgePipelineStep execution with sources from context."""

    @pytest.mark.asyncio
    async def test_sources_from_context_inputs(self):
        """Test that sources can be provided via context inputs."""
        from aragora.workflow.nodes.knowledge_pipeline import KnowledgePipelineStep

        step = KnowledgePipelineStep(
            name="Sources from Inputs",
            config={"workspace_id": "test"},
        )

        # Mock the pipeline imports to avoid actual processing
        with patch.object(step, "_process_source", new_callable=AsyncMock) as mock_process:
            mock_process.return_value = {
                "source": "/path/to/doc",
                "type": "file",
                "documents": 1,
                "chunks": 5,
            }

            mock_pipeline_module, mock_pipeline = _create_mock_pipeline_module()
            mock_chunking_module = _create_mock_chunking_module()

            with patch.dict(
                sys.modules,
                {
                    "aragora.knowledge.pipeline": mock_pipeline_module,
                    "aragora.documents.chunking": mock_chunking_module,
                },
            ):
                ctx = _make_context(inputs={"sources": ["/path/to/doc"]})
                result = await step.execute(ctx)

        assert result["success"] is True
        assert result["sources_processed"] == 1
        mock_process.assert_called_once()

    @pytest.mark.asyncio
    async def test_sources_merged_from_config_and_inputs(self):
        """Test that sources from config and inputs are merged."""
        from aragora.workflow.nodes.knowledge_pipeline import KnowledgePipelineStep

        step = KnowledgePipelineStep(
            name="Merged Sources",
            config={"sources": ["/config/source"], "workspace_id": "test"},
        )

        with patch.object(step, "_process_source", new_callable=AsyncMock) as mock_process:
            mock_process.return_value = {
                "source": "test",
                "type": "file",
                "documents": 1,
                "chunks": 5,
            }

            mock_pipeline_module, mock_pipeline = _create_mock_pipeline_module()
            mock_chunking_module = _create_mock_chunking_module()

            with patch.dict(
                sys.modules,
                {
                    "aragora.knowledge.pipeline": mock_pipeline_module,
                    "aragora.documents.chunking": mock_chunking_module,
                },
            ):
                ctx = _make_context(inputs={"sources": ["/input/source"]})
                result = await step.execute(ctx)

        assert result["sources_processed"] == 2
        assert mock_process.call_count == 2


# ============================================================================
# Execution Tests - Chunk Strategy Handling
# ============================================================================


class TestKnowledgePipelineChunkStrategy:
    """Tests for KnowledgePipelineStep chunk strategy handling."""

    @pytest.mark.asyncio
    async def test_invalid_chunk_strategy_falls_back_to_semantic(self):
        """Test that invalid chunk strategy falls back to semantic."""
        from aragora.workflow.nodes.knowledge_pipeline import KnowledgePipelineStep

        step = KnowledgePipelineStep(
            name="Invalid Strategy Test",
            config={
                "sources": ["/test/path"],
                "workspace_id": "test",
                "chunk_strategy": "invalid_strategy",
            },
        )

        with patch.object(step, "_process_source", new_callable=AsyncMock) as mock_process:
            mock_process.return_value = {
                "source": "test",
                "type": "file",
                "documents": 1,
                "chunks": 5,
            }

            mock_pipeline_module, mock_pipeline = _create_mock_pipeline_module()
            mock_chunking_module = _create_mock_chunking_module()

            with patch.dict(
                sys.modules,
                {
                    "aragora.knowledge.pipeline": mock_pipeline_module,
                    "aragora.documents.chunking": mock_chunking_module,
                },
            ):
                ctx = _make_context()
                result = await step.execute(ctx)

        assert result["chunk_strategy"] == "semantic"


# ============================================================================
# Execution Tests - Import Error Handling
# ============================================================================


class TestKnowledgePipelineImportErrors:
    """Tests for KnowledgePipelineStep import error handling."""

    @pytest.mark.asyncio
    async def test_import_error_returns_failure(self):
        """Test that ImportError is handled gracefully."""
        from aragora.workflow.nodes.knowledge_pipeline import KnowledgePipelineStep

        step = KnowledgePipelineStep(
            name="Import Error Test",
            config={"sources": ["/test/path"], "workspace_id": "test"},
        )

        ctx = _make_context()

        # Simulate ImportError by patching the import
        with patch.dict("sys.modules", {"aragora.knowledge.pipeline": None}):
            original_import = (
                __builtins__.__import__ if hasattr(__builtins__, "__import__") else __import__
            )

            def mock_import(name, *args, **kwargs):
                if "aragora.knowledge.pipeline" in name or name == "aragora.knowledge.pipeline":
                    raise ImportError("No module named 'aragora.knowledge.pipeline'")
                return original_import(name, *args, **kwargs)

            with patch("builtins.__import__", side_effect=mock_import):
                result = await step.execute(ctx)

        assert result["success"] is False
        assert "Knowledge pipeline not available" in result["error"]
        assert result["documents_processed"] == 0


# ============================================================================
# Source Processing Tests
# ============================================================================


class TestKnowledgePipelineProcessSource:
    """Tests for KnowledgePipelineStep source processing."""

    @pytest.mark.asyncio
    async def test_process_source_detects_local_directory(self):
        """Test that process_source correctly handles local directories."""
        from aragora.workflow.nodes.knowledge_pipeline import KnowledgePipelineStep

        with tempfile.TemporaryDirectory() as tmpdir:
            # Create test file
            test_file = Path(tmpdir) / "test.txt"
            test_file.write_text("Test content")

            step = KnowledgePipelineStep(
                name="Directory Test",
                config={"sources": [tmpdir], "workspace_id": "test"},
            )

            # Mock the pipeline
            mock_pipeline_module, mock_pipeline = _create_mock_pipeline_module()
            mock_chunking_module = _create_mock_chunking_module()

            with patch.dict(
                sys.modules,
                {
                    "aragora.knowledge.pipeline": mock_pipeline_module,
                    "aragora.documents.chunking": mock_chunking_module,
                },
            ):
                ctx = _make_context()
                result = await step.execute(ctx)

            assert result["success"] is True
            assert result["sources_processed"] == 1
            # Should have processed the directory
            assert result["results"][0]["type"] == "directory"

    @pytest.mark.asyncio
    async def test_process_source_detects_local_file(self):
        """Test that process_source correctly handles local files."""
        from aragora.workflow.nodes.knowledge_pipeline import KnowledgePipelineStep

        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
            f.write("Test file content")
            temp_path = f.name

        try:
            step = KnowledgePipelineStep(
                name="File Test",
                config={"sources": [temp_path], "workspace_id": "test"},
            )

            mock_pipeline_module, mock_pipeline = _create_mock_pipeline_module()
            mock_chunking_module = _create_mock_chunking_module()

            with patch.dict(
                sys.modules,
                {
                    "aragora.knowledge.pipeline": mock_pipeline_module,
                    "aragora.documents.chunking": mock_chunking_module,
                },
            ):
                ctx = _make_context()
                result = await step.execute(ctx)

            assert result["success"] is True
            assert result["results"][0]["type"] == "file"
            assert result["results"][0]["documents"] == 1
        finally:
            Path(temp_path).unlink()

    @pytest.mark.asyncio
    async def test_process_source_detects_http_url(self):
        """Test that process_source correctly identifies HTTP URLs."""
        from aragora.workflow.nodes.knowledge_pipeline import KnowledgePipelineStep

        step = KnowledgePipelineStep(
            name="URL Test",
            config={"sources": ["https://example.com/doc.pdf"], "workspace_id": "test"},
        )

        mock_pipeline_module, mock_pipeline = _create_mock_pipeline_module()
        mock_chunking_module = _create_mock_chunking_module()

        # Mock the web connector
        mock_connector = MagicMock()
        mock_connector.fetch = AsyncMock(return_value="Fetched content from URL")

        with (
            patch.dict(
                sys.modules,
                {
                    "aragora.knowledge.pipeline": mock_pipeline_module,
                    "aragora.documents.chunking": mock_chunking_module,
                },
            ),
            patch(CREATE_CONNECTOR, return_value=mock_connector),
        ):
            ctx = _make_context()
            result = await step.execute(ctx)

        assert result["success"] is True
        assert result["results"][0]["type"] == "url"

    @pytest.mark.asyncio
    async def test_process_source_falls_back_to_connector(self):
        """Test that process_source falls back to connector for unknown sources."""
        from aragora.workflow.nodes.knowledge_pipeline import KnowledgePipelineStep

        step = KnowledgePipelineStep(
            name="Connector Test",
            config={
                "sources": ["repo/my-project"],
                "workspace_id": "test",
                "connector_type": "github",
            },
        )

        mock_pipeline_module, mock_pipeline = _create_mock_pipeline_module()
        mock_chunking_module = _create_mock_chunking_module()

        # Mock the connector module
        mock_connector = MagicMock()
        mock_connector.fetch_all = AsyncMock(
            return_value=[
                {"content": "File 1", "filename": "readme.md", "metadata": {}},
                {"content": "File 2", "filename": "main.py", "metadata": {}},
            ]
        )
        mock_connector_class = MagicMock(return_value=mock_connector)
        mock_github_module = MagicMock()
        mock_github_module.GithubConnector = mock_connector_class

        with patch.dict(
            sys.modules,
            {
                "aragora.knowledge.pipeline": mock_pipeline_module,
                "aragora.documents.chunking": mock_chunking_module,
                "aragora.connectors.github": mock_github_module,
            },
        ):
            ctx = _make_context()
            result = await step.execute(ctx)

        assert result["results"][0]["type"] == "github"
        assert result["results"][0]["documents"] == 2


# ============================================================================
# File Type Support Tests
# ============================================================================


class TestKnowledgePipelineFileSupport:
    """Tests for KnowledgePipelineStep file type support."""

    def test_is_supported_file_text_formats(self):
        """Test that text formats are supported."""
        from aragora.workflow.nodes.knowledge_pipeline import KnowledgePipelineStep

        step = KnowledgePipelineStep(name="File Support Test")

        assert step._is_supported_file(Path("test.txt")) is True
        assert step._is_supported_file(Path("test.md")) is True
        assert step._is_supported_file(Path("test.rst")) is True
        assert step._is_supported_file(Path("test.html")) is True
        assert step._is_supported_file(Path("test.htm")) is True

    def test_is_supported_file_document_formats(self):
        """Test that document formats are supported."""
        from aragora.workflow.nodes.knowledge_pipeline import KnowledgePipelineStep

        step = KnowledgePipelineStep(name="Doc Support Test")

        assert step._is_supported_file(Path("test.pdf")) is True
        assert step._is_supported_file(Path("test.docx")) is True
        assert step._is_supported_file(Path("test.doc")) is True
        assert step._is_supported_file(Path("test.pptx")) is True
        assert step._is_supported_file(Path("test.ppt")) is True

    def test_is_supported_file_code_formats(self):
        """Test that code formats are supported."""
        from aragora.workflow.nodes.knowledge_pipeline import KnowledgePipelineStep

        step = KnowledgePipelineStep(name="Code Support Test")

        assert step._is_supported_file(Path("test.py")) is True
        assert step._is_supported_file(Path("test.js")) is True
        assert step._is_supported_file(Path("test.ts")) is True
        assert step._is_supported_file(Path("test.java")) is True
        assert step._is_supported_file(Path("test.go")) is True
        assert step._is_supported_file(Path("test.rs")) is True

    def test_is_supported_file_data_formats(self):
        """Test that data formats are supported."""
        from aragora.workflow.nodes.knowledge_pipeline import KnowledgePipelineStep

        step = KnowledgePipelineStep(name="Data Support Test")

        assert step._is_supported_file(Path("test.json")) is True
        assert step._is_supported_file(Path("test.yaml")) is True
        assert step._is_supported_file(Path("test.yml")) is True
        assert step._is_supported_file(Path("test.xml")) is True
        assert step._is_supported_file(Path("test.csv")) is True

    def test_is_supported_file_unsupported(self):
        """Test that unsupported formats return False."""
        from aragora.workflow.nodes.knowledge_pipeline import KnowledgePipelineStep

        step = KnowledgePipelineStep(name="Unsupported Test")

        assert step._is_supported_file(Path("test.exe")) is False
        assert step._is_supported_file(Path("test.bin")) is False
        assert step._is_supported_file(Path("test.zip")) is False
        assert step._is_supported_file(Path("test.png")) is False
        assert step._is_supported_file(Path("test.jpg")) is False

    def test_is_supported_file_case_insensitive(self):
        """Test that file extension check is case insensitive."""
        from aragora.workflow.nodes.knowledge_pipeline import KnowledgePipelineStep

        step = KnowledgePipelineStep(name="Case Test")

        assert step._is_supported_file(Path("test.TXT")) is True
        assert step._is_supported_file(Path("test.MD")) is True
        assert step._is_supported_file(Path("test.Py")) is True


# ============================================================================
# Checkpoint/Restore Tests
# ============================================================================


class TestKnowledgePipelineCheckpoint:
    """Tests for KnowledgePipelineStep checkpoint/restore functionality."""

    @pytest.mark.asyncio
    async def test_checkpoint_saves_documents_processed(self):
        """Test that checkpoint saves documents_processed count."""
        from aragora.workflow.nodes.knowledge_pipeline import KnowledgePipelineStep

        step = KnowledgePipelineStep(name="Checkpoint Test")
        step._documents_processed = 42

        state = await step.checkpoint()

        assert state["documents_processed"] == 42

    @pytest.mark.asyncio
    async def test_restore_restores_documents_processed(self):
        """Test that restore restores documents_processed count."""
        from aragora.workflow.nodes.knowledge_pipeline import KnowledgePipelineStep

        step = KnowledgePipelineStep(name="Restore Test")
        assert step._documents_processed == 0

        await step.restore({"documents_processed": 100})

        assert step._documents_processed == 100

    @pytest.mark.asyncio
    async def test_restore_handles_missing_key(self):
        """Test that restore handles missing documents_processed key."""
        from aragora.workflow.nodes.knowledge_pipeline import KnowledgePipelineStep

        step = KnowledgePipelineStep(name="Restore Missing Key")
        step._documents_processed = 50

        await step.restore({})

        assert step._documents_processed == 0


# ============================================================================
# Error Handling Tests
# ============================================================================


class TestKnowledgePipelineErrorHandling:
    """Tests for KnowledgePipelineStep error handling."""

    @pytest.mark.asyncio
    async def test_source_processing_error_captured(self):
        """Test that source processing errors are captured and reported."""
        from aragora.workflow.nodes.knowledge_pipeline import KnowledgePipelineStep

        step = KnowledgePipelineStep(
            name="Error Test",
            config={"sources": ["/nonexistent/path", "/another/path"], "workspace_id": "test"},
        )

        async def mock_process_source_with_error(source, connector_type, connector_config):
            if source == "/nonexistent/path":
                raise ValueError("Source not found")
            return {"source": source, "type": "file", "documents": 1, "chunks": 5}

        mock_pipeline_module, mock_pipeline = _create_mock_pipeline_module()
        mock_chunking_module = _create_mock_chunking_module()

        with patch.dict(
            sys.modules,
            {
                "aragora.knowledge.pipeline": mock_pipeline_module,
                "aragora.documents.chunking": mock_chunking_module,
            },
        ):
            with patch.object(step, "_process_source", side_effect=mock_process_source_with_error):
                ctx = _make_context()
                result = await step.execute(ctx)

        assert result["success"] is False
        assert result["sources_failed"] == 1
        assert result["sources_processed"] == 1
        assert len(result["errors"]) == 1
        assert result["errors"][0]["source"] == "/nonexistent/path"
        assert result["errors"][0]["error"] == "Source processing failed"

    @pytest.mark.asyncio
    async def test_all_sources_fail_returns_failure(self):
        """Test that result is failure when all sources fail."""
        from aragora.workflow.nodes.knowledge_pipeline import KnowledgePipelineStep

        step = KnowledgePipelineStep(
            name="All Fail Test",
            config={"sources": ["/bad/path1", "/bad/path2"], "workspace_id": "test"},
        )

        async def mock_always_fail(source, connector_type, connector_config):
            raise RuntimeError("Processing failed")

        mock_pipeline_module, mock_pipeline = _create_mock_pipeline_module()
        mock_chunking_module = _create_mock_chunking_module()

        with patch.dict(
            sys.modules,
            {
                "aragora.knowledge.pipeline": mock_pipeline_module,
                "aragora.documents.chunking": mock_chunking_module,
            },
        ):
            with patch.object(step, "_process_source", side_effect=mock_always_fail):
                ctx = _make_context()
                result = await step.execute(ctx)

        assert result["success"] is False
        assert result["sources_failed"] == 2
        assert result["sources_processed"] == 0
        assert result["documents_processed"] == 0


# ============================================================================
# URL Processing Tests
# ============================================================================


class TestKnowledgePipelineURLProcessing:
    """Tests for KnowledgePipelineStep URL processing."""

    @pytest.mark.asyncio
    async def test_process_url_with_web_connector(self):
        """Test URL processing with WebConnector."""
        from aragora.workflow.nodes.knowledge_pipeline import KnowledgePipelineStep

        step = KnowledgePipelineStep(name="URL Process Test")
        step._pipeline = MagicMock()
        step._pipeline.process_document = AsyncMock(return_value={"chunks_created": 3})

        mock_connector = MagicMock()
        mock_connector.fetch = AsyncMock(return_value="Fetched web content")

        with patch(CREATE_CONNECTOR, return_value=mock_connector):
            result = await step._process_url("https://example.com/page", {})

        assert result["type"] == "url"
        assert result["source"] == "https://example.com/page"
        assert result["documents"] == 1
        assert result["chunks"] == 3

    @pytest.mark.asyncio
    async def test_process_url_without_web_connector(self):
        """Test URL processing when WebConnector is not available."""
        from aragora.workflow.nodes.knowledge_pipeline import KnowledgePipelineStep

        step = KnowledgePipelineStep(name="URL No Connector Test")

        with patch(CREATE_CONNECTOR, side_effect=ImportError("no httpx")):
            result = await step._process_url("https://example.com/page", {})

        assert result["type"] == "url"
        assert result["documents"] == 0
        assert "error" in result
        assert "Web connector not available" in result["error"]

    @pytest.mark.asyncio
    async def test_process_url_extracts_filename_from_path(self):
        """Test that URL processing extracts filename from URL path."""
        from aragora.workflow.nodes.knowledge_pipeline import KnowledgePipelineStep

        step = KnowledgePipelineStep(name="URL Filename Test")
        step._pipeline = MagicMock()
        step._pipeline.process_document = AsyncMock(return_value={"chunks_created": 1})

        mock_connector = MagicMock()
        mock_connector.fetch = AsyncMock(return_value="Content")

        with patch(CREATE_CONNECTOR, return_value=mock_connector):
            await step._process_url("https://example.com/docs/readme.md", {})

        # Verify the filename was extracted
        call_kwargs = step._pipeline.process_document.call_args.kwargs
        assert call_kwargs["filename"] == "readme.md"


# ============================================================================
# Connector Processing Tests
# ============================================================================


class TestKnowledgePipelineConnectorProcessing:
    """Tests for KnowledgePipelineStep connector processing."""

    @pytest.mark.asyncio
    async def test_process_with_unknown_connector_type(self):
        """Test processing with unknown connector type returns error."""
        from aragora.workflow.nodes.knowledge_pipeline import KnowledgePipelineStep

        step = KnowledgePipelineStep(name="Unknown Connector Test")

        result = await step._process_with_connector(
            source="some-source",
            connector_type="unknown_type",
            connector_config={},
        )

        assert result["type"] == "unknown_type"
        assert result["documents"] == 0
        assert "error" in result
        assert "Unknown connector type" in result["error"]

    @pytest.mark.asyncio
    async def test_process_with_connector_error(self):
        """Test processing when connector raises an error."""
        from aragora.workflow.nodes.knowledge_pipeline import KnowledgePipelineStep

        step = KnowledgePipelineStep(name="Connector Error Test")

        mock_module = MagicMock()
        mock_connector_class = MagicMock(side_effect=RuntimeError("Connection failed"))
        mock_module.GithubConnector = mock_connector_class

        with patch("importlib.import_module", return_value=mock_module):
            result = await step._process_with_connector(
                source="repo/project",
                connector_type="github",
                connector_config={},
            )

        assert result["type"] == "github"
        assert result["documents"] == 0
        assert "error" in result
        assert result["error"] == "Connector processing failed"


# ============================================================================
# Directory Processing Tests
# ============================================================================


class TestKnowledgePipelineDirectoryProcessing:
    """Tests for KnowledgePipelineStep directory processing."""

    @pytest.mark.asyncio
    async def test_process_directory_with_multiple_files(self):
        """Test processing a directory with multiple files."""
        from aragora.workflow.nodes.knowledge_pipeline import KnowledgePipelineStep

        with tempfile.TemporaryDirectory() as tmpdir:
            # Create test files
            (Path(tmpdir) / "file1.txt").write_text("Content 1")
            (Path(tmpdir) / "file2.md").write_text("Content 2")
            (Path(tmpdir) / "file3.py").write_text("print('hello')")
            # Create unsupported file
            (Path(tmpdir) / "image.png").write_bytes(b"\x89PNG")

            step = KnowledgePipelineStep(name="Multi-File Test")
            step._pipeline = MagicMock()
            step._pipeline.process_document = AsyncMock(return_value={"chunks_created": 2})

            result = await step._process_directory(Path(tmpdir))

            assert result["type"] == "directory"
            assert result["documents"] == 3  # Only supported files
            assert result["chunks"] == 6  # 3 files * 2 chunks each

    @pytest.mark.asyncio
    async def test_process_directory_handles_file_errors(self):
        """Test that directory processing handles individual file errors gracefully."""
        from aragora.workflow.nodes.knowledge_pipeline import KnowledgePipelineStep

        with tempfile.TemporaryDirectory() as tmpdir:
            # Create test files
            (Path(tmpdir) / "good.txt").write_text("Good content")
            (Path(tmpdir) / "bad.txt").write_text("Bad content")

            step = KnowledgePipelineStep(name="File Error Test")
            step._pipeline = MagicMock()

            call_count = [0]

            async def mock_process_document(**kwargs):
                call_count[0] += 1
                if "bad" in kwargs.get("filename", ""):
                    raise ValueError("Failed to process")
                return {"chunks_created": 1}

            step._pipeline.process_document = mock_process_document

            result = await step._process_directory(Path(tmpdir))

            # Should process good file but skip bad file
            assert result["documents"] == 1

    @pytest.mark.asyncio
    async def test_process_directory_recursive(self):
        """Test that directory processing is recursive."""
        from aragora.workflow.nodes.knowledge_pipeline import KnowledgePipelineStep

        with tempfile.TemporaryDirectory() as tmpdir:
            # Create nested structure
            subdir = Path(tmpdir) / "subdir"
            subdir.mkdir()
            (Path(tmpdir) / "root.txt").write_text("Root content")
            (subdir / "nested.txt").write_text("Nested content")

            step = KnowledgePipelineStep(name="Recursive Test")
            step._pipeline = MagicMock()
            step._pipeline.process_document = AsyncMock(return_value={"chunks_created": 1})

            result = await step._process_directory(Path(tmpdir))

            assert result["documents"] == 2  # Both root and nested file


# ============================================================================
# Metrics Collection Tests
# ============================================================================


class TestKnowledgePipelineMetrics:
    """Tests for KnowledgePipelineStep metrics collection."""

    @pytest.mark.asyncio
    async def test_documents_processed_accumulated(self):
        """Test that documents_processed is accumulated across sources."""
        from aragora.workflow.nodes.knowledge_pipeline import KnowledgePipelineStep

        step = KnowledgePipelineStep(
            name="Metrics Test",
            config={"sources": ["/source1", "/source2", "/source3"], "workspace_id": "test"},
        )

        call_count = [0]

        async def mock_process_source(source, connector_type, connector_config):
            call_count[0] += 1
            return {
                "source": source,
                "type": "file",
                "documents": call_count[0] * 2,  # 2, 4, 6
                "chunks": 10,
            }

        mock_pipeline_module, mock_pipeline = _create_mock_pipeline_module()
        mock_chunking_module = _create_mock_chunking_module()

        with patch.dict(
            sys.modules,
            {
                "aragora.knowledge.pipeline": mock_pipeline_module,
                "aragora.documents.chunking": mock_chunking_module,
            },
        ):
            with patch.object(step, "_process_source", side_effect=mock_process_source):
                ctx = _make_context()
                result = await step.execute(ctx)

        assert result["documents_processed"] == 12  # 2 + 4 + 6
        assert step._documents_processed == 12

    @pytest.mark.asyncio
    async def test_result_includes_workspace_id(self):
        """Test that result includes the workspace_id."""
        from aragora.workflow.nodes.knowledge_pipeline import KnowledgePipelineStep

        step = KnowledgePipelineStep(
            name="Workspace Test",
            config={"sources": ["/test"], "workspace_id": "my_workspace"},
        )

        with patch.object(step, "_process_source", new_callable=AsyncMock) as mock_process:
            mock_process.return_value = {
                "source": "test",
                "type": "file",
                "documents": 1,
                "chunks": 1,
            }

            mock_pipeline_module, mock_pipeline = _create_mock_pipeline_module()
            mock_chunking_module = _create_mock_chunking_module()

            with patch.dict(
                sys.modules,
                {
                    "aragora.knowledge.pipeline": mock_pipeline_module,
                    "aragora.documents.chunking": mock_chunking_module,
                },
            ):
                ctx = _make_context()
                result = await step.execute(ctx)

        assert result["workspace_id"] == "my_workspace"

    @pytest.mark.asyncio
    async def test_workspace_id_from_context_input(self):
        """Test that workspace_id can be provided via context input."""
        from aragora.workflow.nodes.knowledge_pipeline import KnowledgePipelineStep

        step = KnowledgePipelineStep(
            name="Context Workspace Test",
            config={"sources": ["/test"]},
        )

        with patch.object(step, "_process_source", new_callable=AsyncMock) as mock_process:
            mock_process.return_value = {
                "source": "test",
                "type": "file",
                "documents": 1,
                "chunks": 1,
            }

            mock_pipeline_module, mock_pipeline = _create_mock_pipeline_module()
            mock_chunking_module = _create_mock_chunking_module()

            with patch.dict(
                sys.modules,
                {
                    "aragora.knowledge.pipeline": mock_pipeline_module,
                    "aragora.documents.chunking": mock_chunking_module,
                },
            ):
                ctx = _make_context(inputs={"workspace_id": "context_workspace"})
                result = await step.execute(ctx)

        assert result["workspace_id"] == "context_workspace"


# ============================================================================
# Web Connector Config Tests
# ============================================================================


class TestWebConnectorConfig:
    """Tests for WebConnectorConfig TypedDict."""

    def test_web_connector_config_type(self):
        """Test WebConnectorConfig TypedDict structure."""
        from aragora.workflow.nodes.knowledge_pipeline import WebConnectorConfig

        config: WebConnectorConfig = {
            "default_confidence": 0.7,
            "timeout": 30,
            "max_content_length": 10000,
            "rate_limit_delay": 1.0,
            "cache_dir": ".cache",
            "enable_circuit_breaker": True,
        }

        assert config["default_confidence"] == 0.7
        assert config["timeout"] == 30
        assert config["max_content_length"] == 10000

    def test_web_connector_config_partial(self):
        """Test that WebConnectorConfig allows partial specification."""
        from aragora.workflow.nodes.knowledge_pipeline import WebConnectorConfig

        # total=False means all fields are optional
        config: WebConnectorConfig = {"timeout": 60}

        assert config["timeout"] == 60


# ============================================================================
# Pipeline Lifecycle Tests
# ============================================================================


class TestKnowledgePipelineLifecycle:
    """Tests for KnowledgePipelineStep pipeline lifecycle management."""

    @pytest.mark.asyncio
    async def test_pipeline_start_and_stop_called(self):
        """Test that pipeline start() and stop() are called."""
        from aragora.workflow.nodes.knowledge_pipeline import KnowledgePipelineStep

        step = KnowledgePipelineStep(
            name="Lifecycle Test",
            config={"sources": ["/test"], "workspace_id": "test"},
        )

        with patch.object(step, "_process_source", new_callable=AsyncMock) as mock_process:
            mock_process.return_value = {
                "source": "test",
                "type": "file",
                "documents": 1,
                "chunks": 1,
            }

            mock_pipeline_module, mock_pipeline = _create_mock_pipeline_module()
            mock_chunking_module = _create_mock_chunking_module()

            with patch.dict(
                sys.modules,
                {
                    "aragora.knowledge.pipeline": mock_pipeline_module,
                    "aragora.documents.chunking": mock_chunking_module,
                },
            ):
                ctx = _make_context()
                await step.execute(ctx)

        mock_pipeline.start.assert_called_once()
        mock_pipeline.stop.assert_called_once()

    @pytest.mark.asyncio
    async def test_pipeline_stored_on_step(self):
        """Test that pipeline instance is stored on step during execution."""
        from aragora.workflow.nodes.knowledge_pipeline import KnowledgePipelineStep

        step = KnowledgePipelineStep(
            name="Storage Test",
            config={"sources": ["/test"], "workspace_id": "test"},
        )

        assert step._pipeline is None

        with patch.object(step, "_process_source", new_callable=AsyncMock) as mock_process:
            mock_process.return_value = {
                "source": "test",
                "type": "file",
                "documents": 1,
                "chunks": 1,
            }

            mock_pipeline_module, mock_pipeline = _create_mock_pipeline_module()
            mock_chunking_module = _create_mock_chunking_module()

            with patch.dict(
                sys.modules,
                {
                    "aragora.knowledge.pipeline": mock_pipeline_module,
                    "aragora.documents.chunking": mock_chunking_module,
                },
            ):
                ctx = _make_context()
                await step.execute(ctx)

        assert step._pipeline is mock_pipeline


# ============================================================================
# Config Override Tests
# ============================================================================


class TestKnowledgePipelineConfigOverride:
    """Tests for KnowledgePipelineStep config override via context."""

    @pytest.mark.asyncio
    async def test_current_step_config_overrides_step_config(self):
        """Test that current_step_config overrides step config."""
        from aragora.workflow.nodes.knowledge_pipeline import KnowledgePipelineStep

        step = KnowledgePipelineStep(
            name="Override Test",
            config={
                "sources": ["/original"],
                "workspace_id": "original",
                "chunk_strategy": "semantic",
            },
        )

        with patch.object(step, "_process_source", new_callable=AsyncMock) as mock_process:
            mock_process.return_value = {
                "source": "test",
                "type": "file",
                "documents": 1,
                "chunks": 1,
            }

            mock_pipeline_module, mock_pipeline = _create_mock_pipeline_module()
            mock_chunking_module = _create_mock_chunking_module()

            with patch.dict(
                sys.modules,
                {
                    "aragora.knowledge.pipeline": mock_pipeline_module,
                    "aragora.documents.chunking": mock_chunking_module,
                },
            ):
                ctx = _make_context(
                    current_step_config={
                        "workspace_id": "overridden",
                        "chunk_strategy": "sliding",
                    }
                )
                result = await step.execute(ctx)

        assert result["workspace_id"] == "overridden"
        assert result["chunk_strategy"] == "sliding"


# ============================================================================
# File Processing Tests
# ============================================================================


class TestKnowledgePipelineFileProcessing:
    """Tests for KnowledgePipelineStep single file processing."""

    @pytest.mark.asyncio
    async def test_process_file_reads_content(self):
        """Test that process_file reads file content correctly."""
        from aragora.workflow.nodes.knowledge_pipeline import KnowledgePipelineStep

        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
            f.write("Test file content for processing")
            temp_path = f.name

        try:
            step = KnowledgePipelineStep(name="File Read Test")
            step._pipeline = MagicMock()
            step._pipeline.process_document = AsyncMock(return_value={"chunks_created": 5})

            result = await step._process_file(Path(temp_path))

            assert result["type"] == "file"
            assert result["documents"] == 1
            assert result["chunks"] == 5

            # Verify process_document was called with correct content
            call_kwargs = step._pipeline.process_document.call_args.kwargs
            assert call_kwargs["content"] == "Test file content for processing"
        finally:
            Path(temp_path).unlink()

    @pytest.mark.asyncio
    async def test_process_file_includes_metadata(self):
        """Test that process_file includes path metadata."""
        from aragora.workflow.nodes.knowledge_pipeline import KnowledgePipelineStep

        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
            f.write("Content")
            temp_path = f.name

        try:
            step = KnowledgePipelineStep(name="File Metadata Test")
            step._pipeline = MagicMock()
            step._pipeline.process_document = AsyncMock(return_value={"chunks_created": 1})

            await step._process_file(Path(temp_path))

            call_kwargs = step._pipeline.process_document.call_args.kwargs
            assert "metadata" in call_kwargs
            assert call_kwargs["metadata"]["path"] == temp_path
        finally:
            Path(temp_path).unlink()
