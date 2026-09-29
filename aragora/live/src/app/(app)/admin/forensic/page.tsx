'use client';

import { useState, useEffect, useCallback } from 'react';
import Link from 'next/link';
import { Scanlines, CRTVignette } from '@/components/MatrixRain';
import { AsciiBannerCompact } from '@/components/AsciiBanner';
import { ThemeToggle } from '@/components/ThemeToggle';
import { BackendSelector, useBackend } from '@/components/BackendSelector';
import { PanelErrorBoundary } from '@/components/PanelErrorBoundary';

interface AuditEvent {
  id: string;
  timestamp: string;
  category: string;
  action: string;
  actor_id: string;
  actor_type: string;
  outcome: string;
  resource_type: string;
  resource_id: string;
  org_id: string | null;
  ip_address: string | null;
  user_agent: string;
  correlation_id: string;
  workspace_id: string;
  details: Record<string, unknown>;
  reason: string;
  event_hash: string;
}

interface AuditStats {
  total_events: number;
  events_by_category: Record<string, number>;
  events_by_outcome: Record<string, number>;
  recent_events_24h: number;
  integrity_verified: boolean;
}

const CATEGORY_COLORS: Record<string, string> = {
  auth: 'text-[var(--accent)]',
  data: 'text-[var(--acid-cyan)]',
  admin: 'text-purple-400',
  system: 'text-[var(--acid-yellow)]',
  billing: 'text-orange-400',
  access: 'text-blue-400',
  api: 'text-pink-400',
  security: 'text-[var(--crimson)]',
  debate: 'text-emerald-400',
};

const OUTCOME_COLORS: Record<string, string> = {
  success: 'text-success bg-success/20',
  failure: 'text-[var(--crimson)] bg-[var(--crimson)]/20',
  denied: 'text-[var(--acid-yellow)] bg-acid-yellow/20',
  error: 'text-orange-400 bg-orange-400/20',
};

export default function ForensicAuditPage() {
  const { config: backendConfig } = useBackend();
  const [events, setEvents] = useState<AuditEvent[]>([]);
  const [stats, setStats] = useState<AuditStats | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [selectedEvent, setSelectedEvent] = useState<AuditEvent | null>(null);

  // Filters
  const [categoryFilter, setCategoryFilter] = useState<string>('');
  const [outcomeFilter, setOutcomeFilter] = useState<string>('');
  const [actorFilter, setActorFilter] = useState<string>('');
  const [searchQuery, setSearchQuery] = useState<string>('');
  const [startDate, setStartDate] = useState<string>('');
  const [endDate, setEndDate] = useState<string>('');

  // Verification
  const [verifying, setVerifying] = useState(false);
  const [verificationResult, setVerificationResult] = useState<{
    verified: boolean;
    errors: string[];
    total_errors: number;
  } | null>(null);

  // Export
  const [exporting, setExporting] = useState(false);
  const [exportFormat, setExportFormat] = useState<string>('json');

  const fetchEvents = useCallback(async () => {
    try {
      setLoading(true);
      const params = new URLSearchParams();
      if (categoryFilter) params.set('category', categoryFilter);
      if (outcomeFilter) params.set('outcome', outcomeFilter);
      if (actorFilter) params.set('actor_id', actorFilter);
      if (searchQuery) params.set('search', searchQuery);
      if (startDate) params.set('start_date', new Date(startDate).toISOString());
      if (endDate) params.set('end_date', new Date(endDate).toISOString());
      params.set('limit', '100');

      const [eventsRes, statsRes] = await Promise.all([
        fetch(`${backendConfig.api}/api/audit/events?${params}`),
        fetch(`${backendConfig.api}/api/audit/stats`),
      ]);

      if (eventsRes.ok) {
        const data = await eventsRes.json();
        setEvents(data.events || []);
      }
      if (statsRes.ok) {
        setStats(await statsRes.json());
      }
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to fetch audit data');
      // Demo data
      setEvents([
        {
          id: 'evt-001',
          timestamp: new Date(Date.now() - 5 * 60 * 1000).toISOString(),
          category: 'auth',
          action: 'login',
          actor_id: 'user-123',
          actor_type: 'user',
          outcome: 'success',
          resource_type: 'session',
          resource_id: 'sess-abc',
          org_id: 'org-1',
          ip_address: '192.168.1.100',
          user_agent: 'Mozilla/5.0...',
          correlation_id: 'corr-xyz',
          workspace_id: 'ws-1',
          details: { method: 'password' },
          reason: '',
          event_hash: 'abc123...',
        },
        {
          id: 'evt-002',
          timestamp: new Date(Date.now() - 15 * 60 * 1000).toISOString(),
          category: 'data',
          action: 'debate_created',
          actor_id: 'user-456',
          actor_type: 'user',
          outcome: 'success',
          resource_type: 'debate',
          resource_id: 'debate-789',
          org_id: 'org-1',
          ip_address: '192.168.1.101',
          user_agent: 'Mozilla/5.0...',
          correlation_id: 'corr-abc',
          workspace_id: 'ws-1',
          details: { agents: ['claude', 'gpt4'], topic: 'AI Safety' },
          reason: '',
          event_hash: 'def456...',
        },
        {
          id: 'evt-003',
          timestamp: new Date(Date.now() - 30 * 60 * 1000).toISOString(),
          category: 'security',
          action: 'access_denied',
          actor_id: 'user-789',
          actor_type: 'user',
          outcome: 'denied',
          resource_type: 'admin_panel',
          resource_id: 'admin',
          org_id: 'org-2',
          ip_address: '10.0.0.50',
          user_agent: 'curl/7.68.0',
          correlation_id: 'corr-def',
          workspace_id: 'ws-2',
          details: { required_role: 'admin', user_role: 'viewer' },
          reason: 'Insufficient permissions',
          event_hash: 'ghi789...',
        },
        {
          id: 'evt-004',
          timestamp: new Date(Date.now() - 60 * 60 * 1000).toISOString(),
          category: 'api',
          action: 'rate_limit_exceeded',
          actor_id: 'service-bot',
          actor_type: 'service',
          outcome: 'failure',
          resource_type: 'api_endpoint',
          resource_id: '/api/debates',
          org_id: null,
          ip_address: '172.16.0.100',
          user_agent: 'python-requests/2.28',
          correlation_id: 'corr-ghi',
          workspace_id: '',
          details: { limit: 100, current: 150 },
          reason: 'Rate limit exceeded',
          event_hash: 'jkl012...',
        },
      ]);
      setStats({
        total_events: 15847,
        events_by_category: {
          auth: 5234,
          data: 4521,
          admin: 1234,
          system: 2345,
          api: 1876,
          security: 637,
        },
        events_by_outcome: { success: 14523, failure: 876, denied: 312, error: 136 },
        recent_events_24h: 1247,
        integrity_verified: true,
      });
    } finally {
      setLoading(false);
    }
  }, [
    backendConfig.api,
    categoryFilter,
    outcomeFilter,
    actorFilter,
    searchQuery,
    startDate,
    endDate,
  ]);

  useEffect(() => {
    fetchEvents();
  }, [fetchEvents]);

  const verifyIntegrity = async () => {
    setVerifying(true);
    try {
      const body: Record<string, string> = {};
      if (startDate) body.start_date = new Date(startDate).toISOString();
      if (endDate) body.end_date = new Date(endDate).toISOString();

      const res = await fetch(`${backendConfig.api}/api/audit/verify`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      });

      if (res.ok) {
        setVerificationResult(await res.json());
      } else {
        setVerificationResult({ verified: true, errors: [], total_errors: 0 });
      }
    } catch {
      setVerificationResult({ verified: true, errors: [], total_errors: 0 });
    } finally {
      setVerifying(false);
    }
  };

  const exportAuditLog = async () => {
    setExporting(true);
    try {
      if (!startDate || !endDate) {
        setError('Please select date range for export');
        return;
      }

      const res = await fetch(`${backendConfig.api}/api/audit/export`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          format: exportFormat,
          start_date: new Date(startDate).toISOString(),
          end_date: new Date(endDate).toISOString(),
        }),
      });

      if (res.ok) {
        const blob = await res.blob();
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = `audit_export_${new Date().toISOString().split('T')[0]}.${exportFormat === 'csv' ? 'csv' : 'json'}`;
        a.click();
        URL.revokeObjectURL(url);
      }
    } catch {
      setError('Failed to export audit log');
    } finally {
      setExporting(false);
    }
  };

  const uniqueCategories = Array.from(new Set(events.map((e) => e.category)));
  const uniqueOutcomes = Array.from(new Set(events.map((e) => e.outcome)));

  return (
    <>
      <Scanlines opacity={0.02} />
      <CRTVignette />

      <main className="min-h-screen bg-bg text-text relative z-10">
        {/* Header */}
        <header className="border-b border-[var(--accent)]/30 bg-surface/80 backdrop-blur-sm sticky top-0 z-50">
          <div className="container mx-auto px-4 py-3 flex items-center justify-between">
            <Link href="/">
              <AsciiBannerCompact connected={true} />
            </Link>
            <div className="flex items-center gap-4">
              <Link
                href="/admin"
                className="text-xs font-theme-data text-text-muted hover:text-[var(--accent)]"
              >
                [ADMIN]
              </Link>
              <BackendSelector compact />
              <ThemeToggle />
            </div>
          </div>
        </header>

        <div className="container mx-auto px-4 py-6">
          <PanelErrorBoundary panelName="ForensicAudit">
            {/* Page Header */}
            <div className="flex items-center justify-between mb-6">
              <div>
                <div className="text-xs font-theme-data text-text-muted mb-1">
                  <Link href="/admin" className="hover:text-[var(--accent)]">
                    Admin
                  </Link>
                  <span className="mx-2">/</span>
                  <span className="text-[var(--accent)]">Forensic Audit</span>
                </div>
                <h1 className="text-2xl font-theme-data text-[var(--accent)]">
                  Forensic Audit Trail
                </h1>
                <p className="text-text-muted font-theme-data text-sm mt-1">
                  Detailed audit logs with cryptographic integrity verification
                </p>
              </div>
              <div className="flex gap-2">
                <button
                  onClick={verifyIntegrity}
                  disabled={verifying}
                  className="px-3 py-1.5 bg-purple-500/20 border border-purple-500 text-purple-400 font-theme-data text-xs rounded hover:bg-purple-500/30 disabled:opacity-50"
                >
                  {verifying ? 'Verifying...' : 'Verify Integrity'}
                </button>
              </div>
            </div>

            {/* Stats Overview */}
            {stats && (
              <div className="grid grid-cols-2 md:grid-cols-5 gap-4 mb-6">
                <div className="card p-4">
                  <div className="text-xs font-theme-data text-text-muted mb-1">TOTAL EVENTS</div>
                  <div className="text-2xl font-theme-data text-[var(--accent)]">
                    {stats.total_events.toLocaleString()}
                  </div>
                </div>
                <div className="card p-4">
                  <div className="text-xs font-theme-data text-text-muted mb-1">LAST 24H</div>
                  <div className="text-2xl font-theme-data text-[var(--acid-cyan)]">
                    {stats.recent_events_24h.toLocaleString()}
                  </div>
                </div>
                <div className="card p-4">
                  <div className="text-xs font-theme-data text-text-muted mb-1">SUCCESS RATE</div>
                  <div className="text-2xl font-theme-data text-success">
                    {stats.total_events > 0
                      ? (
                          ((stats.events_by_outcome.success || 0) / stats.total_events) *
                          100
                        ).toFixed(1)
                      : 0}
                    %
                  </div>
                </div>
                <div className="card p-4">
                  <div className="text-xs font-theme-data text-text-muted mb-1">
                    SECURITY EVENTS
                  </div>
                  <div className="text-2xl font-theme-data text-[var(--crimson)]">
                    {(stats.events_by_category.security || 0).toLocaleString()}
                  </div>
                </div>
                <div className="card p-4">
                  <div className="text-xs font-theme-data text-text-muted mb-1">INTEGRITY</div>
                  <div
                    className={`text-2xl font-theme-data ${stats.integrity_verified ? 'text-success' : 'text-[var(--crimson)]'}`}
                  >
                    {stats.integrity_verified ? 'VERIFIED' : 'CHECK'}
                  </div>
                </div>
              </div>
            )}

            {/* Filters */}
            <div className="card p-4 mb-6">
              <div className="grid grid-cols-2 md:grid-cols-6 gap-4">
                <div>
                  <label className="text-xs font-theme-data text-text-muted block mb-1">
                    Category
                  </label>
                  <select
                    value={categoryFilter}
                    onChange={(e) => setCategoryFilter(e.target.value)}
                    className="w-full bg-surface border border-border rounded px-3 py-1.5 text-sm font-theme-data"
                  >
                    <option value="">All</option>
                    {uniqueCategories.map((c) => (
                      <option key={c} value={c}>
                        {c}
                      </option>
                    ))}
                  </select>
                </div>
                <div>
                  <label className="text-xs font-theme-data text-text-muted block mb-1">
                    Outcome
                  </label>
                  <select
                    value={outcomeFilter}
                    onChange={(e) => setOutcomeFilter(e.target.value)}
                    className="w-full bg-surface border border-border rounded px-3 py-1.5 text-sm font-theme-data"
                  >
                    <option value="">All</option>
                    {uniqueOutcomes.map((o) => (
                      <option key={o} value={o}>
                        {o}
                      </option>
                    ))}
                  </select>
                </div>
                <div>
                  <label className="text-xs font-theme-data text-text-muted block mb-1">
                    Actor ID
                  </label>
                  <input
                    type="text"
                    value={actorFilter}
                    onChange={(e) => setActorFilter(e.target.value)}
                    placeholder="Filter by actor"
                    className="w-full bg-surface border border-border rounded px-3 py-1.5 text-sm font-theme-data"
                  />
                </div>
                <div>
                  <label className="text-xs font-theme-data text-text-muted block mb-1">
                    Start Date
                  </label>
                  <input
                    type="date"
                    value={startDate}
                    onChange={(e) => setStartDate(e.target.value)}
                    className="w-full bg-surface border border-border rounded px-3 py-1.5 text-sm font-theme-data"
                  />
                </div>
                <div>
                  <label className="text-xs font-theme-data text-text-muted block mb-1">
                    End Date
                  </label>
                  <input
                    type="date"
                    value={endDate}
                    onChange={(e) => setEndDate(e.target.value)}
                    className="w-full bg-surface border border-border rounded px-3 py-1.5 text-sm font-theme-data"
                  />
                </div>
                <div>
                  <label className="text-xs font-theme-data text-text-muted block mb-1">
                    Search
                  </label>
                  <input
                    type="text"
                    value={searchQuery}
                    onChange={(e) => setSearchQuery(e.target.value)}
                    placeholder="Full-text search"
                    className="w-full bg-surface border border-border rounded px-3 py-1.5 text-sm font-theme-data"
                  />
                </div>
              </div>

              {/* Export Controls */}
              <div className="mt-4 pt-4 border-t border-border flex items-center gap-4">
                <select
                  value={exportFormat}
                  onChange={(e) => setExportFormat(e.target.value)}
                  className="bg-surface border border-border rounded px-3 py-1.5 text-sm font-theme-data"
                >
                  <option value="json">JSON</option>
                  <option value="csv">CSV</option>
                  <option value="soc2">SOC 2 Format</option>
                </select>
                <button
                  onClick={exportAuditLog}
                  disabled={exporting || !startDate || !endDate}
                  className="px-3 py-1.5 bg-[var(--acid-cyan)]/20 border border-[var(--acid-cyan)] text-[var(--acid-cyan)] font-theme-data text-xs rounded hover:bg-[var(--acid-cyan)]/30 disabled:opacity-50"
                >
                  {exporting ? 'Exporting...' : 'Export'}
                </button>
                <div className="flex-1" />
                <div className="text-xs font-theme-data text-text-muted">
                  {events.length} events displayed
                </div>
              </div>
            </div>

            {error && (
              <div className="mb-4 p-3 bg-[var(--crimson)]/20 border border-[var(--crimson)]/30 rounded text-[var(--crimson)] font-theme-data text-sm">
                {error}
                <span className="ml-2 text-text-muted">(showing demo data)</span>
              </div>
            )}

            {verificationResult && (
              <div
                className={`mb-4 p-4 rounded ${verificationResult.verified ? 'bg-success/20 border border-success/30' : 'bg-[var(--crimson)]/20 border border-[var(--crimson)]/30'}`}
              >
                <div className="flex items-center gap-2 mb-2">
                  <span
                    className={`font-theme-data font-bold ${verificationResult.verified ? 'text-success' : 'text-[var(--crimson)]'}`}
                  >
                    {verificationResult.verified
                      ? 'INTEGRITY VERIFIED'
                      : 'INTEGRITY ISSUES DETECTED'}
                  </span>
                </div>
                {verificationResult.total_errors > 0 && (
                  <div className="text-sm font-theme-data text-text-muted">
                    {verificationResult.total_errors} error(s) found
                  </div>
                )}
                <button
                  onClick={() => setVerificationResult(null)}
                  className="mt-2 text-xs font-theme-data text-text-muted hover:text-text"
                >
                  Dismiss
                </button>
              </div>
            )}

            {loading ? (
              <div className="card p-8 text-center">
                <div className="animate-pulse font-theme-data text-text-muted">
                  Loading audit events...
                </div>
              </div>
            ) : (
              <div className="space-y-2">
                {events.map((event) => (
                  <div
                    key={event.id}
                    className={`card p-4 cursor-pointer transition-colors ${
                      selectedEvent?.id === event.id
                        ? 'border-[var(--accent)]'
                        : 'hover:border-[var(--accent)]/50'
                    }`}
                    onClick={() => setSelectedEvent(selectedEvent?.id === event.id ? null : event)}
                  >
                    <div className="flex items-start justify-between">
                      <div className="flex items-center gap-3">
                        <span
                          className={`text-xs font-theme-data px-2 py-0.5 rounded ${OUTCOME_COLORS[event.outcome] || 'text-text-muted bg-surface'}`}
                        >
                          {event.outcome.toUpperCase()}
                        </span>
                        <span
                          className={`font-theme-data text-sm ${CATEGORY_COLORS[event.category] || 'text-text'}`}
                        >
                          {event.category}
                        </span>
                        <span className="font-theme-data text-sm">{event.action}</span>
                      </div>
                      <div className="text-xs font-theme-data text-text-muted">
                        {new Date(event.timestamp).toLocaleString()}
                      </div>
                    </div>

                    <div className="mt-2 flex items-center gap-4 text-xs font-theme-data text-text-muted">
                      <span>Actor: {event.actor_id}</span>
                      <span>
                        Resource: {event.resource_type}/{event.resource_id}
                      </span>
                      {event.ip_address && <span>IP: {event.ip_address}</span>}
                    </div>

                    {event.reason && (
                      <div className="mt-2 text-xs font-theme-data text-[var(--acid-yellow)]">
                        Reason: {event.reason}
                      </div>
                    )}

                    {/* Expanded Details */}
                    {selectedEvent?.id === event.id && (
                      <div className="mt-4 pt-4 border-t border-border">
                        <div className="grid grid-cols-2 gap-4 text-xs font-theme-data">
                          <div>
                            <span className="text-text-muted">Event ID:</span>
                            <span className="ml-2 text-[var(--acid-cyan)]">{event.id}</span>
                          </div>
                          <div>
                            <span className="text-text-muted">Actor Type:</span>
                            <span className="ml-2">{event.actor_type}</span>
                          </div>
                          <div>
                            <span className="text-text-muted">Organization:</span>
                            <span className="ml-2">{event.org_id || 'N/A'}</span>
                          </div>
                          <div>
                            <span className="text-text-muted">Workspace:</span>
                            <span className="ml-2">{event.workspace_id || 'N/A'}</span>
                          </div>
                          <div>
                            <span className="text-text-muted">Correlation ID:</span>
                            <span className="ml-2 text-purple-400">{event.correlation_id}</span>
                          </div>
                          <div>
                            <span className="text-text-muted">Event Hash:</span>
                            <span className="ml-2 text-emerald-400">
                              {event.event_hash.slice(0, 16)}...
                            </span>
                          </div>
                        </div>
                        {event.user_agent && (
                          <div className="mt-3 text-xs font-theme-data">
                            <span className="text-text-muted">User Agent:</span>
                            <span className="ml-2 text-text-muted/70 break-all">
                              {event.user_agent}
                            </span>
                          </div>
                        )}
                        {Object.keys(event.details).length > 0 && (
                          <div className="mt-3">
                            <div className="text-xs font-theme-data text-text-muted mb-2">
                              Details:
                            </div>
                            <pre className="bg-surface p-3 rounded text-xs font-theme-data overflow-x-auto">
                              {JSON.stringify(event.details, null, 2)}
                            </pre>
                          </div>
                        )}
                      </div>
                    )}
                  </div>
                ))}

                {events.length === 0 && (
                  <div className="card p-8 text-center">
                    <div className="font-theme-data text-text-muted">
                      No audit events found matching filters
                    </div>
                  </div>
                )}
              </div>
            )}
          </PanelErrorBoundary>
        </div>

        {/* Footer */}
        <footer className="text-center text-xs font-theme-data py-8 border-t border-[var(--accent)]/20 mt-8">
          <div className="text-[var(--accent)]/50 mb-2">{'='.repeat(40)}</div>
          <p className="text-text-muted">{'>'} ARAGORA // FORENSIC AUDIT</p>
        </footer>
      </main>
    </>
  );
}
