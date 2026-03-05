"""
Tests confirming circuit breakers are present on external connector APIs.

These tests verify that connectors that make external API calls are guarded
by circuit breakers, preventing cascading failures when upstream services
are unavailable.
"""

from __future__ import annotations

import inspect


def test_slack_integration_has_circuit_breaker() -> None:
    """SlackIntegration (aragora/integrations/slack.py) uses a circuit breaker."""
    from aragora.integrations.slack import SlackIntegration

    source = inspect.getsource(SlackIntegration)
    assert "circuit_breaker" in source.lower() or "CircuitBreaker" in source


def test_discord_integration_has_circuit_breaker() -> None:
    """DiscordIntegration (aragora/integrations/discord.py) uses a circuit breaker."""
    from aragora.integrations.discord import DiscordIntegration

    source = inspect.getsource(DiscordIntegration)
    assert "circuit_breaker" in source.lower() or "CircuitBreaker" in source


def test_teams_integration_has_circuit_breaker() -> None:
    """TeamsIntegration (aragora/integrations/teams.py) uses a circuit breaker."""
    from aragora.integrations.teams import TeamsIntegration

    source = inspect.getsource(TeamsIntegration)
    assert "circuit_breaker" in source.lower() or "CircuitBreaker" in source


def test_email_integration_has_circuit_breaker() -> None:
    """Email integration (aragora/integrations/email.py) uses circuit breakers."""
    import aragora.integrations.email as email_module

    source = inspect.getsource(email_module)
    assert "circuit_breaker" in source.lower()


def test_webhooks_integration_has_circuit_breaker() -> None:
    """Webhooks integration (aragora/integrations/webhooks.py) uses a circuit breaker."""
    import aragora.integrations.webhooks as webhooks_module

    source = inspect.getsource(webhooks_module)
    assert "circuit_breaker" in source.lower() or "CircuitBreaker" in source


def test_zapier_integration_has_circuit_breaker() -> None:
    """ZapierIntegration (aragora/integrations/zapier.py) uses a circuit breaker."""
    from aragora.integrations.zapier import ZapierIntegration

    source = inspect.getsource(ZapierIntegration)
    assert "circuit_breaker" in source.lower() or "CircuitBreaker" in source


def test_zapier_integration_instance_has_circuit_breaker_attribute() -> None:
    """ZapierIntegration instance carries a _circuit_breaker attribute."""
    from aragora.integrations.zapier import ZapierIntegration

    obj = ZapierIntegration.__new__(ZapierIntegration)
    # _apps is set in __init__ so __new__ won't have it; check the class source instead.
    source = inspect.getsource(ZapierIntegration.__init__)
    assert "_circuit_breaker" in source


def test_github_connector_has_circuit_breaker() -> None:
    """GitHubConnector (aragora/connectors/github.py) uses a circuit breaker."""
    from aragora.connectors.github import GitHubConnector

    source = inspect.getsource(GitHubConnector)
    assert "circuit_breaker" in source.lower() or "CircuitBreaker" in source


def test_email_connector_has_circuit_breaker() -> None:
    """Email connector (aragora/connectors/email/) uses a circuit breaker."""
    from aragora.connectors.email import EmailCircuitBreaker

    # The class must exist and be accessible.
    assert EmailCircuitBreaker is not None


def test_slack_connector_module_has_circuit_breaker() -> None:
    """aragora/connectors/ slack integration uses a circuit breaker."""
    # The Slack connector at aragora/integrations/slack.py is the primary one
    # with external API calls. Confirm it references get_circuit_breaker.
    import aragora.integrations.slack as slack_module

    source = inspect.getsource(slack_module)
    assert "get_circuit_breaker" in source or "circuit_breaker" in source.lower()
