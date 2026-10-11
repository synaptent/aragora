"""
Compliance tests for Knowledge Mound adapters.

Ensures all adapters follow the unified KnowledgeMoundAdapter pattern
with proper inheritance, adapter_name, and observability methods.
"""

from __future__ import annotations

import importlib
from typing import Any

import pytest


# Adapter specifications: module path and class name
ADAPTER_SPECS: list[dict[str, str]] = [
    {
        "module": "aragora.knowledge.mound.adapters.openclaw_adapter",
        "class_name": "OpenClawAdapter",
    },
    {
        "module": "aragora.knowledge.mound.adapters.fabric_adapter",
        "class_name": "FabricAdapter",
    },
    {
        "module": "aragora.knowledge.mound.adapters.gateway_adapter",
        "class_name": "GatewayAdapter",
    },
    {
        "module": "aragora.knowledge.mound.adapters.calibration_fusion_adapter",
        "class_name": "CalibrationFusionAdapter",
    },
    {
        "module": "aragora.knowledge.mound.adapters.erc8004_adapter",
        "class_name": "ERC8004Adapter",
    },
    {
        "module": "aragora.knowledge.mound.adapters.computer_use_adapter",
        "class_name": "ComputerUseAdapter",
    },
    {
        "module": "aragora.knowledge.mound.adapters.extraction_adapter",
        "class_name": "ExtractionAdapter",
    },
    {
        "module": "aragora.knowledge.mound.adapters.workspace_adapter",
        "class_name": "WorkspaceAdapter",
    },
    {
        "module": "aragora.knowledge.mound.adapters.consensus_adapter",
        "class_name": "ConsensusAdapter",
    },
    {
        "module": "aragora.knowledge.mound.adapters.continuum_adapter",
        "class_name": "ContinuumAdapter",
    },
    {
        "module": "aragora.knowledge.mound.adapters.belief_adapter",
        "class_name": "BeliefAdapter",
    },
    {
        "module": "aragora.knowledge.mound.adapters.evidence_adapter",
        "class_name": "EvidenceAdapter",
    },
    {
        "module": "aragora.knowledge.mound.adapters.insights_adapter",
        "class_name": "InsightsAdapter",
    },
    {
        "module": "aragora.knowledge.mound.adapters.cost_adapter",
        "class_name": "CostAdapter",
    },
    {
        "module": "aragora.knowledge.mound.adapters.pulse_adapter",
        "class_name": "PulseAdapter",
    },
    {
        "module": "aragora.knowledge.mound.adapters.performance.adapter",
        "class_name": "PerformanceAdapter",
    },
    {
        "module": "aragora.knowledge.mound.adapters.critique_adapter",
        "class_name": "CritiqueAdapter",
    },
    {
        "module": "aragora.knowledge.mound.adapters.control_plane_adapter",
        "class_name": "ControlPlaneAdapter",
    },
    {
        "module": "aragora.knowledge.mound.adapters.receipt_adapter",
        "class_name": "ReceiptAdapter",
    },
    {
        "module": "aragora.knowledge.mound.adapters.culture_adapter",
        "class_name": "CultureAdapter",
    },
    {
        "module": "aragora.knowledge.mound.adapters.rlm_adapter",
        "class_name": "RlmAdapter",
    },
    {
        "module": "aragora.knowledge.mound.adapters.provenance_adapter",
        "class_name": "ProvenanceAdapter",
    },
    {
        "module": "aragora.knowledge.mound.adapters.executable_claim_adapter",
        "class_name": "ExecutableClaimAdapter",
    },
]


def _load_adapter_class(module_path: str, class_name: str) -> type:
    """Dynamically load an adapter class.

    All adapters are expected to be importable.  If an import fails the test
    should *fail* (not skip) so regressions are caught immediately.
    """
    module = importlib.import_module(module_path)
    cls = getattr(module, class_name)
    return cls


def _load_base_class() -> type:
    """Load the KnowledgeMoundAdapter base class."""
    from aragora.knowledge.mound.adapters._base import KnowledgeMoundAdapter

    return KnowledgeMoundAdapter


def _get_adapter_id(spec: dict[str, str]) -> str:
    """Generate a test ID from adapter spec."""
    return spec["class_name"]


_ADAPTER_PARAMS = [pytest.param(spec, id=_get_adapter_id(spec)) for spec in ADAPTER_SPECS]


class TestAdapterCompliance:
    """Test that all adapters comply with the unified adapter pattern."""

    @pytest.mark.parametrize("spec", _ADAPTER_PARAMS)
    def test_inherits_from_knowledge_mound_adapter(self, spec: dict[str, str]) -> None:
        """Adapter should inherit from KnowledgeMoundAdapter."""
        base_class = _load_base_class()
        adapter_class = _load_adapter_class(spec["module"], spec["class_name"])

        assert issubclass(adapter_class, base_class), (
            f"{spec['class_name']} should inherit from KnowledgeMoundAdapter"
        )

    @pytest.mark.parametrize("spec", _ADAPTER_PARAMS)
    def test_has_unique_adapter_name(self, spec: dict[str, str]) -> None:
        """Adapter should have a unique adapter_name that is not 'base'."""
        adapter_class = _load_adapter_class(spec["module"], spec["class_name"])

        assert hasattr(adapter_class, "adapter_name"), (
            f"{spec['class_name']} should have adapter_name attribute"
        )

        adapter_name = getattr(adapter_class, "adapter_name", None)
        assert adapter_name is not None, f"{spec['class_name']}.adapter_name should not be None"
        assert adapter_name != "base", f"{spec['class_name']}.adapter_name should not be 'base'"
        assert isinstance(adapter_name, str), (
            f"{spec['class_name']}.adapter_name should be a string"
        )
        assert len(adapter_name) > 0, f"{spec['class_name']}.adapter_name should not be empty"

    @pytest.mark.parametrize("spec", _ADAPTER_PARAMS)
    def test_has_emit_event_method(self, spec: dict[str, str]) -> None:
        """Adapter should have _emit_event method (inherited or defined)."""
        adapter_class = _load_adapter_class(spec["module"], spec["class_name"])

        assert hasattr(adapter_class, "_emit_event"), (
            f"{spec['class_name']} should have _emit_event method"
        )

        emit_event = getattr(adapter_class, "_emit_event")
        assert callable(emit_event), f"{spec['class_name']}._emit_event should be callable"

    @pytest.mark.parametrize("spec", _ADAPTER_PARAMS)
    def test_has_record_metric_method(self, spec: dict[str, str]) -> None:
        """Adapter should have _record_metric method (inherited or defined)."""
        adapter_class = _load_adapter_class(spec["module"], spec["class_name"])

        assert hasattr(adapter_class, "_record_metric"), (
            f"{spec['class_name']} should have _record_metric method"
        )

        record_metric = getattr(adapter_class, "_record_metric")
        assert callable(record_metric), f"{spec['class_name']}._record_metric should be callable"

    @pytest.mark.parametrize("spec", _ADAPTER_PARAMS)
    def test_has_health_check_method(self, spec: dict[str, str]) -> None:
        """Adapter should have health_check method (inherited or defined)."""
        adapter_class = _load_adapter_class(spec["module"], spec["class_name"])

        assert hasattr(adapter_class, "health_check"), (
            f"{spec['class_name']} should have health_check method"
        )

        health_check = getattr(adapter_class, "health_check")
        assert callable(health_check), f"{spec['class_name']}.health_check should be callable"


class TestAdapterNameUniqueness:
    """Test that adapter_name values are unique across all adapters."""

    def test_no_duplicate_adapter_names(self) -> None:
        """All adapters should have unique adapter_name values."""
        adapter_names: dict[str, str] = {}  # adapter_name -> class_name

        for spec in ADAPTER_SPECS:
            adapter_class = _load_adapter_class(spec["module"], spec["class_name"])
            if adapter_class is None:
                continue

            adapter_name = getattr(adapter_class, "adapter_name", None)
            if adapter_name is None or adapter_name == "base":
                continue

            if adapter_name in adapter_names:
                pytest.fail(
                    f"Duplicate adapter_name '{adapter_name}' found in "
                    f"{spec['class_name']} and {adapter_names[adapter_name]}"
                )
            else:
                adapter_names[adapter_name] = spec["class_name"]

        assert len(adapter_names) > 0, "Should find at least one valid adapter_name"


class TestComplianceSummary:
    """Summary tests for tracking migration progress."""

    def test_count_compliant_adapters(self) -> None:
        """Count how many adapters are fully compliant."""
        base_class = _load_base_class()

        compliant_count = 0
        total_count = len(ADAPTER_SPECS)

        for spec in ADAPTER_SPECS:
            adapter_class = _load_adapter_class(spec["module"], spec["class_name"])
            if adapter_class is None:
                continue

            is_subclass = issubclass(adapter_class, base_class)
            has_valid_name = (
                hasattr(adapter_class, "adapter_name") and adapter_class.adapter_name != "base"
            )
            has_emit_event = hasattr(adapter_class, "_emit_event")
            has_record_metric = hasattr(adapter_class, "_record_metric")
            has_health_check = hasattr(adapter_class, "health_check")

            if all(
                [is_subclass, has_valid_name, has_emit_event, has_record_metric, has_health_check]
            ):
                compliant_count += 1

        compliance_pct = (compliant_count / total_count) * 100 if total_count > 0 else 0

        assert compliant_count == total_count, (
            f"Expected all {total_count} adapters to be compliant, found {compliant_count}"
        )

        print(f"\nAdapter Compliance: {compliant_count}/{total_count} ({compliance_pct:.1f}%)")
