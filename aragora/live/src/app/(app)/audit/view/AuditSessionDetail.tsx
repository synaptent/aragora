'use client';

/**
 * Audit Session Detail Client Component
 *
 * Real-time view of an active or completed audit session:
 * - Live findings stream via SSE
 * - Severity distribution visualization
 * - Progress by document
 * - Agent activity timeline
 * - Human intervention controls
 * - Report export functionality
 */

import { useState, useEffect, useCallback, useRef } from 'react';
import { useSearchParams, useRouter } from 'next/navigation';
import Link from 'next/link';
import { Scanlines, CRTVignette } from '@/components/MatrixRain';
import { AsciiBannerCompact } from '@/components/AsciiBanner';
import { ThemeToggle } from '@/components/ThemeToggle';
import { BackendSelector, useBackend } from '@/components/BackendSelector';
import { PanelErrorBoundary } from '@/components/PanelErrorBoundary';
import { useAuth } from '@/context/AuthContext';

interface AuditSession {
  id: string;
  name: string;
  status: 'pending' | 'running' | 'paused' | 'completed' | 'failed' | 'cancelled';
  document_ids: string[];
  audit_types: string[];
  model: string;
  progress: number;
  current_phase?: string;
  findings_count: number;
  findings_by_severity: Record<string, number>;
  created_at: string;
  started_at?: string;
  completed_at?: string;
  duration_seconds?: number;
}

interface AuditFinding {
  id: string;
  document_id: string;
  document_name?: string;
  chunk_id?: string;
  category: string;
  severity: 'critical' | 'high' | 'medium' | 'low' | 'info';
  confidence: number;
  title: string;
  description: string;
  evidence_text: string;
  evidence_location: string;
  found_by: string;
  confirmed_by: string[];
  disputed_by: string[];
  status: string;
  created_at: string;
}

interface AgentActivity {
  agent: string;
  action: string;
  timestamp: string;
  document_id?: string;
}

type TabId = 'findings' | 'documents' | 'activity' | 'export';

const SEVERITY_COLORS: Record<string, string> = {
  critical: 'bg-acid-red/20 text-acid-red border-acid-red/40',
  high: 'bg-acid-orange/20 text-acid-orange border-acid-orange/40',
  medium: 'bg-acid-yellow/20 text-[var(--acid-yellow)] border-acid-yellow/40',
  low: 'bg-acid-blue/20 text-acid-blue border-acid-blue/40',
  info: 'bg-muted/20 text-muted border-muted/40',
};

const SEVERITY_ORDER = ['critical', 'high', 'medium', 'low', 'info'];

function StatusBadge({ status }: { status: string }) {
  const colors: Record<string, string> = {
    completed: 'bg-[var(--accent)]/20 text-[var(--accent)] border-[var(--accent)]/40',
    running:
      'bg-[var(--acid-cyan)]/20 text-[var(--acid-cyan)] border-[var(--acid-cyan)]/40 animate-pulse',
    pending: 'bg-acid-blue/20 text-acid-blue border-acid-blue/40',
    paused: 'bg-acid-purple/20 text-acid-purple border-acid-purple/40',
    failed: 'bg-acid-red/20 text-acid-red border-acid-red/40',
    cancelled: 'bg-muted/20 text-muted border-muted/40',
  };
  return (
    <span
      className={`px-2 py-0.5 text-xs font-theme-data rounded border ${colors[status] || colors.pending}`}
    >
      {status.toUpperCase()}
    </span>
  );
}

function SeverityBadge({ severity }: { severity: string }) {
  return (
    <span
      className={`px-2 py-0.5 text-xs font-theme-data rounded border ${SEVERITY_COLORS[severity] || SEVERITY_COLORS.info}`}
    >
      {severity.toUpperCase()}
    </span>
  );
}

function formatDuration(seconds?: number): string {
  if (!seconds) return '-';
  if (seconds < 60) return `${Math.round(seconds)}s`;
  if (seconds < 3600) return `${Math.round(seconds / 60)}m ${Math.round(seconds % 60)}s`;
  return `${Math.floor(seconds / 3600)}h ${Math.round((seconds % 3600) / 60)}m`;
}

function formatDate(dateStr?: string): string {
  if (!dateStr) return '-';
  return new Date(dateStr).toLocaleString('en-US', {
    month: 'short',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  });
}

export default function AuditSessionDetail() {
  const searchParams = useSearchParams();
  const router = useRouter();
  // Get session ID from query params: /audit/view?id=xxx
  const sessionId = searchParams.get('id');
  const { config: backendConfig } = useBackend();
  const { tokens } = useAuth();

  const [session, setSession] = useState<AuditSession | null>(null);
  const [findings, setFindings] = useState<AuditFinding[]>([]);
  const [activities, setActivities] = useState<AgentActivity[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [activeTab, setActiveTab] = useState<TabId>('findings');
  const [severityFilter, setSeverityFilter] = useState<string>('all');
  const [categoryFilter, setCategoryFilter] = useState<string>('all');
  const [exportFormat, setExportFormat] = useState<string>('json');
  const [exporting, setExporting] = useState(false);

  const eventSourceRef = useRef<EventSource | null>(null);
  const findingsEndRef = useRef<HTMLDivElement>(null);

  // Fetch session details
  const fetchSession = useCallback(async () => {
    try {
      const response = await fetch(`${backendConfig.api}/api/audit/sessions/${sessionId}`, {
        headers: { Authorization: `Bearer ${tokens?.access_token || ''}` },
      });
      if (!response.ok) throw new Error('Session not found');
      const data = await response.json();
      setSession(data);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to fetch session');
    } finally {
      setLoading(false);
    }
  }, [backendConfig.api, sessionId, tokens?.access_token]);

  // Fetch findings
  const fetchFindings = useCallback(async () => {
    try {
      const response = await fetch(
        `${backendConfig.api}/api/audit/sessions/${sessionId}/findings`,
        { headers: { Authorization: `Bearer ${tokens?.access_token || ''}` } },
      );
      if (response.ok) {
        const data = await response.json();
        setFindings(data.findings || []);
      }
    } catch {
      // Silent fail, SSE will provide updates
    }
  }, [backendConfig.api, sessionId, tokens?.access_token]);

  // Connect to SSE for live updates
  useEffect(() => {
    if (!session || session.status !== 'running') return;

    const eventSource = new EventSource(
      `${backendConfig.api}/api/audit/sessions/${sessionId}/events`,
    );
    eventSourceRef.current = eventSource;

    eventSource.onmessage = (event) => {
      const data = JSON.parse(event.data);

      switch (data.type) {
        case 'finding':
          setFindings((prev) => [data.finding, ...prev]);
          // Auto-scroll to new finding
          findingsEndRef.current?.scrollIntoView({ behavior: 'smooth' });
          break;
        case 'progress':
          setSession((prev) =>
            prev ? { ...prev, progress: data.progress, current_phase: data.phase } : prev,
          );
          break;
        case 'activity':
          setActivities((prev) => [data.activity, ...prev].slice(0, 100));
          break;
        case 'complete':
          setSession((prev) =>
            prev ? { ...prev, status: 'completed', completed_at: new Date().toISOString() } : prev,
          );
          eventSource.close();
          break;
        case 'error':
          setSession((prev) => (prev ? { ...prev, status: 'failed' } : prev));
          setError(data.message);
          eventSource.close();
          break;
      }
    };

    eventSource.onerror = () => {
      // Reconnect on error
      eventSource.close();
    };

    return () => {
      eventSource.close();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps -- only re-subscribe when status changes, not entire session
  }, [session?.status, backendConfig.api, sessionId]);

  // Initial fetch
  useEffect(() => {
    fetchSession();
    fetchFindings();

    // Poll for updates if not using SSE
    const interval = setInterval(fetchSession, 5000);
    return () => clearInterval(interval);
  }, [fetchSession, fetchFindings]);

  // Session controls
  const handlePause = async () => {
    await fetch(`${backendConfig.api}/api/audit/sessions/${sessionId}/pause`, {
      method: 'POST',
      headers: { Authorization: `Bearer ${tokens?.access_token || ''}` },
    });
    fetchSession();
  };

  const handleResume = async () => {
    await fetch(`${backendConfig.api}/api/audit/sessions/${sessionId}/resume`, {
      method: 'POST',
      headers: { Authorization: `Bearer ${tokens?.access_token || ''}` },
    });
    fetchSession();
  };

  const handleCancel = async () => {
    if (confirm('Are you sure you want to cancel this audit?')) {
      await fetch(`${backendConfig.api}/api/audit/sessions/${sessionId}`, {
        method: 'DELETE',
        headers: { Authorization: `Bearer ${tokens?.access_token || ''}` },
      });
      router.push('/audit');
    }
  };

  // Export report
  const handleExport = async () => {
    setExporting(true);
    try {
      const response = await fetch(
        `${backendConfig.api}/api/audit/sessions/${sessionId}/report?format=${exportFormat}`,
        { headers: { Authorization: `Bearer ${tokens?.access_token || ''}` } },
      );
      if (!response.ok) throw new Error('Export failed');

      const blob = await response.blob();
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = `audit-report-${sessionId}.${exportFormat}`;
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      URL.revokeObjectURL(url);
    } catch {
      setError('Failed to export report');
    } finally {
      setExporting(false);
    }
  };

  // Filter findings
  const filteredFindings = findings.filter((f) => {
    if (severityFilter !== 'all' && f.severity !== severityFilter) return false;
    if (categoryFilter !== 'all' && f.category !== categoryFilter) return false;
    return true;
  });

  // Get unique categories
  const categories = [...new Set(findings.map((f) => f.category))];

  // Severity distribution for chart
  const severityDistribution = SEVERITY_ORDER.map((sev) => ({
    severity: sev,
    count: findings.filter((f) => f.severity === sev).length,
  }));

  const tabs = [
    { id: 'findings' as TabId, label: 'FINDINGS', count: findings.length },
    { id: 'documents' as TabId, label: 'DOCUMENTS', count: session?.document_ids.length || 0 },
    { id: 'activity' as TabId, label: 'ACTIVITY' },
    { id: 'export' as TabId, label: 'EXPORT' },
  ];

  if (loading) {
    return (
      <div className="min-h-screen bg-background flex items-center justify-center">
        <div className="text-muted font-theme-data animate-pulse">LOADING SESSION...</div>
      </div>
    );
  }

  // If no session ID provided (direct access to /audit), show error
  if (!sessionId) {
    return (
      <div className="min-h-screen bg-background flex items-center justify-center">
        <div className="text-center">
          <div className="text-muted font-theme-data mb-4">No session ID provided</div>
          <Link href="/audit" className="btn btn-primary">
            Go to Audit Dashboard
          </Link>
        </div>
      </div>
    );
  }

  if (error && !session) {
    return (
      <div className="min-h-screen bg-background flex items-center justify-center">
        <div className="text-center">
          <div className="text-acid-red font-theme-data mb-4">{error}</div>
          <Link href="/audit" className="btn btn-primary">
            Back to Dashboard
          </Link>
        </div>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-background">
      <Scanlines />
      <CRTVignette />

      <header className="border-b border-border bg-surface/50 backdrop-blur-sm sticky top-0 z-40">
        <div className="container mx-auto px-4 py-3 flex items-center justify-between">
          <div className="flex items-center gap-4">
            <Link href="/" className="hover:text-accent">
              <AsciiBannerCompact />
            </Link>
            <span className="text-muted font-theme-data text-sm">{'//'} AUDIT SESSION</span>
          </div>
          <div className="flex items-center gap-3">
            <BackendSelector />
            <ThemeToggle />
          </div>
        </div>
      </header>

      <main className="container mx-auto px-4 py-6">
        {/* Session Header */}
        <div className="card p-4 mb-6">
          <div className="flex items-start justify-between mb-4">
            <div>
              <div className="flex items-center gap-3 mb-2">
                <h1 className="text-xl font-theme-data">
                  {session?.name || sessionId?.slice(0, 8) || 'New Session'}
                </h1>
                {session && <StatusBadge status={session.status} />}
              </div>
              <div className="text-sm text-muted font-theme-data">
                {session?.document_ids.length} documents | Model: {session?.model} | Started:{' '}
                {formatDate(session?.started_at)}
              </div>
            </div>
            <div className="flex items-center gap-2">
              {session?.status === 'running' && (
                <button onClick={handlePause} className="btn btn-sm btn-ghost">
                  Pause
                </button>
              )}
              {session?.status === 'paused' && (
                <button onClick={handleResume} className="btn btn-sm btn-ghost">
                  Resume
                </button>
              )}
              {['pending', 'running', 'paused'].includes(session?.status || '') && (
                <button onClick={handleCancel} className="btn btn-sm btn-ghost text-acid-red">
                  Cancel
                </button>
              )}
              <Link href="/audit" className="btn btn-sm btn-ghost">
                Back
              </Link>
            </div>
          </div>

          {/* Progress Bar */}
          {session && ['running', 'paused'].includes(session.status) && (
            <div className="mb-4">
              <div className="flex items-center justify-between text-xs font-theme-data text-muted mb-1">
                <span>{session.current_phase || 'Processing'}</span>
                <span>{Math.round(session.progress * 100)}%</span>
              </div>
              <div className="w-full bg-surface rounded-full h-2">
                <div
                  className={`h-2 rounded-full transition-all ${
                    session.status === 'paused' ? 'bg-acid-yellow' : 'bg-accent'
                  }`}
                  style={{ width: `${session.progress * 100}%` }}
                />
              </div>
            </div>
          )}

          {/* Severity Summary */}
          <div className="flex items-center gap-4">
            {severityDistribution.map(({ severity, count }) =>
              count > 0 ? (
                <div key={severity} className="flex items-center gap-2">
                  <span
                    className={`px-2 py-0.5 rounded text-xs font-theme-data ${SEVERITY_COLORS[severity]}`}
                  >
                    {count}
                  </span>
                  <span className="text-xs text-muted capitalize">{severity}</span>
                </div>
              ) : null,
            )}
            {session?.duration_seconds && (
              <div className="ml-auto text-xs font-theme-data text-muted">
                Duration: {formatDuration(session.duration_seconds)}
              </div>
            )}
          </div>
        </div>

        {/* Tabs */}
        <div className="border-b border-border mb-6">
          <div className="flex gap-4 overflow-x-auto">
            {tabs.map((tab) => (
              <button
                key={tab.id}
                onClick={() => setActiveTab(tab.id)}
                className={`px-4 py-2 font-theme-data text-sm transition-colors flex items-center gap-2 ${
                  activeTab === tab.id
                    ? 'text-accent border-b-2 border-accent'
                    : 'text-muted hover:text-foreground'
                }`}
              >
                {tab.label}
                {tab.count !== undefined && (
                  <span className="px-1.5 py-0.5 bg-surface rounded text-xs">{tab.count}</span>
                )}
              </button>
            ))}
          </div>
        </div>

        <PanelErrorBoundary panelName="Session Content">
          {/* Findings Tab */}
          {activeTab === 'findings' && (
            <div>
              {/* Filters */}
              <div className="flex items-center gap-4 mb-4">
                <select
                  value={severityFilter}
                  onChange={(e) => setSeverityFilter(e.target.value)}
                  className="input"
                >
                  <option value="all">All Severities</option>
                  {SEVERITY_ORDER.map((sev) => (
                    <option key={sev} value={sev}>
                      {sev.charAt(0).toUpperCase() + sev.slice(1)}
                    </option>
                  ))}
                </select>
                <select
                  value={categoryFilter}
                  onChange={(e) => setCategoryFilter(e.target.value)}
                  className="input"
                >
                  <option value="all">All Categories</option>
                  {categories.map((cat) => (
                    <option key={cat} value={cat}>
                      {cat.charAt(0).toUpperCase() + cat.slice(1)}
                    </option>
                  ))}
                </select>
                <span className="text-sm text-muted font-theme-data ml-auto">
                  {filteredFindings.length} findings
                </span>
              </div>

              {/* Findings List */}
              <div className="space-y-4">
                {filteredFindings.length === 0 ? (
                  <div className="card p-8 text-center">
                    <div className="text-4xl mb-3">🔍</div>
                    <div className="text-muted font-theme-data">
                      {findings.length === 0
                        ? session?.status === 'running'
                          ? 'Scanning for issues...'
                          : 'No findings detected'
                        : 'No findings match filters'}
                    </div>
                  </div>
                ) : (
                  filteredFindings.map((finding) => (
                    <div key={finding.id} className="card p-4">
                      <div className="flex items-start justify-between mb-2">
                        <div className="flex items-center gap-2">
                          <SeverityBadge severity={finding.severity} />
                          <span className="text-xs font-theme-data text-muted px-2 py-0.5 bg-surface rounded">
                            {finding.category}
                          </span>
                        </div>
                        <span className="text-xs font-theme-data text-muted">
                          {Math.round(finding.confidence * 100)}% confidence
                        </span>
                      </div>

                      <h3 className="font-theme-data font-medium mb-2">{finding.title}</h3>
                      <p className="text-sm text-muted mb-3">{finding.description}</p>

                      {finding.evidence_text && (
                        <div className="p-3 bg-surface rounded border-l-2 border-accent mb-3">
                          <div className="text-xs font-theme-data text-muted mb-1">Evidence:</div>
                          <code className="text-sm">{finding.evidence_text}</code>
                          {finding.evidence_location && (
                            <div className="text-xs text-muted mt-1">
                              Location: {finding.evidence_location}
                            </div>
                          )}
                        </div>
                      )}

                      <div className="flex items-center justify-between text-xs font-theme-data text-muted">
                        <div className="flex items-center gap-4">
                          <span>Found by: {finding.found_by}</span>
                          {finding.confirmed_by.length > 0 && (
                            <span className="text-[var(--accent)]">
                              Confirmed: {finding.confirmed_by.join(', ')}
                            </span>
                          )}
                          {finding.disputed_by.length > 0 && (
                            <span className="text-acid-red">
                              Disputed: {finding.disputed_by.join(', ')}
                            </span>
                          )}
                        </div>
                        <span>{formatDate(finding.created_at)}</span>
                      </div>
                    </div>
                  ))
                )}
                <div ref={findingsEndRef} />
              </div>
            </div>
          )}

          {/* Documents Tab */}
          {activeTab === 'documents' && (
            <div className="card">
              <table className="w-full">
                <thead className="bg-surface border-b border-border">
                  <tr>
                    <th className="p-3 text-left font-theme-data text-xs text-muted">DOCUMENT</th>
                    <th className="p-3 text-left font-theme-data text-xs text-muted">FINDINGS</th>
                    <th className="p-3 text-left font-theme-data text-xs text-muted">STATUS</th>
                  </tr>
                </thead>
                <tbody>
                  {session?.document_ids.map((docId) => {
                    const docFindings = findings.filter((f) => f.document_id === docId);
                    const criticalCount = docFindings.filter(
                      (f) => f.severity === 'critical',
                    ).length;
                    const highCount = docFindings.filter((f) => f.severity === 'high').length;

                    return (
                      <tr key={docId} className="border-b border-border">
                        <td className="p-3 font-theme-data text-sm">{docId.slice(0, 16)}...</td>
                        <td className="p-3">
                          <div className="flex items-center gap-2">
                            <span className="font-theme-data">{docFindings.length}</span>
                            {criticalCount > 0 && (
                              <span className="px-1.5 py-0.5 text-xs rounded bg-acid-red/20 text-acid-red">
                                {criticalCount} critical
                              </span>
                            )}
                            {highCount > 0 && (
                              <span className="px-1.5 py-0.5 text-xs rounded bg-acid-orange/20 text-acid-orange">
                                {highCount} high
                              </span>
                            )}
                          </div>
                        </td>
                        <td className="p-3">
                          <StatusBadge
                            status={session?.status === 'completed' ? 'completed' : 'processing'}
                          />
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          )}

          {/* Activity Tab */}
          {activeTab === 'activity' && (
            <div className="space-y-2">
              {activities.length === 0 ? (
                <div className="card p-8 text-center">
                  <div className="text-muted font-theme-data">No activity recorded yet</div>
                </div>
              ) : (
                activities.map((activity, idx) => (
                  <div key={idx} className="card p-3 flex items-center gap-4">
                    <span className="text-xs font-theme-data text-muted">
                      {formatDate(activity.timestamp)}
                    </span>
                    <span className="text-sm font-theme-data text-accent">{activity.agent}</span>
                    <span className="text-sm">{activity.action}</span>
                  </div>
                ))
              )}
            </div>
          )}

          {/* Export Tab */}
          {activeTab === 'export' && (
            <div className="max-w-xl">
              <div className="card p-6">
                <h3 className="font-theme-data text-lg mb-4">Export Audit Report</h3>

                <div className="mb-6">
                  <label className="block text-sm font-theme-data text-muted mb-2">FORMAT</label>
                  <div className="grid grid-cols-4 gap-2">
                    {['json', 'markdown', 'html', 'csv'].map((format) => (
                      <button
                        key={format}
                        onClick={() => setExportFormat(format)}
                        className={`px-4 py-2 rounded border font-theme-data text-sm transition-colors ${
                          exportFormat === format
                            ? 'border-accent bg-accent/10 text-accent'
                            : 'border-border hover:border-accent/50'
                        }`}
                      >
                        {format.toUpperCase()}
                      </button>
                    ))}
                  </div>
                </div>

                <div className="mb-6 p-4 bg-surface rounded">
                  <div className="text-sm font-theme-data text-muted mb-2">
                    Report will include:
                  </div>
                  <ul className="text-sm space-y-1">
                    <li>Session metadata and configuration</li>
                    <li>{findings.length} findings with evidence</li>
                    <li>Severity distribution summary</li>
                    <li>Agent attribution details</li>
                  </ul>
                </div>

                <button
                  onClick={handleExport}
                  disabled={exporting}
                  className="btn btn-primary w-full"
                >
                  {exporting ? 'EXPORTING...' : `DOWNLOAD ${exportFormat.toUpperCase()} REPORT`}
                </button>
              </div>
            </div>
          )}
        </PanelErrorBoundary>
      </main>

      <footer className="border-t border-border bg-surface/50 py-4 mt-8">
        <div className="container mx-auto px-4 flex items-center justify-between text-xs text-muted font-theme-data">
          <span>ARAGORA AUDIT ENGINE</span>
          <Link href="/audit" className="hover:text-accent">
            DASHBOARD
          </Link>
        </div>
      </footer>
    </div>
  );
}
