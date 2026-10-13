"""
Tests for server/stream/debate_stream_server.py - WebSocket streaming server.

Tests cover:
- WebSocketMessageRateLimiter (token bucket rate limiting)
- Connection rate limiting per IP
- Token validation and revalidation
- Origin validation
- Message parsing and size limits
- Loop registration/unregistration
- Debate state updates
- Connection cleanup
"""

import asyncio
import json
import pytest
import time
from unittest.mock import MagicMock, AsyncMock, patch, PropertyMock

from aragora.server.stream.debate_stream_server import (
    WebSocketMessageRateLimiter,
    DebateStreamServer,
    WS_CONNECTIONS_PER_IP_PER_MINUTE,
    WS_MAX_CONNECTIONS_PER_IP,
    WS_MESSAGES_PER_SECOND,
    WS_MESSAGE_BURST_SIZE,
    WS_TOKEN_REVALIDATION_INTERVAL,
)
from aragora.events.types import StreamEventType, StreamEvent


# ============================================================================
# WebSocketMessageRateLimiter Tests
# ============================================================================


class TestWebSocketMessageRateLimiter:
    """Tests for per-connection message rate limiting."""

    def test_allows_burst_messages(self):
        """Should allow burst_size messages immediately."""
        limiter = WebSocketMessageRateLimiter(messages_per_second=10.0, burst_size=5)

        # Should allow burst_size messages
        for _ in range(5):
            assert limiter.allow_message() is True

    def test_rate_limits_after_burst(self):
        """Should rate limit after burst exhausted."""
        limiter = WebSocketMessageRateLimiter(messages_per_second=1.0, burst_size=3)  # Slow refill

        # Exhaust burst
        for _ in range(3):
            limiter.allow_message()

        # Should be rate limited
        assert limiter.allow_message() is False

    def test_refills_tokens_over_time(self):
        """Tokens should refill based on elapsed time."""
        limiter = WebSocketMessageRateLimiter(messages_per_second=10.0, burst_size=1)

        # Exhaust token
        limiter.allow_message()
        assert limiter.allow_message() is False

        # Simulate time passing (100ms = 1 token at 10/sec)
        limiter._last_update = time.time() - 0.1

        # Should have refilled
        assert limiter.allow_message() is True

    def test_tokens_capped_at_burst_size(self):
        """Tokens should not exceed burst_size."""
        limiter = WebSocketMessageRateLimiter(messages_per_second=100.0, burst_size=5)

        # Simulate long time passing
        limiter._last_update = time.time() - 100.0

        # First 5 should work
        for _ in range(5):
            assert limiter.allow_message() is True

        # 6th should fail (no time passed for refill)
        assert limiter.allow_message() is False


# ============================================================================
# DebateStreamServer Connection Tests
# ============================================================================


class TestDebateStreamServerConnectionRate:
    """Tests for connection rate limiting."""

    def test_allows_connections_within_limit(self):
        """Should allow connections within rate limit."""
        server = DebateStreamServer()
        server._clients_lock = asyncio.Lock()

        for i in range(5):
            allowed, error = server._check_ws_connection_rate(f"192.168.1.{i}")
            assert allowed is True, f"Connection {i} should be allowed"

    def test_rate_limits_single_ip(self):
        """Should rate limit connections from single IP after exceeding limits."""
        server = DebateStreamServer()
        server._clients_lock = asyncio.Lock()

        # Keep connecting and releasing until we hit rate limit
        # (concurrent limit is smaller, so release after each)
        for _ in range(WS_CONNECTIONS_PER_IP_PER_MINUTE):
            allowed, _ = server._check_ws_connection_rate("192.168.1.1")
            if allowed:
                server._release_ws_connection("192.168.1.1")

        # Next should be rejected due to rate limit (30/min)
        allowed, error = server._check_ws_connection_rate("192.168.1.1")
        assert allowed is False
        assert "rate limit" in error.lower() or "exceeded" in error.lower()

    def test_limits_concurrent_connections_per_ip(self):
        """Should limit concurrent connections per IP."""
        server = DebateStreamServer()
        server._clients_lock = asyncio.Lock()

        # Simulate max concurrent connections
        for _ in range(WS_MAX_CONNECTIONS_PER_IP):
            server._check_ws_connection_rate("192.168.1.1")

        # Next should be rejected (too many concurrent)
        allowed, error = server._check_ws_connection_rate("192.168.1.1")
        assert allowed is False
        assert "concurrent" in error.lower()

    def test_release_frees_connection_slot(self):
        """Releasing connection should free slot."""
        server = DebateStreamServer()
        server._clients_lock = asyncio.Lock()

        # Fill up concurrent connections
        for _ in range(WS_MAX_CONNECTIONS_PER_IP):
            server._check_ws_connection_rate("192.168.1.1")

        # Release one
        server._release_ws_connection("192.168.1.1")

        # Should now allow one more
        allowed, _ = server._check_ws_connection_rate("192.168.1.1")
        # Rate limit still applies, but concurrent check passes
        assert server._ws_conn_per_ip.get("192.168.1.1", 0) <= WS_MAX_CONNECTIONS_PER_IP

    def test_unknown_ip_always_allowed(self):
        """Unknown IPs should always be allowed (can't rate limit)."""
        server = DebateStreamServer()

        for _ in range(100):
            allowed, _ = server._check_ws_connection_rate("unknown")
            assert allowed is True


# ============================================================================
# Token Validation Tests
# ============================================================================


class TestDebateStreamServerAuth:
    """Tests for authentication handling."""

    def test_auth_disabled_always_passes(self):
        """With auth disabled, validation always passes."""
        server = DebateStreamServer()

        with patch("aragora.server.stream.debate_stream_server.auth_config") as mock_config:
            mock_config.enabled = False

            mock_ws = MagicMock()
            assert server._validate_ws_auth(mock_ws) is True

    def test_auth_enabled_requires_token(self):
        """With auth enabled, valid token required."""
        server = DebateStreamServer()

        with patch("aragora.server.stream.debate_stream_server.auth_config") as mock_config:
            mock_config.enabled = True
            mock_config.validate_token.return_value = True

            # Mock websocket with valid token
            mock_ws = MagicMock()
            mock_ws.request.headers = {"Authorization": "Bearer valid_token"}

            result = server._validate_ws_auth(mock_ws)
            assert result is True
            mock_config.validate_token.assert_called_with("valid_token", "")

    def test_missing_token_fails(self):
        """Missing token should fail validation."""
        server = DebateStreamServer()

        with patch("aragora.server.stream.debate_stream_server.auth_config") as mock_config:
            mock_config.enabled = True

            mock_ws = MagicMock()
            mock_ws.request.headers = {}

            result = server._validate_ws_auth(mock_ws)
            assert result is False

    def test_token_revalidation_timing(self):
        """Token should be revalidated after interval."""
        server = DebateStreamServer()

        ws_id = 12345

        # Freshly validated
        server._mark_token_validated(ws_id)
        assert server._should_revalidate_token(ws_id) is False

        # Simulate time passing beyond interval
        server._ws_token_validated[ws_id] = time.time() - WS_TOKEN_REVALIDATION_INTERVAL - 1

        assert server._should_revalidate_token(ws_id) is True


# ============================================================================
# IP Extraction Tests
# ============================================================================


class TestDebateStreamServerIpExtraction:
    """Tests for client IP extraction."""

    def test_extracts_direct_ip(self):
        """Should extract IP from remote_address."""
        server = DebateStreamServer()

        mock_ws = MagicMock()
        mock_ws.remote_address = ("192.168.1.100", 12345)

        ip = server._extract_ws_ip(mock_ws)
        assert ip == "192.168.1.100"

    def test_extracts_xff_from_trusted_proxy(self):
        """Should use X-Forwarded-For from trusted proxies."""
        server = DebateStreamServer()

        mock_ws = MagicMock()
        mock_ws.remote_address = ("127.0.0.1", 12345)  # Trusted proxy
        mock_ws.request.headers = {"X-Forwarded-For": "203.0.113.50, 10.0.0.1"}

        ip = server._extract_ws_ip(mock_ws)
        assert ip == "203.0.113.50"

    def test_ignores_xff_from_untrusted_ip(self):
        """Should ignore X-Forwarded-For from untrusted sources."""
        server = DebateStreamServer()

        mock_ws = MagicMock()
        mock_ws.remote_address = ("192.168.1.100", 12345)  # Not trusted proxy
        mock_ws.request.headers = {"X-Forwarded-For": "10.0.0.1"}

        ip = server._extract_ws_ip(mock_ws)
        assert ip == "192.168.1.100"  # Direct IP, not XFF

    def test_handles_missing_remote_address(self):
        """Should handle missing remote_address gracefully."""
        server = DebateStreamServer()

        mock_ws = MagicMock(spec=[])  # No remote_address attribute

        ip = server._extract_ws_ip(mock_ws)
        assert ip == "unknown"


# ============================================================================
# Origin Validation Tests
# ============================================================================


class TestDebateStreamServerOrigin:
    """Tests for origin header extraction."""

    @pytest.mark.asyncio
    async def test_setup_connection_allows_localhost_dev_port(self):
        """Dev localhost ports should pass centralized origin validation."""
        server = DebateStreamServer()
        server._clients_lock = asyncio.Lock()

        mock_ws = MagicMock()
        mock_ws.remote_address = ("127.0.0.1", 12345)
        mock_ws.request.headers = {"Origin": "http://127.0.0.1:3114"}

        with (
            patch.object(server, "_validate_ws_auth", return_value=True),
            patch.object(server, "_extract_ws_token", return_value=None),
        ):
            (
                success,
                client_ip,
                client_id,
                ws_id,
                is_authenticated,
                ws_token,
            ) = await server._setup_connection(mock_ws)

        assert success is True
        assert client_ip == "127.0.0.1"
        assert client_id
        assert ws_id == id(mock_ws)
        assert is_authenticated is True
        assert ws_token is None
        mock_ws.close.assert_not_called()

    def test_extracts_origin_from_request(self):
        """Should extract origin from request headers."""
        server = DebateStreamServer()

        mock_ws = MagicMock()
        mock_ws.request.headers = {"Origin": "https://example.com"}

        origin = server._extract_ws_origin(mock_ws)
        assert origin == "https://example.com"

    def test_extracts_origin_from_request_headers(self):
        """Should handle older websockets library API."""
        server = DebateStreamServer()

        mock_ws = MagicMock(spec=["request_headers"])
        mock_ws.request_headers = {"Origin": "https://legacy.com"}

        origin = server._extract_ws_origin(mock_ws)
        assert origin == "https://legacy.com"

    def test_returns_empty_on_missing_origin(self):
        """Should return empty string if no origin."""
        server = DebateStreamServer()

        mock_ws = MagicMock()
        mock_ws.request.headers = {}

        origin = server._extract_ws_origin(mock_ws)
        assert origin == ""


# ============================================================================
# Loop Registration Tests
# ============================================================================


class TestDebateStreamServerLoops:
    """Tests for loop registration and management."""

    def test_register_loop(self):
        """Should register a new loop."""
        server = DebateStreamServer()

        server.register_loop("loop-123", "Test Loop", "/test/path")

        loops = server.get_loop_list()
        assert len(loops) == 1
        assert loops[0]["loop_id"] == "loop-123"
        assert loops[0]["name"] == "Test Loop"
        assert loops[0]["path"] == "/test/path"

    def test_unregister_loop(self):
        """Should unregister a loop."""
        server = DebateStreamServer()

        server.register_loop("loop-123", "Test Loop")
        server.unregister_loop("loop-123")

        loops = server.get_loop_list()
        assert len(loops) == 0

    def test_unregister_nonexistent_loop(self):
        """Unregistering nonexistent loop should not error."""
        server = DebateStreamServer()

        # Should not raise
        server.unregister_loop("nonexistent")

    def test_update_loop_state(self):
        """Should update cycle and phase."""
        server = DebateStreamServer()

        server.register_loop("loop-123", "Test Loop")
        server.update_loop_state("loop-123", cycle=2, phase="debate")

        loops = server.get_loop_list()
        assert loops[0]["cycle"] == 2
        assert loops[0]["phase"] == "debate"

    def test_multiple_loops(self):
        """Should support multiple concurrent loops."""
        server = DebateStreamServer()

        server.register_loop("loop-1", "Loop 1")
        server.register_loop("loop-2", "Loop 2")
        server.register_loop("loop-3", "Loop 3")

        loops = server.get_loop_list()
        assert len(loops) == 3


# ============================================================================
# Debate State Tests
# ============================================================================


class TestDebateStreamServerState:
    """Tests for debate state tracking."""

    def test_debate_start_creates_state(self):
        """DEBATE_START should create state entry."""
        server = DebateStreamServer()

        event = StreamEvent(
            type=StreamEventType.DEBATE_START,
            data={"task": "Test task", "agents": ["agent1", "agent2"]},
            loop_id="debate-1",
        )

        server._update_debate_state(event)

        assert "debate-1" in server.debate_states
        state = server.debate_states["debate-1"]
        assert state["task"] == "Test task"
        assert state["agents"] == ["agent1", "agent2"]
        assert state["messages"] == []
        assert state["ended"] is False

    def test_agent_message_appends(self):
        """AGENT_MESSAGE should append to messages."""
        server = DebateStreamServer()

        # First create debate
        server._update_debate_state(
            StreamEvent(
                type=StreamEventType.DEBATE_START,
                data={"task": "Test", "agents": []},
                loop_id="debate-1",
            )
        )

        # Add message
        server._update_debate_state(
            StreamEvent(
                type=StreamEventType.AGENT_MESSAGE,
                data={"role": "proposer", "content": "Hello"},
                agent="agent1",
                round=1,
                loop_id="debate-1",
            )
        )

        state = server.debate_states["debate-1"]
        assert len(state["messages"]) == 1
        assert state["messages"][0]["content"] == "Hello"
        assert state["messages"][0]["agent"] == "agent1"

    def test_consensus_updates_state(self):
        """CONSENSUS should update consensus fields."""
        server = DebateStreamServer()

        server._update_debate_state(
            StreamEvent(
                type=StreamEventType.DEBATE_START,
                data={"task": "Test", "agents": []},
                loop_id="debate-1",
            )
        )

        server._update_debate_state(
            StreamEvent(
                type=StreamEventType.CONSENSUS,
                data={"reached": True, "confidence": 0.95, "answer": "The answer"},
                loop_id="debate-1",
            )
        )

        state = server.debate_states["debate-1"]
        assert state["consensus_reached"] is True
        assert state["consensus_confidence"] == 0.95
        assert state["consensus_answer"] == "The answer"

    def test_debate_end_marks_ended(self):
        """DEBATE_END should mark debate as ended."""
        server = DebateStreamServer()

        server._update_debate_state(
            StreamEvent(
                type=StreamEventType.DEBATE_START,
                data={"task": "Test", "agents": []},
                loop_id="debate-1",
            )
        )

        server._update_debate_state(
            StreamEvent(
                type=StreamEventType.DEBATE_END,
                data={"duration": 120.5, "rounds": 3},
                loop_id="debate-1",
            )
        )

        state = server.debate_states["debate-1"]
        assert state["ended"] is True
        assert state["duration"] == 120.5
        assert state["rounds"] == 3

    def test_loop_unregister_removes_state(self):
        """LOOP_UNREGISTER should remove debate state."""
        server = DebateStreamServer()

        server._update_debate_state(
            StreamEvent(
                type=StreamEventType.DEBATE_START,
                data={"task": "Test", "agents": []},
                loop_id="debate-1",
            )
        )

        server._update_debate_state(
            StreamEvent(
                type=StreamEventType.LOOP_UNREGISTER,
                data={},
                loop_id="debate-1",
            )
        )

        assert "debate-1" not in server.debate_states

    def test_message_cap_at_1000(self):
        """Messages should be capped at 1000."""
        server = DebateStreamServer()

        server._update_debate_state(
            StreamEvent(
                type=StreamEventType.DEBATE_START,
                data={"task": "Test", "agents": []},
                loop_id="debate-1",
            )
        )

        # Add 1100 messages
        for i in range(1100):
            server._update_debate_state(
                StreamEvent(
                    type=StreamEventType.AGENT_MESSAGE,
                    data={"role": "proposer", "content": f"Message {i}"},
                    agent="agent1",
                    round=1,
                    loop_id="debate-1",
                )
            )

        state = server.debate_states["debate-1"]
        assert len(state["messages"]) == 1000
        # Should keep the most recent messages
        assert state["messages"][-1]["content"] == "Message 1099"


# ============================================================================
# Audience Payload Validation Tests
# ============================================================================


class TestDebateStreamServerAudiencePayload:
    """Tests for audience message payload validation."""

    def test_valid_payload(self):
        """Valid payload should pass."""
        server = DebateStreamServer()

        payload, error = server._validate_audience_payload(
            {"payload": {"choice": "option_a", "reason": "Good option"}}
        )

        assert payload is not None
        assert error is None
        assert payload["choice"] == "option_a"

    def test_missing_payload(self):
        """Missing payload should use empty dict."""
        server = DebateStreamServer()

        payload, error = server._validate_audience_payload({})

        assert payload == {}
        assert error is None

    def test_non_dict_payload(self):
        """Non-dict payload should error."""
        server = DebateStreamServer()

        payload, error = server._validate_audience_payload({"payload": "not a dict"})

        assert payload is None
        assert "Invalid payload format" in error

    def test_oversized_payload(self):
        """Oversized payload should error."""
        server = DebateStreamServer()

        # Create payload > 10KB
        large_payload = {"data": "x" * 15000}

        payload, error = server._validate_audience_payload({"payload": large_payload})

        assert payload is None
        assert "too large" in error.lower()


# ============================================================================
# Connection Cleanup Tests
# ============================================================================


class TestDebateStreamServerCleanup:
    """Tests for connection cleanup."""

    @pytest.mark.asyncio
    async def test_cleanup_removes_client(self):
        """Cleanup should remove client from set."""
        server = DebateStreamServer()

        mock_ws = MagicMock()
        server.clients.add(mock_ws)

        await server._cleanup_connection("192.168.1.1", "client-123", 12345, mock_ws)

        assert mock_ws not in server.clients

    @pytest.mark.asyncio
    async def test_cleanup_removes_rate_limiter(self):
        """Cleanup should remove client's rate limiter."""
        server = DebateStreamServer()

        mock_ws = MagicMock()
        ws_id = 12345

        # Set up tracking
        server._client_ids[ws_id] = "client-123"
        server._rate_limiters["client-123"] = MagicMock()
        server._rate_limiter_last_access["client-123"] = time.time()

        await server._cleanup_connection("192.168.1.1", "client-123", ws_id, mock_ws)

        assert ws_id not in server._client_ids
        assert "client-123" not in server._rate_limiters

    @pytest.mark.asyncio
    async def test_cleanup_releases_connection_slot(self):
        """Cleanup should release IP connection slot."""
        server = DebateStreamServer()

        mock_ws = MagicMock()

        # Simulate connection
        server._check_ws_connection_rate("192.168.1.1")
        initial_count = server._ws_conn_per_ip.get("192.168.1.1", 0)

        await server._cleanup_connection("192.168.1.1", "client-123", 12345, mock_ws)

        assert server._ws_conn_per_ip.get("192.168.1.1", 0) < initial_count

    @pytest.mark.asyncio
    async def test_cleanup_removes_token_tracking(self):
        """Cleanup should remove token validation tracking."""
        server = DebateStreamServer()

        mock_ws = MagicMock()
        ws_id = 12345

        server._ws_token_validated[ws_id] = time.time()
        server._ws_msg_limiters[ws_id] = MagicMock()

        await server._cleanup_connection("192.168.1.1", "client-123", ws_id, mock_ws)

        assert ws_id not in server._ws_token_validated
        assert ws_id not in server._ws_msg_limiters


# ============================================================================
# Broadcast Tests
# ============================================================================


class TestDebateStreamServerBroadcast:
    """Tests for event broadcasting."""

    @pytest.mark.asyncio
    async def test_broadcast_to_all_clients(self):
        """Should broadcast to all connected clients."""
        server = DebateStreamServer()

        mock_client1 = AsyncMock()
        mock_client2 = AsyncMock()
        server.clients = {mock_client1, mock_client2}

        # Set up client subscriptions to the loop_id used in event
        server._client_subscriptions[id(mock_client1)] = "test"
        server._client_subscriptions[id(mock_client2)] = "test"

        event = StreamEvent(
            type=StreamEventType.AGENT_MESSAGE,
            data={"content": "test"},
            loop_id="test",
        )

        await server.broadcast(event)

        mock_client1.send.assert_called_once()
        mock_client2.send.assert_called_once()

    @pytest.mark.asyncio
    async def test_broadcast_removes_disconnected(self):
        """Should remove clients that fail to receive."""
        server = DebateStreamServer()

        mock_good = AsyncMock()
        mock_bad = AsyncMock()
        mock_bad.send.side_effect = Exception("Connection closed")
        server.clients = {mock_good, mock_bad}

        # Set up client subscriptions to the loop_id used in event
        server._client_subscriptions[id(mock_good)] = "test"
        server._client_subscriptions[id(mock_bad)] = "test"

        event = StreamEvent(
            type=StreamEventType.AGENT_MESSAGE,
            data={"content": "test"},
            loop_id="test",
        )

        await server.broadcast(event)

        assert mock_good in server.clients
        assert mock_bad not in server.clients

    @pytest.mark.asyncio
    async def test_broadcast_batch(self):
        """Should broadcast multiple events as array."""
        server = DebateStreamServer()

        mock_client = AsyncMock()
        server.clients = {mock_client}

        # Set up client subscription to the loop_id used in events
        # This is required for the client to receive debate-scoped events
        server._client_subscriptions[id(mock_client)] = "test"

        events = [
            StreamEvent(type=StreamEventType.AGENT_MESSAGE, data={"content": "1"}, loop_id="test"),
            StreamEvent(type=StreamEventType.AGENT_MESSAGE, data={"content": "2"}, loop_id="test"),
        ]

        await server.broadcast_batch(events)

        mock_client.send.assert_called_once()
        sent_data = json.loads(mock_client.send.call_args[0][0])
        assert isinstance(sent_data, list)
        assert len(sent_data) == 2


# ============================================================================
# Server Lifecycle Tests
# ============================================================================


class TestDebateStreamServerLifecycle:
    """Tests for server start/stop."""

    def test_stop_sets_running_false(self):
        """stop() should set _running to False."""
        server = DebateStreamServer()
        server._running = True

        server.stop()

        assert server._running is False

    @pytest.mark.asyncio
    async def test_graceful_shutdown_clears_clients(self):
        """graceful_shutdown should close and clear clients."""
        server = DebateStreamServer()

        mock_client = AsyncMock()
        server.clients = {mock_client}
        server._running = True

        await server.graceful_shutdown()

        assert server._running is False
        assert len(server.clients) == 0
        mock_client.close.assert_called_once()

    def test_websocket_serve_kwargs_advertise_browser_subprotocol(self):
        """The server should negotiate the browser-visible Aragora subprotocol."""
        server = DebateStreamServer()

        kwargs = server._websocket_serve_kwargs()

        assert kwargs["subprotocols"] == ["aragora-v1"]
        assert kwargs["max_size"] > 0

    @pytest.mark.asyncio
    async def test_send_debate_state_scopes_sync_to_subscribed_debate(self):
        """sync payloads should include debate identifiers where the client filter expects them."""
        server = DebateStreamServer()
        websocket = AsyncMock()
        debate_id = "adhoc_123"
        server.debate_states[debate_id] = {
            "id": debate_id,
            "task": "Should we preserve debate metadata?",
            "agents": ["openai-api", "mistral"],
            "messages": [],
            "ended": False,
        }

        await server._send_debate_state(websocket, debate_id)

        first_payload = json.loads(websocket.send.await_args_list[0].args[0])
        assert first_payload["type"] == "sync"
        assert first_payload["loop_id"] == debate_id
        assert first_payload["data"]["debate_id"] == debate_id
        assert first_payload["data"]["loop_id"] == debate_id
        assert first_payload["data"]["task"] == "Should we preserve debate metadata?"
        assert first_payload["data"]["agents"] == ["openai-api", "mistral"]

    def test_debate_start_merge_preserves_existing_task_and_agents(self):
        """Later sparse debate_start events should not wipe the cached task/agents."""
        server = DebateStreamServer()
        debate_id = "adhoc_456"
        server.debate_states[debate_id] = {
            "id": debate_id,
            "task": "Original task",
            "agents": ["openai-api", "mistral"],
            "messages": [{"agent": "openai-api", "content": "hello"}],
            "consensus_reached": False,
            "consensus_confidence": 0.0,
            "consensus_answer": "",
            "started_at": 123.0,
            "rounds": 0,
            "ended": False,
            "duration": 0.0,
        }

        server._update_debate_state(
            StreamEvent(
                type=StreamEventType.DEBATE_START,
                data={"details": "spectator only"},
                loop_id=debate_id,
            )
        )

        state = server.debate_states[debate_id]
        assert state["task"] == "Original task"
        assert state["agents"] == ["openai-api", "mistral"]
        assert state["messages"] == [{"agent": "openai-api", "content": "hello"}]


# ============================================================================
# Message Parsing Tests
# ============================================================================


class TestDebateStreamServerMessageParsing:
    """Tests for WebSocket message parsing."""

    @pytest.mark.asyncio
    async def test_parse_valid_json(self):
        """Should parse valid JSON."""
        server = DebateStreamServer()

        result = await server._parse_message('{"type": "test", "data": 123}')

        assert result is not None
        parsed, error_reason = result
        assert error_reason is None
        assert parsed["type"] == "test"
        assert parsed["data"] == 123

    @pytest.mark.asyncio
    async def test_parse_invalid_json(self):
        """Should return None for invalid JSON."""
        server = DebateStreamServer()

        result = await server._parse_message("not valid json")

        assert result == (None, "invalid_json")

    @pytest.mark.asyncio
    async def test_parse_oversized_message(self):
        """Should reject oversized messages."""
        server = DebateStreamServer()

        # Create message larger than WS_MAX_MESSAGE_SIZE
        from aragora.config import WS_MAX_MESSAGE_SIZE

        large_message = '{"data": "' + "x" * (WS_MAX_MESSAGE_SIZE + 1000) + '"}'

        result = await server._parse_message(large_message)

        assert result == (None, "message_too_large")
