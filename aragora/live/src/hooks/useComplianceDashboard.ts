'use client';

import { useSWRFetch, type UseSWRFetchOptions } from './useSWRFetch';

// ============================================================================
// Types - RBAC Coverage
// ============================================================================

export interface RBACCoverage {
  roles_defined: number;
  permissions_defined: number;
  assignments_active: number;
  unprotected_endpoints: number;
  total_endpoints: number;
  coverage_percent: number;
}

// ============================================================================
// Types - Encryption Status
// ============================================================================

export interface EncryptionStatus {
  at_rest: {
    algorithm: string;
    status: 'active' | 'inactive' | 'degraded';
    key_rotation_days: number;
    last_rotation: string | null;
  };
  in_transit: {
    protocol: string;
    status: 'active' | 'inactive' | 'degraded';
    certificate_expiry: string | null;
    min_version: string;
  };
}

// ============================================================================
// Types - Compliance Framework Status
// ============================================================================

export interface FrameworkIndicator {
  name: string;
  status: 'compliant' | 'partial' | 'non_compliant' | 'not_assessed';
  controls_met: number;
  controls_total: number;
  last_assessed: string | null;
  notes?: string;
}

export interface ComplianceFrameworks {
  frameworks: FrameworkIndicator[];
  overall_score: number;
  last_audit: string | null;
  next_audit_due: string | null;
}

// ============================================================================
// Types - Audit Trail Entries
// ============================================================================

export interface AuditEntry {
  id: string;
  timestamp: string;
  event_type: string;
  actor: string;
  resource: string;
  action: string;
  outcome: 'success' | 'failure' | 'denied';
  details?: string;
}

export interface AuditTrailResponse {
  entries: AuditEntry[];
  total: number;
}

// ============================================================================
// Types - Combined Status (from /api/v2/compliance/status)
// ============================================================================

export interface ComplianceStatusResponse {
  status: string;
  compliance_score: number;
  frameworks: {
    soc2_type2: { status: string; controls_assessed: number; controls_compliant: number };
    gdpr: {
      status: string;
      data_export: boolean;
      consent_tracking: boolean;
      retention_policy: boolean;
    };
    hipaa: { status: string; note?: string };
  };
  controls_summary: { total: number; compliant: number; non_compliant: number };
  last_audit: string;
  next_audit_due: string;
  generated_at: string;
}

// ============================================================================
// Mock/Fallback Data
// ============================================================================

const MOCK_RBAC_COVERAGE: RBACCoverage = {
  roles_defined: 7,
  permissions_defined: 52,
  assignments_active: 14,
  unprotected_endpoints: 3,
  total_endpoints: 1847,
  coverage_percent: 99.8,
};

const MOCK_ENCRYPTION_STATUS: EncryptionStatus = {
  at_rest: {
    algorithm: 'AES-256-GCM',
    status: 'active',
    key_rotation_days: 90,
    last_rotation: new Date(Date.now() - 12 * 24 * 60 * 60 * 1000).toISOString(),
  },
  in_transit: {
    protocol: 'TLS 1.3',
    status: 'active',
    certificate_expiry: new Date(Date.now() + 240 * 24 * 60 * 60 * 1000).toISOString(),
    min_version: '1.2',
  },
};

const MOCK_FRAMEWORKS: ComplianceFrameworks = {
  frameworks: [
    {
      name: 'SOC 2 Type II',
      status: 'partial',
      controls_met: 42,
      controls_total: 51,
      last_assessed: new Date(Date.now() - 7 * 24 * 60 * 60 * 1000).toISOString(),
      notes: 'In progress - 82% controls met',
    },
    {
      name: 'GDPR',
      status: 'compliant',
      controls_met: 18,
      controls_total: 18,
      last_assessed: new Date(Date.now() - 14 * 24 * 60 * 60 * 1000).toISOString(),
      notes: 'Data export, consent tracking, retention policy active',
    },
    {
      name: 'EU AI Act',
      status: 'partial',
      controls_met: 4,
      controls_total: 6,
      last_assessed: new Date(Date.now() - 3 * 24 * 60 * 60 * 1000).toISOString(),
      notes: 'Enforcement begins August 2, 2026',
    },
    {
      name: 'HIPAA',
      status: 'partial',
      controls_met: 8,
      controls_total: 12,
      last_assessed: new Date(Date.now() - 21 * 24 * 60 * 60 * 1000).toISOString(),
      notes: 'PHI handling requires additional configuration',
    },
  ],
  overall_score: 87,
  last_audit: new Date(Date.now() - 7 * 24 * 60 * 60 * 1000).toISOString(),
  next_audit_due: new Date(Date.now() + 83 * 24 * 60 * 60 * 1000).toISOString(),
};

const MOCK_AUDIT_ENTRIES: AuditEntry[] = [
  {
    id: 'aud-001',
    timestamp: new Date(Date.now() - 12 * 60 * 1000).toISOString(),
    event_type: 'auth.login',
    actor: 'admin@acme.com',
    resource: '/api/v2/auth/token',
    action: 'POST',
    outcome: 'success',
  },
  {
    id: 'aud-002',
    timestamp: new Date(Date.now() - 34 * 60 * 1000).toISOString(),
    event_type: 'rbac.permission_check',
    actor: 'analyst@acme.com',
    resource: 'compliance:read',
    action: 'CHECK',
    outcome: 'success',
  },
  {
    id: 'aud-003',
    timestamp: new Date(Date.now() - 47 * 60 * 1000).toISOString(),
    event_type: 'compliance.report_generated',
    actor: 'system',
    resource: '/api/v2/compliance/soc2-report',
    action: 'GET',
    outcome: 'success',
  },
  {
    id: 'aud-004',
    timestamp: new Date(Date.now() - 2 * 60 * 60 * 1000).toISOString(),
    event_type: 'auth.login',
    actor: 'unknown@external.com',
    resource: '/api/v2/auth/token',
    action: 'POST',
    outcome: 'denied',
    details: 'Invalid credentials',
  },
  {
    id: 'aud-005',
    timestamp: new Date(Date.now() - 3 * 60 * 60 * 1000).toISOString(),
    event_type: 'security.key_rotation',
    actor: 'system',
    resource: 'encryption.at_rest',
    action: 'ROTATE',
    outcome: 'success',
  },
  {
    id: 'aud-006',
    timestamp: new Date(Date.now() - 5 * 60 * 60 * 1000).toISOString(),
    event_type: 'debate.receipt_generated',
    actor: 'arena-orchestrator',
    resource: 'RCP-2026-0215',
    action: 'CREATE',
    outcome: 'success',
  },
  {
    id: 'aud-007',
    timestamp: new Date(Date.now() - 8 * 60 * 60 * 1000).toISOString(),
    event_type: 'gdpr.data_export',
    actor: 'user@acme.com',
    resource: '/api/v2/compliance/gdpr-export',
    action: 'GET',
    outcome: 'success',
  },
  {
    id: 'aud-008',
    timestamp: new Date(Date.now() - 12 * 60 * 60 * 1000).toISOString(),
    event_type: 'rbac.role_assignment',
    actor: 'admin@acme.com',
    resource: 'analyst@acme.com',
    action: 'ASSIGN',
    outcome: 'success',
    details: 'Assigned role: compliance_viewer',
  },
];

// ============================================================================
// Hooks
// ============================================================================

/**
 * Hook for fetching compliance overview status from the backend.
 * Falls back to mock data when the backend is unavailable.
 */
export function useComplianceStatus(
  options?: UseSWRFetchOptions<{ data: ComplianceStatusResponse }>,
) {
  const result = useSWRFetch<{ data: ComplianceStatusResponse }>('/api/v2/compliance/status', {
    refreshInterval: 120000,
    ...options,
  });

  return { ...result, status: result.data?.data ?? null };
}

/**
 * Hook for RBAC coverage summary.
 * Tries /api/v1/rbac/roles for role count, falls back to mock data.
 */
export function useRBACCoverage(options?: UseSWRFetchOptions<{ data: RBACCoverage }>) {
  const result = useSWRFetch<{ data: RBACCoverage }>('/api/v2/security/rbac-coverage', {
    refreshInterval: 300000,
    ...options,
  });

  return { ...result, rbac: result.data?.data ?? null, rbacFallback: MOCK_RBAC_COVERAGE };
}

/**
 * Hook for encryption status.
 */
export function useEncryptionStatus(options?: UseSWRFetchOptions<{ data: EncryptionStatus }>) {
  const result = useSWRFetch<{ data: EncryptionStatus }>('/api/v2/security/encryption-status', {
    refreshInterval: 300000,
    ...options,
  });

  return {
    ...result,
    encryption: result.data?.data ?? null,
    encryptionFallback: MOCK_ENCRYPTION_STATUS,
  };
}

/**
 * Hook for audit trail entries.
 * Uses the compliance audit-events SIEM endpoint.
 */
export function useAuditTrail(
  limit: number = 10,
  options?: UseSWRFetchOptions<{ data: AuditTrailResponse }>,
) {
  const result = useSWRFetch<{ data: AuditTrailResponse }>(
    `/api/v2/compliance/audit-events?limit=${limit}&format=json`,
    { refreshInterval: 60000, ...options },
  );

  return {
    ...result,
    entries: result.data?.data?.entries ?? null,
    auditFallback: MOCK_AUDIT_ENTRIES.slice(0, limit),
  };
}

/**
 * Helper: build framework indicators from the backend status response,
 * or return mock data if unavailable.
 */
export function buildFrameworkIndicators(
  status: ComplianceStatusResponse | null,
): ComplianceFrameworks {
  if (!status) return MOCK_FRAMEWORKS;

  const fw = status.frameworks;
  const indicators: FrameworkIndicator[] = [
    {
      name: 'SOC 2 Type II',
      status:
        fw.soc2_type2.status === 'in_progress'
          ? 'partial'
          : (fw.soc2_type2.status as FrameworkIndicator['status']),
      controls_met: fw.soc2_type2.controls_compliant,
      controls_total: fw.soc2_type2.controls_assessed,
      last_assessed: status.last_audit,
      notes: `${fw.soc2_type2.controls_compliant}/${fw.soc2_type2.controls_assessed} controls met`,
    },
    {
      name: 'GDPR',
      status:
        fw.gdpr.status === 'supported'
          ? 'compliant'
          : (fw.gdpr.status as FrameworkIndicator['status']),
      controls_met:
        (fw.gdpr.data_export ? 1 : 0) +
        (fw.gdpr.consent_tracking ? 1 : 0) +
        (fw.gdpr.retention_policy ? 1 : 0),
      controls_total: 3,
      last_assessed: status.last_audit,
      notes: [
        fw.gdpr.data_export && 'Data export',
        fw.gdpr.consent_tracking && 'Consent tracking',
        fw.gdpr.retention_policy && 'Retention policy',
      ]
        .filter(Boolean)
        .join(', '),
    },
    {
      name: 'EU AI Act',
      status: 'partial',
      controls_met: 4,
      controls_total: 6,
      last_assessed: status.last_audit,
      notes: 'Enforcement begins August 2, 2026',
    },
    {
      name: 'HIPAA',
      status: fw.hipaa.status as FrameworkIndicator['status'],
      controls_met: fw.hipaa.status === 'partial' ? 8 : 12,
      controls_total: 12,
      last_assessed: status.last_audit,
      notes: fw.hipaa.note,
    },
  ];

  return {
    frameworks: indicators,
    overall_score: status.compliance_score,
    last_audit: status.last_audit,
    next_audit_due: status.next_audit_due,
  };
}

// Re-export mock data for direct use when needed
export { MOCK_RBAC_COVERAGE, MOCK_ENCRYPTION_STATUS, MOCK_FRAMEWORKS, MOCK_AUDIT_ENTRIES };
