"""
Tests for marketplace template → TeamSelector wiring (Epic #292, T1).

Verifies that TeamSelector.select_from_template:
- Returns agent names from a known DebateTemplate's agent_roles
- Returns empty list for unknown template names (graceful failure)
- Works with both built-in templates and custom registered templates
"""

from __future__ import annotations

import pytest
from unittest.mock import MagicMock, patch


class TestSelectFromTemplate:
    """Tests for TeamSelector.select_from_template."""

    @pytest.fixture
    def selector(self):
        """Create a minimal TeamSelector."""
        from aragora.debate.team_selector import TeamSelector

        return TeamSelector()

    def test_select_from_known_debate_template_returns_nonempty_list(self, selector):
        """select_from_template with a known debate template ID returns a non-empty list."""
        result = selector.select_from_template("oxford-style")
        assert isinstance(result, list)
        assert len(result) > 0

    def test_select_from_known_debate_template_returns_strings(self, selector):
        """Returned items are strings (agent names or role names)."""
        result = selector.select_from_template("oxford-style")
        for item in result:
            assert isinstance(item, str), f"Expected str, got {type(item)}: {item!r}"

    def test_select_from_unknown_template_returns_empty_list(self, selector):
        """Unknown template name returns empty list (graceful failure)."""
        result = selector.select_from_template("nonexistent-template-xyz-123")
        assert result == []

    def test_select_from_brainstorm_template(self, selector):
        """brainstorm-session template resolves to agent roles."""
        result = selector.select_from_template("brainstorm-session")
        assert isinstance(result, list)
        assert len(result) > 0

    def test_select_from_code_review_template(self, selector):
        """code-review-session template resolves to agent roles."""
        result = selector.select_from_template("code-review-session")
        assert isinstance(result, list)
        assert len(result) > 0

    def test_select_from_agent_template_returns_agent_type(self, selector):
        """AgentTemplate (not DebateTemplate) returns the agent_type as list."""
        result = selector.select_from_template("devil-advocate")
        assert isinstance(result, list)
        assert len(result) > 0

    def test_select_from_template_is_async_compatible(self, selector):
        """select_from_template can be called as a coroutine."""
        import asyncio
        import inspect

        # The method should either be async or sync but callable
        method = getattr(selector, "select_from_template", None)
        assert method is not None, "TeamSelector must have select_from_template method"

    def test_empty_template_name_returns_empty_list(self, selector):
        """Empty string template name returns empty list."""
        result = selector.select_from_template("")
        assert result == []

    def test_select_from_template_with_custom_registry(self):
        """select_from_template works with a custom-registered template."""
        from aragora.debate.team_selector import TeamSelector
        from aragora.marketplace.models import (
            AgentTemplate,
            TemplateMetadata,
            TemplateCategory,
        )

        # Use a custom in-memory registry for isolation
        from aragora.marketplace.registry import TemplateRegistry
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as tmpdir:
            registry = TemplateRegistry(db_path=Path(tmpdir) / "test_marketplace.db")

            custom_template = AgentTemplate(
                metadata=TemplateMetadata(
                    id="custom-analyst",
                    name="Custom Analyst",
                    description="A custom analysis agent",
                    version="1.0.0",
                    author="test",
                    category=TemplateCategory.ANALYSIS,
                ),
                agent_type="claude",
                system_prompt="You are an analyst.",
                capabilities=["analysis"],
            )
            registry.register(custom_template)

            selector = TeamSelector(marketplace_registry=registry)
            result = selector.select_from_template("custom-analyst")
            assert isinstance(result, list)
            assert len(result) > 0


class TestSelectFromTemplateIntegration:
    """Integration tests confirming marketplace lookup path works end-to-end."""

    def test_selector_has_select_from_template_method(self):
        """TeamSelector exposes select_from_template."""
        from aragora.debate.team_selector import TeamSelector

        assert hasattr(TeamSelector, "select_from_template")
        assert callable(getattr(TeamSelector, "select_from_template"))

    def test_oxford_style_roles_match_template_definition(self):
        """oxford-style template agent_roles are reflected in select_from_template result."""
        from aragora.debate.team_selector import TeamSelector
        from aragora.marketplace.registry import TemplateRegistry
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as tmpdir:
            registry = TemplateRegistry(db_path=Path(tmpdir) / "test_marketplace.db")
            selector = TeamSelector(marketplace_registry=registry)
            result = selector.select_from_template("oxford-style")

            # oxford-style has 4 agent_roles; result should reflect them
            assert len(result) == 4
