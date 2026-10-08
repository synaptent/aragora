"""Tests for ClaudeComputerUseBridge."""

from unittest.mock import MagicMock, patch

import pytest

from aragora.computer_use.actions import (
    Action,
    ActionType,
    ClickAction,
    KeyAction,
    ScreenshotAction,
    TypeAction,
)
from aragora.computer_use.claude_bridge import (
    BridgeConfig,
    ClaudeComputerUseBridge,
    ConversationMessage,
)


class TestBridgeConfig:
    """Test BridgeConfig dataclass."""

    def test_default_values(self):
        """Test default configuration values."""
        config = BridgeConfig()
        assert config.model == "claude-opus-5"
        assert config.max_tokens == 4096
        assert config.temperature == 0.0
        assert config.display_width == 1920
        assert config.display_height == 1080
        assert config.max_retries == 3

    def test_custom_values(self):
        """Test custom configuration."""
        config = BridgeConfig(
            model="claude-opus-4-20250514",
            max_tokens=8192,
            display_width=2560,
            display_height=1440,
        )
        assert config.model == "claude-opus-4-20250514"
        assert config.max_tokens == 8192
        assert config.display_width == 2560
        assert config.display_height == 1440


class TestConversationMessage:
    """Test ConversationMessage dataclass."""

    def test_creation(self):
        """Test creating a conversation message."""
        msg = ConversationMessage(
            role="user",
            content=[{"type": "text", "text": "Hello"}],
        )
        assert msg.role == "user"
        assert len(msg.content) == 1
        assert msg.content[0]["type"] == "text"


class TestClaudeComputerUseBridge:
    """Test ClaudeComputerUseBridge class."""

    def test_init_default_config(self):
        """Test initialization with default config."""
        bridge = ClaudeComputerUseBridge(api_key="test-key")
        assert bridge._api_key == "test-key"
        assert bridge.config.model == "claude-opus-5"

    def test_init_custom_config(self):
        """Test initialization with custom config."""
        config = BridgeConfig(model="claude-opus-4-20250514")
        bridge = ClaudeComputerUseBridge(api_key="test-key", config=config)
        assert bridge.config.model == "claude-opus-4-20250514"

    def test_init_from_env(self):
        """Test API key from environment variable."""
        with patch.dict("os.environ", {"ANTHROPIC_API_KEY": "env-key"}):
            bridge = ClaudeComputerUseBridge()
            assert bridge._api_key == "env-key"

    def test_reset_clears_conversation(self):
        """Test that reset clears conversation history."""
        bridge = ClaudeComputerUseBridge(api_key="test-key")
        bridge._conversation.append(
            ConversationMessage(role="user", content=[{"type": "text", "text": "Hi"}])
        )
        assert len(bridge._conversation) == 1

        bridge.reset()
        assert len(bridge._conversation) == 0

    def test_get_conversation_length(self):
        """Test getting conversation length."""
        bridge = ClaudeComputerUseBridge(api_key="test-key")
        assert bridge.get_conversation_length() == 0

        bridge._conversation.append(
            ConversationMessage(role="user", content=[{"type": "text", "text": "Hi"}])
        )
        assert bridge.get_conversation_length() == 1

    def test_build_system_prompt(self):
        """Test building system prompt."""
        bridge = ClaudeComputerUseBridge(api_key="test-key")
        prompt = bridge._build_system_prompt("Open settings", "Context info")

        assert "Open settings" in prompt
        assert "Context info" in prompt
        assert "computer tool" in prompt.lower() or "screenshot" in prompt.lower()

    def test_build_system_prompt_with_prefix_suffix(self):
        """Test system prompt with custom prefix and suffix."""
        config = BridgeConfig(
            system_prompt_prefix="PREFIX:",
            system_prompt_suffix="SUFFIX.",
        )
        bridge = ClaudeComputerUseBridge(api_key="test-key", config=config)
        prompt = bridge._build_system_prompt("Goal", "")

        assert "PREFIX:" in prompt
        assert "SUFFIX." in prompt

    def test_build_tools(self):
        """Test building tool definitions."""
        config = BridgeConfig(
            display_width=1920,
            display_height=1080,
            display_number=1,
        )
        bridge = ClaudeComputerUseBridge(api_key="test-key", config=config)
        tools = bridge._build_tools()

        assert len(tools) == 1
        assert tools[0]["type"] == "computer_20241022"
        assert tools[0]["name"] == "computer"
        assert tools[0]["display_width_px"] == 1920
        assert tools[0]["display_height_px"] == 1080

    def test_build_messages_initial(self):
        """Test building messages for initial request."""
        bridge = ClaudeComputerUseBridge(api_key="test-key")
        messages = bridge._build_messages(
            goal="Click the button",
            screenshot_b64="base64data",
            previous_steps=[],
            initial_context="This is a test",
        )

        assert len(messages) == 1
        assert messages[0]["role"] == "user"
        # Should have image and text content
        content = messages[0]["content"]
        assert any(c.get("type") == "image" for c in content)
        assert any(c.get("type") == "text" for c in content)

    def test_get_client_missing_key(self):
        """Test that missing API key raises error."""
        bridge = ClaudeComputerUseBridge(api_key="")
        bridge._api_key = ""  # Clear it

        with pytest.raises(ValueError, match="API key"):
            bridge._get_client()


class TestActionParsing:
    """Test action parsing from tool use responses."""

    def test_parse_screenshot_action(self):
        """Test parsing screenshot action."""
        tool_input = {"action": "screenshot"}
        action = Action.from_tool_use(tool_input)
        assert isinstance(action, ScreenshotAction)
        assert action.action_type == ActionType.SCREENSHOT

    def test_parse_click_action(self):
        """Test parsing click action."""
        tool_input = {"action": "click", "coordinate": [100, 200]}
        action = Action.from_tool_use(tool_input)
        assert isinstance(action, ClickAction)
        assert action.x == 100
        assert action.y == 200

    def test_parse_double_click_action(self):
        """Test parsing double-click action."""
        tool_input = {"action": "double_click", "coordinate": [150, 250]}
        action = Action.from_tool_use(tool_input)
        assert isinstance(action, ClickAction)
        assert action.x == 150
        assert action.y == 250
        assert action.double_click is True

    def test_parse_type_action(self):
        """Test parsing type action."""
        tool_input = {"action": "type", "text": "Hello World"}
        action = Action.from_tool_use(tool_input)
        assert isinstance(action, TypeAction)
        assert action.text == "Hello World"

    def test_parse_key_action(self):
        """Test parsing key action."""
        tool_input = {"action": "key", "text": "Enter"}
        action = Action.from_tool_use(tool_input)
        assert isinstance(action, KeyAction)
        assert action.key == "Enter"

    def test_parse_unknown_action_defaults_to_screenshot(self):
        """Test that unknown action defaults to screenshot."""
        tool_input = {"action": "unknown_action"}
        action = Action.from_tool_use(tool_input)
        assert isinstance(action, ScreenshotAction)


class TestToolUseParsing:
    """Test tool use response parsing."""

    def test_parse_tool_use_with_action(self):
        """Test parsing response with tool use."""
        bridge = ClaudeComputerUseBridge(api_key="test-key")

        # Mock response with tool_use
        mock_response = MagicMock()
        mock_response.stop_reason = "tool_use"
        mock_response.content = [
            MagicMock(type="text", text="I will click the button"),
            MagicMock(type="tool_use", input={"action": "click", "coordinate": [100, 200]}),
        ]
        mock_response.content[1].name = "computer"

        action, text, is_complete = bridge._parse_tool_use(mock_response)

        assert action is not None
        assert isinstance(action, ClickAction)
        assert text == "I will click the button"
        assert is_complete is False

    def test_parse_tool_use_completion(self):
        """Test parsing response indicating completion."""
        bridge = ClaudeComputerUseBridge(api_key="test-key")

        mock_response = MagicMock()
        mock_response.stop_reason = "end_turn"
        mock_response.content = [
            MagicMock(type="text", text="The task is complete"),
        ]

        action, text, is_complete = bridge._parse_tool_use(mock_response)

        assert action is None
        assert "task is complete" in text.lower()
        assert is_complete is True

    def test_parse_tool_use_with_completion_phrase(self):
        """Test parsing response with completion phrase in text."""
        bridge = ClaudeComputerUseBridge(api_key="test-key")

        mock_response = MagicMock()
        mock_response.stop_reason = "end_turn"
        mock_response.content = [
            MagicMock(type="text", text="The goal has been achieved successfully."),
        ]

        action, text, is_complete = bridge._parse_tool_use(mock_response)

        assert action is None
        assert is_complete is True
