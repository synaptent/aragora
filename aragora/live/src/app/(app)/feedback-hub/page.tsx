'use client';

import { useState } from 'react';
import Link from 'next/link';
import { Scanlines, CRTVignette } from '@/components/MatrixRain';
import { PanelErrorBoundary } from '@/components/PanelErrorBoundary';
import { useSWRFetch } from '@/hooks/useSWRFetch';

// ---------------------------------------------------------------------------
// Types matching feedback_hub.py response shapes
// ---------------------------------------------------------------------------

interface RoutingStats {
  total_routed: number;
  by_source: Record<string, number>;
  by_destination: Record<string, number>;
  by_priority: Record<string, number>;
  avg_latency_ms: number;
  error_count: number;
  success_rate: number;
}

interface HistoryEntry {
  id: string;
  timestamp: string;
  source: string;
  destination: string;
  priority: string;
  status: string;
  content_preview: string;
  latency_ms: number;
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function PriorityBadge({ priority }: { priority: string }) {
  const colors: Record<string, string> = {
    critical: 'text-red-400 bg-red-500/10 border-red-500/30',
    high: 'text-yellow-400 bg-yellow-500/10 border-yellow-500/30',
    medium: 'text-[var(--acid-cyan)] bg-[var(--acid-cyan)]/10 border-[var(--acid-cyan)]/30',
    low: 'text-[var(--text-muted)] bg-[var(--surface)] border-[var(--border)]',
  };

  const style = colors[priority.toLowerCase()] || colors.low;

  return (
    <span className={`px-2 py-0.5 text-[10px] font-theme-data uppercase rounded border ${style}`}>
      {priority}
    </span>
  );
}

function StatusDot({ status }: { status: string }) {
  const color =
    status === 'delivered' || status === 'success'
      ? 'bg-[var(--acid-green)]'
      : status === 'failed' || status === 'error'
        ? 'bg-red-400'
        : status === 'pending'
          ? 'bg-yellow-400'
          : 'bg-[var(--text-muted)]';

  return (
    <div className="flex items-center gap-1.5">
      <span className={`w-1.5 h-1.5 rounded-full ${color}`} />
      <span className="text-xs font-theme-data text-[var(--text-muted)]">{status}</span>
    </div>
  );
}

function BarChart({
  data,
  colorFn,
}: {
  data: [string, number][];
  colorFn?: (key: string) => string;
}) {
  if (data.length === 0)
    return <p className="text-xs font-theme-data text-[var(--text-muted)]">No data</p>;

  const maxValue = Math.max(...data.map(([, v]) => v));

  return (
    <div className="space-y-2">
      {data.map(([label, count]) => (
        <div key={label} className="flex items-center gap-3">
          <span
            className="text-[10px] font-theme-data text-[var(--text-muted)] w-28 truncate text-right"
            title={label}
          >
            {label}
          </span>
          <div className="flex-1 h-3 bg-[var(--bg)] rounded-full overflow-hidden">
            <div
              className={`h-full rounded-full transition-all ${colorFn ? colorFn(label) : 'bg-[var(--acid-green)]/60'}`}
              style={{ width: `${maxValue > 0 ? (count / maxValue) * 100 : 0}%` }}
            />
          </div>
          <span className="text-[10px] font-theme-data text-[var(--text)] w-10 text-right">
            {count}
          </span>
        </div>
      ))}
    </div>
  );
}

function formatTimestamp(ts: string | null): string {
  if (!ts) return '--';
  try {
    return new Date(ts).toLocaleString();
  } catch {
    return ts;
  }
}

// ---------------------------------------------------------------------------
// Page Component
// ---------------------------------------------------------------------------

type ActiveTab = 'overview' | 'history';

export default function FeedbackHubPage() {
  const [activeTab, setActiveTab] = useState<ActiveTab>('overview');
  const [historyLimit, setHistoryLimit] = useState(50);

  // Fetch routing stats
  const {
    data: statsResponse,
    isLoading: statsLoading,
    error: statsError,
  } = useSWRFetch<{ data: RoutingStats }>('/api/v1/feedback-hub/stats', { refreshInterval: 15000 });

  // Fetch routing history
  const { data: historyResponse, isLoading: historyLoading } = useSWRFetch<{
    data: HistoryEntry[];
  }>(activeTab === 'history' ? `/api/v1/feedback-hub/history?limit=${historyLimit}` : null, {
    refreshInterval: 30000,
  });

  const stats = statsResponse?.data;
  const history = historyResponse?.data ?? [];

  const sourceEntries = stats?.by_source
    ? Object.entries(stats.by_source).sort(([, a], [, b]) => b - a)
    : [];
  const destEntries = stats?.by_destination
    ? Object.entries(stats.by_destination).sort(([, a], [, b]) => b - a)
    : [];
  const priorityEntries = stats?.by_priority
    ? Object.entries(stats.by_priority).sort(([, a], [, b]) => b - a)
    : [];

  return (
    <>
      <Scanlines opacity={0.02} />
      <CRTVignette />

      <main className="min-h-screen bg-[var(--bg)] text-[var(--text)] relative z-10">
        <div className="container mx-auto px-4 py-6">
          {/* Header */}
          <div className="mb-6">
            <div className="flex items-center gap-2 mb-2">
              <Link
                href="/self-improve"
                className="text-xs font-theme-data text-[var(--text-muted)] hover:text-[var(--acid-green)] transition-colors"
              >
                Self-Improve
              </Link>
              <span className="text-[var(--text-muted)]">/</span>
              <span className="text-xs font-theme-data text-[var(--acid-green)]">Feedback Hub</span>
            </div>
            <h1 className="text-xl font-theme-data text-[var(--acid-green)]">{'>'} FEEDBACK HUB</h1>
            <p className="text-xs text-[var(--text-muted)] font-theme-data mt-1">
              Unified feedback routing hub connecting all self-improvement loops. Outcome feedback,
              calibration signals, and Nomic Loop goals flow through here.
            </p>
          </div>

          {/* Error State */}
          {statsError && (
            <div className="mb-6 p-4 bg-red-500/10 border border-red-500/30 text-red-400 font-theme-data text-sm">
              Failed to load feedback hub data. The feedback hub module may not be available.
            </div>
          )}

          {/* Tabs */}
          <div className="flex gap-2 mb-6">
            {[
              { key: 'overview' as const, label: 'OVERVIEW' },
              { key: 'history' as const, label: 'ROUTING HISTORY' },
            ].map(({ key, label }) => (
              <button
                key={key}
                onClick={() => setActiveTab(key)}
                className={`px-4 py-2 font-theme-data text-sm border transition-colors ${
                  activeTab === key
                    ? 'border-[var(--acid-green)] bg-[var(--acid-green)]/10 text-[var(--acid-green)]'
                    : 'border-[var(--border)] text-[var(--text-muted)] hover:text-[var(--text)]'
                }`}
              >
                [{label}]
              </button>
            ))}
          </div>

          <PanelErrorBoundary panelName="Feedback Hub">
            {/* Overview Tab */}
            {activeTab === 'overview' && (
              <div>
                {/* Summary Stats */}
                <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-6">
                  <div className="p-4 bg-[var(--surface)] border border-[var(--border)] text-center">
                    <div className="text-2xl font-theme-data text-[var(--acid-green)]">
                      {statsLoading ? '-' : (stats?.total_routed ?? 0)}
                    </div>
                    <div className="text-[10px] font-theme-data text-[var(--text-muted)] uppercase">
                      Total Routed
                    </div>
                  </div>
                  <div className="p-4 bg-[var(--surface)] border border-[var(--border)] text-center">
                    <div
                      className={`text-2xl font-theme-data ${
                        (stats?.success_rate ?? 0) >= 0.95
                          ? 'text-[var(--acid-green)]'
                          : (stats?.success_rate ?? 0) >= 0.8
                            ? 'text-yellow-400'
                            : 'text-red-400'
                      }`}
                    >
                      {statsLoading
                        ? '-'
                        : stats?.success_rate != null
                          ? `${(stats.success_rate * 100).toFixed(1)}%`
                          : '--'}
                    </div>
                    <div className="text-[10px] font-theme-data text-[var(--text-muted)] uppercase">
                      Success Rate
                    </div>
                  </div>
                  <div className="p-4 bg-[var(--surface)] border border-[var(--border)] text-center">
                    <div className="text-2xl font-theme-data text-[var(--acid-cyan)]">
                      {statsLoading
                        ? '-'
                        : stats?.avg_latency_ms != null
                          ? `${Math.round(stats.avg_latency_ms)}ms`
                          : '--'}
                    </div>
                    <div className="text-[10px] font-theme-data text-[var(--text-muted)] uppercase">
                      Avg Latency
                    </div>
                  </div>
                  <div className="p-4 bg-[var(--surface)] border border-[var(--border)] text-center">
                    <div
                      className={`text-2xl font-theme-data ${(stats?.error_count ?? 0) > 0 ? 'text-red-400' : 'text-[var(--acid-green)]'}`}
                    >
                      {statsLoading ? '-' : (stats?.error_count ?? 0)}
                    </div>
                    <div className="text-[10px] font-theme-data text-[var(--text-muted)] uppercase">
                      Errors
                    </div>
                  </div>
                </div>

                {/* Charts */}
                <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
                  {/* By Source */}
                  <div className="p-4 bg-[var(--surface)] border border-[var(--border)]">
                    <h3 className="text-sm font-theme-data text-[var(--acid-green)] uppercase mb-4">
                      By Source
                    </h3>
                    {statsLoading ? (
                      <div className="h-32 flex items-center justify-center text-[var(--text-muted)] font-theme-data animate-pulse">
                        Loading...
                      </div>
                    ) : (
                      <BarChart data={sourceEntries} colorFn={() => 'bg-[var(--acid-green)]/60'} />
                    )}
                  </div>

                  {/* By Destination */}
                  <div className="p-4 bg-[var(--surface)] border border-[var(--border)]">
                    <h3 className="text-sm font-theme-data text-[var(--acid-green)] uppercase mb-4">
                      By Destination
                    </h3>
                    {statsLoading ? (
                      <div className="h-32 flex items-center justify-center text-[var(--text-muted)] font-theme-data animate-pulse">
                        Loading...
                      </div>
                    ) : (
                      <BarChart data={destEntries} colorFn={() => 'bg-[var(--acid-cyan)]/60'} />
                    )}
                  </div>

                  {/* By Priority */}
                  <div className="p-4 bg-[var(--surface)] border border-[var(--border)]">
                    <h3 className="text-sm font-theme-data text-[var(--acid-green)] uppercase mb-4">
                      By Priority
                    </h3>
                    {statsLoading ? (
                      <div className="h-32 flex items-center justify-center text-[var(--text-muted)] font-theme-data animate-pulse">
                        Loading...
                      </div>
                    ) : (
                      <BarChart
                        data={priorityEntries}
                        colorFn={(key) =>
                          key === 'critical'
                            ? 'bg-red-400/60'
                            : key === 'high'
                              ? 'bg-yellow-400/60'
                              : key === 'medium'
                                ? 'bg-[var(--acid-cyan)]/60'
                                : 'bg-[var(--text-muted)]/40'
                        }
                      />
                    )}
                  </div>
                </div>
              </div>
            )}

            {/* History Tab */}
            {activeTab === 'history' && (
              <div>
                <div className="flex items-center gap-3 mb-4">
                  <select
                    value={historyLimit}
                    onChange={(e) => setHistoryLimit(Number(e.target.value))}
                    className="px-3 py-1.5 bg-[var(--surface)] border border-[var(--border)] text-[var(--text)] text-xs font-theme-data rounded focus:outline-none focus:border-[var(--acid-green)]/50"
                  >
                    <option value={20}>Last 20</option>
                    <option value={50}>Last 50</option>
                    <option value={100}>Last 100</option>
                    <option value={200}>Last 200</option>
                  </select>
                  <span className="text-[10px] font-theme-data text-[var(--text-muted)]">
                    {history.length} entries
                  </span>
                </div>

                <div className="bg-[var(--surface)] border border-[var(--border)] overflow-hidden">
                  <div className="overflow-x-auto">
                    <table className="w-full text-sm">
                      <thead>
                        <tr className="text-left text-[10px] font-theme-data text-[var(--text-muted)] uppercase border-b border-[var(--border)]">
                          <th className="px-4 py-3">Time</th>
                          <th className="px-4 py-3">Source</th>
                          <th className="px-4 py-3">Destination</th>
                          <th className="px-4 py-3">Priority</th>
                          <th className="px-4 py-3">Status</th>
                          <th className="px-4 py-3">Latency</th>
                          <th className="px-4 py-3">Preview</th>
                        </tr>
                      </thead>
                      <tbody>
                        {historyLoading ? (
                          <tr>
                            <td
                              colSpan={7}
                              className="px-4 py-12 text-center text-[var(--text-muted)] font-theme-data animate-pulse"
                            >
                              Loading routing history...
                            </td>
                          </tr>
                        ) : history.length === 0 ? (
                          <tr>
                            <td
                              colSpan={7}
                              className="px-4 py-12 text-center text-[var(--text-muted)] font-theme-data"
                            >
                              No routing history available. Run debates with feedback loops enabled.
                            </td>
                          </tr>
                        ) : (
                          history.map((entry) => (
                            <tr
                              key={entry.id}
                              className="border-b border-[var(--border)]/50 hover:bg-[var(--acid-green)]/5 transition-colors"
                            >
                              <td className="px-4 py-3 text-xs font-theme-data text-[var(--text-muted)]">
                                {formatTimestamp(entry.timestamp)}
                              </td>
                              <td className="px-4 py-3">
                                <span className="text-xs font-theme-data text-[var(--acid-cyan)]">
                                  {entry.source}
                                </span>
                              </td>
                              <td className="px-4 py-3">
                                <span className="text-xs font-theme-data text-purple-400">
                                  {entry.destination}
                                </span>
                              </td>
                              <td className="px-4 py-3">
                                <PriorityBadge priority={entry.priority} />
                              </td>
                              <td className="px-4 py-3">
                                <StatusDot status={entry.status} />
                              </td>
                              <td className="px-4 py-3 text-xs font-theme-data text-[var(--text-muted)]">
                                {entry.latency_ms}ms
                              </td>
                              <td className="px-4 py-3 text-xs font-theme-data text-[var(--text-muted)] max-w-[200px] truncate">
                                {entry.content_preview}
                              </td>
                            </tr>
                          ))
                        )}
                      </tbody>
                    </table>
                  </div>
                </div>
              </div>
            )}
          </PanelErrorBoundary>

          {/* Quick Links */}
          <div className="mt-8 flex flex-wrap gap-3">
            <Link
              href="/self-improve"
              className="px-3 py-2 text-xs font-theme-data bg-[var(--surface)] text-[var(--text-muted)] border border-[var(--border)] hover:border-[var(--acid-green)]/30 transition-colors"
            >
              Self-Improve
            </Link>
            <Link
              href="/nomic-control"
              className="px-3 py-2 text-xs font-theme-data bg-[var(--surface)] text-[var(--text-muted)] border border-[var(--border)] hover:border-[var(--acid-green)]/30 transition-colors"
            >
              Nomic Control
            </Link>
            <Link
              href="/calibration"
              className="px-3 py-2 text-xs font-theme-data bg-[var(--surface)] text-[var(--text-muted)] border border-[var(--border)] hover:border-[var(--acid-green)]/30 transition-colors"
            >
              Calibration
            </Link>
          </div>
        </div>

        {/* Footer */}
        <footer className="text-center text-xs font-theme-data py-8 border-t border-[var(--acid-green)]/20 mt-8">
          <div className="text-[var(--acid-green)]/50 mb-2" aria-hidden="true">
            {'='.repeat(40)}
          </div>
          <p className="text-[var(--text-muted)]">{'>'} ARAGORA // FEEDBACK HUB</p>
        </footer>
      </main>
    </>
  );
}
