"""Tests for aragora.verticals.config module."""

import os
import tempfile

import pytest
import yaml

from aragora.verticals.config import (
    ComplianceConfig,
    ComplianceLevel,
    ModelConfig,
    ToolConfig,
    VerticalConfig,
)


# ---------------------------------------------------------------------------
# ComplianceLevel enum
# ---------------------------------------------------------------------------


class TestComplianceLevel:
    def test_enum_values(self):
        assert ComplianceLevel.ADVISORY.value == "advisory"
        assert ComplianceLevel.WARNING.value == "warning"
        assert ComplianceLevel.ENFORCED.value == "enforced"

    def test_from_string(self):
        assert ComplianceLevel("advisory") is ComplianceLevel.ADVISORY
        assert ComplianceLevel("enforced") is ComplianceLevel.ENFORCED

    def test_invalid_value_raises(self):
        with pytest.raises(ValueError):
            ComplianceLevel("invalid")


# ---------------------------------------------------------------------------
# ToolConfig
# ---------------------------------------------------------------------------


class TestToolConfig:
    def test_defaults(self):
        tc = ToolConfig(name="lint", description="Run linter")
        assert tc.name == "lint"
        assert tc.description == "Run linter"
        assert tc.enabled is True
        assert tc.parameters == {}
        assert tc.requires_auth is False
        assert tc.connector_type is None

    def test_custom_values(self):
        tc = ToolConfig(
            name="github",
            description="GitHub connector",
            enabled=False,
            parameters={"repo": "org/repo"},
            requires_auth=True,
            connector_type="github",
        )
        assert tc.enabled is False
        assert tc.parameters == {"repo": "org/repo"}
        assert tc.requires_auth is True
        assert tc.connector_type == "github"

    def test_to_dict(self):
        tc = ToolConfig(name="t", description="d", parameters={"k": "v"})
        d = tc.to_dict()
        assert d["name"] == "t"
        assert d["parameters"] == {"k": "v"}
        assert d["enabled"] is True
        assert d["connector_type"] is None

    def test_from_dict_minimal(self):
        tc = ToolConfig.from_dict({"name": "x"})
        assert tc.name == "x"
        assert tc.description == ""
        assert tc.enabled is True

    def test_roundtrip(self):
        original = ToolConfig(
            name="pub",
            description="PubMed",
            enabled=False,
            parameters={"limit": 10},
            requires_auth=True,
            connector_type="pubmed",
        )
        rebuilt = ToolConfig.from_dict(original.to_dict())
        assert rebuilt == original


# ---------------------------------------------------------------------------
# ComplianceConfig
# ---------------------------------------------------------------------------


class TestComplianceConfig:
    def test_defaults(self):
        cc = ComplianceConfig(framework="HIPAA")
        assert cc.framework == "HIPAA"
        assert cc.version == "latest"
        assert cc.level is ComplianceLevel.WARNING
        assert cc.rules == []
        assert cc.exemptions == []

    def test_to_dict_serialises_level(self):
        cc = ComplianceConfig(framework="SOX", level=ComplianceLevel.ENFORCED)
        d = cc.to_dict()
        assert d["level"] == "enforced"
        assert d["framework"] == "SOX"

    def test_from_dict_with_level_string(self):
        cc = ComplianceConfig.from_dict({"framework": "OWASP", "level": "advisory"})
        assert cc.level is ComplianceLevel.ADVISORY

    def test_roundtrip(self):
        original = ComplianceConfig(
            framework="GDPR",
            version="2.0",
            level=ComplianceLevel.ENFORCED,
            rules=["r1", "r2"],
            exemptions=["e1"],
        )
        rebuilt = ComplianceConfig.from_dict(original.to_dict())
        assert rebuilt == original


# ---------------------------------------------------------------------------
# ModelConfig
# ---------------------------------------------------------------------------


class TestModelConfig:
    def test_defaults(self):
        mc = ModelConfig()
        assert mc.primary_model == "claude-opus-5"
        assert mc.primary_provider == "anthropic"
        assert mc.specialist_model is None
        assert mc.specialist_quantization is None
        assert mc.finetuned_adapter is None
        assert mc.temperature == pytest.approx(0.7)
        assert mc.top_p == pytest.approx(0.9)
        assert mc.max_tokens == 4096

    def test_custom_generation_params(self):
        mc = ModelConfig(temperature=0.2, top_p=0.5, max_tokens=1024)
        assert mc.temperature == pytest.approx(0.2)
        assert mc.max_tokens == 1024

    def test_from_dict_empty(self):
        mc = ModelConfig.from_dict({})
        assert mc == ModelConfig()

    def test_roundtrip(self):
        original = ModelConfig(
            primary_model="gpt-4",
            primary_provider="openai",
            specialist_model="biogpt",
            specialist_quantization="4bit",
            finetuned_adapter="/adapters/lora",
            temperature=0.3,
            top_p=0.8,
            max_tokens=2048,
        )
        rebuilt = ModelConfig.from_dict(original.to_dict())
        assert rebuilt == original


# ---------------------------------------------------------------------------
# VerticalConfig
# ---------------------------------------------------------------------------


class TestVerticalConfig:
    def _make_config(self, **overrides):
        defaults = dict(
            vertical_id="security",
            display_name="Security Specialist",
            description="Cyber-security vertical",
        )
        defaults.update(overrides)
        return VerticalConfig(**defaults)

    def test_minimal(self):
        vc = self._make_config()
        assert vc.vertical_id == "security"
        assert vc.tools == []
        assert vc.version == "1.0.0"
        assert vc.author is None

    def test_get_enabled_tools(self):
        tools = [
            ToolConfig(name="a", description="A", enabled=True),
            ToolConfig(name="b", description="B", enabled=False),
            ToolConfig(name="c", description="C", enabled=True),
        ]
        vc = self._make_config(tools=tools)
        enabled = vc.get_enabled_tools()
        assert [t.name for t in enabled] == ["a", "c"]

    def test_get_compliance_frameworks_no_filter(self):
        frameworks = [
            ComplianceConfig(framework="HIPAA", level=ComplianceLevel.ENFORCED),
            ComplianceConfig(framework="SOX", level=ComplianceLevel.ADVISORY),
        ]
        vc = self._make_config(compliance_frameworks=frameworks)
        assert len(vc.get_compliance_frameworks()) == 2

    def test_get_compliance_frameworks_filtered(self):
        frameworks = [
            ComplianceConfig(framework="HIPAA", level=ComplianceLevel.ENFORCED),
            ComplianceConfig(framework="SOX", level=ComplianceLevel.ADVISORY),
            ComplianceConfig(framework="GDPR", level=ComplianceLevel.ENFORCED),
        ]
        vc = self._make_config(compliance_frameworks=frameworks)
        enforced = vc.get_compliance_frameworks(level=ComplianceLevel.ENFORCED)
        assert len(enforced) == 2
        assert {c.framework for c in enforced} == {"HIPAA", "GDPR"}

    def test_to_dict_and_from_dict_roundtrip(self):
        vc = VerticalConfig(
            vertical_id="health",
            display_name="Health",
            description="Healthcare vertical",
            domain_keywords=["medicine", "clinical"],
            expertise_areas=["diagnostics"],
            system_prompt_template="You are a {{role}}.",
            tools=[ToolConfig(name="pubmed", description="PubMed search")],
            compliance_frameworks=[
                ComplianceConfig(framework="HIPAA", level=ComplianceLevel.ENFORCED)
            ],
            model_config=ModelConfig(temperature=0.3),
            version="2.0.0",
            author="test",
            tags=["health", "compliance"],
        )
        d = vc.to_dict()
        rebuilt = VerticalConfig.from_dict(d)
        assert rebuilt.vertical_id == vc.vertical_id
        assert rebuilt.display_name == vc.display_name
        assert rebuilt.domain_keywords == vc.domain_keywords
        assert rebuilt.tools[0].name == "pubmed"
        assert rebuilt.compliance_frameworks[0].level is ComplianceLevel.ENFORCED
        assert rebuilt.model_config.temperature == pytest.approx(0.3)
        assert rebuilt.version == "2.0.0"
        assert rebuilt.author == "test"
        assert rebuilt.tags == ["health", "compliance"]

    def test_yaml_roundtrip(self, tmp_path):
        vc = self._make_config(
            tools=[ToolConfig(name="scan", description="Scanner")],
            tags=["sec"],
        )
        yaml_file = str(tmp_path / "config.yaml")
        vc.to_yaml(yaml_file)

        loaded = VerticalConfig.from_yaml(yaml_file)
        assert loaded.vertical_id == vc.vertical_id
        assert loaded.tools[0].name == "scan"
        assert loaded.tags == ["sec"]

    def test_from_dict_defaults(self):
        data = {
            "vertical_id": "fin",
            "display_name": "Finance",
        }
        vc = VerticalConfig.from_dict(data)
        assert vc.description == ""
        assert vc.domain_keywords == []
        assert vc.tools == []
        assert vc.compliance_frameworks == []
        assert vc.model_config == ModelConfig()
        assert vc.version == "1.0.0"
        assert vc.author is None
