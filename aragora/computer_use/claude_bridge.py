"""
Claude API Bridge for Computer Use.

Pattern: Claude Computer Use API Integration
Inspired by: Anthropic's computer_20241022 tool specification
Aragora adaptation: Integrated with Aragora agent fabric and policy enforcement.

Bridges the ComputerUseOrchestrator with Claude's API, handling:
- Message construction with screenshots
- Tool use parsing for computer actions
- Session history management
- Completion detection

Usage:
    from aragora.computer_use.claude_bridge import ClaudeComputerUseBridge

    bridge = ClaudeComputerUseBridge(api_key="...")
    action, response, is_complete = await bridge.get_next_action(
        goal="Open settings",
        screenshot_b64=screenshot,
        history=previous_steps,
    )
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from aragora.config import get_api_key
from aragora.computer_use.actions import Action
from aragora.models.compat import strip_sampling_params

if TYPE_CHECKING:
    from aragora.computer_use.orchestrator import StepResult

logger = logging.getLogger(__name__)


@dataclass
class BridgeConfig:
    """Configuration for the Claude Computer Use bridge."""

    # Model settings
    model: str = "claude-opus-5"
    max_tokens: int = 4096
    temperature: float = 0.0

    # Display settings (for computer_use tool)
    display_width: int = 1920
    display_height: int = 1080
    display_number: int = 1

    # System prompt customization
    system_prompt_prefix: str = ""
    system_prompt_suffix: str = ""

    # Retry settings
    max_retries: int = 3
    retry_delay_seconds: float = 1.0


@dataclass
class ConversationMessage:
    """A message in the conversation history."""

    role: str  # "user" or "assistant"
    content: list[dict[str, Any]]


class ClaudeComputerUseBridge:
    """
    Bridge between ComputerUseOrchestrator and Claude API.

    Handles the translation between Aragora's action model and Claude's
    computer_use tool format, managing conversation state and parsing
    tool use responses.

    Usage:
        bridge = ClaudeComputerUseBridge()
        action, text, done = await bridge.get_next_action(
            goal="Navigate to settings",
            screenshot_b64=screenshot,
            history=[],
        )
    """

    def __init__(
        self,
        api_key: str | None = None,
        config: BridgeConfig | None = None,
    ) -> None:
        """
        Initialize the bridge.

        Args:
            api_key: Anthropic API key (uses ANTHROPIC_API_KEY env var if not provided)
            config: Bridge configuration
        """
        self._api_key = api_key or get_api_key("ANTHROPIC_API_KEY", required=False) or ""
        self._config = config or BridgeConfig()
        self._client: Any = None
        self._conversation: list[ConversationMessage] = []

    @property
    def config(self) -> BridgeConfig:
        """Get the configuration."""
        return self._config

    def _get_client(self) -> Any:
        """Get or create the Anthropic client."""
        if self._client is None:
            if not self._api_key:
                raise ValueError(
                    "Anthropic API key is required. "
                    "Set ANTHROPIC_API_KEY environment variable or pass api_key parameter."
                )
            try:
                import anthropic
            except ImportError as e:
                raise ImportError(
                    "anthropic package is required for ClaudeComputerUseBridge. "
                    "Install with: pip install anthropic"
                ) from e

            self._client = anthropic.Anthropic(api_key=self._api_key)

        return self._client

    def _build_system_prompt(self, goal: str, initial_context: str = "") -> str:
        """Build the system prompt for computer use."""
        parts = []

        if self._config.system_prompt_prefix:
            parts.append(self._config.system_prompt_prefix)

        parts.append(
            f"You are a computer use agent. Your goal is: {goal}\n\n"
            "You can interact with the computer using the computer tool. "
            "Use screenshots to see the current state, then take actions like "
            "clicking, typing, scrolling, and pressing keys.\n\n"
            "Guidelines:\n"
            "- Analyze the screenshot carefully before taking action\n"
            "- Click on specific UI elements at their coordinates\n"
            "- Type text when input fields are focused\n"
            "- Use keyboard shortcuts when appropriate\n"
            "- Scroll to reveal more content if needed\n"
            "- Stop when the goal is achieved or if you encounter errors\n"
        )

        if initial_context:
            parts.append(f"\nAdditional context:\n{initial_context}\n")

        if self._config.system_prompt_suffix:
            parts.append(self._config.system_prompt_suffix)

        return "\n".join(parts)

    def _build_tools(self) -> list[dict[str, Any]]:
        """Build the tool definitions for Claude."""
        return [
            {
                "type": "computer_20241022",
                "name": "computer",
                "display_width_px": self._config.display_width,
                "display_height_px": self._config.display_height,
                "display_number": self._config.display_number,
            }
        ]

    def _build_messages(
        self,
        goal: str,
        screenshot_b64: str,
        previous_steps: list[StepResult],
        initial_context: str = "",
    ) -> list[dict[str, Any]]:
        """Build the messages array for the API call."""
        messages: list[dict[str, Any]] = []

        # Add previous conversation history
        for msg in self._conversation:
            messages.append({"role": msg.role, "content": msg.content})

        # Build current user message with screenshot
        user_content: list[dict[str, Any]] = []

        # Add screenshot as image
        if screenshot_b64:
            user_content.append(
                {
                    "type": "image",
                    "source": {
                        "type": "base64",
                        "media_type": "image/png",
                        "data": screenshot_b64,
                    },
                }
            )

        # Add text based on step history
        if not previous_steps:
            # First message
            text = f"Here is the current screen. Please help me: {goal}"
            if initial_context:
                text += f"\n\nContext: {initial_context}"
        else:
            # Subsequent message after action
            last_step = previous_steps[-1]
            if last_step.result.success:
                text = (
                    f"The {last_step.action.action_type.value} action was successful. "
                    "Here is the updated screen. Continue with the task."
                )
            else:
                text = (
                    f"The {last_step.action.action_type.value} action failed: "
                    f"{last_step.result.error}. Here is the current screen. "
                    "Please try a different approach."
                )

        user_content.append({"type": "text", "text": text})

        messages.append({"role": "user", "content": user_content})

        return messages

    def _parse_tool_use(self, response: Any) -> tuple[Action | None, str, bool]:
        """
        Parse the Claude response for tool use.

        Returns:
            (action, model_response, is_complete) tuple
        """
        text_parts = []
        tool_input = None

        # Process content blocks
        for block in response.content:
            if block.type == "text":
                text_parts.append(block.text)
            elif block.type == "tool_use":
                if block.name == "computer":
                    tool_input = block.input

        model_response = "\n".join(text_parts)

        # Check if model indicated completion
        if response.stop_reason == "end_turn" and tool_input is None:
            return None, model_response, True

        # Check for explicit completion indicators in text
        completion_phrases = [
            "task is complete",
            "goal has been achieved",
            "successfully completed",
            "finished the task",
            "done with the task",
        ]
        lower_response = model_response.lower()
        for phrase in completion_phrases:
            if phrase in lower_response:
                return None, model_response, True

        # Parse tool use into action
        if tool_input:
            action = Action.from_tool_use(tool_input)
            return action, model_response, False

        # No tool use and no completion - might be asking for clarification
        return None, model_response, True

    async def get_next_action(
        self,
        goal: str,
        screenshot_b64: str,
        previous_steps: list[StepResult],
        initial_context: str = "",
    ) -> tuple[Action | None, str, bool]:
        """
        Call Claude to determine the next action.

        Args:
            goal: The task goal
            screenshot_b64: Current screenshot as base64
            previous_steps: Previous step results
            initial_context: Additional context

        Returns:
            (action, model_response, is_complete) tuple where:
            - action: The next action to take, or None if complete
            - model_response: Claude's text response
            - is_complete: True if the task is considered complete
        """
        client = self._get_client()

        # Build request
        system = self._build_system_prompt(goal, initial_context)
        tools = self._build_tools()
        messages = self._build_messages(goal, screenshot_b64, previous_steps, initial_context)

        logger.debug(
            "Calling Claude API: %s messages, screenshot=%s",
            len(messages),
            "yes" if screenshot_b64 else "no",
        )

        # Make API call
        try:
            create_kwargs: dict[str, Any] = {
                "model": self._config.model,
                "max_tokens": self._config.max_tokens,
                "temperature": self._config.temperature,
                "system": system,
                "tools": tools,
                "messages": messages,
            }
            # Opus 4.7+ (incl. the Opus 5 default) reject temperature with a 400.
            strip_sampling_params(create_kwargs, self._config.model)
            response = client.messages.create(**create_kwargs)
        except Exception as e:  # noqa: BLE001 - must catch all API errors before re-raising
            logger.error("Claude API call failed: %s", e)
            raise

        # Parse response
        action, model_response, is_complete = self._parse_tool_use(response)

        # Update conversation history for multi-turn
        self._conversation.append(
            ConversationMessage(
                role="user",
                content=messages[-1]["content"],
            )
        )
        self._conversation.append(
            ConversationMessage(
                role="assistant",
                content=[
                    {"type": "text", "text": model_response}
                    if model_response
                    else {"type": "text", "text": "..."}
                ],
            )
        )

        return action, model_response, is_complete

    def reset(self) -> None:
        """Reset conversation history for a new task."""
        self._conversation.clear()

    def get_conversation_length(self) -> int:
        """Get the number of messages in conversation history."""
        return len(self._conversation)


__all__ = [
    "BridgeConfig",
    "ClaudeComputerUseBridge",
    "ConversationMessage",
]
