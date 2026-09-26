'use client';

import { useState, useEffect, useCallback } from 'react';
import { Scanlines, CRTVignette } from '@/components/MatrixRain';
import { useBackend } from '@/components/BackendSelector';
import { logger } from '@/utils/logger';

interface ComponentStatus {
  id: string;
  name: string;
  status: string;
  response_time_ms: number | null;
  message: string | null;
  description?: string;
  last_check?: string;
}

interface StatusSummary {
  status: string;
  message: string;
  uptime_seconds: number;
  uptime_formatted: string;
  timestamp: string;
  components: ComponentStatus[];
}

interface UptimePeriod {
  uptime_percent: number;
  incidents: number;
}

interface UptimeHistory {
  current: { status: string; uptime_seconds: number };
  periods: Record<string, UptimePeriod>;
  timestamp: string;
}

interface IncidentUpdate {
  timestamp: string;
  status: string;
  message: string;
}

interface Incident {
  id: string;
  title: string;
  status: string;
  severity: string;
  components: string[];
  created_at: string;
  updated_at: string;
  resolved_at: string | null;
  updates: IncidentUpdate[];
}

interface IncidentsData {
  active: Incident[];
  recent: Incident[];
  scheduled_maintenance: Incident[];
}

type TabType = 'overview' | 'components' | 'uptime' | 'incidents';

const STATUS_COLORS: Record<string, string> = {
  operational: 'text-[var(--accent)]',
  degraded: 'text-yellow-400',
  partial_outage: 'text-orange-400',
  major_outage: 'text-red-400',
  maintenance: 'text-blue-400',
};

const STATUS_BG: Record<string, string> = {
  operational: 'border-[var(--accent)]/30 bg-[var(--accent)]/5',
  degraded: 'border-yellow-500/30 bg-yellow-500/5',
  partial_outage: 'border-orange-500/30 bg-orange-500/5',
  major_outage: 'border-red-500/30 bg-red-500/5',
  maintenance: 'border-blue-500/30 bg-blue-500/5',
};

const STATUS_DOT: Record<string, string> = {
  operational: 'bg-[var(--accent)]',
  degraded: 'bg-yellow-400',
  partial_outage: 'bg-orange-400',
  major_outage: 'bg-red-400',
  maintenance: 'bg-blue-400',
};

export default function StatusPage() {
  const { config: backendConfig } = useBackend();
  const [activeTab, setActiveTab] = useState<TabType>('overview');

  const [summary, setSummary] = useState<StatusSummary | null>(null);
  const [summaryLoading, setSummaryLoading] = useState(false);

  const [uptime, setUptime] = useState<UptimeHistory | null>(null);
  const [uptimeLoading, setUptimeLoading] = useState(false);

  const [incidents, setIncidents] = useState<IncidentsData | null>(null);
  const [incidentsLoading, setIncidentsLoading] = useState(false);

  const [lastRefresh, setLastRefresh] = useState<Date>(new Date());

  const fetchSummary = useCallback(async () => {
    setSummaryLoading(true);
    try {
      const res = await fetch(`${backendConfig.api}/api/status`);
      if (res.ok) {
        const data = await res.json();
        setSummary(data);
        setLastRefresh(new Date());
      }
    } catch (err) {
      logger.error('Failed to fetch status summary:', err);
    } finally {
      setSummaryLoading(false);
    }
  }, [backendConfig.api]);

  const fetchUptime = useCallback(async () => {
    setUptimeLoading(true);
    try {
      const res = await fetch(`${backendConfig.api}/api/status/history`);
      if (res.ok) {
        const data = await res.json();
        setUptime(data);
      }
    } catch (err) {
      logger.error('Failed to fetch uptime history:', err);
    } finally {
      setUptimeLoading(false);
    }
  }, [backendConfig.api]);

  const fetchIncidents = useCallback(async () => {
    setIncidentsLoading(true);
    try {
      const res = await fetch(`${backendConfig.api}/api/status/incidents`);
      if (res.ok) {
        const data = await res.json();
        setIncidents(data);
      }
    } catch (err) {
      logger.error('Failed to fetch incidents:', err);
    } finally {
      setIncidentsLoading(false);
    }
  }, [backendConfig.api]);

  // Load summary on mount and auto-refresh every 30s
  useEffect(() => {
    fetchSummary();
    const interval = setInterval(fetchSummary, 30000);
    return () => clearInterval(interval);
  }, [fetchSummary]);

  // Load tab data on switch
  useEffect(() => {
    if (activeTab === 'uptime') fetchUptime();
    if (activeTab === 'incidents') fetchIncidents();
  }, [activeTab, fetchUptime, fetchIncidents]);

  const overallStatus = summary?.status || 'operational';
  const operationalCount =
    summary?.components.filter((c) => c.status === 'operational').length || 0;
  const totalCount = summary?.components.length || 0;

  return (
    <>
      <Scanlines opacity={0.02} />
      <CRTVignette />

      <main className="min-h-screen bg-bg text-text relative z-10">
        <div className="container mx-auto px-4 py-6">
          {/* Header */}
          <div className="mb-6">
            <h1 className="text-2xl font-theme-data text-[var(--accent)] mb-2">
              {'>'} SYSTEM STATUS
            </h1>
            <p className="text-text-muted font-theme-data text-sm">
              Real-time health monitoring for all Aragora platform components.
            </p>
          </div>

          {/* Overall Status Banner */}
          <div
            className={`p-6 border rounded mb-6 ${STATUS_BG[overallStatus] || STATUS_BG.operational}`}
          >
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-3">
                <div
                  className={`w-3 h-3 rounded-full animate-pulse ${STATUS_DOT[overallStatus] || STATUS_DOT.operational}`}
                />
                <span
                  className={`text-xl font-theme-data font-bold ${STATUS_COLORS[overallStatus] || STATUS_COLORS.operational}`}
                >
                  {summary?.message || 'Checking...'}
                </span>
              </div>
              <div className="text-right">
                {summary && (
                  <div className="font-theme-data text-sm text-text-muted">
                    Uptime: <span className="text-text">{summary.uptime_formatted}</span>
                  </div>
                )}
                <div className="font-theme-data text-xs text-text-muted/60 mt-1">
                  {operationalCount}/{totalCount} components operational
                </div>
              </div>
            </div>
          </div>

          {/* Quick Component Status Grid */}
          {summary && (
            <div className="grid grid-cols-2 md:grid-cols-4 gap-3 mb-6">
              {summary.components.map((c) => (
                <div
                  key={c.id}
                  className={`p-3 border rounded ${STATUS_BG[c.status] || STATUS_BG.operational}`}
                >
                  <div className="flex items-center gap-2 mb-1">
                    <div
                      className={`w-2 h-2 rounded-full ${STATUS_DOT[c.status] || STATUS_DOT.operational}`}
                    />
                    <span className="font-theme-data text-sm text-text truncate">{c.name}</span>
                  </div>
                  <div className="flex items-center justify-between">
                    <span
                      className={`text-xs font-theme-data capitalize ${STATUS_COLORS[c.status] || STATUS_COLORS.operational}`}
                    >
                      {c.status.replace(/_/g, ' ')}
                    </span>
                    {c.response_time_ms !== null && (
                      <span className="text-xs font-theme-data text-text-muted">
                        {c.response_time_ms.toFixed(0)}ms
                      </span>
                    )}
                  </div>
                  {c.message && (
                    <div className="text-xs font-theme-data text-text-muted/60 mt-1 truncate">
                      {c.message}
                    </div>
                  )}
                </div>
              ))}
            </div>
          )}
          {summaryLoading && !summary && (
            <div className="text-center py-8 text-[var(--accent)] font-theme-data animate-pulse mb-6">
              Checking system status...
            </div>
          )}

          {/* Tab Navigation */}
          <div className="flex gap-2 mb-6">
            {[
              { id: 'overview' as const, label: 'OVERVIEW' },
              { id: 'components' as const, label: 'COMPONENTS' },
              { id: 'uptime' as const, label: 'UPTIME' },
              { id: 'incidents' as const, label: 'INCIDENTS' },
            ].map((tab) => (
              <button
                key={tab.id}
                onClick={() => setActiveTab(tab.id)}
                className={`px-4 py-2 font-theme-data text-sm border transition-colors ${
                  activeTab === tab.id
                    ? 'border-[var(--accent)] bg-[var(--accent)]/10 text-[var(--accent)]'
                    : 'border-[var(--accent)]/30 text-text-muted hover:text-text'
                }`}
              >
                [{tab.label}]
              </button>
            ))}
          </div>

          {/* Overview Tab */}
          {activeTab === 'overview' && summary && (
            <div className="space-y-6">
              {/* Component Summary Table */}
              <div className="border border-[var(--accent)]/20 rounded bg-surface/30">
                <div className="p-4 border-b border-[var(--accent)]/20">
                  <h3 className="font-theme-data text-[var(--acid-cyan)] text-sm">
                    Component Health Summary
                  </h3>
                </div>
                <div className="divide-y divide-acid-green/10">
                  {summary.components.map((c) => (
                    <div key={c.id} className="flex items-center justify-between p-4">
                      <div className="flex items-center gap-3">
                        <div
                          className={`w-2.5 h-2.5 rounded-full ${STATUS_DOT[c.status] || STATUS_DOT.operational}`}
                        />
                        <div>
                          <span className="font-theme-data text-sm text-text">{c.name}</span>
                          {c.message && (
                            <span className="ml-2 font-theme-data text-xs text-text-muted">
                              ({c.message})
                            </span>
                          )}
                        </div>
                      </div>
                      <div className="flex items-center gap-4">
                        {c.response_time_ms !== null && (
                          <span className="font-theme-data text-xs text-text-muted">
                            {c.response_time_ms.toFixed(1)}ms
                          </span>
                        )}
                        <span
                          className={`font-theme-data text-xs capitalize ${STATUS_COLORS[c.status] || STATUS_COLORS.operational}`}
                        >
                          {c.status.replace(/_/g, ' ')}
                        </span>
                      </div>
                    </div>
                  ))}
                </div>
              </div>

              {/* System Info */}
              <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
                <div className="p-4 border border-[var(--accent)]/20 rounded bg-surface/30">
                  <div className="font-theme-data text-xs text-text-muted mb-1">Server Uptime</div>
                  <div className="font-theme-data text-lg text-[var(--accent)]">
                    {summary.uptime_formatted}
                  </div>
                </div>
                <div className="p-4 border border-[var(--accent)]/20 rounded bg-surface/30">
                  <div className="font-theme-data text-xs text-text-muted mb-1">Last Check</div>
                  <div className="font-theme-data text-lg text-text">
                    {lastRefresh.toLocaleTimeString()}
                  </div>
                </div>
                <div className="p-4 border border-[var(--accent)]/20 rounded bg-surface/30">
                  <div className="font-theme-data text-xs text-text-muted mb-1">Components</div>
                  <div className="font-theme-data text-lg">
                    <span className="text-[var(--accent)]">{operationalCount}</span>
                    <span className="text-text-muted">/{totalCount} operational</span>
                  </div>
                </div>
              </div>
            </div>
          )}

          {/* Components Detail Tab */}
          {activeTab === 'components' && summary && (
            <div className="space-y-4">
              {summary.components.map((c) => (
                <div
                  key={c.id}
                  className={`p-5 border rounded ${STATUS_BG[c.status] || STATUS_BG.operational}`}
                >
                  <div className="flex items-start justify-between">
                    <div>
                      <div className="flex items-center gap-2 mb-2">
                        <div
                          className={`w-2.5 h-2.5 rounded-full ${STATUS_DOT[c.status] || STATUS_DOT.operational}`}
                        />
                        <h3 className="font-theme-data text-text font-bold">{c.name}</h3>
                      </div>
                      <p className="font-theme-data text-xs text-text-muted">
                        {c.description || `Component: ${c.id}`}
                      </p>
                      {c.message && (
                        <p className="font-theme-data text-xs text-text-muted/70 mt-1">
                          {c.message}
                        </p>
                      )}
                    </div>
                    <div className="text-right">
                      <span
                        className={`font-theme-data text-sm capitalize font-bold ${STATUS_COLORS[c.status] || STATUS_COLORS.operational}`}
                      >
                        {c.status.replace(/_/g, ' ')}
                      </span>
                      {c.response_time_ms !== null && (
                        <div className="font-theme-data text-xs text-text-muted mt-1">
                          {c.response_time_ms.toFixed(1)}ms response
                        </div>
                      )}
                    </div>
                  </div>
                </div>
              ))}
            </div>
          )}

          {/* Uptime Tab */}
          {activeTab === 'uptime' && (
            <div className="space-y-6">
              {uptimeLoading ? (
                <div className="text-center py-8 text-[var(--accent)] font-theme-data animate-pulse">
                  Loading uptime history...
                </div>
              ) : uptime ? (
                <>
                  <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
                    {Object.entries(uptime.periods).map(([period, data]) => (
                      <div
                        key={period}
                        className="p-4 border border-[var(--accent)]/20 rounded bg-surface/30 text-center"
                      >
                        <div className="font-theme-data text-xs text-text-muted mb-2 uppercase">
                          {period}
                        </div>
                        <div
                          className={`font-theme-data text-2xl font-bold ${
                            data.uptime_percent >= 99.9
                              ? 'text-[var(--accent)]'
                              : data.uptime_percent >= 99.0
                                ? 'text-yellow-400'
                                : 'text-red-400'
                          }`}
                        >
                          {data.uptime_percent.toFixed(2)}%
                        </div>
                        <div className="font-theme-data text-xs text-text-muted mt-1">
                          {data.incidents} incident{data.incidents !== 1 ? 's' : ''}
                        </div>
                        {/* Visual uptime bar */}
                        <div className="mt-3 h-2 bg-bg rounded-full overflow-hidden">
                          <div
                            className={`h-full rounded-full ${
                              data.uptime_percent >= 99.9
                                ? 'bg-[var(--accent)]'
                                : data.uptime_percent >= 99.0
                                  ? 'bg-yellow-400'
                                  : 'bg-red-400'
                            }`}
                            style={{ width: `${Math.max(0, data.uptime_percent)}%` }}
                          />
                        </div>
                      </div>
                    ))}
                  </div>

                  {/* SLA Thresholds Reference */}
                  <div className="p-4 border border-[var(--accent)]/20 rounded bg-surface/30">
                    <h3 className="font-theme-data text-[var(--acid-cyan)] text-sm mb-3">
                      SLA Reference
                    </h3>
                    <div className="grid grid-cols-3 gap-4 font-theme-data text-xs">
                      <div>
                        <span className="text-[var(--accent)]">99.99%</span>
                        <span className="text-text-muted ml-2">= 4.3m downtime/mo</span>
                      </div>
                      <div>
                        <span className="text-yellow-400">99.9%</span>
                        <span className="text-text-muted ml-2">= 43m downtime/mo</span>
                      </div>
                      <div>
                        <span className="text-orange-400">99.0%</span>
                        <span className="text-text-muted ml-2">= 7.3h downtime/mo</span>
                      </div>
                    </div>
                  </div>
                </>
              ) : (
                <div className="p-8 border border-[var(--accent)]/20 rounded text-center">
                  <p className="font-theme-data text-text-muted">Uptime data unavailable.</p>
                </div>
              )}
            </div>
          )}

          {/* Incidents Tab */}
          {activeTab === 'incidents' && (
            <div className="space-y-6">
              {incidentsLoading ? (
                <div className="text-center py-8 text-[var(--accent)] font-theme-data animate-pulse">
                  Loading incidents...
                </div>
              ) : incidents ? (
                <>
                  {/* Active Incidents */}
                  <div>
                    <h3 className="font-theme-data text-[var(--acid-cyan)] text-sm mb-3">
                      Active Incidents
                    </h3>
                    {incidents.active.length === 0 ? (
                      <div className="p-6 border border-[var(--accent)]/20 rounded text-center">
                        <div className="text-[var(--accent)] font-theme-data text-sm">
                          No active incidents
                        </div>
                        <div className="text-text-muted font-theme-data text-xs mt-1">
                          All systems operating normally.
                        </div>
                      </div>
                    ) : (
                      <div className="space-y-3">
                        {incidents.active.map((inc) => (
                          <div
                            key={inc.id}
                            className="p-4 border border-red-500/30 rounded bg-red-500/5"
                          >
                            <div className="flex items-start justify-between mb-2">
                              <span className="font-theme-data text-text font-bold">
                                {inc.title}
                              </span>
                              <div className="flex gap-2">
                                <span className="px-2 py-0.5 text-xs font-theme-data border rounded uppercase border-red-500/30 text-red-400">
                                  {inc.severity}
                                </span>
                                <span className="px-2 py-0.5 text-xs font-theme-data border rounded uppercase border-yellow-500/30 text-yellow-400">
                                  {inc.status}
                                </span>
                              </div>
                            </div>
                            <div className="font-theme-data text-xs text-text-muted">
                              Components: {inc.components.join(', ')}
                            </div>
                            <div className="font-theme-data text-xs text-text-muted/60 mt-1">
                              Started: {new Date(inc.created_at).toLocaleString()}
                            </div>
                          </div>
                        ))}
                      </div>
                    )}
                  </div>

                  {/* Recent Incidents */}
                  <div>
                    <h3 className="font-theme-data text-[var(--acid-cyan)] text-sm mb-3">
                      Recent Incidents (7d)
                    </h3>
                    {incidents.recent.length === 0 ? (
                      <div className="p-6 border border-[var(--accent)]/20 rounded text-center">
                        <div className="font-theme-data text-text-muted text-sm">
                          No recent incidents in the past 7 days.
                        </div>
                      </div>
                    ) : (
                      <div className="space-y-3">
                        {incidents.recent.map((inc) => (
                          <div
                            key={inc.id}
                            className="p-4 border border-[var(--accent)]/20 rounded bg-surface/30"
                          >
                            <div className="flex items-start justify-between mb-2">
                              <span className="font-theme-data text-text text-sm">{inc.title}</span>
                              <span
                                className={`px-2 py-0.5 text-xs font-theme-data border rounded uppercase ${
                                  inc.resolved_at
                                    ? 'border-[var(--accent)]/30 text-[var(--accent)]'
                                    : 'border-yellow-500/30 text-yellow-400'
                                }`}
                              >
                                {inc.resolved_at ? 'resolved' : inc.status}
                              </span>
                            </div>
                            <div className="font-theme-data text-xs text-text-muted">
                              {new Date(inc.created_at).toLocaleString()}
                              {inc.resolved_at &&
                                ` - ${new Date(inc.resolved_at).toLocaleString()}`}
                            </div>
                          </div>
                        ))}
                      </div>
                    )}
                  </div>

                  {/* Scheduled Maintenance */}
                  {incidents.scheduled_maintenance.length > 0 && (
                    <div>
                      <h3 className="font-theme-data text-blue-400 text-sm mb-3">
                        Scheduled Maintenance
                      </h3>
                      <div className="space-y-3">
                        {incidents.scheduled_maintenance.map((inc) => (
                          <div
                            key={inc.id}
                            className="p-4 border border-blue-500/30 rounded bg-blue-500/5"
                          >
                            <span className="font-theme-data text-text text-sm">{inc.title}</span>
                            <div className="font-theme-data text-xs text-text-muted mt-1">
                              Scheduled: {new Date(inc.created_at).toLocaleString()}
                            </div>
                          </div>
                        ))}
                      </div>
                    </div>
                  )}
                </>
              ) : (
                <div className="p-8 border border-[var(--accent)]/20 rounded text-center">
                  <p className="font-theme-data text-text-muted">Incident data unavailable.</p>
                </div>
              )}
            </div>
          )}
        </div>

        {/* Footer */}
        <footer className="text-center text-xs font-theme-data py-8 border-t border-[var(--accent)]/20 mt-8">
          <div className="text-[var(--accent)]/50 mb-2">{'='.repeat(40)}</div>
          <p className="text-text-muted">
            {'>'} ARAGORA // SYSTEM STATUS // Auto-refreshes every 30s
          </p>
        </footer>
      </main>
    </>
  );
}
