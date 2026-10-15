"""
Browser Automation Step for Workflows.

Provides browser automation capabilities in workflows using Playwright.
Supports navigation, interaction, screenshot capture, and data extraction.

Usage in workflow definition:
    steps:
      - id: "open_page"
        type: "browser"
        config:
          action: "navigate"
          url: "https://example.com"
          wait_until: "networkidle"

      - id: "fill_form"
        type: "browser"
        config:
          action: "fill"
          selector: "input[name='email']"
          value: "{inputs.email}"

      - id: "submit"
        type: "browser"
        config:
          action: "click"
          selector: "button[type='submit']"

      - id: "capture"
        type: "browser"
        config:
          action: "screenshot"
          full_page: true
"""

from __future__ import annotations

import base64
import logging
from dataclasses import dataclass, field
from typing import Any

from aragora.runtime.connector_factory import create_connector
from aragora.workflow.step import BaseStep, WorkflowContext

logger = logging.getLogger(__name__)

# Global connector instance for session persistence across steps
_browser_connector = None


async def _get_browser_connector(config: dict[str, Any]):
    """Get or create browser connector with session persistence."""
    global _browser_connector

    # Check if we need a new connector
    force_new = config.get("new_session", False)
    if force_new and _browser_connector:
        await _browser_connector.close()
        _browser_connector = None

    if _browser_connector is None:
        _browser_connector = create_connector(
            "browser",
            headless=config.get("headless", True),
            browser_type=config.get("browser_type", "chromium"),
            allowed_domains=set(config.get("allowed_domains", [])),
            blocked_domains=set(config.get("blocked_domains", [])),
            timeout_ms=config.get("timeout_ms", 30000),
            viewport_width=config.get("viewport_width", 1280),
            viewport_height=config.get("viewport_height", 720),
            user_agent=config.get("user_agent"),
            proxy=config.get("proxy"),
            ignore_https_errors=config.get("ignore_https_errors", False),
        )
        await _browser_connector.initialize()

    return _browser_connector


async def _close_browser_connector():
    """Close the global browser connector."""
    global _browser_connector
    if _browser_connector:
        await _browser_connector.close()
        _browser_connector = None


@dataclass
class BrowserStepConfig:
    """Configuration for a browser step."""

    action: str  # navigate, click, fill, screenshot, etc.
    url: str | None = None
    selector: str | None = None
    value: str | None = None
    wait_until: str = "load"
    timeout_ms: int | None = None
    full_page: bool = False
    selectors: dict[str, str] | None = None  # For extract_data
    script: str | None = None  # For execute_script
    attribute: str | None = None  # For get_attribute
    state: str = "visible"  # For wait_for
    force: bool = False  # For click
    new_session: bool = False  # Start new browser session
    close_session: bool = False  # Close browser after step

    # Browser configuration (for new sessions)
    headless: bool = True
    browser_type: str = "chromium"
    allowed_domains: list[str] = field(default_factory=list)
    blocked_domains: list[str] = field(default_factory=list)
    viewport_width: int = 1280
    viewport_height: int = 720
    user_agent: str | None = None
    proxy: dict[str, str] | None = None
    ignore_https_errors: bool = False


class BrowserStep(BaseStep):
    """
    Workflow step for browser automation.

    Executes browser actions using Playwright connector.
    Maintains session across multiple steps for stateful navigation.
    """

    step_type = "browser"

    def __init__(self, name: str, config: dict[str, Any]):
        """
        Initialize browser step.

        Args:
            name: Step name
            config: Step configuration with action and parameters
        """
        super().__init__(name, config)
        self._step_config = BrowserStepConfig(
            action=config.get("action", "navigate"),
            url=config.get("url"),
            selector=config.get("selector"),
            value=config.get("value"),
            wait_until=config.get("wait_until", "load"),
            timeout_ms=config.get("timeout_ms"),
            full_page=config.get("full_page", False),
            selectors=config.get("selectors"),
            script=config.get("script"),
            attribute=config.get("attribute"),
            state=config.get("state", "visible"),
            force=config.get("force", False),
            new_session=config.get("new_session", False),
            close_session=config.get("close_session", False),
            headless=config.get("headless", True),
            browser_type=config.get("browser_type", "chromium"),
            allowed_domains=config.get("allowed_domains", []),
            blocked_domains=config.get("blocked_domains", []),
            viewport_width=config.get("viewport_width", 1280),
            viewport_height=config.get("viewport_height", 720),
            user_agent=config.get("user_agent"),
            proxy=config.get("proxy"),
            ignore_https_errors=config.get("ignore_https_errors", False),
        )

    def _resolve_template(self, value: str | None, context: WorkflowContext) -> str | None:
        """Resolve template variables in a value."""
        if value is None:
            return None

        # Simple template resolution for {inputs.x} and {steps.x.y}
        import re

        def replace_var(match):
            var_path = match.group(1)
            parts = var_path.split(".")

            if parts[0] == "inputs" and len(parts) > 1:
                return str(context.get_input(parts[1], match.group(0)))
            elif parts[0] == "steps" and len(parts) > 2:
                step_output = context.get_step_output(parts[1])
                if step_output and isinstance(step_output, dict):
                    return str(step_output.get(parts[2], match.group(0)))
            elif parts[0] == "state" and len(parts) > 1:
                return str(context.get_state(parts[1], match.group(0)))

            return match.group(0)

        return re.sub(r"\{([^}]+)\}", replace_var, value)

    async def execute(self, context: WorkflowContext) -> dict[str, Any]:
        """
        Execute the browser action.

        Args:
            context: Workflow context with inputs and state

        Returns:
            Dict with action result

        Raises:
            ValueError: For invalid configuration
            RuntimeError: For browser action failures
        """
        config = self._step_config
        action = config.action.lower()

        # Get or create browser connector
        connector = await _get_browser_connector(self._config)

        # Resolve template variables
        url = self._resolve_template(config.url, context)
        selector = self._resolve_template(config.selector, context)
        value = self._resolve_template(config.value, context)
        script = self._resolve_template(config.script, context)

        result_data: dict[str, Any] = {"action": action}

        # Execute action
        if action == "navigate":
            if not url:
                raise ValueError("URL is required for navigate action")
            state = await connector.navigate(
                url,
                wait_until=config.wait_until,
                timeout_ms=config.timeout_ms,
            )
            result_data.update(state.to_dict())

        elif action == "click":
            if not selector:
                raise ValueError("Selector is required for click action")
            result = await connector.click(
                selector,
                timeout_ms=config.timeout_ms,
                force=config.force,
            )
            result_data.update(result.to_dict())
            if not result.success:
                raise RuntimeError(f"Click failed: {result.error}")

        elif action == "fill":
            if not selector or value is None:
                raise ValueError("Selector and value are required for fill action")
            result = await connector.fill(
                selector,
                value,
                timeout_ms=config.timeout_ms,
            )
            result_data.update(result.to_dict())
            if not result.success:
                raise RuntimeError(f"Fill failed: {result.error}")

        elif action == "select":
            if not selector or value is None:
                raise ValueError("Selector and value are required for select action")
            result = await connector.select(
                selector,
                value,
                timeout_ms=config.timeout_ms,
            )
            result_data.update(result.to_dict())
            if not result.success:
                raise RuntimeError(f"Select failed: {result.error}")

        elif action == "screenshot":
            screenshot_bytes = await connector.screenshot(
                full_page=config.full_page,
                selector=selector,
            )
            result_data["screenshot_base64"] = base64.b64encode(screenshot_bytes).decode()
            result_data["size_bytes"] = len(screenshot_bytes)

        elif action == "get_text":
            if not selector:
                raise ValueError("Selector is required for get_text action")
            text = await connector.get_text(selector, timeout_ms=config.timeout_ms)
            result_data["text"] = text

        elif action == "get_attribute":
            if not selector or not config.attribute:
                raise ValueError("Selector and attribute are required for get_attribute action")
            attr_value = await connector.get_attribute(
                selector,
                config.attribute,
                timeout_ms=config.timeout_ms,
            )
            result_data["attribute"] = config.attribute
            result_data["value"] = attr_value

        elif action == "get_html":
            html = await connector.get_html(selector)
            result_data["html"] = html

        elif action == "wait_for":
            if not selector:
                raise ValueError("Selector is required for wait_for action")
            found = await connector.wait_for(
                selector,
                state=config.state,
                timeout_ms=config.timeout_ms,
            )
            result_data["found"] = found
            if not found:
                raise RuntimeError(f"Element not found: {selector}")

        elif action == "execute_script":
            if not script:
                raise ValueError("Script is required for execute_script action")
            script_result = await connector.execute_script(script)
            result_data["result"] = script_result

        elif action == "extract_data":
            if not config.selectors:
                raise ValueError("Selectors dict is required for extract_data action")
            # Resolve templates in selectors
            resolved_selectors = {
                k: self._resolve_template(v, context) or v for k, v in config.selectors.items()
            }
            data = await connector.extract_data(
                resolved_selectors,
                timeout_ms=config.timeout_ms,
            )
            result_data["data"] = data

        elif action == "get_cookies":
            cookies = await connector.get_cookies()
            result_data["cookies"] = cookies

        elif action == "clear_cookies":
            await connector.clear_cookies()
            result_data["cleared"] = True

        elif action == "reload":
            state = await connector.reload()
            result_data.update(state.to_dict())

        elif action == "go_back":
            state = await connector.go_back()
            result_data.update(state.to_dict())

        elif action == "go_forward":
            state = await connector.go_forward()
            result_data.update(state.to_dict())

        elif action == "close":
            await _close_browser_connector()
            result_data["closed"] = True

        else:
            raise ValueError(f"Unknown action: {action}")

        # Add current URL to result
        if connector.is_initialized:
            result_data["current_url"] = connector.current_url

        # Close session if requested
        if config.close_session:
            await _close_browser_connector()
            result_data["session_closed"] = True

        logger.info("[BrowserStep] %s: %s completed", self._name, action)
        return result_data


# Register step type
def register_browser_step():
    """Register the browser step type with the workflow engine."""
    from aragora.workflow.nodes import register_step_type

    register_step_type("browser", BrowserStep)
    logger.debug("Registered browser step type")
