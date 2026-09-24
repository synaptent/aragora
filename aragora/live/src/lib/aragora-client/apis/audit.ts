/**
 * Audit API
 *
 * Handles audit session management, findings, and compliance reporting.
 * Supports document audits, deep audits, and real-time event streaming.
 */

import { BaseAPI, HttpClient } from './base';

// =============================================================================
// Types
// =============================================================================

export type AuditSessionStatus =
  'created' | 'running' | 'paused' | 'completed' | 'cancelled' | 'failed';

export type FindingSeverity = 'info' | 'low' | 'medium' | 'high' | 'critical';
export type FindingStatus = 'open' | 'acknowledged' | 'in_progress' | 'resolved' | 'dismissed';
export type FindingCategory = 'security' | 'compliance' | 'quality' | 'performance' | 'other';
export type ReportFormat = 'json' | 'pdf' | 'html' | 'markdown';

export interface AuditSession {
  id: string;
  name: string;
  description?: string;
  status: AuditSessionStatus;
  document_ids: string[];
  config?: AuditConfig;
  progress?: number;
  findings_count?: number;
  created_at: string;
  started_at?: string;
  completed_at?: string;
  created_by?: string;
}

export interface AuditConfig {
  depth?: 'shallow' | 'standard' | 'deep';
  categories?: FindingCategory[];
  agents?: string[];
  max_findings?: number;
  timeout_seconds?: number;
}

export interface CreateSessionRequest {
  name: string;
  description?: string;
  document_ids: string[];
  config?: AuditConfig;
}

export interface Finding {
  id: string;
  session_id: string;
  category: FindingCategory;
  severity: FindingSeverity;
  status: FindingStatus;
  title: string;
  description: string;
  location?: { document_id: string; line?: number; column?: number; path?: string };
  recommendation?: string;
  evidence?: string[];
  metadata?: Record<string, unknown>;
  created_at: string;
  updated_at?: string;
  resolved_at?: string;
  resolved_by?: string;
}

export interface FindingsResponse {
  findings: Finding[];
  total: number;
  by_severity: Record<FindingSeverity, number>;
  by_status: Record<FindingStatus, number>;
}

export interface FindingsListParams {
  severity?: FindingSeverity;
  status?: FindingStatus;
  category?: FindingCategory;
  limit?: number;
  offset?: number;
}

export interface FindingUpdateRequest {
  status?: FindingStatus;
  resolution_notes?: string;
}

export interface AuditEvent {
  type: 'progress' | 'finding' | 'status_change' | 'error' | 'complete';
  session_id: string;
  timestamp: string;
  data: {
    progress?: number;
    finding?: Finding;
    old_status?: AuditSessionStatus;
    new_status?: AuditSessionStatus;
    error?: string;
    summary?: AuditSummary;
  };
}

export interface AuditSummary {
  total_findings: number;
  critical_count: number;
  high_count: number;
  medium_count: number;
  low_count: number;
  info_count: number;
  documents_audited: number;
  duration_seconds: number;
}

export interface InterventionRequest {
  action: 'approve' | 'reject' | 'modify' | 'skip';
  finding_id?: string;
  notes?: string;
  modified_value?: unknown;
}

export interface AuditReport {
  session: AuditSession;
  summary: AuditSummary;
  findings: Finding[];
  recommendations: string[];
  generated_at: string;
}

export interface DeepAuditRequest {
  task: string;
  context?: Record<string, unknown>;
  agents?: string[];
  max_rounds?: number;
}

export interface DeepAuditResponse {
  audit_id: string;
  task: string;
  result: {
    concerns: string[];
    recommendations: string[];
    risk_level: 'low' | 'medium' | 'high' | 'critical';
    confidence: number;
  };
  rounds: number;
  duration_ms: number;
}

export interface SessionListParams {
  status?: AuditSessionStatus;
  limit?: number;
  offset?: number;
}

// =============================================================================
// Audit API Class
// =============================================================================

export class AuditAPI extends BaseAPI {
  constructor(http: HttpClient) {
    super(http);
  }

  // ===========================================================================
  // Session Management
  // ===========================================================================

  /**
   * Create a new audit session
   */
  async createSession(data: CreateSessionRequest): Promise<AuditSession> {
    return this.http.post('/api/v1/audit/sessions', data);
  }

  /**
   * List all audit sessions
   */
  async listSessions(params?: SessionListParams): Promise<AuditSession[]> {
    const searchParams = new URLSearchParams();
    if (params?.status) searchParams.set('status', params.status);
    if (params?.limit) searchParams.set('limit', params.limit.toString());
    if (params?.offset) searchParams.set('offset', params.offset.toString());

    const query = searchParams.toString();
    return this.http.get(`/api/v1/audit/sessions${query ? `?${query}` : ''}`);
  }

  /**
   * Get audit session details
   */
  async getSession(sessionId: string): Promise<AuditSession> {
    return this.http.get(`/api/v1/audit/sessions/${sessionId}`);
  }

  /**
   * Delete an audit session
   */
  async deleteSession(sessionId: string): Promise<void> {
    return this.http.delete(`/api/v1/audit/sessions/${sessionId}`);
  }

  // ===========================================================================
  // Session Lifecycle
  // ===========================================================================

  /**
   * Start an audit session
   */
  async startSession(sessionId: string): Promise<AuditSession> {
    return this.http.post(`/api/v1/audit/sessions/${sessionId}/start`, {});
  }

  /**
   * Pause an audit session
   */
  async pauseSession(sessionId: string): Promise<AuditSession> {
    return this.http.post(`/api/v1/audit/sessions/${sessionId}/pause`, {});
  }

  /**
   * Resume a paused audit session
   */
  async resumeSession(sessionId: string): Promise<AuditSession> {
    return this.http.post(`/api/v1/audit/sessions/${sessionId}/resume`, {});
  }

  /**
   * Cancel an audit session
   */
  async cancelSession(sessionId: string): Promise<AuditSession> {
    return this.http.post(`/api/v1/audit/sessions/${sessionId}/cancel`, {});
  }

  // ===========================================================================
  // Findings
  // ===========================================================================

  /**
   * Get findings for an audit session
   */
  async getFindings(sessionId: string, params?: FindingsListParams): Promise<FindingsResponse> {
    const searchParams = new URLSearchParams();
    if (params?.severity) searchParams.set('severity', params.severity);
    if (params?.status) searchParams.set('status', params.status);
    if (params?.category) searchParams.set('category', params.category);
    if (params?.limit) searchParams.set('limit', params.limit.toString());
    if (params?.offset) searchParams.set('offset', params.offset.toString());

    const query = searchParams.toString();
    return this.http.get(`/api/v1/audit/sessions/${sessionId}/findings${query ? `?${query}` : ''}`);
  }

  /**
   * Update a finding status
   */
  async updateFinding(findingId: string, update: FindingUpdateRequest): Promise<Finding> {
    return this.http.patch(`/api/v1/audit/findings/${findingId}/status`, update);
  }

  // ===========================================================================
  // Intervention & Events
  // ===========================================================================

  /**
   * Submit human intervention for an audit
   */
  async intervene(sessionId: string, intervention: InterventionRequest): Promise<void> {
    return this.http.post(`/api/v1/audit/sessions/${sessionId}/intervene`, intervention);
  }

  /**
   * Get the events endpoint URL for SSE streaming
   * Use this with EventSource for real-time updates
   */
  getEventsUrl(sessionId: string): string {
    return `${this.http.baseUrl}/api/v1/audit/sessions/${sessionId}/events`;
  }

  // ===========================================================================
  // Reports
  // ===========================================================================

  /**
   * Export audit report
   */
  async exportReport(sessionId: string, format: ReportFormat = 'json'): Promise<AuditReport> {
    return this.http.get(`/api/v1/audit/sessions/${sessionId}/report?format=${format}`);
  }

  // ===========================================================================
  // Deep Audit (Multi-Agent)
  // ===========================================================================

  /**
   * Run a deep multi-agent audit on a task/topic
   *
   * This is a heavier analysis using debate-style multi-agent verification
   * to identify concerns and provide recommendations.
   */
  async deepAudit(request: DeepAuditRequest): Promise<DeepAuditResponse> {
    return this.http.post('/api/v1/debates/deep-audit', request);
  }

  // ===========================================================================
  // Convenience Methods
  // ===========================================================================

  /**
   * Create and immediately start an audit session
   */
  async createAndStart(data: CreateSessionRequest): Promise<AuditSession> {
    const session = await this.createSession(data);
    return this.startSession(session.id);
  }

  /**
   * Get all critical findings for a session
   */
  async getCriticalFindings(sessionId: string): Promise<Finding[]> {
    const response = await this.getFindings(sessionId, { severity: 'critical' });
    return response.findings;
  }

  /**
   * Get all open findings for a session
   */
  async getOpenFindings(sessionId: string): Promise<Finding[]> {
    const response = await this.getFindings(sessionId, { status: 'open' });
    return response.findings;
  }
}
