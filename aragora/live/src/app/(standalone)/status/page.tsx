'use client';

import { useState, useEffect, useCallback } from 'react';

/**
 * Public Status Page (Standalone).
 *
 * A self-contained status page for displaying Aragora platform health.
 * Uses the /api/v1/status/* endpoints which are public (no auth required).
 *
 * Designed to be hosted independently at status.aragora.ai.
 */

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface ComponentStatus {
  id: string;
  name: string;
  description: string;
  status: string;
  response_time_ms: number | null;
  last_check: string | null;
  message: string | null;
}

interface SLALatency {
  p50: number;
  p95: number;
  p99: number;
  count: number;
  mean: number;
  min: number;
  max: number;
}

interface SLAErrorRate {
  total_requests: number;
  error_count: number;
  error_rate: number;
}

interface StatusData {
  status: string; // operational | degraded | down | maintenance
  status_detail: string;
  message: string;
  uptime_seconds: number;
  uptime_formatted: string;
  timestamp: string;
  components_summary: { total: number; operational: number; degraded: number; down: number };
  sla: { latency: SLALatency; error_rate: SLAErrorRate };
}

interface UptimePeriod {
  uptime_percent: number;
  total_requests: number;
  error_count: number;
  incidents: number;
}

interface UptimeData {
  current: { status: string; uptime_seconds: number };
  periods: Record<string, UptimePeriod>;
  timestamp: string;
}

interface IncidentUpdate {
  id: string;
  status: string;
  message: string;
  timestamp: string;
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
  timestamp: string;
}

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const STATUS_COLORS: Record<string, { bg: string; text: string; dot: string; border: string }> = {
  operational: {
    bg: 'bg-green-500/10',
    text: 'text-green-400',
    dot: 'bg-green-400',
    border: 'border-green-500/30',
  },
  degraded: {
    bg: 'bg-yellow-500/10',
    text: 'text-yellow-400',
    dot: 'bg-yellow-400',
    border: 'border-yellow-500/30',
  },
  partial_outage: {
    bg: 'bg-orange-500/10',
    text: 'text-orange-400',
    dot: 'bg-orange-400',
    border: 'border-orange-500/30',
  },
  down: {
    bg: 'bg-red-500/10',
    text: 'text-red-400',
    dot: 'bg-red-400',
    border: 'border-red-500/30',
  },
  major_outage: {
    bg: 'bg-red-500/10',
    text: 'text-red-400',
    dot: 'bg-red-400',
    border: 'border-red-500/30',
  },
  maintenance: {
    bg: 'bg-blue-500/10',
    text: 'text-blue-400',
    dot: 'bg-blue-400',
    border: 'border-blue-500/30',
  },
};

function getStatusStyle(status: string) {
  return STATUS_COLORS[status] || STATUS_COLORS.operational;
}

function getApiBase(): string {
  if (typeof window !== 'undefined' && window.location.hostname === 'localhost') {
    return 'http://localhost:8080';
  }
  return '';
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export default function PublicStatusPage() {
  const [statusData, setStatusData] = useState<StatusData | null>(null);
  const [components, setComponents] = useState<ComponentStatus[]>([]);
  const [uptime, setUptime] = useState<UptimeData | null>(null);
  const [incidents, setIncidents] = useState<IncidentsData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [lastRefresh, setLastRefresh] = useState<Date>(new Date());

  const apiBase = getApiBase();

  const fetchAll = useCallback(async () => {
    try {
      const [statusRes, componentsRes, uptimeRes, incidentsRes] = await Promise.allSettled([
        fetch(`${apiBase}/api/v1/status`),
        fetch(`${apiBase}/api/v1/status/components`),
        fetch(`${apiBase}/api/v1/status/uptime`),
        fetch(`${apiBase}/api/v1/status/incidents`),
      ]);

      if (statusRes.status === 'fulfilled' && statusRes.value.ok) {
        const json = await statusRes.value.json();
        setStatusData(json.data);
      }

      if (componentsRes.status === 'fulfilled' && componentsRes.value.ok) {
        const json = await componentsRes.value.json();
        setComponents(json.data?.components || []);
      }

      if (uptimeRes.status === 'fulfilled' && uptimeRes.value.ok) {
        const json = await uptimeRes.value.json();
        setUptime(json.data);
      }

      if (incidentsRes.status === 'fulfilled' && incidentsRes.value.ok) {
        const json = await incidentsRes.value.json();
        setIncidents(json.data);
      }

      setError(null);
      setLastRefresh(new Date());
    } catch {
      setError('Failed to fetch status data');
    } finally {
      setLoading(false);
    }
  }, [apiBase]);

  // Load on mount, auto-refresh every 30 seconds
  useEffect(() => {
    fetchAll();
    const interval = setInterval(fetchAll, 30_000);
    return () => clearInterval(interval);
  }, [fetchAll]);

  const overallStatus = statusData?.status || 'operational';
  const style = getStatusStyle(overallStatus);

  if (loading && !statusData) {
    return (
      <div className="min-h-screen bg-slate-950 flex items-center justify-center">
        <div className="text-green-400 font-theme-data animate-pulse text-lg">
          Checking system status...
        </div>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-slate-950 text-slate-200">
      <div className="max-w-4xl mx-auto px-4 py-8">
        {/* Header */}
        <header className="text-center mb-8">
          <h1 className="text-3xl font-theme-data font-bold text-white mb-2">Aragora Status</h1>
          <p className="text-slate-400 font-theme-data text-sm">
            Platform health and SLA monitoring
          </p>
        </header>

        {/* Overall Status Banner */}
        <div className={`p-6 rounded-lg border mb-8 ${style.bg} ${style.border}`}>
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-3">
              <div className={`w-3 h-3 rounded-full animate-pulse ${style.dot}`} />
              <span className={`text-xl font-theme-data font-bold ${style.text}`}>
                {statusData?.message || 'All Systems Operational'}
              </span>
            </div>
            <div className="text-right font-theme-data text-sm text-slate-400">
              {statusData && (
                <div>
                  Uptime: <span className="text-slate-200">{statusData.uptime_formatted}</span>
                </div>
              )}
              {statusData && (
                <div className="text-xs mt-1">
                  {statusData.components_summary.operational}/{statusData.components_summary.total}{' '}
                  operational
                </div>
              )}
            </div>
          </div>
        </div>

        {error && (
          <div className="p-4 border border-red-500/30 rounded-lg bg-red-500/5 mb-6 text-center font-theme-data text-red-400 text-sm">
            {error}
          </div>
        )}

        {/* Component Status Grid */}
        <section className="mb-8">
          <h2 className="text-lg font-theme-data text-slate-300 mb-4">Components</h2>
          <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
            {components.map((c) => {
              const cs = getStatusStyle(c.status);
              return (
                <div key={c.id} className={`p-3 rounded-lg border ${cs.bg} ${cs.border}`}>
                  <div className="flex items-center gap-2 mb-1">
                    <div className={`w-2 h-2 rounded-full ${cs.dot}`} />
                    <span className="font-theme-data text-sm text-slate-200 truncate">
                      {c.name}
                    </span>
                  </div>
                  <div className="flex items-center justify-between">
                    <span className={`text-xs font-theme-data capitalize ${cs.text}`}>
                      {c.status.replace(/_/g, ' ')}
                    </span>
                    {c.response_time_ms !== null && (
                      <span className="text-xs font-theme-data text-slate-500">
                        {c.response_time_ms.toFixed(0)}ms
                      </span>
                    )}
                  </div>
                  {c.message && (
                    <div className="text-xs font-theme-data text-slate-500 mt-1 truncate">
                      {c.message}
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        </section>

        {/* Uptime Chart */}
        {uptime && (
          <section className="mb-8">
            <h2 className="text-lg font-theme-data text-slate-300 mb-4">Uptime</h2>
            <div className="grid grid-cols-3 gap-4">
              {Object.entries(uptime.periods).map(([period, data]) => {
                const pct = data.uptime_percent;
                const color =
                  pct >= 99.9 ? 'text-green-400' : pct >= 99.0 ? 'text-yellow-400' : 'text-red-400';
                const barColor =
                  pct >= 99.9 ? 'bg-green-400' : pct >= 99.0 ? 'bg-yellow-400' : 'bg-red-400';

                return (
                  <div
                    key={period}
                    className="p-4 border border-slate-700 rounded-lg bg-slate-900/50 text-center"
                  >
                    <div className="font-theme-data text-xs text-slate-500 mb-2 uppercase">
                      {period}
                    </div>
                    <div className={`font-theme-data text-2xl font-bold ${color}`}>
                      {pct.toFixed(2)}%
                    </div>
                    <div className="font-theme-data text-xs text-slate-500 mt-1">
                      {data.total_requests > 0
                        ? `${data.total_requests.toLocaleString()} requests`
                        : 'No data yet'}
                    </div>
                    {/* Uptime bar */}
                    <div className="mt-3 h-1.5 bg-slate-800 rounded-full overflow-hidden">
                      <div
                        className={`h-full rounded-full ${barColor}`}
                        style={{ width: `${Math.max(0, pct)}%` }}
                      />
                    </div>
                  </div>
                );
              })}
            </div>

            {/* SLA Reference */}
            <div className="mt-4 p-3 border border-slate-700 rounded-lg bg-slate-900/50">
              <div className="font-theme-data text-xs text-slate-500 mb-2">SLA Targets</div>
              <div className="grid grid-cols-3 gap-4 font-theme-data text-xs">
                <div>
                  <span className="text-green-400">99.9%</span>
                  <span className="text-slate-600 ml-2">= 43m downtime/mo</span>
                </div>
                <div>
                  <span className="text-yellow-400">99.5%</span>
                  <span className="text-slate-600 ml-2">= 3.6h downtime/mo</span>
                </div>
                <div>
                  <span className="text-orange-400">99.0%</span>
                  <span className="text-slate-600 ml-2">= 7.3h downtime/mo</span>
                </div>
              </div>
            </div>
          </section>
        )}

        {/* SLA Metrics */}
        {statusData?.sla && statusData.sla.latency.count > 0 && (
          <section className="mb-8">
            <h2 className="text-lg font-theme-data text-slate-300 mb-4">Performance (24h)</h2>
            <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
              <div className="p-4 border border-slate-700 rounded-lg bg-slate-900/50">
                <div className="font-theme-data text-xs text-slate-500 mb-1">p50 Latency</div>
                <div className="font-theme-data text-lg text-slate-200">
                  {(statusData.sla.latency.p50 * 1000).toFixed(0)}ms
                </div>
              </div>
              <div className="p-4 border border-slate-700 rounded-lg bg-slate-900/50">
                <div className="font-theme-data text-xs text-slate-500 mb-1">p95 Latency</div>
                <div className="font-theme-data text-lg text-slate-200">
                  {(statusData.sla.latency.p95 * 1000).toFixed(0)}ms
                </div>
              </div>
              <div className="p-4 border border-slate-700 rounded-lg bg-slate-900/50">
                <div className="font-theme-data text-xs text-slate-500 mb-1">p99 Latency</div>
                <div className="font-theme-data text-lg text-slate-200">
                  {(statusData.sla.latency.p99 * 1000).toFixed(0)}ms
                </div>
              </div>
              <div className="p-4 border border-slate-700 rounded-lg bg-slate-900/50">
                <div className="font-theme-data text-xs text-slate-500 mb-1">Error Rate</div>
                <div
                  className={`font-theme-data text-lg ${
                    statusData.sla.error_rate.error_rate <= 0.001
                      ? 'text-green-400'
                      : statusData.sla.error_rate.error_rate <= 0.01
                        ? 'text-yellow-400'
                        : 'text-red-400'
                  }`}
                >
                  {(statusData.sla.error_rate.error_rate * 100).toFixed(2)}%
                </div>
              </div>
            </div>
          </section>
        )}

        {/* Incidents Timeline */}
        {incidents && (
          <section className="mb-8">
            <h2 className="text-lg font-theme-data text-slate-300 mb-4">Incidents</h2>

            {/* Active Incidents */}
            {incidents.active.length > 0 ? (
              <div className="space-y-3 mb-6">
                {incidents.active.map((inc) => (
                  <div
                    key={inc.id}
                    className="p-4 border border-red-500/30 rounded-lg bg-red-500/5"
                  >
                    <div className="flex items-start justify-between mb-2">
                      <span className="font-theme-data text-slate-200 font-bold">{inc.title}</span>
                      <div className="flex gap-2">
                        <span className="px-2 py-0.5 text-xs font-theme-data border rounded uppercase border-red-500/30 text-red-400">
                          {inc.severity}
                        </span>
                        <span className="px-2 py-0.5 text-xs font-theme-data border rounded uppercase border-yellow-500/30 text-yellow-400">
                          {inc.status}
                        </span>
                      </div>
                    </div>
                    <div className="font-theme-data text-xs text-slate-500">
                      Components: {inc.components.join(', ')}
                    </div>
                    <div className="font-theme-data text-xs text-slate-600 mt-1">
                      Started: {new Date(inc.created_at).toLocaleString()}
                    </div>
                    {/* Incident Timeline */}
                    {inc.updates.length > 0 && (
                      <div className="mt-3 border-t border-red-500/20 pt-3 space-y-2">
                        {inc.updates.map((u) => (
                          <div key={u.id} className="flex gap-2 text-xs font-theme-data">
                            <span className="text-slate-600 shrink-0">
                              {new Date(u.timestamp).toLocaleTimeString()}
                            </span>
                            <span className="text-yellow-400 uppercase shrink-0">[{u.status}]</span>
                            <span className="text-slate-400">{u.message}</span>
                          </div>
                        ))}
                      </div>
                    )}
                  </div>
                ))}
              </div>
            ) : (
              <div className="p-6 border border-green-500/20 rounded-lg bg-green-500/5 text-center mb-6">
                <div className="text-green-400 font-theme-data text-sm">No active incidents</div>
                <div className="text-slate-500 font-theme-data text-xs mt-1">
                  All systems operating normally.
                </div>
              </div>
            )}

            {/* Recent Resolved Incidents */}
            {incidents.recent.length > 0 && (
              <div>
                <h3 className="font-theme-data text-sm text-slate-400 mb-3">Recent (7 days)</h3>
                <div className="space-y-2">
                  {incidents.recent.map((inc) => (
                    <div
                      key={inc.id}
                      className="p-3 border border-slate-700 rounded-lg bg-slate-900/50"
                    >
                      <div className="flex items-center justify-between">
                        <span className="font-theme-data text-sm text-slate-300">{inc.title}</span>
                        <span className="px-2 py-0.5 text-xs font-theme-data border rounded border-green-500/30 text-green-400">
                          resolved
                        </span>
                      </div>
                      <div className="font-theme-data text-xs text-slate-600 mt-1">
                        {new Date(inc.created_at).toLocaleDateString()}
                        {inc.resolved_at && ` - ${new Date(inc.resolved_at).toLocaleDateString()}`}
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            )}
          </section>
        )}

        {/* Footer */}
        <footer className="text-center font-theme-data text-xs text-slate-600 py-8 border-t border-slate-800 mt-8">
          <p>Last updated: {lastRefresh.toLocaleTimeString()} | Auto-refreshes every 30s</p>
          <p className="mt-2">
            <a href="/api/v1/status" className="text-blue-400 hover:text-blue-300">
              JSON API
            </a>
            {' | '}
            <a href="https://aragora.ai" className="text-blue-400 hover:text-blue-300">
              Aragora
            </a>
          </p>
        </footer>
      </div>
    </div>
  );
}
