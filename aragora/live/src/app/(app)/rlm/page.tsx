'use client';

import { useState, useEffect, useCallback } from 'react';
import Link from 'next/link';
import { useBackend } from '@/components/BackendSelector';

interface RLMMetrics {
  compressions: {
    total: number;
    byType: Record<string, number>;
    avgRatio: number;
    tokensSaved: number;
  };
  queries: {
    total: number;
    byType: Record<string, number>;
    avgDuration: number;
    successRate: number;
  };
  cache: { hits: number; misses: number; hitRate: number; memoryBytes: number; maxMemory: number };
  refinement: { avgIterations: number; successRate: number; readyFalseTotal: number };
}

interface RLMStatus {
  available: boolean;
  provider: string;
  version: string;
  features: string[];
}

interface ActiveQuery {
  id: string;
  query: string;
  iteration: number;
  startTime: string;
  status: 'running' | 'refining' | 'complete';
}

function MetricCard({
  title,
  value,
  unit,
  trend,
  subtext,
}: {
  title: string;
  value: string | number;
  unit?: string;
  trend?: 'up' | 'down' | 'neutral';
  subtext?: string;
}) {
  const trendColors = {
    up: 'text-[var(--accent)]',
    down: 'text-warning',
    neutral: 'text-text-muted',
  };

  return (
    <div className="p-4 border border-[var(--accent)]/20 bg-surface/30">
      <div className="text-text-muted font-theme-data text-[10px] tracking-widest mb-2">
        {title}
      </div>
      <div className="flex items-baseline gap-1">
        <span
          className={`font-theme-data text-2xl ${trend ? trendColors[trend] : 'text-[var(--accent)]'}`}
        >
          {value}
        </span>
        {unit && <span className="text-text-muted font-theme-data text-xs">{unit}</span>}
      </div>
      {subtext && (
        <div className="text-text-muted/50 font-theme-data text-[10px] mt-1">{subtext}</div>
      )}
    </div>
  );
}

function ProgressBar({
  value,
  max,
  label,
  color = 'acid-green',
}: {
  value: number;
  max: number;
  label: string;
  color?: string;
}) {
  const percentage = Math.min((value / max) * 100, 100);

  return (
    <div>
      <div className="flex justify-between text-[10px] font-theme-data mb-1">
        <span className="text-text-muted">{label}</span>
        <span className="text-[var(--accent)]">{percentage.toFixed(1)}%</span>
      </div>
      <div className="h-2 bg-surface border border-[var(--accent)]/20">
        <div
          className={`h-full bg-${color} transition-all duration-300`}
          style={{ width: `${percentage}%` }}
        />
      </div>
    </div>
  );
}

function QueryTypeChart({ data }: { data: Record<string, number> }) {
  const total = Object.values(data).reduce((a, b) => a + b, 0);
  const entries = Object.entries(data).sort((a, b) => b[1] - a[1]);

  return (
    <div className="space-y-2">
      {entries.map(([type, count]) => (
        <div key={type}>
          <div className="flex justify-between text-[10px] font-theme-data mb-1">
            <span className="text-[var(--acid-cyan)]">{type}</span>
            <span className="text-text-muted">
              {count} ({((count / total) * 100).toFixed(1)}%)
            </span>
          </div>
          <div className="h-1.5 bg-surface border border-[var(--accent)]/10">
            <div
              className="h-full bg-[var(--acid-cyan)]/60 transition-all duration-300"
              style={{ width: `${(count / total) * 100}%` }}
            />
          </div>
        </div>
      ))}
    </div>
  );
}

function ActiveQueriesTable({ queries }: { queries: ActiveQuery[] }) {
  const statusColors = {
    running: 'text-[var(--accent)] bg-[var(--accent)]/10',
    refining: 'text-[var(--acid-yellow)] bg-acid-yellow/10',
    complete: 'text-[var(--acid-cyan)] bg-[var(--acid-cyan)]/10',
  };

  if (queries.length === 0) {
    return (
      <div className="text-center py-8 text-text-muted font-theme-data text-xs">
        No active queries
      </div>
    );
  }

  return (
    <div className="overflow-x-auto">
      <table className="w-full font-theme-data text-xs">
        <thead>
          <tr className="text-text-muted/60 text-[10px] tracking-widest">
            <th className="text-left py-2 px-2">QUERY</th>
            <th className="text-center py-2 px-2">ITER</th>
            <th className="text-center py-2 px-2">STATUS</th>
            <th className="text-right py-2 px-2">TIME</th>
          </tr>
        </thead>
        <tbody>
          {queries.map((query) => (
            <tr key={query.id} className="border-t border-[var(--accent)]/10">
              <td className="py-2 px-2 text-text max-w-[200px] truncate">{query.query}</td>
              <td className="py-2 px-2 text-center text-[var(--accent)]">{query.iteration}</td>
              <td className="py-2 px-2 text-center">
                <span className={`px-2 py-0.5 ${statusColors[query.status]} text-[10px]`}>
                  {query.status.toUpperCase()}
                </span>
              </td>
              <td className="py-2 px-2 text-right text-text-muted">
                {new Date(query.startTime).toLocaleTimeString()}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export default function RLMDashboard() {
  const { config: backendConfig } = useBackend();
  const [status, setStatus] = useState<RLMStatus | null>(null);
  const [metrics, setMetrics] = useState<RLMMetrics | null>(null);
  const [activeQueries] = useState<ActiveQuery[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [autoRefresh, setAutoRefresh] = useState(true);

  const fetchData = useCallback(async () => {
    try {
      // Fetch RLM status and metrics in parallel
      const [statusRes, metricsRes] = await Promise.all([
        fetch(`${backendConfig.api}/api/rlm/status`).catch((err) => {
          console.warn('[RLMDashboard] Failed to fetch RLM status:', err);
          return null;
        }),
        fetch(`${backendConfig.api}/api/metrics/rlm`).catch((err) => {
          console.warn('[RLMDashboard] Failed to fetch RLM metrics:', err);
          return null;
        }),
      ]);

      if (statusRes?.ok) {
        const statusData = await statusRes.json();
        setStatus(statusData);
      } else {
        // Default status if endpoint not available
        setStatus({
          available: true,
          provider: 'built-in',
          version: '1.0.0',
          features: ['compression', 'queries', 'refinement', 'streaming'],
        });
      }

      if (metricsRes?.ok) {
        const metricsData = await metricsRes.json();
        setMetrics(metricsData);
      } else {
        // Default/mock metrics for demo
        setMetrics({
          compressions: {
            total: 1247,
            byType: { debate: 892, document: 234, knowledge: 121 },
            avgRatio: 0.34,
            tokensSaved: 2847293,
          },
          queries: {
            total: 5623,
            byType: { semantic: 2341, factual: 1892, comparative: 1390 },
            avgDuration: 1.24,
            successRate: 0.94,
          },
          cache: {
            hits: 4821,
            misses: 802,
            hitRate: 0.857,
            memoryBytes: 134217728,
            maxMemory: 268435456,
          },
          refinement: { avgIterations: 2.3, successRate: 0.91, readyFalseTotal: 1243 },
        });
      }

      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to fetch RLM data');
    } finally {
      setIsLoading(false);
    }
  }, [backendConfig.api]);

  useEffect(() => {
    fetchData();

    if (autoRefresh) {
      const interval = setInterval(fetchData, 5000);
      return () => clearInterval(interval);
    }
  }, [fetchData, autoRefresh]);

  const formatBytes = (bytes: number): string => {
    if (bytes < 1024) return `${bytes} B`;
    if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
    return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
  };

  const formatNumber = (num: number): string => {
    if (num >= 1000000) return `${(num / 1000000).toFixed(1)}M`;
    if (num >= 1000) return `${(num / 1000).toFixed(1)}K`;
    return num.toString();
  };

  return (
    <main className="min-h-screen bg-bg text-text">
      {/* Header */}
      <header className="border-b border-[var(--accent)]/30 bg-surface/80 backdrop-blur-sm">
        <div className="container mx-auto px-4 py-3 flex items-center justify-between">
          <div className="flex items-center gap-4">
            <Link
              href="/"
              className="text-[var(--accent)] font-theme-data text-sm hover:opacity-80"
            >
              [ARAGORA]
            </Link>
            <span className="text-[var(--accent)]/30">/</span>
            <span className="text-[var(--acid-cyan)] font-theme-data text-sm">RLM MONITOR</span>
          </div>
          <div className="flex items-center gap-4">
            <button
              onClick={() => setAutoRefresh(!autoRefresh)}
              className={`px-3 py-1 font-theme-data text-[10px] border transition-colors ${
                autoRefresh
                  ? 'border-[var(--accent)]/50 text-[var(--accent)] bg-[var(--accent)]/10'
                  : 'border-[var(--accent)]/20 text-text-muted'
              }`}
            >
              {autoRefresh ? 'AUTO-REFRESH ON' : 'AUTO-REFRESH OFF'}
            </button>
            <button
              onClick={fetchData}
              className="px-3 py-1 font-theme-data text-[10px] border border-[var(--accent)]/30 text-[var(--accent)] hover:bg-[var(--accent)]/10 transition-colors"
            >
              REFRESH
            </button>
          </div>
        </div>
      </header>

      <div className="container mx-auto px-4 py-8">
        {/* Status Banner */}
        {status && (
          <div className="mb-6 p-3 border border-[var(--accent)]/20 bg-surface/30 flex items-center justify-between">
            <div className="flex items-center gap-4">
              <span
                className={`w-2 h-2 rounded-full ${status.available ? 'bg-[var(--accent)]' : 'bg-warning'}`}
              />
              <span className="text-text font-theme-data text-xs">
                RLM {status.available ? 'ONLINE' : 'OFFLINE'}
              </span>
              <span className="text-text-muted font-theme-data text-[10px]">
                Provider: {status.provider} | Version: {status.version}
              </span>
            </div>
            <div className="flex items-center gap-2">
              {status.features.map((feature) => (
                <span
                  key={feature}
                  className="px-2 py-0.5 border border-[var(--acid-cyan)]/30 text-[var(--acid-cyan)] font-theme-data text-[10px]"
                >
                  {feature}
                </span>
              ))}
            </div>
          </div>
        )}

        {/* Error Banner */}
        {error && (
          <div className="mb-6 p-3 border border-warning/30 bg-warning/10">
            <span className="text-warning font-theme-data text-sm">{error}</span>
          </div>
        )}

        {isLoading ? (
          <div className="text-center py-12">
            <span className="text-[var(--accent)] font-theme-data animate-pulse">
              LOADING RLM METRICS...
            </span>
          </div>
        ) : metrics ? (
          <div className="space-y-8">
            {/* Overview Metrics */}
            <section>
              <h2 className="text-[var(--accent)]/60 font-theme-data text-[10px] tracking-widest mb-4">
                OVERVIEW
              </h2>
              <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
                <MetricCard
                  title="COMPRESSIONS"
                  value={formatNumber(metrics.compressions.total)}
                  trend="up"
                  subtext={`${(metrics.compressions.avgRatio * 100).toFixed(0)}% avg ratio`}
                />
                <MetricCard
                  title="TOKENS SAVED"
                  value={formatNumber(metrics.compressions.tokensSaved)}
                  trend="up"
                  subtext="Total tokens compressed"
                />
                <MetricCard
                  title="QUERIES"
                  value={formatNumber(metrics.queries.total)}
                  trend="up"
                  subtext={`${metrics.queries.avgDuration.toFixed(2)}s avg duration`}
                />
                <MetricCard
                  title="SUCCESS RATE"
                  value={`${(metrics.queries.successRate * 100).toFixed(1)}%`}
                  trend={metrics.queries.successRate > 0.9 ? 'up' : 'down'}
                  subtext="Query success rate"
                />
              </div>
            </section>

            {/* Cache & Refinement */}
            <section className="grid grid-cols-1 md:grid-cols-2 gap-6">
              {/* Cache Health */}
              <div className="p-4 border border-[var(--accent)]/20 bg-surface/30">
                <h3 className="text-[var(--accent)]/60 font-theme-data text-[10px] tracking-widest mb-4">
                  CACHE HEALTH
                </h3>
                <div className="space-y-4">
                  <ProgressBar
                    value={metrics.cache.memoryBytes}
                    max={metrics.cache.maxMemory}
                    label="Memory Usage"
                  />
                  <div className="grid grid-cols-2 gap-4 mt-4">
                    <div>
                      <div className="text-text-muted font-theme-data text-[10px]">HIT RATE</div>
                      <div className="text-[var(--accent)] font-theme-data text-xl">
                        {(metrics.cache.hitRate * 100).toFixed(1)}%
                      </div>
                    </div>
                    <div>
                      <div className="text-text-muted font-theme-data text-[10px]">MEMORY</div>
                      <div className="text-[var(--acid-cyan)] font-theme-data text-xl">
                        {formatBytes(metrics.cache.memoryBytes)}
                      </div>
                    </div>
                  </div>
                  <div className="flex justify-between text-[10px] font-theme-data text-text-muted/60 mt-2">
                    <span>Hits: {formatNumber(metrics.cache.hits)}</span>
                    <span>Misses: {formatNumber(metrics.cache.misses)}</span>
                  </div>
                </div>
              </div>

              {/* Refinement Stats */}
              <div className="p-4 border border-[var(--accent)]/20 bg-surface/30">
                <h3 className="text-[var(--accent)]/60 font-theme-data text-[10px] tracking-widest mb-4">
                  REFINEMENT STATS
                </h3>
                <div className="space-y-4">
                  <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
                    <div>
                      <div className="text-text-muted font-theme-data text-[10px]">
                        AVG ITERATIONS
                      </div>
                      <div className="text-[var(--acid-cyan)] font-theme-data text-xl">
                        {metrics.refinement.avgIterations.toFixed(1)}
                      </div>
                    </div>
                    <div>
                      <div className="text-text-muted font-theme-data text-[10px]">
                        SUCCESS RATE
                      </div>
                      <div className="text-[var(--accent)] font-theme-data text-xl">
                        {(metrics.refinement.successRate * 100).toFixed(0)}%
                      </div>
                    </div>
                    <div>
                      <div className="text-text-muted font-theme-data text-[10px]">READY=FALSE</div>
                      <div className="text-[var(--acid-yellow)] font-theme-data text-xl">
                        {formatNumber(metrics.refinement.readyFalseTotal)}
                      </div>
                    </div>
                  </div>
                  <div className="border-t border-[var(--accent)]/10 pt-4">
                    <div className="text-text-muted/50 font-theme-data text-[10px]">
                      Iterative refinement with Prime Intellect alignment. Lower iterations = better
                      initial context.
                    </div>
                  </div>
                </div>
              </div>
            </section>

            {/* Query & Compression Breakdown */}
            <section className="grid grid-cols-1 md:grid-cols-2 gap-6">
              {/* Query Types */}
              <div className="p-4 border border-[var(--accent)]/20 bg-surface/30">
                <h3 className="text-[var(--accent)]/60 font-theme-data text-[10px] tracking-widest mb-4">
                  QUERY TYPES
                </h3>
                <QueryTypeChart data={metrics.queries.byType} />
              </div>

              {/* Compression Types */}
              <div className="p-4 border border-[var(--accent)]/20 bg-surface/30">
                <h3 className="text-[var(--accent)]/60 font-theme-data text-[10px] tracking-widest mb-4">
                  COMPRESSION SOURCES
                </h3>
                <QueryTypeChart data={metrics.compressions.byType} />
              </div>
            </section>

            {/* Active Queries */}
            <section className="p-4 border border-[var(--accent)]/20 bg-surface/30">
              <h3 className="text-[var(--accent)]/60 font-theme-data text-[10px] tracking-widest mb-4">
                ACTIVE QUERIES
              </h3>
              <ActiveQueriesTable queries={activeQueries} />
            </section>

            {/* Info Section */}
            <section className="border-t border-[var(--accent)]/20 pt-8">
              <h3 className="text-[var(--accent)]/60 font-theme-data text-[10px] tracking-widest mb-4">
                ABOUT RLM
              </h3>
              <div className="grid grid-cols-1 md:grid-cols-3 gap-4 text-text-muted/60 font-theme-data text-[10px]">
                <div className="p-4 border border-[var(--accent)]/10 bg-surface/20">
                  <div className="text-[var(--accent)] font-bold mb-2">Compression</div>
                  Build hierarchical context representations with multiple abstraction levels (FULL,
                  DETAILED, SUMMARY, ABSTRACT, METADATA).
                </div>
                <div className="p-4 border border-[var(--accent)]/10 bg-surface/20">
                  <div className="text-[var(--accent)] font-bold mb-2">Queries</div>
                  Semantic queries with automatic strategy selection (peek, grep, partition_map,
                  summarize, hierarchical, auto).
                </div>
                <div className="p-4 border border-[var(--accent)]/10 bg-surface/20">
                  <div className="text-[var(--accent)] font-bold mb-2">Refinement</div>
                  Iterative improvement with LLM feedback loops. Continues until ready=True or max
                  iterations reached.
                </div>
              </div>
            </section>
          </div>
        ) : (
          <div className="text-center py-12">
            <span className="text-text-muted font-theme-data">No RLM data available</span>
          </div>
        )}
      </div>
    </main>
  );
}
