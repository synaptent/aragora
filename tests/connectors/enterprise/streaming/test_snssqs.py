"""
Tests for AWS SNS/SQS Enterprise Streaming Connector.

Tests cover:
- Configuration and initialization
- Message parsing and deserialization
- SNS notification unwrapping
- SyncItem conversion for Knowledge Mound
- Error handling and circuit breaker integration
- FIFO queue support

These tests mock aioboto3 to avoid requiring actual AWS services.
"""

import asyncio
import json
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# =============================================================================
# Configuration Tests
# =============================================================================


class TestSNSSQSConfig:
    """Tests for SNSSQSConfig."""

    def test_default_config_requires_queue_url(self):
        """Should require queue_url."""
        from aragora.connectors.enterprise.streaming.snssqs import SNSSQSConfig

        with pytest.raises(ValueError, match="queue_url is required"):
            SNSSQSConfig()

    def test_config_with_queue_url(self):
        """Should initialize with queue URL."""
        from aragora.connectors.enterprise.streaming.snssqs import SNSSQSConfig

        config = SNSSQSConfig(queue_url="https://sqs.us-east-1.amazonaws.com/123456789/my-queue")

        assert config.region == "us-east-1"
        assert config.queue_url == "https://sqs.us-east-1.amazonaws.com/123456789/my-queue"
        assert config.max_messages == 10
        assert config.wait_time_seconds == 20
        assert config.visibility_timeout_seconds == 300
        assert config.auto_delete is True
        assert config.is_fifo_queue is False

    def test_custom_config(self):
        """Should accept custom configuration."""
        from aragora.connectors.enterprise.streaming.snssqs import SNSSQSConfig

        config = SNSSQSConfig(
            region="eu-west-1",
            queue_url="https://sqs.eu-west-1.amazonaws.com/123456789/prod-queue.fifo",
            topic_arn="arn:aws:sns:eu-west-1:123456789:prod-topic",
            max_messages=5,
            wait_time_seconds=10,
            visibility_timeout_seconds=600,
            is_fifo_queue=True,
            message_group_id="group-1",
        )

        assert config.region == "eu-west-1"
        assert config.topic_arn == "arn:aws:sns:eu-west-1:123456789:prod-topic"
        assert config.max_messages == 5
        assert config.wait_time_seconds == 10
        assert config.is_fifo_queue is True
        assert config.message_group_id == "group-1"

    def test_config_validation_max_messages(self):
        """Should validate max_messages range."""
        from aragora.connectors.enterprise.streaming.snssqs import SNSSQSConfig

        with pytest.raises(ValueError, match="max_messages must be between 1 and 10"):
            SNSSQSConfig(
                queue_url="https://sqs.us-east-1.amazonaws.com/123456789/queue",
                max_messages=0,
            )

        with pytest.raises(ValueError, match="max_messages must be between 1 and 10"):
            SNSSQSConfig(
                queue_url="https://sqs.us-east-1.amazonaws.com/123456789/queue",
                max_messages=11,
            )

    def test_config_validation_wait_time(self):
        """Should validate wait_time_seconds range."""
        from aragora.connectors.enterprise.streaming.snssqs import SNSSQSConfig

        with pytest.raises(ValueError, match="wait_time_seconds must be between 0 and 20"):
            SNSSQSConfig(
                queue_url="https://sqs.us-east-1.amazonaws.com/123456789/queue",
                wait_time_seconds=-1,
            )

        with pytest.raises(ValueError, match="wait_time_seconds must be between 0 and 20"):
            SNSSQSConfig(
                queue_url="https://sqs.us-east-1.amazonaws.com/123456789/queue",
                wait_time_seconds=21,
            )


# =============================================================================
# Connector Initialization Tests
# =============================================================================


class TestSNSSQSConnectorInitialization:
    """Tests for connector initialization."""

    def test_init_with_defaults(self):
        """Should initialize with default config."""
        from aragora.connectors.enterprise.streaming.snssqs import (
            SNSSQSConnector,
            SNSSQSConfig,
        )

        config = SNSSQSConfig(queue_url="https://sqs.us-east-1.amazonaws.com/123456789/test-queue")
        connector = SNSSQSConnector(config)

        assert connector.connector_id == "snssqs"
        assert (
            connector.config.queue_url == "https://sqs.us-east-1.amazonaws.com/123456789/test-queue"
        )
        assert connector._sqs_client is None
        assert connector._running is False
        assert connector._consumed_count == 0
        assert connector._error_count == 0

    def test_connector_stats(self):
        """Should provide accurate statistics."""
        from aragora.connectors.enterprise.streaming.snssqs import (
            SNSSQSConnector,
            SNSSQSConfig,
        )

        config = SNSSQSConfig(
            region="us-west-2",
            queue_url="https://sqs.us-west-2.amazonaws.com/123456789/prod-queue",
        )
        connector = SNSSQSConnector(config)

        stats = connector.get_stats()

        assert stats["consumed_count"] == 0
        assert stats["error_count"] == 0
        assert stats["dlq_count"] == 0
        assert stats["pending_deletes"] == 0
        assert stats["is_running"] is False

    def test_circuit_breaker_enabled_by_default(self):
        """Should enable circuit breaker by default."""
        from aragora.connectors.enterprise.streaming.snssqs import (
            SNSSQSConnector,
            SNSSQSConfig,
        )

        config = SNSSQSConfig(queue_url="https://sqs.us-east-1.amazonaws.com/123456789/queue")
        connector = SNSSQSConnector(config)

        assert connector._streaming_circuit_breaker is not None

    def test_circuit_breaker_can_be_disabled(self):
        """Should allow disabling circuit breaker."""
        from aragora.connectors.enterprise.streaming.snssqs import (
            SNSSQSConnector,
            SNSSQSConfig,
        )

        config = SNSSQSConfig(
            queue_url="https://sqs.us-east-1.amazonaws.com/123456789/queue",
            enable_circuit_breaker=False,
        )
        connector = SNSSQSConnector(config)

        assert connector._streaming_circuit_breaker is None


# =============================================================================
# Message Parsing Tests
# =============================================================================


class TestSQSMessageParsing:
    """Tests for SQS message parsing."""

    def test_parse_json_message(self):
        """Should parse JSON message body."""
        from aragora.connectors.enterprise.streaming.snssqs import SQSMessage

        msg_data = {
            "MessageId": "abc123",
            "ReceiptHandle": "handle123",
            "Body": json.dumps({"type": "decision", "data": "test"}),
            "MD5OfBody": "d41d8cd98f00b204e9800998ecf8427e",
            "Attributes": {
                "SentTimestamp": "1700000000000",
            },
            "MessageAttributes": {},
        }

        msg = SQSMessage.from_sqs_response(msg_data)

        assert msg.message_id == "abc123"
        assert msg.receipt_handle == "handle123"
        assert msg.body == {"type": "decision", "data": "test"}
        assert msg.md5_of_body == "d41d8cd98f00b204e9800998ecf8427e"

    def test_parse_string_message(self):
        """Should handle plain string message body."""
        from aragora.connectors.enterprise.streaming.snssqs import SQSMessage

        msg_data = {
            "MessageId": "abc123",
            "ReceiptHandle": "handle123",
            "Body": "Plain text message",
            "MD5OfBody": "abc123",
            "Attributes": {},
            "MessageAttributes": {},
        }

        msg = SQSMessage.from_sqs_response(msg_data)

        assert msg.body == "Plain text message"

    def test_parse_sns_notification(self):
        """Should unwrap SNS notifications."""
        from aragora.connectors.enterprise.streaming.snssqs import SQSMessage

        sns_notification = {
            "Type": "Notification",
            "MessageId": "sns-msg-id",
            "TopicArn": "arn:aws:sns:us-east-1:123456789:topic",
            "Message": json.dumps({"event": "created", "id": "123"}),
            "Timestamp": "2024-01-01T00:00:00.000Z",
        }

        msg_data = {
            "MessageId": "sqs-msg-id",
            "ReceiptHandle": "handle123",
            "Body": json.dumps(sns_notification),
            "MD5OfBody": "abc123",
            "Attributes": {"SentTimestamp": "1700000000000"},
            "MessageAttributes": {},
        }

        msg = SQSMessage.from_sqs_response(msg_data)

        # Should unwrap the SNS message
        assert msg.body == {"event": "created", "id": "123"}

    def test_parse_fifo_attributes(self):
        """Should parse FIFO queue attributes."""
        from aragora.connectors.enterprise.streaming.snssqs import SQSMessage

        msg_data = {
            "MessageId": "abc123",
            "ReceiptHandle": "handle123",
            "Body": json.dumps({"data": "test"}),
            "MD5OfBody": "abc123",
            "Attributes": {
                "SentTimestamp": "1700000000000",
                "SequenceNumber": "12345678901234567890",
                "MessageDeduplicationId": "dedup-123",
                "MessageGroupId": "group-1",
            },
            "MessageAttributes": {},
        }

        msg = SQSMessage.from_sqs_response(msg_data)

        assert msg.sequence_number == "12345678901234567890"
        assert msg.message_deduplication_id == "dedup-123"
        assert msg.message_group_id == "group-1"

    def test_parse_message_attributes(self):
        """Should parse message attributes."""
        from aragora.connectors.enterprise.streaming.snssqs import SQSMessage

        msg_data = {
            "MessageId": "abc123",
            "ReceiptHandle": "handle123",
            "Body": json.dumps({"data": "test"}),
            "MD5OfBody": "abc123",
            "Attributes": {"SentTimestamp": "1700000000000"},
            "MessageAttributes": {
                "producer": {
                    "DataType": "String",
                    "StringValue": "my-service",
                },
                "priority": {
                    "DataType": "Number",
                    "StringValue": "5",
                },
            },
        }

        msg = SQSMessage.from_sqs_response(msg_data)

        assert msg.message_attributes["producer"]["StringValue"] == "my-service"
        assert msg.message_attributes["priority"]["StringValue"] == "5"


# =============================================================================
# SyncItem Conversion Tests
# =============================================================================


class TestSQSMessageToSyncItem:
    """Tests for SyncItem conversion."""

    def test_convert_dict_body_to_sync_item(self):
        """Should convert dict body to SyncItem."""
        from aragora.connectors.enterprise.streaming.snssqs import SQSMessage

        msg = SQSMessage(
            message_id="abc123",
            receipt_handle="handle123",
            body={"title": "Test Event", "data": "test"},
            md5_of_body="abc123",
            attributes={"SentTimestamp": "1700000000000"},
            message_attributes={
                "producer": {"StringValue": "my-service"},
            },
            timestamp=datetime(2024, 1, 1, tzinfo=timezone.utc),
        )

        sync_item = msg.to_sync_item()

        assert sync_item.id == "sqs-abc123"
        assert sync_item.source_type == "event_stream"
        assert sync_item.source_id == "sqs/abc123"
        assert sync_item.title == "Test Event"
        assert sync_item.domain == "enterprise/sqs"
        assert sync_item.confidence == 0.9
        assert "title" in sync_item.content
        assert sync_item.metadata["message_id"] == "abc123"

    def test_convert_string_body_to_sync_item(self):
        """Should convert string body to SyncItem."""
        from aragora.connectors.enterprise.streaming.snssqs import SQSMessage

        msg = SQSMessage(
            message_id="abc123",
            receipt_handle="handle123",
            body="Plain text content",
            md5_of_body="abc123",
            attributes={},
            message_attributes={},
            timestamp=datetime(2024, 1, 1, tzinfo=timezone.utc),
        )

        sync_item = msg.to_sync_item()

        assert sync_item.content == "Plain text content"
        assert sync_item.title.startswith("SQS:")

    def test_convert_to_dlq_message(self):
        """Should convert to DLQMessage."""
        from aragora.connectors.enterprise.streaming.snssqs import SQSMessage

        msg = SQSMessage(
            message_id="abc123",
            receipt_handle="handle123",
            body={"data": "test"},
            md5_of_body="abc123",
            attributes={"ApproximateReceiveCount": "3"},
            message_attributes={},
            timestamp=datetime(2024, 1, 1, tzinfo=timezone.utc),
        )

        dlq_msg = msg.to_dlq_message(ValueError("Processing failed"))

        assert dlq_msg.original_key == "abc123"
        assert dlq_msg.error_type == "ValueError"
        assert dlq_msg.error_message == "Processing failed"
        assert dlq_msg.retry_count == 3
        assert dlq_msg.original_timestamp == datetime(2024, 1, 1, tzinfo=timezone.utc)


# =============================================================================
# Connection Tests
# =============================================================================


class TestSNSSQSConnectorConnection:
    """Tests for connector connection."""

    @pytest.mark.asyncio
    async def test_connect_creates_clients(self):
        """Should create SQS client on connect."""
        from aragora.connectors.enterprise.streaming.snssqs import (
            SNSSQSConnector,
            SNSSQSConfig,
        )

        config = SNSSQSConfig(queue_url="https://sqs.us-east-1.amazonaws.com/123456789/queue")
        connector = SNSSQSConnector(config)

        # Mock aioboto3
        mock_session = MagicMock()
        mock_sqs_client = AsyncMock()
        mock_sqs_client.get_queue_attributes = AsyncMock(
            return_value={"Attributes": {"QueueArn": "arn:aws:sqs:us-east-1:123456789:queue"}}
        )

        mock_context = AsyncMock()
        mock_context.__aenter__ = AsyncMock(return_value=mock_sqs_client)
        mock_session.client = MagicMock(return_value=mock_context)

        with patch.dict("sys.modules", {"aioboto3": MagicMock()}):
            with patch(
                "aragora.connectors.enterprise.streaming.snssqs.SNSSQSConnector._connect_internal"
            ) as mock_connect:
                mock_connect.return_value = True
                # Manually set the client to simulate successful connection
                connector._sqs_client = mock_sqs_client
                result = await connector.connect()

        assert result is True
        assert connector._sqs_client is not None

    @pytest.mark.asyncio
    async def test_connect_handles_import_error(self):
        """Should handle missing aioboto3."""
        from aragora.connectors.enterprise.streaming.snssqs import (
            SNSSQSConnector,
            SNSSQSConfig,
        )

        config = SNSSQSConfig(queue_url="https://sqs.us-east-1.amazonaws.com/123456789/queue")
        connector = SNSSQSConnector(config)

        with patch.dict("sys.modules", {"aioboto3": None}):
            with patch(
                "aragora.connectors.enterprise.streaming.snssqs.SNSSQSConnector._create_clients"
            ) as mock:
                mock.side_effect = ImportError("aioboto3 not found")
                result = await connector.connect()

        assert result is False

    @pytest.mark.asyncio
    async def test_disconnect_closes_clients(self):
        """Should close clients on disconnect."""
        from aragora.connectors.enterprise.streaming.snssqs import (
            SNSSQSConnector,
            SNSSQSConfig,
        )

        config = SNSSQSConfig(queue_url="https://sqs.us-east-1.amazonaws.com/123456789/queue")
        connector = SNSSQSConnector(config)

        # Setup mock client
        mock_client = AsyncMock()
        mock_client.__aexit__ = AsyncMock(return_value=False)
        connector._sqs_client = mock_client

        await connector.disconnect()

        mock_client.__aexit__.assert_called_once()
        assert connector._sqs_client is None
        assert connector._running is False


# =============================================================================
# Consume Tests
# =============================================================================


class TestSNSSQSConnectorConsume:
    """Tests for consuming SQS messages."""

    @pytest.mark.asyncio
    async def test_consume_cancelled_error_preserves_context(self):
        """Should preserve the original cancellation context."""
        from aragora.connectors.enterprise.streaming.snssqs import (
            SNSSQSConnector,
            SNSSQSConfig,
        )

        config = SNSSQSConfig(
            queue_url="https://sqs.us-east-1.amazonaws.com/123456789/queue",
            enable_circuit_breaker=False,
            enable_dlq=False,
            enable_graceful_shutdown=False,
        )
        connector = SNSSQSConnector(config)
        cancelled = asyncio.CancelledError("poll cancelled")
        connector._sqs_client = AsyncMock()
        connector._sqs_client.receive_message = AsyncMock(side_effect=cancelled)

        with pytest.raises(
            asyncio.CancelledError,
            match="SNS/SQS consumer cancelled during consume",
        ) as exc_info:
            await connector.consume().__anext__()

        assert exc_info.value.__cause__ is cancelled


# =============================================================================
# Health Check Tests
# =============================================================================


class TestSNSSQSConnectorHealth:
    """Tests for health status."""

    @pytest.mark.asyncio
    async def test_health_when_not_connected(self):
        """Should report unhealthy when not connected."""
        from aragora.connectors.enterprise.streaming.snssqs import (
            SNSSQSConnector,
            SNSSQSConfig,
        )

        config = SNSSQSConfig(
            queue_url="https://sqs.us-east-1.amazonaws.com/123456789/queue",
            enable_circuit_breaker=False,  # Disable for simpler testing
        )
        connector = SNSSQSConnector(config)

        # Disable health monitor for direct testing
        connector._health_monitor = None

        health = await connector.get_health()

        assert health.healthy is False
        assert health.last_check is not None

    @pytest.mark.asyncio
    async def test_health_when_connected(self):
        """Should report healthy when connected."""
        from aragora.connectors.enterprise.streaming.snssqs import (
            SNSSQSConnector,
            SNSSQSConfig,
        )

        config = SNSSQSConfig(
            queue_url="https://sqs.us-east-1.amazonaws.com/123456789/queue",
            enable_circuit_breaker=False,  # Disable for simpler testing
        )
        connector = SNSSQSConnector(config)

        # Disable health monitor for direct testing
        connector._health_monitor = None

        # Setup mock client
        mock_client = AsyncMock()
        connector._sqs_client = mock_client

        health = await connector.get_health()

        assert health.healthy is True
        assert health.last_check is not None


# =============================================================================
# Unsupported Methods Tests
# =============================================================================


class TestSNSSQSUnsupportedMethods:
    """Tests for unsupported streaming methods."""

    @pytest.mark.asyncio
    async def test_search_not_supported(self):
        """Should raise NotImplementedError for search."""
        from aragora.connectors.enterprise.streaming.snssqs import (
            SNSSQSConnector,
            SNSSQSConfig,
        )

        config = SNSSQSConfig(queue_url="https://sqs.us-east-1.amazonaws.com/123456789/queue")
        connector = SNSSQSConnector(config)

        with pytest.raises(NotImplementedError, match="Search not supported"):
            await connector.search("query")

    @pytest.mark.asyncio
    async def test_fetch_not_supported(self):
        """Should raise NotImplementedError for fetch."""
        from aragora.connectors.enterprise.streaming.snssqs import (
            SNSSQSConnector,
            SNSSQSConfig,
        )

        config = SNSSQSConfig(queue_url="https://sqs.us-east-1.amazonaws.com/123456789/queue")
        connector = SNSSQSConnector(config)

        with pytest.raises(NotImplementedError, match="Fetch not supported"):
            await connector.fetch("item-id")
