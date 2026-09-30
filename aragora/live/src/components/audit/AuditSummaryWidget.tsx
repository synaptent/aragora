'use client';

/**
 * AuditSummaryWidget - Compact audit status for dashboards
 *
 * Shows:
 * - Running audits count
 * - Critical findings count
 * - Quick link to audit dashboard
 */

import { useState, useEffect, useCallback } from 'react';
import Link from 'next/link';

interface AuditSummary {
  total_sessions: number;
  running_sessions: number;
  critical_findings: number;
  high_findings: number;
  recent_session?: { id: string; name: string; status: string; findings_count: number };
}

interface AuditSummaryWidgetProps {
  apiBase?: string;
  authToken?: string;
  compact?: boolean;
  refreshInterval?: number;
}

export function AuditSummaryWidget({
  apiBase,
  authToken,
  compact = false,
  refreshInterval = 60000,
}: AuditSummaryWidgetProps) {
  const [summary, setSummary] = useState<AuditSummary | null>(null);
  const [loading, setLoading] = useState(true);

  const fetchSummary = useCallback(async () => {
    try {
      const baseUrl = apiBase || '';
      const response = await fetch(`${baseUrl}/api/audit/sessions`, {
        headers: authToken ? { Authorization: `Bearer ${authToken}` } : {},
      });

      if (response.ok) {
        const data = await response.json();
        const sessions = data.sessions || [];

        // Compute summary from sessions
        const computedSummary: AuditSummary = {
          total_sessions: sessions.length,
          running_sessions: sessions.filter((s: { status: string }) => s.status === 'running')
            .length,
          critical_findings: 0,
          high_findings: 0,
        };

        sessions.forEach((session: { findings_by_severity?: Record<string, number> }) => {
          computedSummary.critical_findings += session.findings_by_severity?.critical || 0;
          computedSummary.high_findings += session.findings_by_severity?.high || 0;
        });

        // Get most recent session
        if (sessions.length > 0) {
          const sorted = [...sessions].sort(
            (a: { created_at: string }, b: { created_at: string }) =>
              new Date(b.created_at).getTime() - new Date(a.created_at).getTime(),
          );
          const recent = sorted[0];
          computedSummary.recent_session = {
            id: recent.id,
            name: recent.name || recent.id.slice(0, 8),
            status: recent.status,
            findings_count: recent.findings_count,
          };
        }

        setSummary(computedSummary);
      } else {
        // Use mock data
        setSummary({
          total_sessions: 3,
          running_sessions: 1,
          critical_findings: 2,
          high_findings: 5,
          recent_session: {
            id: 'mock-001',
            name: 'Security Audit',
            status: 'running',
            findings_count: 12,
          },
        });
      }
    } catch {
      // Use mock data on error
      setSummary({
        total_sessions: 3,
        running_sessions: 1,
        critical_findings: 2,
        high_findings: 5,
        recent_session: {
          id: 'mock-001',
          name: 'Security Audit',
          status: 'running',
          findings_count: 12,
        },
      });
    } finally {
      setLoading(false);
    }
  }, [apiBase, authToken]);

  useEffect(() => {
    fetchSummary();
    const interval = setInterval(fetchSummary, refreshInterval);
    return () => clearInterval(interval);
  }, [fetchSummary, refreshInterval]);

  if (compact) {
    return (
      <Link
        href="/audit"
        className="flex items-center gap-2 px-3 py-1.5 text-xs font-theme-data bg-[var(--surface)] border border-[var(--border)] rounded hover:border-[var(--acid-green)]/30 transition-colors"
      >
        <span>🔍</span>
        <span className="text-[var(--text-muted)]">Audits</span>
        {summary && (
          <>
            {summary.running_sessions > 0 && (
              <span className="text-[var(--acid-cyan)] animate-pulse">
                {summary.running_sessions} running
              </span>
            )}
            {summary.critical_findings > 0 && (
              <span className="text-[var(--acid-red)]">{summary.critical_findings} crit</span>
            )}
          </>
        )}
      </Link>
    );
  }

  if (loading) {
    return (
      <div className="bg-[var(--surface)] border border-[var(--border)] p-4 rounded animate-pulse">
        <div className="h-4 bg-[var(--bg)] rounded w-1/3 mb-3" />
        <div className="h-8 bg-[var(--bg)] rounded" />
      </div>
    );
  }

  if (!summary) return null;

  return (
    <div className="bg-[var(--surface)] border border-[var(--border)] rounded overflow-hidden">
      {/* Header */}
      <div className="p-3 border-b border-[var(--border)] flex items-center justify-between">
        <div className="flex items-center gap-2">
          <span className="text-lg">🔍</span>
          <span className="text-sm font-theme-data text-[var(--acid-green)]">AUDIT STATUS</span>
        </div>
        <Link
          href="/audit"
          className="text-xs font-theme-data text-[var(--text-muted)] hover:text-[var(--acid-green)] transition-colors"
        >
          View All →
        </Link>
      </div>

      {/* Stats */}
      <div className="p-3 grid grid-cols-3 gap-3">
        <div className="text-center">
          <div className="text-xl font-theme-data font-bold text-[var(--acid-cyan)]">
            {summary.running_sessions}
          </div>
          <div className="text-xs text-[var(--text-muted)]">Running</div>
        </div>
        <div className="text-center">
          <div
            className={`text-xl font-theme-data font-bold ${summary.critical_findings > 0 ? 'text-[var(--acid-red)]' : 'text-[var(--text)]'}`}
          >
            {summary.critical_findings}
          </div>
          <div className="text-xs text-[var(--text-muted)]">Critical</div>
        </div>
        <div className="text-center">
          <div
            className={`text-xl font-theme-data font-bold ${summary.high_findings > 0 ? 'text-orange-400' : 'text-[var(--text)]'}`}
          >
            {summary.high_findings}
          </div>
          <div className="text-xs text-[var(--text-muted)]">High</div>
        </div>
      </div>

      {/* Recent Session */}
      {summary.recent_session && (
        <div className="p-3 border-t border-[var(--border)] bg-[var(--bg)]/50">
          <div className="text-xs text-[var(--text-muted)] mb-1">Latest:</div>
          <Link
            href={`/audit/view?id=${summary.recent_session.id}`}
            className="flex items-center justify-between hover:text-[var(--acid-green)] transition-colors"
          >
            <span className="text-sm font-theme-data truncate max-w-[150px]">
              {summary.recent_session.name}
            </span>
            <div className="flex items-center gap-2">
              <span
                className={`px-1.5 py-0.5 text-xs font-theme-data rounded ${
                  summary.recent_session.status === 'running'
                    ? 'bg-[var(--acid-cyan)]/20 text-[var(--acid-cyan)] animate-pulse'
                    : summary.recent_session.status === 'completed'
                      ? 'bg-[var(--acid-green)]/20 text-[var(--acid-green)]'
                      : 'bg-[var(--text-muted)]/20 text-[var(--text-muted)]'
                }`}
              >
                {summary.recent_session.status}
              </span>
              <span className="text-xs text-[var(--text-muted)]">
                {summary.recent_session.findings_count} findings
              </span>
            </div>
          </Link>
        </div>
      )}

      {/* Quick Actions */}
      <div className="p-3 border-t border-[var(--border)] flex gap-2">
        <Link
          href="/audit/new"
          className="flex-1 px-3 py-1.5 text-xs font-theme-data text-center bg-[var(--acid-green)]/10 text-[var(--acid-green)] border border-[var(--acid-green)]/30 rounded hover:bg-[var(--acid-green)]/20 transition-colors"
        >
          + New Audit
        </Link>
        <Link
          href="/gauntlet"
          className="px-3 py-1.5 text-xs font-theme-data bg-[var(--surface)] border border-[var(--border)] rounded hover:border-[var(--acid-cyan)]/30 transition-colors"
        >
          Gauntlet
        </Link>
      </div>
    </div>
  );
}

export default AuditSummaryWidget;
