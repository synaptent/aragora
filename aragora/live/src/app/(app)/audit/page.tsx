'use client';

/**
 * Audit Dashboard - Main Codebase Audit Results View
 *
 * Displays:
 * - Overview stats (total sessions, findings by severity)
 * - Recent audit sessions list
 * - Quick filters and search
 * - Links to create new audits
 */

import { useState, useEffect, useCallback } from 'react';
import Link from 'next/link';
import { useRouter } from 'next/navigation';
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
  findings_count: number;
  findings_by_severity: Record<string, number>;
  created_at: string;
  started_at?: string;
  completed_at?: string;
  duration_seconds?: number;
}

interface DashboardStats {
  total_sessions: number;
  completed_sessions: number;
  running_sessions: number;
  total_findings: number;
  critical_findings: number;
  high_findings: number;
  medium_findings: number;
  low_findings: number;
  avg_duration_seconds: number;
}

const SEVERITY_COLORS: Record<string, string> = {
  critical: 'bg-acid-red/20 text-acid-red border-acid-red/40',
  high: 'bg-acid-orange/20 text-acid-orange border-acid-orange/40',
  medium: 'bg-acid-yellow/20 text-[var(--acid-yellow)] border-acid-yellow/40',
  low: 'bg-acid-blue/20 text-acid-blue border-acid-blue/40',
  info: 'bg-muted/20 text-muted border-muted/40',
};

const STATUS_COLORS: Record<string, string> = {
  completed: 'bg-[var(--accent)]/20 text-[var(--accent)] border-[var(--accent)]/40',
  running: 'bg-[var(--acid-cyan)]/20 text-[var(--acid-cyan)] border-[var(--acid-cyan)]/40',
  pending: 'bg-acid-blue/20 text-acid-blue border-acid-blue/40',
  paused: 'bg-acid-purple/20 text-acid-purple border-acid-purple/40',
  failed: 'bg-acid-red/20 text-acid-red border-acid-red/40',
  cancelled: 'bg-muted/20 text-muted border-muted/40',
};

function StatusBadge({ status }: { status: string }) {
  const isRunning = status === 'running';
  return (
    <span
      className={`px-2 py-0.5 text-xs font-theme-data rounded border ${
        STATUS_COLORS[status] || STATUS_COLORS.pending
      } ${isRunning ? 'animate-pulse' : ''}`}
    >
      {status.toUpperCase()}
    </span>
  );
}

function StatCard({
  label,
  value,
  color,
  bgColor,
  icon,
  subtext,
}: {
  label: string;
  value: number | string;
  color: string;
  bgColor: string;
  icon: string;
  subtext?: string;
}) {
  return (
    <div className={`border rounded p-4 ${bgColor}`}>
      <div className="flex items-center justify-between">
        <span className={`text-2xl font-bold font-theme-data ${color}`}>{value}</span>
        <span className="text-xl">{icon}</span>
      </div>
      <div className={`text-xs font-theme-data mt-1 ${color}`}>{label}</div>
      {subtext && <div className="text-xs text-text-muted mt-1">{subtext}</div>}
    </div>
  );
}

function formatDuration(seconds?: number): string {
  if (!seconds) return '-';
  if (seconds < 60) return `${Math.round(seconds)}s`;
  if (seconds < 3600) return `${Math.round(seconds / 60)}m`;
  return `${Math.floor(seconds / 3600)}h ${Math.round((seconds % 3600) / 60)}m`;
}

function formatDate(dateStr?: string): string {
  if (!dateStr) return '-';
  return new Date(dateStr).toLocaleDateString('en-US', {
    month: 'short',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  });
}

export default function AuditDashboardPage() {
  const router = useRouter();
  const { config: backendConfig } = useBackend();
  const { tokens } = useAuth();

  const [sessions, setSessions] = useState<AuditSession[]>([]);
  const [stats, setStats] = useState<DashboardStats | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [statusFilter, setStatusFilter] = useState<string>('all');
  const [searchQuery, setSearchQuery] = useState('');

  const fetchSessions = useCallback(async () => {
    try {
      const response = await fetch(`${backendConfig.api}/api/audit/sessions`, {
        headers: { Authorization: `Bearer ${tokens?.access_token || ''}` },
      });
      if (response.ok) {
        const data = await response.json();
        setSessions(data.sessions || []);

        // Compute stats from sessions
        const sessionList = data.sessions || [];
        const computedStats: DashboardStats = {
          total_sessions: sessionList.length,
          completed_sessions: sessionList.filter((s: AuditSession) => s.status === 'completed')
            .length,
          running_sessions: sessionList.filter((s: AuditSession) => s.status === 'running').length,
          total_findings: 0,
          critical_findings: 0,
          high_findings: 0,
          medium_findings: 0,
          low_findings: 0,
          avg_duration_seconds: 0,
        };

        let totalDuration = 0;
        let durationCount = 0;

        sessionList.forEach((session: AuditSession) => {
          computedStats.total_findings += session.findings_count || 0;
          computedStats.critical_findings += session.findings_by_severity?.critical || 0;
          computedStats.high_findings += session.findings_by_severity?.high || 0;
          computedStats.medium_findings += session.findings_by_severity?.medium || 0;
          computedStats.low_findings += session.findings_by_severity?.low || 0;
          if (session.duration_seconds) {
            totalDuration += session.duration_seconds;
            durationCount++;
          }
        });

        computedStats.avg_duration_seconds = durationCount > 0 ? totalDuration / durationCount : 0;
        setStats(computedStats);
        setError(null);
      } else if (response.status === 404) {
        // API not available, use mock data
        setMockData();
      } else {
        throw new Error('Failed to fetch sessions');
      }
    } catch {
      // Use mock data on error
      setMockData();
    } finally {
      setLoading(false);
    }
  }, [backendConfig.api, tokens?.access_token]);

  const setMockData = () => {
    const mockSessions: AuditSession[] = [
      {
        id: 'session-001',
        name: 'Q4 Security Audit',
        status: 'completed',
        document_ids: ['doc-1', 'doc-2', 'doc-3'],
        audit_types: ['security', 'compliance'],
        model: 'claude-3.5-sonnet',
        progress: 1,
        findings_count: 24,
        findings_by_severity: { critical: 2, high: 5, medium: 12, low: 5 },
        created_at: new Date(Date.now() - 86400000 * 2).toISOString(),
        started_at: new Date(Date.now() - 86400000 * 2).toISOString(),
        completed_at: new Date(Date.now() - 86400000 * 2 + 3600000).toISOString(),
        duration_seconds: 3420,
      },
      {
        id: 'session-002',
        name: 'API Docs Consistency Check',
        status: 'running',
        document_ids: ['doc-4', 'doc-5'],
        audit_types: ['consistency', 'quality'],
        model: 'gemini-3-pro',
        progress: 0.65,
        findings_count: 8,
        findings_by_severity: { critical: 0, high: 1, medium: 4, low: 3 },
        created_at: new Date(Date.now() - 3600000).toISOString(),
        started_at: new Date(Date.now() - 3600000).toISOString(),
      },
      {
        id: 'session-003',
        name: 'HIPAA Compliance Review',
        status: 'completed',
        document_ids: ['doc-6'],
        audit_types: ['compliance'],
        model: 'gpt-4-turbo',
        progress: 1,
        findings_count: 15,
        findings_by_severity: { critical: 1, high: 3, medium: 7, low: 4 },
        created_at: new Date(Date.now() - 86400000 * 5).toISOString(),
        started_at: new Date(Date.now() - 86400000 * 5).toISOString(),
        completed_at: new Date(Date.now() - 86400000 * 5 + 2700000).toISOString(),
        duration_seconds: 2580,
      },
    ];

    setSessions(mockSessions);
    setStats({
      total_sessions: 3,
      completed_sessions: 2,
      running_sessions: 1,
      total_findings: 47,
      critical_findings: 3,
      high_findings: 9,
      medium_findings: 23,
      low_findings: 12,
      avg_duration_seconds: 3000,
    });
  };

  useEffect(() => {
    fetchSessions();
    // Poll for updates
    const interval = setInterval(fetchSessions, 30000);
    return () => clearInterval(interval);
  }, [fetchSessions]);

  // Filter sessions
  const filteredSessions = sessions.filter((session) => {
    if (statusFilter !== 'all' && session.status !== statusFilter) return false;
    if (searchQuery && !session.name.toLowerCase().includes(searchQuery.toLowerCase()))
      return false;
    return true;
  });

  // Sort by created_at descending
  const sortedSessions = [...filteredSessions].sort(
    (a, b) => new Date(b.created_at).getTime() - new Date(a.created_at).getTime(),
  );

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
            <span className="text-muted font-theme-data text-sm">{'//'} AUDIT DASHBOARD</span>
          </div>
          <div className="flex items-center gap-3">
            <BackendSelector />
            <ThemeToggle />
          </div>
        </div>
      </header>

      <main className="container mx-auto px-4 py-6">
        {/* Page Header */}
        <div className="flex items-center justify-between mb-6">
          <div>
            <h1 className="text-2xl font-theme-data mb-1">CODEBASE AUDIT RESULTS</h1>
            <p className="text-muted text-sm font-theme-data">
              Multi-agent security, compliance, and quality analysis
            </p>
          </div>
          <div className="flex items-center gap-2">
            <Link href="/audit/templates" className="btn btn-ghost">
              Templates
            </Link>
            <Link href="/audit/new" className="btn btn-primary">
              + New Audit
            </Link>
          </div>
        </div>

        <PanelErrorBoundary panelName="Dashboard Stats">
          {/* Stats Overview */}
          {loading ? (
            <div className="grid grid-cols-2 md:grid-cols-4 lg:grid-cols-6 gap-4 mb-6">
              {[1, 2, 3, 4, 5, 6].map((i) => (
                <div key={i} className="border border-border rounded p-4 animate-pulse">
                  <div className="h-8 bg-surface rounded mb-2" />
                  <div className="h-4 bg-surface rounded w-2/3" />
                </div>
              ))}
            </div>
          ) : stats ? (
            <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-6 gap-4 mb-6">
              <StatCard
                label="TOTAL AUDITS"
                value={stats.total_sessions}
                color="text-accent"
                bgColor="bg-accent/10 border-accent/40"
                icon="#"
              />
              <StatCard
                label="RUNNING"
                value={stats.running_sessions}
                color="text-[var(--acid-cyan)]"
                bgColor="bg-[var(--acid-cyan)]/10 border-[var(--acid-cyan)]/40"
                icon=">"
                subtext={stats.running_sessions > 0 ? 'In progress' : 'None active'}
              />
              <StatCard
                label="CRITICAL"
                value={stats.critical_findings}
                color="text-acid-red"
                bgColor="bg-acid-red/10 border-acid-red/40"
                icon="!"
                subtext={stats.critical_findings > 0 ? 'Needs attention' : 'All clear'}
              />
              <StatCard
                label="HIGH"
                value={stats.high_findings}
                color="text-acid-orange"
                bgColor="bg-acid-orange/10 border-acid-orange/40"
                icon="^"
              />
              <StatCard
                label="TOTAL FINDINGS"
                value={stats.total_findings}
                color="text-accent"
                bgColor="bg-surface border-border"
                icon="*"
              />
              <StatCard
                label="AVG DURATION"
                value={formatDuration(stats.avg_duration_seconds)}
                color="text-muted"
                bgColor="bg-surface border-border"
                icon="~"
              />
            </div>
          ) : null}
        </PanelErrorBoundary>

        {/* Filters */}
        <div className="flex items-center gap-4 mb-4">
          <div className="flex-1">
            <input
              type="text"
              placeholder="Search audits..."
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              className="input w-full max-w-xs"
            />
          </div>
          <select
            value={statusFilter}
            onChange={(e) => setStatusFilter(e.target.value)}
            className="input"
          >
            <option value="all">All Status</option>
            <option value="running">Running</option>
            <option value="completed">Completed</option>
            <option value="failed">Failed</option>
            <option value="paused">Paused</option>
          </select>
          <button onClick={fetchSessions} className="btn btn-ghost text-sm">
            Refresh
          </button>
        </div>

        <PanelErrorBoundary panelName="Sessions List">
          {/* Sessions List */}
          {loading ? (
            <div className="card animate-pulse">
              <div className="p-4 space-y-4">
                {[1, 2, 3].map((i) => (
                  <div key={i} className="h-20 bg-surface rounded" />
                ))}
              </div>
            </div>
          ) : error ? (
            <div className="card p-6 border-acid-red bg-acid-red/5 text-center">
              <div className="text-acid-red font-theme-data mb-2">{error}</div>
              <button onClick={fetchSessions} className="btn btn-ghost text-sm">
                Retry
              </button>
            </div>
          ) : sortedSessions.length === 0 ? (
            <div className="card p-12 text-center">
              <div className="text-4xl mb-4">🔍</div>
              <div className="text-muted font-theme-data mb-4">
                {sessions.length === 0 ? 'No audit sessions yet' : 'No sessions match your filters'}
              </div>
              <Link href="/audit/new" className="btn btn-primary">
                Create First Audit
              </Link>
            </div>
          ) : (
            <div className="card overflow-hidden">
              <table className="w-full">
                <thead className="bg-surface border-b border-border">
                  <tr>
                    <th className="p-3 text-left font-theme-data text-xs text-muted">SESSION</th>
                    <th className="p-3 text-left font-theme-data text-xs text-muted">STATUS</th>
                    <th className="p-3 text-left font-theme-data text-xs text-muted">FINDINGS</th>
                    <th className="p-3 text-left font-theme-data text-xs text-muted">DOCUMENTS</th>
                    <th className="p-3 text-left font-theme-data text-xs text-muted">CREATED</th>
                    <th className="p-3 text-left font-theme-data text-xs text-muted">DURATION</th>
                    <th className="p-3 text-right font-theme-data text-xs text-muted">ACTIONS</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-border">
                  {sortedSessions.map((session) => (
                    <tr
                      key={session.id}
                      className="hover:bg-surface/50 cursor-pointer transition-colors"
                      onClick={() => router.push(`/audit/view?id=${session.id}`)}
                    >
                      <td className="p-3">
                        <div className="font-theme-data text-sm">
                          {session.name || session.id.slice(0, 12)}
                        </div>
                        <div className="text-xs text-muted flex items-center gap-2 mt-1">
                          <span>{session.model}</span>
                          <span className="text-border">|</span>
                          <span>{session.audit_types.join(', ')}</span>
                        </div>
                      </td>
                      <td className="p-3">
                        <div className="flex items-center gap-2">
                          <StatusBadge status={session.status} />
                          {session.status === 'running' && (
                            <span className="text-xs text-muted">
                              {Math.round(session.progress * 100)}%
                            </span>
                          )}
                        </div>
                      </td>
                      <td className="p-3">
                        <div className="flex items-center gap-2">
                          <span className="font-theme-data">{session.findings_count}</span>
                          {(session.findings_by_severity?.critical || 0) > 0 && (
                            <span
                              className={`px-1.5 py-0.5 text-xs rounded ${SEVERITY_COLORS.critical}`}
                            >
                              {session.findings_by_severity.critical} crit
                            </span>
                          )}
                          {(session.findings_by_severity?.high || 0) > 0 && (
                            <span
                              className={`px-1.5 py-0.5 text-xs rounded ${SEVERITY_COLORS.high}`}
                            >
                              {session.findings_by_severity.high} high
                            </span>
                          )}
                        </div>
                      </td>
                      <td className="p-3">
                        <span className="font-theme-data text-sm">
                          {session.document_ids.length}
                        </span>
                      </td>
                      <td className="p-3">
                        <span className="text-sm text-muted">{formatDate(session.created_at)}</span>
                      </td>
                      <td className="p-3">
                        <span className="text-sm font-theme-data text-muted">
                          {formatDuration(session.duration_seconds)}
                        </span>
                      </td>
                      <td className="p-3 text-right">
                        <div className="flex items-center justify-end gap-1">
                          <button
                            onClick={(e) => {
                              e.stopPropagation();
                              router.push(`/audit/view?id=${session.id}`);
                            }}
                            className="px-2 py-1 text-xs font-theme-data bg-accent/10 text-accent hover:bg-accent/20 rounded transition-colors"
                          >
                            View
                          </button>
                          {session.status === 'completed' && (
                            <button
                              onClick={(e) => {
                                e.stopPropagation();
                                // Export functionality
                                window.open(
                                  `${backendConfig.api}/api/audit/sessions/${session.id}/report?format=html`,
                                  '_blank',
                                );
                              }}
                              className="px-2 py-1 text-xs font-theme-data bg-surface hover:bg-accent/10 rounded transition-colors"
                            >
                              Export
                            </button>
                          )}
                        </div>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </PanelErrorBoundary>

        {/* Severity Breakdown Chart */}
        {stats && stats.total_findings > 0 && (
          <div className="mt-6 card p-4">
            <h3 className="text-sm font-theme-data text-muted mb-4">FINDINGS BY SEVERITY</h3>
            <div className="flex items-end gap-2 h-32">
              {[
                {
                  key: 'critical',
                  label: 'Critical',
                  count: stats.critical_findings,
                  color: 'bg-acid-red',
                },
                { key: 'high', label: 'High', count: stats.high_findings, color: 'bg-acid-orange' },
                {
                  key: 'medium',
                  label: 'Medium',
                  count: stats.medium_findings,
                  color: 'bg-acid-yellow',
                },
                {
                  key: 'low',
                  label: 'Low',
                  count: stats.low_findings,
                  color: 'bg-[var(--acid-cyan)]',
                },
              ].map((item) => {
                const maxCount = Math.max(
                  stats.critical_findings,
                  stats.high_findings,
                  stats.medium_findings,
                  stats.low_findings,
                  1,
                );
                const height = (item.count / maxCount) * 100;

                return (
                  <div key={item.key} className="flex-1 flex flex-col items-center gap-2">
                    <div
                      className="w-full flex items-end justify-center"
                      style={{ height: '100px' }}
                    >
                      <div
                        className={`w-full max-w-[60px] ${item.color} rounded-t transition-all`}
                        style={{ height: `${Math.max(height, 4)}%` }}
                      />
                    </div>
                    <div className="text-center">
                      <div className="font-theme-data text-sm">{item.count}</div>
                      <div className="text-xs text-muted">{item.label}</div>
                    </div>
                  </div>
                );
              })}
            </div>
          </div>
        )}
      </main>

      <footer className="border-t border-border bg-surface/50 py-4 mt-8">
        <div className="container mx-auto px-4 flex items-center justify-between text-xs text-muted font-theme-data">
          <span>ARAGORA AUDIT ENGINE</span>
          <div className="flex items-center gap-4">
            <Link href="/admin/audit" className="hover:text-accent">
              AUDIT LOGS
            </Link>
            <Link href="/gauntlet" className="hover:text-accent">
              GAUNTLET
            </Link>
          </div>
        </div>
      </footer>
    </div>
  );
}
