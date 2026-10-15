"""Streaming Connector Management API Handlers.

Stability: STABLE

Provides REST endpoints for managing enterprise streaming connectors
(Kafka, RabbitMQ, SNS/SQS) including configuration, connection management,
and health monitoring.

Routes:
    GET  /api/streaming/connectors              - List streaming connectors
    GET  /api/streaming/connectors/{type}/health - Health check
    GET  /api/streaming/connectors/{type}/config - Get configuration
    PUT  /api/streaming/connectors/{type}/config - Update configuration
    POST /api/streaming/connectors/{type}/connect - Connect to broker
    POST /api/streaming/connectors/{type}/disconnect - Disconnect
    POST /api/streaming/connectors/{type}/test   - Test connectivity

Phase 6: Frontend/Backend Wiring.
"""

from .handler import StreamingConnectorHandler

__all__ = ["StreamingConnectorHandler"]
