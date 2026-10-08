"""
Aragora Audit System.

Enterprise-grade audit logging for compliance (SOC 2, HIPAA, GDPR, SOX)
and document auditing for defect detection.

Usage:
    # Compliance logging
    from aragora.audit import AuditLog, AuditEvent, AuditCategory

    audit = AuditLog()
    audit.log(AuditEvent(
        category=AuditCategory.AUTH,
        action="login",
        actor_id="user_123",
    ))

    # Document auditing
    from aragora.audit import DocumentAuditor, AuditSession

    auditor = DocumentAuditor()
    session = await auditor.create_session(document_ids=["doc1"])
    await auditor.run_audit(session.id)

    # Custom audit types
    from aragora.audit import BaseAuditor, AuditContext, audit_registry

    class MyAuditor(BaseAuditor):
        @property
        def audit_type_id(self) -> str:
            return "my_custom"
        ...

    audit_registry.register(MyAuditor())
"""

from .log import (
    AuditCategory,
    AuditEvent,
    AuditLog,
    AuditOutcome,
    AuditQuery,
    audit_admin_action,
    audit_auth_login,
    audit_data_access,
)
from .document_auditor import (
    DocumentAuditor,
    AuditSession,
    AuditConfig,
    AuditFinding,
    AuditType,
    AuditStatus,
    FindingSeverity,
    FindingStatus,
    get_document_auditor,
)
from .hive_mind import (
    AuditHiveMind,
    HiveMindConfig,
    HiveMindResult,
    WorkerTask,
    WorkerResult,
    QueenOrchestrator,
)
from .base_auditor import (
    BaseAuditor,
    AuditContext,
    ChunkData,
    AuditorCapabilities,
)
from .registry import (
    AuditRegistry,
    AuditTypeInfo,
    PresetConfig,
    audit_registry,
    get_registry,
    register_auditor,
    get_auditor,
    list_audit_types,
)
from .consensus_adapter import (
    FindingVerifier,
    VerificationConfig,
    VerificationResult,
    verify_finding,
)
from .evidence_adapter import (
    FindingEvidenceCollector,
    EvidenceConfig,
    EvidenceEnrichment,
    EvidenceSource,
    enrich_finding_with_evidence,
)
from .code_scanners import register_code_scanners

register_code_scanners()

__all__ = [
    # Compliance logging
    "AuditCategory",
    "AuditEvent",
    "AuditLog",
    "AuditOutcome",
    "AuditQuery",
    "audit_admin_action",
    "audit_auth_login",
    "audit_data_access",
    # Document auditing
    "DocumentAuditor",
    "AuditSession",
    "AuditConfig",
    "AuditFinding",
    "AuditType",
    "AuditStatus",
    "FindingSeverity",
    "FindingStatus",
    "get_document_auditor",
    # Hive-Mind Architecture
    "AuditHiveMind",
    "HiveMindConfig",
    "HiveMindResult",
    "WorkerTask",
    "WorkerResult",
    "QueenOrchestrator",
    # Pluggable Audit Types
    "BaseAuditor",
    "AuditContext",
    "ChunkData",
    "AuditorCapabilities",
    # Audit Registry
    "AuditRegistry",
    "AuditTypeInfo",
    "PresetConfig",
    "audit_registry",
    "get_registry",
    "register_auditor",
    "get_auditor",
    "list_audit_types",
    # Consensus Verification
    "FindingVerifier",
    "VerificationConfig",
    "VerificationResult",
    "verify_finding",
    # Evidence Collection
    "FindingEvidenceCollector",
    "EvidenceConfig",
    "EvidenceEnrichment",
    "EvidenceSource",
    "enrich_finding_with_evidence",
]
