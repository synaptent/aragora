"""Tests for the Vertical Registry."""

import pytest

from aragora.verticals import (
    VerticalRegistry,
    VerticalConfig,
    VerticalSpec,
    SoftwareSpecialist,
    LegalSpecialist,
    HealthcareSpecialist,
    AccountingSpecialist,
    ResearchSpecialist,
)


class TestVerticalRegistry:
    """Tests for VerticalRegistry."""

    def test_all_verticals_registered(self):
        """All 5 verticals should be registered."""
        registered = VerticalRegistry.get_registered_ids()
        assert len(registered) == 5
        assert "software" in registered
        assert "legal" in registered
        assert "healthcare" in registered
        assert "accounting" in registered
        assert "research" in registered

    def test_is_registered(self):
        """Test is_registered method."""
        assert VerticalRegistry.is_registered("software")
        assert VerticalRegistry.is_registered("legal")
        assert not VerticalRegistry.is_registered("unknown")

    def test_get_spec(self):
        """Test getting vertical specification."""
        spec = VerticalRegistry.get("software")
        assert spec is not None
        assert isinstance(spec, VerticalSpec)
        assert spec.vertical_id == "software"
        assert spec.specialist_class == SoftwareSpecialist

    def test_get_config(self):
        """Test getting vertical configuration."""
        config = VerticalRegistry.get_config("legal")
        assert config is not None
        assert isinstance(config, VerticalConfig)
        assert config.vertical_id == "legal"
        assert "Contract Analysis" in config.expertise_areas

    def test_list_all(self):
        """Test listing all verticals."""
        all_verticals = VerticalRegistry.list_all()
        assert len(all_verticals) == 5

        # Check software vertical metadata
        software = all_verticals["software"]
        assert "display_name" in software
        assert "expertise_areas" in software
        assert "tools" in software
        assert "compliance_frameworks" in software

    def test_get_by_keyword(self):
        """Test finding verticals by keyword."""
        # Software keywords
        matches = VerticalRegistry.get_by_keyword("code")
        assert "software" in matches

        # Legal keywords
        matches = VerticalRegistry.get_by_keyword("contract")
        assert "legal" in matches

        # Healthcare keywords
        matches = VerticalRegistry.get_by_keyword("patient")
        assert "healthcare" in matches

        # Accounting keywords
        matches = VerticalRegistry.get_by_keyword("audit")
        assert "accounting" in matches

        # Research keywords
        matches = VerticalRegistry.get_by_keyword("methodology")
        assert "research" in matches

    def test_get_for_task(self):
        """Test inferring vertical from task description."""
        # Software task
        vertical = VerticalRegistry.get_for_task(
            "Review this Python code for security vulnerabilities"
        )
        assert vertical == "software"

        # Legal task
        vertical = VerticalRegistry.get_for_task("Analyze this contract for liability clauses")
        assert vertical == "legal"

        # Healthcare task
        vertical = VerticalRegistry.get_for_task("Review patient data for HIPAA compliance")
        assert vertical == "healthcare"

        # Accounting task
        vertical = VerticalRegistry.get_for_task(
            "Audit the financial statements for SOX compliance"
        )
        assert vertical == "accounting"

        # Research task
        vertical = VerticalRegistry.get_for_task("Evaluate the methodology of this research study")
        assert vertical == "research"

    def test_create_specialist(self):
        """Test creating specialist instances."""
        specialist = VerticalRegistry.create_specialist(
            "software",
            name="test-reviewer",
            model="test-model",
        )
        assert specialist is not None
        assert specialist.name == "test-reviewer"
        assert specialist.model == "test-model"
        assert specialist.vertical_id == "software"

    def test_create_specialist_with_default_model(self):
        """Test creating specialist with default model from config."""
        specialist = VerticalRegistry.create_specialist(
            "legal",
            name="legal-analyst",
        )
        assert specialist is not None
        assert specialist.model == "claude-opus-5"  # Default from config

    def test_create_specialist_unknown_vertical(self):
        """Test that creating unknown vertical raises error."""
        with pytest.raises(ValueError, match="Unknown vertical"):
            VerticalRegistry.create_specialist(
                "unknown",
                name="test",
            )


class TestVerticalConfig:
    """Tests for VerticalConfig."""

    def test_to_dict(self):
        """Test serialization to dictionary."""
        config = VerticalRegistry.get_config("software")
        data = config.to_dict()

        assert data["vertical_id"] == "software"
        assert "domain_keywords" in data
        assert "expertise_areas" in data
        assert "tools" in data
        assert "compliance_frameworks" in data
        assert "model_config" in data

    def test_from_dict(self):
        """Test deserialization from dictionary."""
        original = VerticalRegistry.get_config("software")
        data = original.to_dict()
        restored = VerticalConfig.from_dict(data)

        assert restored.vertical_id == original.vertical_id
        assert restored.display_name == original.display_name
        assert len(restored.tools) == len(original.tools)

    def test_get_enabled_tools(self):
        """Test getting enabled tools."""
        config = VerticalRegistry.get_config("software")
        enabled_tools = config.get_enabled_tools()

        assert len(enabled_tools) > 0
        assert all(tool.enabled for tool in enabled_tools)

    def test_get_compliance_frameworks(self):
        """Test getting compliance frameworks."""
        config = VerticalRegistry.get_config("healthcare")
        frameworks = config.get_compliance_frameworks()

        assert len(frameworks) > 0
        assert any(f.framework == "HIPAA" for f in frameworks)
