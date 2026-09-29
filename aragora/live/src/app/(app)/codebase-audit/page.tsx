'use client';

/**
 * Codebase Audit Dashboard
 *
 * Comprehensive codebase security and quality analysis:
 * - SAST (Static Application Security Testing)
 * - Bug Detection
 * - Secrets Scanning
 * - Dependency Vulnerabilities
 * - Code Metrics
 */

import { useState, useEffect, useCallback } from 'react';
import { useBackend } from '@/components/BackendSelector';
import { useAuth } from '@/context/AuthContext';
import { PanelErrorBoundary } from '@/components/PanelErrorBoundary';
import { logger } from '@/utils/logger';

// Types matching backend models
type ScanType = 'comprehensive' | 'sast' | 'bugs' | 'secrets' | 'dependencies' | 'metrics';
type ScanStatus = 'pending' | 'running' | 'completed' | 'failed';
type FindingSeverity = 'critical' | 'high' | 'medium' | 'low' | 'info';
type FindingStatus = 'open' | 'acknowledged' | 'fixed' | 'false_positive' | 'wont_fix';

interface Finding {
  id: string;
  scan_id: string;
  scan_type: ScanType;
  severity: FindingSeverity;
  title: string;
  description: string;
  file_path: string;
  line_number?: number;
  column_number?: number;
  code_snippet?: string;
  cwe_id?: string;
  owasp_category?: string;
  fix_suggestion?: string;
  status: FindingStatus;
  dismissed_by?: string;
  dismissed_at?: string;
  dismissal_reason?: string;
  github_issue_url?: string;
  created_at: string;
}

interface ScanResult {
  id: string;
  tenant_id: string;
  scan_type: ScanType;
  status: ScanStatus;
  target_path: string;
  started_at: string;
  completed_at?: string;
  files_scanned: number;
  findings_count: number;
  duration_seconds?: number;
  error_message?: string;
}

interface DashboardSummary {
  total_scans: number;
  total_findings: number;
  open_findings: number;
  findings_by_severity: Record<FindingSeverity, number>;
  findings_by_type: Record<ScanType, number>;
  recent_scans: ScanResult[];
}

interface CodeMetrics {
  total_lines: number;
  total_files: number;
  average_complexity: number;
  maintainability_index: number;
  test_coverage?: number;
  code_duplication?: number;
  hotspots: Array<{ file: string; complexity: number; lines: number }>;
  languages: Record<string, number>;
}

const SEVERITY_CONFIG: Record<FindingSeverity, { color: string; bgColor: string; icon: string }> = {
  critical: { color: 'text-red-400', bgColor: 'bg-red-500/20 border-red-500/40', icon: '!!' },
  high: { color: 'text-orange-400', bgColor: 'bg-orange-500/20 border-orange-500/40', icon: '!' },
  medium: { color: 'text-yellow-400', bgColor: 'bg-yellow-500/20 border-yellow-500/40', icon: '~' },
  low: { color: 'text-blue-400', bgColor: 'bg-blue-500/20 border-blue-500/40', icon: '-' },
  info: { color: 'text-gray-400', bgColor: 'bg-gray-500/20 border-gray-500/40', icon: 'i' },
};

const SCAN_TYPE_LABELS: Record<ScanType, { label: string; description: string }> = {
  comprehensive: { label: 'Comprehensive', description: 'Full security audit' },
  sast: { label: 'SAST', description: 'Static application security testing' },
  bugs: { label: 'Bugs', description: 'Bug detection and code quality' },
  secrets: { label: 'Secrets', description: 'Hardcoded secrets detection' },
  dependencies: { label: 'Dependencies', description: 'Vulnerable dependencies' },
  metrics: { label: 'Metrics', description: 'Code quality metrics' },
};

type TabId = 'dashboard' | 'findings' | 'scans' | 'metrics';

export default function CodebaseAuditPage() {
  const { config: backendConfig } = useBackend();
  const { tokens } = useAuth();
  const [activeTab, setActiveTab] = useState<TabId>('dashboard');
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // Dashboard state
  const [summary, setSummary] = useState<DashboardSummary | null>(null);
  const [metrics, setMetrics] = useState<CodeMetrics | null>(null);

  // Findings state
  const [findings, setFindings] = useState<Finding[]>([]);
  const [findingsFilter, setFindingsFilter] = useState<{
    severity?: FindingSeverity;
    type?: ScanType;
    status?: FindingStatus;
  }>({});

  // Scans state
  const [scans, setScans] = useState<ScanResult[]>([]);

  // New scan state
  const [targetPath, setTargetPath] = useState('.');
  const [selectedScanTypes, setSelectedScanTypes] = useState<ScanType[]>(['sast', 'bugs']);
  const [scanning, setScanning] = useState(false);

  const fetchDashboard = useCallback(async () => {
    try {
      setLoading(true);
      const response = await fetch(`${backendConfig.api}/api/v1/codebase/dashboard`, {
        headers: {
          'Content-Type': 'application/json',
          ...(tokens?.access_token && { Authorization: `Bearer ${tokens.access_token}` }),
        },
      });

      if (!response.ok) throw new Error('Failed to fetch dashboard');
      const data = await response.json();
      setSummary(data.summary || getDemoSummary());
    } catch (err) {
      logger.error('Dashboard fetch error:', err);
      setSummary(getDemoSummary());
    } finally {
      setLoading(false);
    }
  }, [backendConfig.api, tokens?.access_token]);

  const fetchFindings = useCallback(async () => {
    try {
      const params = new URLSearchParams();
      if (findingsFilter.severity) params.set('severity', findingsFilter.severity);
      if (findingsFilter.type) params.set('type', findingsFilter.type);
      if (findingsFilter.status) params.set('status', findingsFilter.status);

      const response = await fetch(
        `${backendConfig.api}/api/v1/codebase/findings?${params.toString()}`,
        {
          headers: {
            'Content-Type': 'application/json',
            ...(tokens?.access_token && { Authorization: `Bearer ${tokens.access_token}` }),
          },
        },
      );

      if (!response.ok) throw new Error('Failed to fetch findings');
      const data = await response.json();
      setFindings(data.findings || getDemoFindings());
    } catch (err) {
      logger.error('Findings fetch error:', err);
      setFindings(getDemoFindings());
    }
  }, [backendConfig.api, tokens?.access_token, findingsFilter]);

  const fetchScans = useCallback(async () => {
    try {
      const response = await fetch(`${backendConfig.api}/api/v1/codebase/scans`, {
        headers: {
          'Content-Type': 'application/json',
          ...(tokens?.access_token && { Authorization: `Bearer ${tokens.access_token}` }),
        },
      });

      if (!response.ok) throw new Error('Failed to fetch scans');
      const data = await response.json();
      setScans(data.scans || []);
    } catch (err) {
      logger.error('Scans fetch error:', err);
      setScans([]);
    }
  }, [backendConfig.api, tokens?.access_token]);

  const fetchMetrics = useCallback(async () => {
    try {
      const response = await fetch(`${backendConfig.api}/api/v1/codebase/metrics`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          ...(tokens?.access_token && { Authorization: `Bearer ${tokens.access_token}` }),
        },
        body: JSON.stringify({ target_path: '.' }),
      });

      if (!response.ok) throw new Error('Failed to fetch metrics');
      const data = await response.json();
      setMetrics(data.metrics || getDemoMetrics());
    } catch (err) {
      logger.error('Metrics fetch error:', err);
      setMetrics(getDemoMetrics());
    }
  }, [backendConfig.api, tokens?.access_token]);

  const startScan = async () => {
    try {
      setScanning(true);
      setError(null);

      const response = await fetch(`${backendConfig.api}/api/v1/codebase/scan`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          ...(tokens?.access_token && { Authorization: `Bearer ${tokens.access_token}` }),
        },
        body: JSON.stringify({ target_path: targetPath, scan_types: selectedScanTypes }),
      });

      if (!response.ok) throw new Error('Failed to start scan');

      // Refresh data after scan
      await Promise.all([fetchDashboard(), fetchScans()]);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Scan failed');
    } finally {
      setScanning(false);
    }
  };

  const dismissFinding = async (findingId: string, reason: string, status: FindingStatus) => {
    try {
      const response = await fetch(
        `${backendConfig.api}/api/v1/codebase/findings/${findingId}/dismiss`,
        {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
            ...(tokens?.access_token && { Authorization: `Bearer ${tokens.access_token}` }),
          },
          body: JSON.stringify({ reason, status }),
        },
      );

      if (!response.ok) throw new Error('Failed to dismiss finding');
      await fetchFindings();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to dismiss finding');
    }
  };

  const createGitHubIssue = async (findingId: string, repo: string) => {
    try {
      const response = await fetch(
        `${backendConfig.api}/api/v1/codebase/findings/${findingId}/create-issue`,
        {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
            ...(tokens?.access_token && { Authorization: `Bearer ${tokens.access_token}` }),
          },
          body: JSON.stringify({ repo }),
        },
      );

      if (!response.ok) throw new Error('Failed to create GitHub issue');
      const data = await response.json();
      await fetchFindings();
      return data.issue_url;
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to create issue');
      return null;
    }
  };

  useEffect(() => {
    fetchDashboard();
  }, [fetchDashboard]);

  useEffect(() => {
    if (activeTab === 'findings') fetchFindings();
    if (activeTab === 'scans') fetchScans();
    if (activeTab === 'metrics') fetchMetrics();
  }, [activeTab, fetchFindings, fetchScans, fetchMetrics]);

  return (
    <div className="container mx-auto px-4 py-6 max-w-6xl">
      {/* Header */}
      <div className="mb-6">
        <h1 className="text-2xl font-theme-data font-bold text-[var(--text)]">Codebase Audit</h1>
        <p className="text-[var(--muted)] text-sm mt-1">
          Security scanning, bug detection, and code quality analysis
        </p>
      </div>

      {/* Tab Navigation */}
      <div className="flex gap-2 mb-6 border-b border-[var(--border)]">
        {(['dashboard', 'findings', 'scans', 'metrics'] as TabId[]).map((tab) => (
          <button
            key={tab}
            onClick={() => setActiveTab(tab)}
            className={`px-4 py-2 font-theme-data text-sm border-b-2 transition-colors capitalize ${
              activeTab === tab
                ? 'border-[var(--accent)] text-[var(--accent)]'
                : 'border-transparent text-[var(--muted)] hover:text-[var(--text)]'
            }`}
          >
            {tab}
          </button>
        ))}
      </div>

      {/* Error Display */}
      {error && (
        <div className="mb-4 p-3 bg-red-500/20 border border-red-500/40 rounded text-red-400 text-sm">
          {error}
          <button onClick={() => setError(null)} className="ml-2 text-red-300 hover:text-red-200">
            [dismiss]
          </button>
        </div>
      )}

      {/* Tab Content */}
      <PanelErrorBoundary panelName={`Codebase ${activeTab}`}>
        {activeTab === 'dashboard' && (
          <DashboardView
            summary={summary}
            loading={loading}
            targetPath={targetPath}
            setTargetPath={setTargetPath}
            selectedScanTypes={selectedScanTypes}
            setSelectedScanTypes={setSelectedScanTypes}
            onStartScan={startScan}
            scanning={scanning}
          />
        )}

        {activeTab === 'findings' && (
          <FindingsView
            findings={findings}
            filter={findingsFilter}
            setFilter={setFindingsFilter}
            onDismiss={dismissFinding}
            onCreateIssue={createGitHubIssue}
          />
        )}

        {activeTab === 'scans' && <ScansView scans={scans} />}

        {activeTab === 'metrics' && <MetricsView metrics={metrics} />}
      </PanelErrorBoundary>
    </div>
  );
}

// Dashboard View Component
function DashboardView({
  summary,
  loading,
  targetPath,
  setTargetPath,
  selectedScanTypes,
  setSelectedScanTypes,
  onStartScan,
  scanning,
}: {
  summary: DashboardSummary | null;
  loading: boolean;
  targetPath: string;
  setTargetPath: (path: string) => void;
  selectedScanTypes: ScanType[];
  setSelectedScanTypes: (types: ScanType[]) => void;
  onStartScan: () => void;
  scanning: boolean;
}) {
  if (loading) {
    return (
      <div className="animate-pulse space-y-4">
        <div className="grid grid-cols-4 gap-4">
          {[...Array(4)].map((_, i) => (
            <div key={i} className="h-24 bg-[var(--surface)] rounded" />
          ))}
        </div>
        <div className="h-64 bg-[var(--surface)] rounded" />
      </div>
    );
  }

  const data = summary || getDemoSummary();

  return (
    <div className="space-y-6">
      {/* Summary Stats */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        <StatCard
          label="Total Findings"
          value={data.total_findings}
          severity="info"
          subtext={`${data.open_findings} open`}
        />
        <StatCard
          label="Critical"
          value={data.findings_by_severity.critical || 0}
          severity="critical"
        />
        <StatCard label="High" value={data.findings_by_severity.high || 0} severity="high" />
        <StatCard label="Medium" value={data.findings_by_severity.medium || 0} severity="medium" />
      </div>

      {/* New Scan Panel */}
      <div className="border border-[var(--border)] rounded p-4 bg-[var(--surface)]">
        <h3 className="font-theme-data font-bold mb-4">Start New Scan</h3>
        <div className="space-y-4">
          <div>
            <label className="block text-sm text-[var(--muted)] mb-1">Target Path</label>
            <input
              type="text"
              value={targetPath}
              onChange={(e) => setTargetPath(e.target.value)}
              className="w-full px-3 py-2 bg-[var(--background)] border border-[var(--border)] rounded font-theme-data text-sm"
              placeholder="."
            />
          </div>
          <div>
            <label className="block text-sm text-[var(--muted)] mb-2">Scan Types</label>
            <div className="flex flex-wrap gap-2">
              {(Object.keys(SCAN_TYPE_LABELS) as ScanType[])
                .filter((t) => t !== 'comprehensive')
                .map((type) => (
                  <button
                    key={type}
                    onClick={() =>
                      setSelectedScanTypes(
                        selectedScanTypes.includes(type)
                          ? selectedScanTypes.filter((t) => t !== type)
                          : [...selectedScanTypes, type],
                      )
                    }
                    className={`px-3 py-1 text-sm font-theme-data rounded border transition-colors ${
                      selectedScanTypes.includes(type)
                        ? 'bg-[var(--accent)]/20 border-[var(--accent)] text-[var(--accent)]'
                        : 'bg-[var(--surface)] border-[var(--border)] text-[var(--muted)] hover:text-[var(--text)]'
                    }`}
                  >
                    {SCAN_TYPE_LABELS[type].label}
                  </button>
                ))}
            </div>
          </div>
          <button
            onClick={onStartScan}
            disabled={scanning || selectedScanTypes.length === 0}
            className="px-4 py-2 bg-[var(--accent)] text-[var(--background)] font-theme-data text-sm rounded hover:opacity-90 disabled:opacity-50 disabled:cursor-not-allowed"
          >
            {scanning ? 'Scanning...' : 'Start Scan'}
          </button>
        </div>
      </div>

      {/* Findings by Type */}
      <div className="border border-[var(--border)] rounded p-4 bg-[var(--surface)]">
        <h3 className="font-theme-data font-bold mb-4">Findings by Type</h3>
        <div className="grid grid-cols-2 md:grid-cols-5 gap-3">
          {(Object.keys(SCAN_TYPE_LABELS) as ScanType[])
            .filter((t) => t !== 'comprehensive')
            .map((type) => (
              <div key={type} className="text-center p-3 border border-[var(--border)] rounded">
                <div className="text-2xl font-theme-data font-bold">
                  {data.findings_by_type[type] || 0}
                </div>
                <div className="text-xs text-[var(--muted)]">{SCAN_TYPE_LABELS[type].label}</div>
              </div>
            ))}
        </div>
      </div>

      {/* Recent Scans */}
      {data.recent_scans && data.recent_scans.length > 0 && (
        <div className="border border-[var(--border)] rounded p-4 bg-[var(--surface)]">
          <h3 className="font-theme-data font-bold mb-4">Recent Scans</h3>
          <div className="space-y-2">
            {data.recent_scans.slice(0, 5).map((scan) => (
              <div
                key={scan.id}
                className="flex items-center justify-between p-2 border border-[var(--border)] rounded text-sm"
              >
                <div className="flex items-center gap-3">
                  <span
                    className={`font-theme-data ${scan.status === 'completed' ? 'text-green-400' : scan.status === 'running' ? 'text-cyan-400' : 'text-yellow-400'}`}
                  >
                    [{scan.status}]
                  </span>
                  <span className="text-[var(--muted)]">{scan.scan_type}</span>
                </div>
                <div className="flex items-center gap-4 text-[var(--muted)]">
                  <span>{scan.files_scanned} files</span>
                  <span>{scan.findings_count} findings</span>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

// Stat Card Component
function StatCard({
  label,
  value,
  severity,
  subtext,
}: {
  label: string;
  value: number;
  severity: FindingSeverity;
  subtext?: string;
}) {
  const config = SEVERITY_CONFIG[severity];
  return (
    <div className={`border rounded p-4 ${config.bgColor}`}>
      <div className={`text-2xl font-theme-data font-bold ${config.color}`}>{value}</div>
      <div className="text-sm text-[var(--muted)]">{label}</div>
      {subtext && <div className="text-xs text-[var(--muted)] mt-1">{subtext}</div>}
    </div>
  );
}

// Findings View Component
function FindingsView({
  findings,
  filter,
  setFilter,
  onDismiss,
  onCreateIssue,
}: {
  findings: Finding[];
  filter: { severity?: FindingSeverity; type?: ScanType; status?: FindingStatus };
  setFilter: (f: typeof filter) => void;
  onDismiss: (id: string, reason: string, status: FindingStatus) => void;
  onCreateIssue: (id: string, repo: string) => Promise<string | null>;
}) {
  const [expandedId, setExpandedId] = useState<string | null>(null);

  return (
    <div className="space-y-4">
      {/* Filters */}
      <div className="flex flex-wrap gap-4 p-4 border border-[var(--border)] rounded bg-[var(--surface)]">
        <div>
          <label className="block text-xs text-[var(--muted)] mb-1">Severity</label>
          <select
            value={filter.severity || ''}
            onChange={(e) =>
              setFilter({ ...filter, severity: (e.target.value || undefined) as FindingSeverity })
            }
            className="px-2 py-1 bg-[var(--background)] border border-[var(--border)] rounded text-sm font-theme-data"
          >
            <option value="">All</option>
            {(['critical', 'high', 'medium', 'low', 'info'] as FindingSeverity[]).map((s) => (
              <option key={s} value={s}>
                {s}
              </option>
            ))}
          </select>
        </div>
        <div>
          <label className="block text-xs text-[var(--muted)] mb-1">Type</label>
          <select
            value={filter.type || ''}
            onChange={(e) =>
              setFilter({ ...filter, type: (e.target.value || undefined) as ScanType })
            }
            className="px-2 py-1 bg-[var(--background)] border border-[var(--border)] rounded text-sm font-theme-data"
          >
            <option value="">All</option>
            {(Object.keys(SCAN_TYPE_LABELS) as ScanType[]).map((t) => (
              <option key={t} value={t}>
                {SCAN_TYPE_LABELS[t].label}
              </option>
            ))}
          </select>
        </div>
        <div>
          <label className="block text-xs text-[var(--muted)] mb-1">Status</label>
          <select
            value={filter.status || ''}
            onChange={(e) =>
              setFilter({ ...filter, status: (e.target.value || undefined) as FindingStatus })
            }
            className="px-2 py-1 bg-[var(--background)] border border-[var(--border)] rounded text-sm font-theme-data"
          >
            <option value="">All</option>
            {(
              ['open', 'acknowledged', 'fixed', 'false_positive', 'wont_fix'] as FindingStatus[]
            ).map((s) => (
              <option key={s} value={s}>
                {s.replace('_', ' ')}
              </option>
            ))}
          </select>
        </div>
      </div>

      {/* Findings List */}
      <div className="space-y-2">
        {findings.length === 0 ? (
          <div className="text-center py-8 text-[var(--muted)]">No findings found</div>
        ) : (
          findings.map((finding) => (
            <FindingCard
              key={finding.id}
              finding={finding}
              expanded={expandedId === finding.id}
              onToggle={() => setExpandedId(expandedId === finding.id ? null : finding.id)}
              onDismiss={onDismiss}
              onCreateIssue={onCreateIssue}
            />
          ))
        )}
      </div>
    </div>
  );
}

// Finding Card Component
function FindingCard({
  finding,
  expanded,
  onToggle,
  onDismiss,
  onCreateIssue,
}: {
  finding: Finding;
  expanded: boolean;
  onToggle: () => void;
  onDismiss: (id: string, reason: string, status: FindingStatus) => void;
  onCreateIssue: (id: string, repo: string) => Promise<string | null>;
}) {
  const config = SEVERITY_CONFIG[finding.severity];

  return (
    <div className={`border rounded ${config.bgColor}`}>
      {/* Header */}
      <div
        className="flex items-center justify-between p-3 cursor-pointer hover:bg-[var(--surface)]"
        onClick={onToggle}
      >
        <div className="flex items-center gap-3">
          <span className={`font-theme-data font-bold ${config.color}`}>[{config.icon}]</span>
          <span className="font-theme-data text-sm">{finding.title}</span>
          <span className="text-xs text-[var(--muted)]">
            {SCAN_TYPE_LABELS[finding.scan_type]?.label}
          </span>
        </div>
        <div className="flex items-center gap-2">
          <span className="text-xs text-[var(--muted)] font-theme-data">{finding.file_path}</span>
          {finding.line_number && (
            <span className="text-xs text-[var(--muted)]">:{finding.line_number}</span>
          )}
        </div>
      </div>

      {/* Expanded Details */}
      {expanded && (
        <div className="border-t border-[var(--border)] p-4 space-y-4">
          <p className="text-sm text-[var(--muted)]">{finding.description}</p>

          {finding.code_snippet && (
            <pre className="p-3 bg-[var(--background)] rounded text-xs font-theme-data overflow-x-auto">
              {finding.code_snippet}
            </pre>
          )}

          {finding.fix_suggestion && (
            <div className="p-3 bg-green-500/10 border border-green-500/30 rounded">
              <div className="text-xs text-green-400 mb-1">Fix Suggestion:</div>
              <p className="text-sm text-green-300">{finding.fix_suggestion}</p>
            </div>
          )}

          <div className="flex flex-wrap gap-2 text-xs">
            {finding.cwe_id && (
              <span className="px-2 py-1 bg-[var(--surface)] rounded">{finding.cwe_id}</span>
            )}
            {finding.owasp_category && (
              <span className="px-2 py-1 bg-[var(--surface)] rounded">
                {finding.owasp_category}
              </span>
            )}
          </div>

          {/* Actions */}
          {finding.status === 'open' && (
            <div className="flex gap-2 pt-2 border-t border-[var(--border)]">
              <button
                onClick={() => onDismiss(finding.id, 'False positive', 'false_positive')}
                className="px-3 py-1 text-xs font-theme-data bg-[var(--surface)] border border-[var(--border)] rounded hover:border-[var(--accent)]"
              >
                False Positive
              </button>
              <button
                onClick={() => onDismiss(finding.id, 'Acknowledged', 'acknowledged')}
                className="px-3 py-1 text-xs font-theme-data bg-[var(--surface)] border border-[var(--border)] rounded hover:border-[var(--accent)]"
              >
                Acknowledge
              </button>
              <button
                onClick={() => onCreateIssue(finding.id, 'owner/repo')}
                className="px-3 py-1 text-xs font-theme-data bg-[var(--accent)]/20 border border-[var(--accent)] rounded text-[var(--accent)] hover:bg-[var(--accent)]/30"
              >
                Create Issue
              </button>
            </div>
          )}

          {finding.github_issue_url && (
            <a
              href={finding.github_issue_url}
              target="_blank"
              rel="noopener noreferrer"
              className="text-sm text-[var(--accent)] hover:underline"
            >
              View GitHub Issue
            </a>
          )}
        </div>
      )}
    </div>
  );
}

// Scans View Component
function ScansView({ scans }: { scans: ScanResult[] }) {
  return (
    <div className="space-y-4">
      {scans.length === 0 ? (
        <div className="text-center py-8 text-[var(--muted)]">
          No scans found. Start a new scan from the dashboard.
        </div>
      ) : (
        scans.map((scan) => (
          <div
            key={scan.id}
            className="border border-[var(--border)] rounded p-4 bg-[var(--surface)]"
          >
            <div className="flex items-center justify-between mb-2">
              <div className="flex items-center gap-3">
                <span
                  className={`font-theme-data text-sm ${
                    scan.status === 'completed'
                      ? 'text-green-400'
                      : scan.status === 'running'
                        ? 'text-cyan-400 animate-pulse'
                        : scan.status === 'failed'
                          ? 'text-red-400'
                          : 'text-yellow-400'
                  }`}
                >
                  [{scan.status.toUpperCase()}]
                </span>
                <span className="font-theme-data">{scan.scan_type}</span>
              </div>
              <span className="text-xs text-[var(--muted)]">
                {new Date(scan.started_at).toLocaleString()}
              </span>
            </div>
            <div className="flex gap-6 text-sm text-[var(--muted)]">
              <span>{scan.files_scanned} files scanned</span>
              <span>{scan.findings_count} findings</span>
              {scan.duration_seconds && <span>{scan.duration_seconds}s</span>}
            </div>
            {scan.error_message && (
              <p className="text-sm text-red-400 mt-2">{scan.error_message}</p>
            )}
          </div>
        ))
      )}
    </div>
  );
}

// Metrics View Component
function MetricsView({ metrics }: { metrics: CodeMetrics | null }) {
  if (!metrics) {
    return (
      <div className="animate-pulse space-y-4">
        <div className="h-32 bg-[var(--surface)] rounded" />
        <div className="h-64 bg-[var(--surface)] rounded" />
      </div>
    );
  }

  return (
    <div className="space-y-6">
      {/* Overview Stats */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        <div className="border border-[var(--border)] rounded p-4 bg-[var(--surface)]">
          <div className="text-2xl font-theme-data font-bold">
            {metrics.total_files.toLocaleString()}
          </div>
          <div className="text-sm text-[var(--muted)]">Total Files</div>
        </div>
        <div className="border border-[var(--border)] rounded p-4 bg-[var(--surface)]">
          <div className="text-2xl font-theme-data font-bold">
            {metrics.total_lines.toLocaleString()}
          </div>
          <div className="text-sm text-[var(--muted)]">Lines of Code</div>
        </div>
        <div className="border border-[var(--border)] rounded p-4 bg-[var(--surface)]">
          <div className="text-2xl font-theme-data font-bold">
            {metrics.average_complexity.toFixed(1)}
          </div>
          <div className="text-sm text-[var(--muted)]">Avg Complexity</div>
        </div>
        <div className="border border-[var(--border)] rounded p-4 bg-[var(--surface)]">
          <div className="text-2xl font-theme-data font-bold">
            {metrics.maintainability_index.toFixed(0)}
          </div>
          <div className="text-sm text-[var(--muted)]">Maintainability</div>
        </div>
      </div>

      {/* Languages */}
      <div className="border border-[var(--border)] rounded p-4 bg-[var(--surface)]">
        <h3 className="font-theme-data font-bold mb-4">Languages</h3>
        <div className="space-y-2">
          {Object.entries(metrics.languages).map(([lang, lines]) => (
            <div key={lang} className="flex items-center gap-3">
              <span className="font-theme-data text-sm w-24">{lang}</span>
              <div className="flex-1 h-4 bg-[var(--background)] rounded overflow-hidden">
                <div
                  className="h-full bg-[var(--accent)]"
                  style={{ width: `${(lines / metrics.total_lines) * 100}%` }}
                />
              </div>
              <span className="text-xs text-[var(--muted)] w-20 text-right">
                {lines.toLocaleString()} lines
              </span>
            </div>
          ))}
        </div>
      </div>

      {/* Hotspots */}
      {metrics.hotspots && metrics.hotspots.length > 0 && (
        <div className="border border-[var(--border)] rounded p-4 bg-[var(--surface)]">
          <h3 className="font-theme-data font-bold mb-4">Complexity Hotspots</h3>
          <div className="space-y-2">
            {metrics.hotspots.map((hotspot, i) => (
              <div
                key={i}
                className="flex items-center justify-between p-2 border border-[var(--border)] rounded text-sm"
              >
                <span className="font-theme-data text-[var(--muted)] truncate flex-1">
                  {hotspot.file}
                </span>
                <div className="flex gap-4 text-xs">
                  <span className="text-orange-400">complexity: {hotspot.complexity}</span>
                  <span className="text-[var(--muted)]">{hotspot.lines} lines</span>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

// Demo data generators
function getDemoSummary(): DashboardSummary {
  return {
    total_scans: 5,
    total_findings: 23,
    open_findings: 18,
    findings_by_severity: { critical: 2, high: 5, medium: 8, low: 6, info: 2 },
    findings_by_type: {
      sast: 8,
      bugs: 6,
      secrets: 2,
      dependencies: 5,
      metrics: 2,
      comprehensive: 0,
    },
    recent_scans: [
      {
        id: 'scan_1',
        tenant_id: 'demo',
        scan_type: 'sast',
        status: 'completed',
        target_path: '.',
        started_at: new Date(Date.now() - 3600000).toISOString(),
        completed_at: new Date().toISOString(),
        files_scanned: 156,
        findings_count: 8,
        duration_seconds: 45,
      },
    ],
  };
}

function getDemoFindings(): Finding[] {
  return [
    {
      id: 'finding_1',
      scan_id: 'scan_1',
      scan_type: 'sast',
      severity: 'critical',
      title: 'SQL Injection Vulnerability',
      description: 'User input is directly concatenated into SQL query without sanitization.',
      file_path: 'src/database/queries.py',
      line_number: 42,
      code_snippet: 'query = f"SELECT * FROM users WHERE id = {user_id}"',
      cwe_id: 'CWE-89',
      owasp_category: 'A03:2021',
      fix_suggestion: 'Use parameterized queries instead of string concatenation.',
      status: 'open',
      created_at: new Date().toISOString(),
    },
    {
      id: 'finding_2',
      scan_id: 'scan_1',
      scan_type: 'secrets',
      severity: 'critical',
      title: 'Hardcoded API Key',
      description: 'API key found hardcoded in source code.',
      file_path: 'src/config/settings.py',
      line_number: 15,
      code_snippet: 'API_KEY = "REDACTED_SECRET_KEY"',
      fix_suggestion: 'Move sensitive credentials to environment variables.',
      status: 'open',
      created_at: new Date().toISOString(),
    },
    {
      id: 'finding_3',
      scan_id: 'scan_1',
      scan_type: 'bugs',
      severity: 'high',
      title: 'Potential Null Pointer Dereference',
      description: 'Variable may be null when accessed.',
      file_path: 'src/handlers/user.py',
      line_number: 78,
      code_snippet: 'return user.name.upper()',
      fix_suggestion: 'Add null check before accessing user.name.',
      status: 'open',
      created_at: new Date().toISOString(),
    },
  ];
}

function getDemoMetrics(): CodeMetrics {
  return {
    total_lines: 45000,
    total_files: 320,
    average_complexity: 4.2,
    maintainability_index: 72,
    test_coverage: 68,
    code_duplication: 3.5,
    hotspots: [
      { file: 'src/debate/orchestrator.py', complexity: 28, lines: 450 },
      { file: 'src/server/unified_server.py', complexity: 24, lines: 680 },
      { file: 'src/analysis/codebase/sast_scanner.py', complexity: 22, lines: 520 },
    ],
    languages: { Python: 35000, TypeScript: 8000, JavaScript: 1500, YAML: 500 },
  };
}
