/**
 * Compliance Namespace API
 *
 * Provides methods for compliance and audit operations including
 * SOC 2 reporting, GDPR compliance, and audit trail verification.
 *
 * Features:
 * - SOC 2 Type II report generation
 * - GDPR data export and right-to-be-forgotten
 * - Audit trail verification
 * - SIEM-compatible event export
 */

/**
 * Audit event types for compliance tracking.
 */
export type AuditEventType =
  | 'authentication'
  | 'authorization'
  | 'data_access'
  | 'data_modification'
  | 'admin_action'
  | 'compliance';

/**
 * Compliance status across frameworks.
 */
export interface ComplianceStatus {
  soc2: {
    compliant: boolean;
    last_audit: string;
    findings_count: number;
  };
  gdpr: {
    compliant: boolean;
    data_processing_agreement: boolean;
    dpo_configured: boolean;
  };
  hipaa?: {
    compliant: boolean;
    baa_signed: boolean;
  };
  overall_status: 'compliant' | 'partial' | 'non_compliant';
}

/**
 * SOC 2 report structure.
 */
export interface Soc2Report {
  report_id: string;
  period_start: string;
  period_end: string;
  controls: Soc2ControlAssessment[];
  findings: Soc2Finding[];
  overall_assessment: 'pass' | 'pass_with_exceptions' | 'fail';
  generated_at: string;
}

/**
 * SOC 2 control assessment.
 */
export interface Soc2ControlAssessment {
  control_id: string;
  control_name: string;
  category: string;
  status: 'pass' | 'fail' | 'not_applicable';
  evidence_count: number;
  notes?: string;
}

/**
 * SOC 2 finding.
 */
export interface Soc2Finding {
  finding_id: string;
  severity: 'low' | 'medium' | 'high' | 'critical';
  control_id: string;
  description: string;
  remediation?: string;
  status: 'open' | 'remediated' | 'accepted';
}

/**
 * GDPR data export result.
 */
export interface GdprExportResult {
  export_id: string;
  user_id: string;
  format: string;
  data: Record<string, unknown>;
  generated_at: string;
  expires_at: string;
}

/**
 * GDPR deletion result.
 */
export interface GdprDeletionResult {
  deletion_id: string;
  user_id: string;
  status: 'pending' | 'in_progress' | 'completed' | 'failed';
  data_deleted: string[];
  data_retained: string[];
  retention_reason?: string;
  completed_at?: string;
}

/**
 * Audit trail verification result.
 */
export interface AuditVerificationResult {
  verified: boolean;
  period_start: string;
  period_end: string;
  events_checked: number;
  anomalies: AuditAnomaly[];
  integrity_hash: string;
  verified_at: string;
}

/**
 * Audit anomaly detected during verification.
 */
export interface AuditAnomaly {
  anomaly_id: string;
  type: 'gap' | 'tampering' | 'sequence_error' | 'timestamp_error';
  severity: 'low' | 'medium' | 'high';
  description: string;
  event_ids?: string[];
  detected_at: string;
}

/**
 * Audit event for SIEM export.
 */
export interface AuditEvent {
  event_id: string;
  event_type: AuditEventType;
  timestamp: string;
  user_id?: string;
  resource_type?: string;
  resource_id?: string;
  action: string;
  outcome: 'success' | 'failure';
  ip_address?: string;
  user_agent?: string;
  metadata?: Record<string, unknown>;
}

/**
 * Audit events export result.
 */
export interface AuditEventsExport {
  events: AuditEvent[];
  total_count: number;
  period_start: string;
  period_end: string;
  format: string;
  exported_at: string;
}

// ===========================================================================
// EU AI Act Types
// ===========================================================================

/**
 * EU AI Act risk level classification.
 */
export type EuAiActRiskLevel = 'unacceptable' | 'high' | 'limited' | 'minimal';

/**
 * EU AI Act risk classification result.
 */
export interface EuAiActRiskClassification {
  risk_level: EuAiActRiskLevel;
  annex_iii_category: string | null;
  annex_iii_number: number | null;
  rationale: string;
  matched_keywords: string[];
  applicable_articles: string[];
  obligations: string[];
}

/**
 * EU AI Act conformity report.
 */
export interface EuAiActConformityReport {
  overall_status: string;
  receipt_id: string;
  article_mappings: Array<{
    article: string;
    article_title: string;
    receipt_field: string;
    evidence: string;
    status: string;
  }>;
  generated_at: string;
  integrity_hash: string;
}

/**
 * EU AI Act compliance artifact bundle.
 */
export interface EuAiActArtifactBundle {
  bundle_id: string;
  regulation: string;
  compliance_deadline: string;
  receipt_id: string;
  generated_at: string;
  risk_classification: EuAiActRiskClassification;
  conformity_report: EuAiActConformityReport;
  article_12_record_keeping: Record<string, unknown>;
  article_13_transparency: Record<string, unknown>;
  article_14_human_oversight: Record<string, unknown>;
  integrity_hash: string;
}

// ===========================================================================
// HIPAA Types
// ===========================================================================

/**
 * HIPAA compliance status overview.
 */
export interface HipaaComplianceStatus {
  compliance_framework: string;
  assessed_at: string;
  overall_status: 'compliant' | 'substantially_compliant' | 'partially_compliant' | 'non_compliant';
  compliance_score: number;
  rules: {
    privacy_rule: { status: string; phi_handling: string };
    security_rule: { status: string; safeguards_assessed: number; safeguards_compliant: number };
    breach_notification_rule: { status: string; procedures_documented: boolean };
  };
  business_associates: { total_baas: number; active: number; expiring_soon: number; expired: number };
  recommendations?: Array<{ priority: string; category: string; recommendation: string; reference: string }>;
}

/**
 * HIPAA breach risk assessment result.
 */
export interface HipaaBreachAssessment {
  assessment_id: string;
  incident_id: string;
  assessed_at: string;
  phi_involved: boolean;
  breach_determination: string | null;
  risk_factors: Array<{ factor: string; risk: string; details: string }>;
  notification_required: boolean;
  notification_deadlines: Record<string, string> | null;
}

/**
 * Business Associate Agreement record.
 */
export interface HipaaBaa {
  baa_id: string;
  business_associate: string;
  ba_type: 'vendor' | 'subcontractor';
  services_provided: string;
  phi_access_scope: string[];
  agreement_date: string;
  expiration_date?: string;
  subcontractor_clause: boolean;
  status: string;
}

/**
 * PHI de-identification result.
 */
export interface HipaaDeidentifyResult {
  original_hash: string;
  anonymized_content: string;
  fields_anonymized: string[];
  method_used: Record<string, string>;
  identifiers_count: number;
  reversible: boolean;
  audit_id: string;
  anonymized_at: string;
}

/**
 * Safe Harbor verification result.
 */
export interface HipaaSafeHarborResult {
  compliant: boolean;
  identifiers_remaining: Array<{
    type: string;
    value_preview: string;
    confidence: number;
    position: { start: number; end: number };
  }>;
  verification_notes: string[];
  verified_at: string;
  hipaa_reference: string;
}

/**
 * PHI detection result.
 */
export interface HipaaPhiDetectionResult {
  identifiers: Array<{
    type: string;
    value: string;
    start: number;
    end: number;
    confidence: number;
  }>;
  count: number;
  min_confidence: number;
  hipaa_reference: string;
}

/**
 * Anonymization method for HIPAA de-identification.
 */
export type HipaaAnonymizationMethod = 'redact' | 'hash' | 'generalize' | 'suppress' | 'pseudonymize';

/**
 * Options for artifact bundle generation.
 */
export interface EuAiActBundleOptions {
  receipt: Record<string, unknown>;
  providerName?: string;
  providerContact?: string;
  euRepresentative?: string;
  systemName?: string;
  systemVersion?: string;
}

/**
 * Client interface for compliance operations.
 */
interface ComplianceClientInterface {
  request<T = unknown>(
    method: string,
    path: string,
    options?: { params?: Record<string, unknown>; json?: Record<string, unknown> }
  ): Promise<T>;
}

/**
 * Compliance API for enterprise compliance and audit operations.
 *
 * @example
 * ```typescript
 * const client = createClient({ baseUrl: 'https://api.aragora.ai' });
 *
 * // Get compliance status
 * const status = await client.compliance.getStatus();
 *
 * // Generate SOC 2 report
 * const report = await client.compliance.generateSoc2Report({
 *   startDate: '2024-01-01',
 *   endDate: '2024-12-31',
 * });
 *
 * // GDPR data export
 * const export = await client.compliance.gdprExport('user-123');
 * ```
 */
export class ComplianceAPI {
  constructor(private client: ComplianceClientInterface) {}

  // ===========================================================================
  // Compliance Status
  // ===========================================================================

  /**
   * Get overall compliance status across frameworks.
   *
   * Returns compliance status for SOC 2, GDPR, HIPAA (if applicable),
   * and an overall assessment.
   */
  async getStatus(): Promise<ComplianceStatus> {
    return this.client.request('GET', '/api/v2/compliance/status');
  }

  // ===========================================================================
  // SOC 2 Compliance
  // ===========================================================================

  /**
   * Generate SOC 2 compliance summary report.
   *
   * @param options - Report generation options
   * @param options.startDate - Report period start (ISO date)
   * @param options.endDate - Report period end (ISO date)
   * @param options.controls - Specific controls to include (default: all)
   */
  async generateSoc2Report(options?: {
    startDate?: string;
    endDate?: string;
    controls?: string[];
  }): Promise<Soc2Report> {
    const params: Record<string, unknown> = {};
    if (options?.startDate) {
      params.start_date = options.startDate;
    }
    if (options?.endDate) {
      params.end_date = options.endDate;
    }
    if (options?.controls) {
      params.controls = options.controls.join(',');
    }

    return this.client.request('GET', '/api/v2/compliance/soc2-report', { params });
  }

  // ===========================================================================
  // GDPR Compliance
  // ===========================================================================

  /**
   * Export user data for GDPR compliance (Article 15 - Right of Access).
   *
   * Generates a complete export of all personal data held for a user,
   * including debate participation, preferences, and activity logs.
   *
   * @param userId - ID of the user whose data to export
   * @param format - Export format (json for programmatic use, csv for spreadsheets)
   * @returns Export result with data and download expiration
   *
   * @example
   * ```typescript
   * // Export user data as JSON
   * const result = await client.compliance.gdprExport('user-123', 'json');
   * console.log(`Export ID: ${result.export_id}`);
   * console.log(`Data categories: ${Object.keys(result.data).join(', ')}`);
   * console.log(`Expires: ${result.expires_at}`);
   *
   * // Export as CSV for user to download
   * const csvExport = await client.compliance.gdprExport('user-123', 'csv');
   * ```
   */
  async gdprExport(userId: string, format: 'json' | 'csv' = 'json'): Promise<GdprExportResult> {
    return this.client.request('GET', '/api/v2/compliance/gdpr-export', {
      params: { user_id: userId, format },
    });
  }

  /**
   * Execute GDPR right to erasure (Article 17 - Right to be Forgotten).
   *
   * Initiates deletion of all personal data for a user. Some data may be
   * retained for legal compliance (e.g., audit logs, financial records).
   *
   * @param userId - ID of the user to erase
   * @param options - Deletion options
   * @param options.confirm - Must be true to confirm deletion (default: true)
   * @param options.reason - Reason for deletion request (recommended for audit)
   * @returns Deletion result with status and list of deleted/retained data
   *
   * @remarks
   * - This operation is irreversible
   * - Some data may be retained for legal compliance (listed in `data_retained`)
   * - The deletion may be processed asynchronously for large datasets
   *
   * @example
   * ```typescript
   * const result = await client.compliance.gdprRightToBeForgotten('user-123', {
   *   confirm: true,
   *   reason: 'User requested account deletion via support ticket #456',
   * });
   *
   * if (result.status === 'completed') {
   *   console.log(`Deleted: ${result.data_deleted.join(', ')}`);
   *   if (result.data_retained.length > 0) {
   *     console.log(`Retained for compliance: ${result.data_retained.join(', ')}`);
   *     console.log(`Reason: ${result.retention_reason}`);
   *   }
   * }
   * ```
   */
  async gdprRightToBeForgotten(
    userId: string,
    options?: {
      confirm?: boolean;
      reason?: string;
    }
  ): Promise<GdprDeletionResult> {
    const data: Record<string, unknown> = {
      user_id: userId,
      confirm: options?.confirm ?? true,
    };
    if (options?.reason) {
      data.reason = options.reason;
    }

    return this.client.request('POST', '/api/v2/compliance/gdpr/right-to-be-forgotten', {
      json: data,
    });
  }

  // ===========================================================================
  // Audit Trail
  // ===========================================================================

  /**
   * Verify audit trail integrity.
   *
   * Checks for gaps, tampering, sequence errors, and timestamp anomalies
   * in the audit log.
   *
   * @param options - Verification options
   * @param options.startDate - Verification period start (ISO date)
   * @param options.endDate - Verification period end (ISO date)
   */
  async verifyAuditTrail(options?: {
    startDate?: string;
    endDate?: string;
  }): Promise<AuditVerificationResult> {
    const data: Record<string, unknown> = {};
    if (options?.startDate) {
      data.start_date = options.startDate;
    }
    if (options?.endDate) {
      data.end_date = options.endDate;
    }

    return this.client.request('POST', '/api/v2/compliance/audit-verify', { json: data });
  }

  /**
   * Export audit events for SIEM integration.
   *
   * @param startDate - Export period start (ISO date)
   * @param endDate - Export period end (ISO date)
   * @param options - Export options
   * @param options.eventTypes - Filter by event types
   * @param options.format - Export format (json, elasticsearch)
   * @param options.limit - Maximum events to export
   */
  async exportAuditEvents(
    startDate: string,
    endDate: string,
    options?: {
      eventTypes?: AuditEventType[];
      format?: 'json' | 'elasticsearch';
      limit?: number;
    }
  ): Promise<AuditEventsExport> {
    const params: Record<string, unknown> = {
      start_date: startDate,
      end_date: endDate,
      format: options?.format ?? 'json',
      limit: options?.limit ?? 1000,
    };
    if (options?.eventTypes) {
      params.event_types = options.eventTypes.join(',');
    }

    return this.client.request('GET', '/api/v2/compliance/audit-events', { params });
  }

  /**
   * Run a compliance check against current configuration.
   *
   * @param params - Check parameters (scope, frameworks, etc.)
   * @returns Compliance check results with pass/fail per framework
   */
  async check(params?: Record<string, unknown>): Promise<Record<string, unknown>> {
    return this.client.request('GET', '/api/v1/compliance/check', { params });
  }

  /**
   * Get compliance statistics (violation counts, trends, scores).
   *
   * @returns Statistics across all compliance frameworks
   */
  async getStats(): Promise<Record<string, unknown>> {
    return this.client.request('GET', '/api/v1/compliance/stats');
  }

  /**
   * List compliance violations.
   *
   * @param options - Pagination options
   * @returns List of compliance violations
   */
  async listViolations(options?: {
    limit?: number;
    offset?: number;
  }): Promise<Record<string, unknown>> {
    return this.client.request('GET', '/api/v1/compliance/violations', {
      params: {
        limit: options?.limit ?? 50,
        offset: options?.offset ?? 0,
      },
    });
  }

  /**
   * Get compliance violation details.
   *
   * @param violationId - Violation identifier
   * @returns Violation details
   */
  async getViolation(violationId: string): Promise<Record<string, unknown>> {
    return this.client.request('GET', `/api/v1/compliance/violations/${encodeURIComponent(violationId)}`);
  }

  /**
   * Update a compliance violation (status, assignment, remediation).
   *
   * @param violationId - Violation identifier
   * @param updates - Fields to update
   * @returns Updated violation details
   */
  async updateViolation(
    violationId: string,
    updates: {
      status?: string;
      assignedTo?: string;
      remediationNotes?: string;
      dueDate?: string;
    }
  ): Promise<Record<string, unknown>> {
    const body: Record<string, unknown> = {};
    if (updates.status) body.status = updates.status;
    if (updates.assignedTo) body.assigned_to = updates.assignedTo;
    if (updates.remediationNotes) body.remediation_notes = updates.remediationNotes;
    if (updates.dueDate) body.due_date = updates.dueDate;
    return this.client.request('PUT', `/api/v1/compliance/violations/${encodeURIComponent(violationId)}`, {
      json: body,
    });
  }

  // ===========================================================================
  // EU AI Act
  // ===========================================================================

  /**
   * Classify an AI use case by EU AI Act risk level.
   *
   * @param description - Free-text description of the AI use case.
   * @returns Risk classification with level, rationale, and obligations.
   *
   * @example
   * ```typescript
   * const result = await client.compliance.euAiActClassify(
   *   'AI system for employment screening and hiring decisions'
   * );
   * console.log(`Risk: ${result.classification.risk_level}`);
   * console.log(`Obligations: ${result.classification.obligations.join(', ')}`);
   * ```
   */
  async euAiActClassify(description: string): Promise<{ classification: EuAiActRiskClassification }> {
    return this.client.request('POST', '/api/v2/compliance/eu-ai-act/classify', {
      json: { description },
    });
  }

  /**
   * Generate a conformity report from a decision receipt.
   *
   * @param receipt - Decision receipt data.
   * @returns Conformity report with article-by-article assessment.
   */
  async euAiActAudit(receipt: Record<string, unknown>): Promise<{ conformity_report: EuAiActConformityReport }> {
    return this.client.request('POST', '/api/v2/compliance/eu-ai-act/audit', {
      json: { receipt },
    });
  }

  /**
   * Generate a full EU AI Act compliance artifact bundle.
   *
   * Produces Articles 12 (Record-Keeping), 13 (Transparency), and
   * 14 (Human Oversight) artifacts bundled with a conformity report
   * and SHA-256 integrity hash.
   *
   * @param options - Bundle generation options including receipt and provider details.
   * @returns Complete artifact bundle.
   *
   * @example
   * ```typescript
   * const result = await client.compliance.euAiActGenerateBundle({
   *   receipt: myDecisionReceipt,
   *   providerName: 'Acme Corp',
   *   systemName: 'Acme Decision Engine',
   * });
   * console.log(`Bundle: ${result.bundle.bundle_id}`);
   * console.log(`Hash: ${result.bundle.integrity_hash}`);
   * ```
   */
  async euAiActGenerateBundle(
    options: EuAiActBundleOptions
  ): Promise<{ bundle: EuAiActArtifactBundle }> {
    const body: Record<string, unknown> = { receipt: options.receipt };
    if (options.providerName) body.provider_name = options.providerName;
    if (options.providerContact) body.provider_contact = options.providerContact;
    if (options.euRepresentative) body.eu_representative = options.euRepresentative;
    if (options.systemName) body.system_name = options.systemName;
    if (options.systemVersion) body.system_version = options.systemVersion;

    return this.client.request('POST', '/api/v2/compliance/eu-ai-act/generate-bundle', {
      json: body,
    });
  }

  // ===========================================================================
  // HIPAA Compliance
  // ===========================================================================

  /**
   * Get HIPAA compliance status overview.
   *
   * @param options - Status options
   * @param options.scope - 'summary' or 'full' (includes safeguard details)
   * @param options.includeRecommendations - Include compliance recommendations
   *
   * @example
   * ```typescript
   * const status = await client.compliance.hipaaStatus();
   * console.log(`Score: ${status.compliance_score}%`);
   * console.log(`Status: ${status.overall_status}`);
   * ```
   */
  async hipaaStatus(options?: {
    scope?: 'summary' | 'full';
    includeRecommendations?: boolean;
  }): Promise<HipaaComplianceStatus> {
    return this.client.request('GET', '/api/v2/compliance/hipaa/status', {
      params: {
        scope: options?.scope ?? 'summary',
        include_recommendations: String(options?.includeRecommendations ?? true),
      },
    });
  }

  /**
   * Get PHI access log for audit purposes (45 CFR 164.312(b)).
   *
   * @param options - Filter options
   * @param options.patientId - Filter by patient ID
   * @param options.userId - Filter by accessing user
   * @param options.from - Start date (ISO format)
   * @param options.to - End date (ISO format)
   * @param options.limit - Max results (default 100, max 1000)
   */
  async hipaaPhiAccessLog(options?: {
    patientId?: string;
    userId?: string;
    from?: string;
    to?: string;
    limit?: number;
  }): Promise<Record<string, unknown>> {
    const params: Record<string, unknown> = { limit: options?.limit ?? 100 };
    if (options?.patientId) params.patient_id = options.patientId;
    if (options?.userId) params.user_id = options.userId;
    if (options?.from) params.from = options.from;
    if (options?.to) params.to = options.to;
    return this.client.request('GET', '/api/v2/compliance/hipaa/phi-access', { params });
  }

  /**
   * Perform HIPAA breach risk assessment (45 CFR 164.402).
   *
   * Four-factor analysis to determine if an incident constitutes a breach
   * requiring notification.
   *
   * @param incidentId - Unique incident identifier
   * @param incidentType - Type of security incident
   * @param options - Assessment details
   */
  async hipaaBreachAssessment(
    incidentId: string,
    incidentType: string,
    options?: {
      phiInvolved?: boolean;
      phiTypes?: string[];
      affectedIndividuals?: number;
      unauthorizedAccess?: Record<string, unknown>;
      mitigationActions?: string[];
    }
  ): Promise<HipaaBreachAssessment> {
    const body: Record<string, unknown> = {
      incident_id: incidentId,
      incident_type: incidentType,
      phi_involved: options?.phiInvolved ?? false,
      affected_individuals: options?.affectedIndividuals ?? 0,
    };
    if (options?.phiTypes) body.phi_types = options.phiTypes;
    if (options?.unauthorizedAccess) body.unauthorized_access = options.unauthorizedAccess;
    if (options?.mitigationActions) body.mitigation_actions = options.mitigationActions;
    return this.client.request('POST', '/api/v2/compliance/hipaa/breach-assessment', { json: body });
  }

  /**
   * List Business Associate Agreements (BAAs).
   *
   * @param options - Filter options
   * @param options.status - Filter by status (active, expired, pending, all)
   * @param options.baType - Filter by BA type (vendor, subcontractor, all)
   */
  async hipaaListBaas(options?: {
    status?: string;
    baType?: string;
  }): Promise<{ business_associates: HipaaBaa[]; count: number }> {
    return this.client.request('GET', '/api/v2/compliance/hipaa/baa', {
      params: {
        status: options?.status ?? 'active',
        ba_type: options?.baType ?? 'all',
      },
    });
  }

  /**
   * Register a new Business Associate Agreement.
   *
   * @param businessAssociate - Name of the business associate
   * @param baType - 'vendor' or 'subcontractor'
   * @param servicesProvided - Description of services
   * @param options - Optional BAA details
   */
  async hipaaCreateBaa(
    businessAssociate: string,
    baType: 'vendor' | 'subcontractor',
    servicesProvided: string,
    options?: {
      phiAccessScope?: string[];
      agreementDate?: string;
      expirationDate?: string;
      subcontractorClause?: boolean;
    }
  ): Promise<{ message: string; baa: HipaaBaa }> {
    const body: Record<string, unknown> = {
      business_associate: businessAssociate,
      ba_type: baType,
      services_provided: servicesProvided,
      subcontractor_clause: options?.subcontractorClause ?? true,
    };
    if (options?.phiAccessScope) body.phi_access_scope = options.phiAccessScope;
    if (options?.agreementDate) body.agreement_date = options.agreementDate;
    if (options?.expirationDate) body.expiration_date = options.expirationDate;
    return this.client.request('POST', '/api/v2/compliance/hipaa/baa', { json: body });
  }

  /**
   * Generate HIPAA Security Rule compliance report.
   *
   * @param options - Report options
   * @param options.format - Output format ('json' or 'html')
   * @param options.includeEvidence - Include evidence references
   */
  async hipaaSecurityReport(options?: {
    format?: 'json' | 'html';
    includeEvidence?: boolean;
  }): Promise<Record<string, unknown>> {
    return this.client.request('GET', '/api/v2/compliance/hipaa/security-report', {
      params: {
        format: options?.format ?? 'json',
        include_evidence: String(options?.includeEvidence ?? false),
      },
    });
  }

  /**
   * De-identify content using HIPAA Safe Harbor method.
   *
   * Removes the 18 HIPAA identifiers from text or structured data.
   *
   * @param options - De-identification options
   * @param options.content - Text content to de-identify
   * @param options.data - Structured data to de-identify (alternative to content)
   * @param options.method - Anonymization method (default: 'redact')
   * @param options.identifierTypes - Specific identifier types to target
   *
   * @example
   * ```typescript
   * const result = await client.compliance.hipaaDeidentify({
   *   content: 'Patient John Smith, SSN 123-45-6789',
   *   method: 'redact',
   * });
   * console.log(result.anonymized_content); // "Patient [NAME], SSN [SSN]"
   * ```
   */
  async hipaaDeidentify(options: {
    content?: string;
    data?: Record<string, unknown>;
    method?: HipaaAnonymizationMethod;
    identifierTypes?: string[];
  }): Promise<HipaaDeidentifyResult> {
    const body: Record<string, unknown> = { method: options.method ?? 'redact' };
    if (options.content) body.content = options.content;
    if (options.data) body.data = options.data;
    if (options.identifierTypes) body.identifier_types = options.identifierTypes;
    return this.client.request('POST', '/api/v2/compliance/hipaa/deidentify', { json: body });
  }

  /**
   * Verify content meets HIPAA Safe Harbor de-identification requirements.
   *
   * Checks content for the 18 HIPAA identifiers and reports compliance.
   *
   * @param content - Text content to verify
   *
   * @example
   * ```typescript
   * const result = await client.compliance.hipaaSafeHarborVerify('Patient data here');
   * if (!result.compliant) {
   *   console.log(`Found ${result.identifiers_remaining.length} identifiers`);
   * }
   * ```
   */
  async hipaaSafeHarborVerify(content: string): Promise<HipaaSafeHarborResult> {
    return this.client.request('POST', '/api/v2/compliance/hipaa/safe-harbor/verify', {
      json: { content },
    });
  }

  /**
   * Detect HIPAA PHI identifiers in content.
   *
   * Scans content and returns all detected identifiers with positions
   * and confidence scores without modifying the content.
   *
   * @param content - Text content to scan
   * @param options - Detection options
   * @param options.minConfidence - Minimum confidence threshold (default: 0.5)
   */
  async hipaaDetectPhi(
    content: string,
    options?: { minConfidence?: number }
  ): Promise<HipaaPhiDetectionResult> {
    return this.client.request('POST', '/api/v2/compliance/hipaa/detect-phi', {
      json: { content, min_confidence: options?.minConfidence ?? 0.5 },
    });
  }

  /** Get compliance overview. */
  async getComplianceOverview(): Promise<Record<string, unknown>> {
    return this.client.request('GET', '/api/v1/compliance');
  }

  /** Get RBAC coverage report for compliance. */
  async getRbacCoverage(): Promise<Record<string, unknown>> {
    return this.client.request('GET', '/api/v1/compliance/rbac-coverage');
  }
}
