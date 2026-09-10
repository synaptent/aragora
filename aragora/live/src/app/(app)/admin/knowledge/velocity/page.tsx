'use client';

import { useState, useEffect, useCallback } from 'react';
import Link from 'next/link';
import { Scanlines, CRTVignette } from '@/components/MatrixRain';
import { useBackend } from '@/components/BackendSelector';

interface VelocityData {
  total_entries: number;
  entries_by_adapter: Record<string, number>;
  adapter_count: number;
  daily_growth: { date: string; count: number }[];
  growth_rate: number;
  contradiction_count: number;
  resolution_count: number;
  resolution_rate: number;
  confidence_distribution: Record<string, number>;
  top_topics: { topic: string; count: number }[];
  workspace_id: string;
  timestamp: string;
}

function MetricCard({
  label,
  value,
  sub,
  color = 'acid-green',
}: {
  label: string;
  value: string | number;
  sub?: string;
  color?: string;
}) {
  return (
    <div className="p-4 bg-[var(--surface)] border border-[var(--border)]">
      <div className="font-theme-data text-xs text-[var(--text-muted)] mb-1">{label}</div>
      <div className="font-theme-data text-2xl" style={{ color: `var(--${color})` }}>
        {typeof value === 'number' ? value.toLocaleString() : value}
      </div>
      {sub && <div className="font-theme-data text-xs text-[var(--text-muted)] mt-1">{sub}</div>}
    </div>
  );
}

function HorizontalBar({
  label,
  value,
  max,
  color,
}: {
  label: string;
  value: number;
  max: number;
  color: string;
}) {
  const pct = max > 0 ? Math.min((value / max) * 100, 100) : 0;
  return (
    <div className="flex items-center gap-3 py-1">
      <div className="font-theme-data text-xs text-[var(--text-muted)] w-32 truncate" title={label}>
        {label}
      </div>
      <div className="flex-1 h-4 bg-[var(--bg)] border border-[var(--border)] relative">
        <div
          className="h-full transition-all duration-500"
          style={{ width: `${pct}%`, backgroundColor: `var(--${color})` }}
        />
      </div>
      <div className="font-theme-data text-xs text-[var(--text)] w-16 text-right">
        {value.toLocaleString()}
      </div>
    </div>
  );
}

function AccumulationChart({ data }: { data: { date: string; count: number }[] }) {
  if (!data.length) return null;
  const max = Math.max(...data.map((d) => d.count), 1);
  const chartHeight = 120;

  return (
    <div className="bg-[var(--surface)] border border-[var(--border)] p-4">
      <h3 className="font-theme-data text-sm text-[var(--acid-green)] mb-3">
        KNOWLEDGE ACCUMULATION (7D)
      </h3>
      <div className="flex items-end gap-1" style={{ height: chartHeight }}>
        {data.map((d, i) => {
          const h = max > 0 ? (d.count / max) * chartHeight : 0;
          return (
            <div key={i} className="flex-1 flex flex-col items-center justify-end gap-1">
              <div className="font-theme-data text-[10px] text-[var(--text-muted)]">
                {d.count > 0 ? d.count.toLocaleString() : ''}
              </div>
              <div
                className="w-full bg-[var(--acid-green)] transition-all duration-500"
                style={{ height: Math.max(h, 1) }}
              />
              <div className="font-theme-data text-[10px] text-[var(--text-muted)]">
                {d.date.slice(5)}
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

function ConfidenceHistogram({ distribution }: { distribution: Record<string, number> }) {
  const entries = Object.entries(distribution);
  const max = Math.max(...entries.map(([, v]) => v), 1);
  const chartHeight = 100;
  const colors = ['acid-red', 'acid-yellow', 'acid-yellow', 'acid-cyan', 'acid-green'];

  return (
    <div className="bg-[var(--surface)] border border-[var(--border)] p-4">
      <h3 className="font-theme-data text-sm text-[var(--acid-green)] mb-3">
        CONFIDENCE DISTRIBUTION
      </h3>
      <div className="flex items-end gap-2" style={{ height: chartHeight }}>
        {entries.map(([label, count], i) => {
          const h = max > 0 ? (count / max) * chartHeight : 0;
          return (
            <div key={label} className="flex-1 flex flex-col items-center justify-end gap-1">
              <div className="font-theme-data text-[10px] text-[var(--text-muted)]">
                {count > 0 ? count : ''}
              </div>
              <div
                className="w-full transition-all duration-500"
                style={{
                  height: Math.max(h, 1),
                  backgroundColor: `var(--${colors[i] || 'acid-green'})`,
                }}
              />
              <div className="font-theme-data text-[10px] text-[var(--text-muted)]">{label}</div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

export default function KnowledgeVelocityPage() {
  const { config: backendConfig } = useBackend();
  const [data, setData] = useState<VelocityData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const fetchData = useCallback(async () => {
    try {
      setLoading(true);
      setError(null);
      const res = await fetch(`${backendConfig.api}/api/v1/knowledge/velocity`);
      if (res.ok) {
        setData(await res.json());
      } else {
        setError(`Failed to fetch velocity data (${res.status})`);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to connect');
    } finally {
      setLoading(false);
    }
  }, [backendConfig.api]);

  useEffect(() => {
    fetchData();
  }, [fetchData]);

  const adapterEntries = data
    ? Object.entries(data.entries_by_adapter).sort((a, b) => b[1] - a[1])
    : [];
  const maxAdapterCount = adapterEntries.length > 0 ? adapterEntries[0][1] : 0;

  return (
    <>
      <Scanlines opacity={0.02} />
      <CRTVignette />

      <main className="min-h-screen bg-[var(--bg)] text-[var(--text)] relative z-10">
        <div className="container mx-auto px-4 py-6">
          {/* Breadcrumb */}
          <div className="flex items-center gap-3 mb-2">
            <Link
              href="/dashboard"
              className="text-xs font-theme-data text-[var(--text-muted)] hover:text-[var(--acid-green)] transition-colors"
            >
              DASHBOARD
            </Link>
            <span className="text-xs font-theme-data text-[var(--text-muted)]">/</span>
            <Link
              href="/admin/knowledge"
              className="text-xs font-theme-data text-[var(--text-muted)] hover:text-[var(--acid-green)] transition-colors"
            >
              KNOWLEDGE
            </Link>
            <span className="text-xs font-theme-data text-[var(--text-muted)]">/</span>
            <span className="text-xs font-theme-data text-[var(--acid-green)]">VELOCITY</span>
          </div>

          {/* Header */}
          <div className="flex items-center justify-between mb-6">
            <div>
              <h1 className="text-xl font-theme-data text-[var(--acid-green)] mb-1">
                {'>'} LEARNING VELOCITY
              </h1>
              <p className="text-xs text-[var(--text-muted)] font-theme-data">
                Knowledge Mound growth, adapter contributions, and confidence metrics
              </p>
            </div>
            <button
              onClick={fetchData}
              disabled={loading}
              className="px-4 py-2 text-xs font-theme-data bg-[var(--surface)] text-[var(--acid-green)] border border-[var(--acid-green)]/30 hover:bg-[var(--acid-green)]/10 transition-colors disabled:opacity-50"
            >
              {loading ? 'LOADING...' : 'REFRESH'}
            </button>
          </div>

          {error && (
            <div className="p-4 mb-6 bg-[var(--surface)] border border-red-500/40">
              <p className="text-red-400 font-theme-data text-sm">{error}</p>
            </div>
          )}

          {loading && !data && (
            <div className="text-center py-20">
              <div className="font-theme-data text-[var(--acid-green)] animate-pulse text-sm">
                LOADING VELOCITY DATA...
              </div>
            </div>
          )}

          {data && (
            <>
              {/* KPI Cards */}
              <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-6">
                <MetricCard
                  label="TOTAL ENTRIES"
                  value={data.total_entries}
                  sub={`across ${data.adapter_count} adapters`}
                />
                <MetricCard
                  label="GROWTH RATE"
                  value={`${(data.growth_rate * 100).toFixed(1)}%`}
                  sub="7-day trend"
                  color="acid-cyan"
                />
                <MetricCard
                  label="CONTRADICTIONS"
                  value={data.contradiction_count}
                  sub={`${(data.resolution_rate * 100).toFixed(0)}% resolved`}
                  color="acid-yellow"
                />
                <MetricCard
                  label="RESOLVED"
                  value={data.resolution_count}
                  sub="validated entries"
                  color="acid-green"
                />
              </div>

              {/* Charts Row */}
              <div className="grid grid-cols-1 lg:grid-cols-2 gap-6 mb-6">
                <AccumulationChart data={data.daily_growth} />
                <ConfidenceHistogram distribution={data.confidence_distribution} />
              </div>

              {/* Adapter Contributions */}
              <div className="bg-[var(--surface)] border border-[var(--border)] p-4 mb-6">
                <h3 className="font-theme-data text-sm text-[var(--acid-green)] mb-3">
                  ADAPTER CONTRIBUTIONS
                </h3>
                {adapterEntries.length === 0 ? (
                  <p className="font-theme-data text-xs text-[var(--text-muted)]">
                    No adapter data available yet.
                  </p>
                ) : (
                  <div className="space-y-1">
                    {adapterEntries.slice(0, 15).map(([name, count]) => (
                      <HorizontalBar
                        key={name}
                        label={name}
                        value={count}
                        max={maxAdapterCount}
                        color="acid-cyan"
                      />
                    ))}
                  </div>
                )}
              </div>

              {/* Top Topics */}
              {data.top_topics.length > 0 && (
                <div className="bg-[var(--surface)] border border-[var(--border)] p-4 mb-6">
                  <h3 className="font-theme-data text-sm text-[var(--acid-green)] mb-3">
                    TOP LEARNING TOPICS
                  </h3>
                  <div className="grid grid-cols-2 md:grid-cols-5 gap-2">
                    {data.top_topics.map((t) => (
                      <div
                        key={t.topic}
                        className="p-3 bg-[var(--bg)] border border-[var(--border)]"
                      >
                        <div className="font-theme-data text-xs text-[var(--text-muted)] truncate">
                          {t.topic}
                        </div>
                        <div className="font-theme-data text-lg text-[var(--text)]">
                          {t.count.toLocaleString()}
                        </div>
                      </div>
                    ))}
                  </div>
                </div>
              )}

              {/* Footer info */}
              <div className="text-xs font-theme-data text-[var(--text-muted)] flex items-center gap-4">
                <span>Last updated: {new Date(data.timestamp).toLocaleString()}</span>
                <span>Workspace: {data.workspace_id}</span>
              </div>
            </>
          )}

          {/* Navigation */}
          <div className="mt-8 flex items-center gap-2 pt-4 border-t border-[var(--border)]">
            <span className="text-xs font-theme-data text-[var(--text-muted)]">Navigate:</span>
            <Link
              href="/admin/knowledge"
              className="px-3 py-1 text-xs font-theme-data bg-[var(--surface)] text-[var(--text-muted)] border border-[var(--border)] hover:border-[var(--acid-green)]/30 transition-colors"
            >
              KNOWLEDGE ADMIN
            </Link>
            <Link
              href="/dashboard"
              className="px-3 py-1 text-xs font-theme-data bg-[var(--surface)] text-[var(--text-muted)] border border-[var(--border)] hover:border-[var(--acid-green)]/30 transition-colors"
            >
              DASHBOARD
            </Link>
            <Link
              href="/usage"
              className="px-3 py-1 text-xs font-theme-data bg-[var(--surface)] text-[var(--text-muted)] border border-[var(--border)] hover:border-[var(--acid-green)]/30 transition-colors"
            >
              USAGE
            </Link>
          </div>
        </div>
      </main>
    </>
  );
}
