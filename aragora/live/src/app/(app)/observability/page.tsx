'use client';

import { useState, useEffect, useCallback } from 'react';
import Link from 'next/link';
import { useBackend } from '@/components/BackendSelector';
import { logger } from '@/utils/logger';

interface SystemMetrics {
  uptime_seconds: number;
  uptime_human: string;
  requests: {
    total: number;
    errors: number;
    error_rate: number;
    top_endpoints: { endpoint: string; count: number }[];
  };
  cache: { entries: number };
  databases: Record<string, { bytes: number; human: string }>;
  timestamp: string;
}

interface HealthStatus {
  status: 'healthy' | 'degraded' | 'unhealthy';
  checks: Record<string, { status: string; error?: string; path?: string }>;
}

interface CacheStats {
  total_entries: number;
  max_entries: number;
  hit_rate: number;
  hits: number;
  misses: number;
  entries_by_prefix: Record<string, number>;
  oldest_entry_age_seconds: number;
  newest_entry_age_seconds: number;
}

interface VerificationStats {
  total_claims_processed: number;
  z3_verified: number;
  z3_disproved: number;
  z3_timeout: number;
  z3_translation_failed: number;
  confidence_fallback: number;
  total_verification_time_ms: number;
  avg_verification_time_ms: number;
  z3_success_rate: number;
}

interface SystemInfo {
  python_version: string;
  platform: string;
  machine: string;
  processor: string;
  pid: number;
  memory?: { rss_mb: number; vms_mb: number };
}

interface BackgroundStats {
  running: boolean;
  task_count: number;
  tasks: Record<string, { status: string; started?: number; completed?: number }>;
}

interface DashboardMetrics {
  summary: {
    total_debates: number;
    consensus_reached: number;
    consensus_rate: number;
    avg_confidence: number;
  };
  recent_activity: { debates_last_hour: number; debates_last_24h: number };
}

function MetricCard({
  title,
  value,
  subtitle,
  status,
}: {
  title: string;
  value: string | number;
  subtitle?: string;
  status?: 'good' | 'warning' | 'error' | 'neutral';
}) {
  const statusColors = {
    good: 'border-[var(--accent)]/50 bg-[var(--accent)]/5',
    warning: 'border-acid-yellow/50 bg-acid-yellow/5',
    error: 'border-warning/50 bg-warning/5',
    neutral: 'border-[var(--accent)]/30 bg-surface/30',
  };

  const valueColors = {
    good: 'text-[var(--accent)]',
    warning: 'text-[var(--acid-yellow)]',
    error: 'text-warning',
    neutral: 'text-[var(--acid-cyan)]',
  };

  return (
    <div className={`p-4 border ${statusColors[status || 'neutral']}`}>
      <div className="text-text-muted font-theme-data text-[10px] tracking-wider mb-1">{title}</div>
      <div className={`font-theme-data text-xl ${valueColors[status || 'neutral']}`}>{value}</div>
      {subtitle && (
        <div className="text-text-muted/50 font-theme-data text-[9px] mt-1">{subtitle}</div>
      )}
    </div>
  );
}

function HealthCheck({ name, check }: { name: string; check: { status: string; error?: string } }) {
  const statusColors = {
    healthy: 'text-[var(--accent)] bg-[var(--accent)]/10',
    unhealthy: 'text-warning bg-warning/10',
    unavailable: 'text-text-muted bg-surface',
    degraded: 'text-[var(--acid-yellow)] bg-acid-yellow/10',
  };

  return (
    <div className="flex items-center justify-between py-2 border-b border-[var(--accent)]/10 last:border-0">
      <span className="font-theme-data text-xs text-text">{name}</span>
      <span
        className={`px-2 py-0.5 font-theme-data text-[10px] ${statusColors[check.status as keyof typeof statusColors] || statusColors.unavailable}`}
      >
        {check.status.toUpperCase()}
      </span>
    </div>
  );
}

function ProgressBar({ value, max, label }: { value: number; max: number; label: string }) {
  const percentage = max > 0 ? (value / max) * 100 : 0;

  return (
    <div className="space-y-1">
      <div className="flex justify-between text-[10px] font-theme-data">
        <span className="text-text-muted">{label}</span>
        <span className="text-[var(--acid-cyan)]">
          {value.toLocaleString()} / {max.toLocaleString()}
        </span>
      </div>
      <div className="h-2 bg-surface border border-[var(--accent)]/20">
        <div
          className="h-full bg-[var(--accent)]/50 transition-all"
          style={{ width: `${Math.min(percentage, 100)}%` }}
        />
      </div>
    </div>
  );
}

export default function ObservabilityPage() {
  const { config: backendConfig } = useBackend();
  const [metrics, setMetrics] = useState<SystemMetrics | null>(null);
  const [health, setHealth] = useState<HealthStatus | null>(null);
  const [cache, setCache] = useState<CacheStats | null>(null);
  const [verification, setVerification] = useState<VerificationStats | null>(null);
  const [system, setSystem] = useState<SystemInfo | null>(null);
  const [background, setBackground] = useState<BackgroundStats | null>(null);
  const [dashboard, setDashboard] = useState<DashboardMetrics | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [lastUpdate, setLastUpdate] = useState<Date | null>(null);
  const [autoRefresh, setAutoRefresh] = useState(true);

  const fetchAllMetrics = useCallback(async () => {
    try {
      const endpoints = [
        { url: '/api/metrics', setter: setMetrics },
        { url: '/api/metrics/health', setter: setHealth },
        { url: '/api/metrics/cache', setter: setCache },
        { url: '/api/metrics/verification', setter: setVerification },
        { url: '/api/metrics/system', setter: setSystem },
        { url: '/api/metrics/background', setter: setBackground },
        { url: '/api/dashboard/debates', setter: setDashboard },
      ];

      await Promise.allSettled(
        endpoints.map(async ({ url, setter }) => {
          const response = await fetch(`${backendConfig.api}${url}`);
          if (response.ok) {
            const data = await response.json();
            setter(data);
          }
        }),
      );

      setLastUpdate(new Date());
    } catch (error) {
      logger.error('Failed to fetch metrics:', error);
    } finally {
      setIsLoading(false);
    }
  }, [backendConfig.api]);

  useEffect(() => {
    fetchAllMetrics();
  }, [fetchAllMetrics]);

  useEffect(() => {
    if (!autoRefresh) return;
    const interval = setInterval(fetchAllMetrics, 10000); // 10 second refresh
    return () => clearInterval(interval);
  }, [autoRefresh, fetchAllMetrics]);

  const getHealthStatus = () => {
    if (!health) return 'neutral';
    if (health.status === 'healthy') return 'good';
    if (health.status === 'degraded') return 'warning';
    return 'error';
  };

  const getErrorRateStatus = () => {
    if (!metrics) return 'neutral';
    if (metrics.requests.error_rate < 0.01) return 'good';
    if (metrics.requests.error_rate < 0.05) return 'warning';
    return 'error';
  };

  const getCacheHitStatus = () => {
    if (!cache) return 'neutral';
    if (cache.hit_rate > 0.8) return 'good';
    if (cache.hit_rate > 0.5) return 'warning';
    return 'error';
  };

  return (
    <main className="min-h-screen bg-bg text-text">
      {/* Header */}
      <header className="border-b border-[var(--accent)]/30 bg-surface/80 backdrop-blur-sm sticky top-0 z-10">
        <div className="container mx-auto px-4 py-3 flex items-center justify-between">
          <div className="flex items-center gap-4">
            <Link
              href="/"
              className="text-[var(--accent)] font-theme-data text-sm hover:opacity-80"
            >
              [ARAGORA]
            </Link>
            <span className="text-[var(--accent)]/30">/</span>
            <span className="text-[var(--acid-cyan)] font-theme-data text-sm">OBSERVABILITY</span>
          </div>
          <div className="flex items-center gap-4">
            <button
              onClick={() => setAutoRefresh(!autoRefresh)}
              className={`px-3 py-1.5 font-theme-data text-[10px] border transition-colors ${
                autoRefresh
                  ? 'border-[var(--accent)]/50 text-[var(--accent)] bg-[var(--accent)]/10'
                  : 'border-[var(--accent)]/30 text-text-muted'
              }`}
            >
              {autoRefresh ? 'AUTO-REFRESH ON' : 'AUTO-REFRESH OFF'}
            </button>
            <button
              onClick={fetchAllMetrics}
              disabled={isLoading}
              className="px-3 py-1.5 font-theme-data text-[10px] border border-[var(--accent)]/50 text-[var(--accent)] hover:bg-[var(--accent)]/10 disabled:opacity-50"
            >
              {isLoading ? 'LOADING...' : 'REFRESH'}
            </button>
            {lastUpdate && (
              <span className="text-text-muted/50 font-theme-data text-[10px]">
                Updated: {lastUpdate.toLocaleTimeString()}
              </span>
            )}
          </div>
        </div>
      </header>

      <div className="container mx-auto px-4 py-8 max-w-7xl">
        {/* Title */}
        <div className="text-center mb-8">
          <h1 className="text-[var(--accent)] font-theme-data text-xl mb-2">
            SYSTEM OBSERVABILITY
          </h1>
          <p className="text-text-muted font-theme-data text-xs">
            Real-time metrics and health monitoring
          </p>
        </div>

        {isLoading && !metrics ? (
          <div className="text-center py-12">
            <span className="text-[var(--accent)] font-theme-data animate-pulse">
              LOADING METRICS...
            </span>
          </div>
        ) : (
          <>
            {/* Summary Cards */}
            <div className="grid grid-cols-2 md:grid-cols-4 lg:grid-cols-6 gap-4 mb-8">
              <MetricCard
                title="SYSTEM STATUS"
                value={health?.status?.toUpperCase() || 'UNKNOWN'}
                status={getHealthStatus()}
              />
              <MetricCard
                title="UPTIME"
                value={metrics?.uptime_human || 'N/A'}
                subtitle={`${metrics?.uptime_seconds?.toLocaleString() || 0}s`}
                status="neutral"
              />
              <MetricCard
                title="TOTAL REQUESTS"
                value={metrics?.requests?.total?.toLocaleString() || '0'}
                status="neutral"
              />
              <MetricCard
                title="ERROR RATE"
                value={`${((metrics?.requests?.error_rate || 0) * 100).toFixed(2)}%`}
                subtitle={`${metrics?.requests?.errors || 0} errors`}
                status={getErrorRateStatus()}
              />
              <MetricCard
                title="CACHE HIT RATE"
                value={`${((cache?.hit_rate || 0) * 100).toFixed(1)}%`}
                subtitle={`${cache?.hits || 0} hits`}
                status={getCacheHitStatus()}
              />
              <MetricCard
                title="DEBATES"
                value={dashboard?.summary?.total_debates?.toLocaleString() || '0'}
                subtitle={`${((dashboard?.summary?.consensus_rate || 0) * 100).toFixed(0)}% consensus`}
                status="neutral"
              />
            </div>

            {/* Main Grid */}
            <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
              {/* Health Checks */}
              <div className="border border-[var(--accent)]/30 bg-surface/30 p-4">
                <h2 className="text-[var(--accent)]/60 font-theme-data text-[10px] tracking-widest mb-4">
                  HEALTH CHECKS
                </h2>
                {health?.checks ? (
                  <div className="space-y-1">
                    {Object.entries(health.checks).map(([name, check]) => (
                      <HealthCheck key={name} name={name} check={check} />
                    ))}
                  </div>
                ) : (
                  <p className="text-text-muted font-theme-data text-xs">
                    No health data available
                  </p>
                )}
              </div>

              {/* Verification Stats */}
              <div className="border border-[var(--accent)]/30 bg-surface/30 p-4">
                <h2 className="text-[var(--accent)]/60 font-theme-data text-[10px] tracking-widest mb-4">
                  Z3 VERIFICATION
                </h2>
                {verification ? (
                  <div className="space-y-3">
                    <div className="grid grid-cols-2 gap-2">
                      <div className="text-center p-2 border border-[var(--accent)]/20">
                        <div className="text-[var(--accent)] font-theme-data text-lg">
                          {verification.z3_verified}
                        </div>
                        <div className="text-text-muted/50 font-theme-data text-[9px]">
                          VERIFIED
                        </div>
                      </div>
                      <div className="text-center p-2 border border-[var(--accent)]/20">
                        <div className="text-warning font-theme-data text-lg">
                          {verification.z3_disproved}
                        </div>
                        <div className="text-text-muted/50 font-theme-data text-[9px]">
                          DISPROVED
                        </div>
                      </div>
                    </div>
                    <ProgressBar
                      value={verification.z3_verified}
                      max={verification.total_claims_processed || 1}
                      label="Success Rate"
                    />
                    <div className="flex justify-between text-[10px] font-theme-data text-text-muted">
                      <span>Timeouts: {verification.z3_timeout}</span>
                      <span>Avg: {verification.avg_verification_time_ms?.toFixed(1)}ms</span>
                    </div>
                  </div>
                ) : (
                  <p className="text-text-muted font-theme-data text-xs">No verification data</p>
                )}
              </div>

              {/* Cache Stats */}
              <div className="border border-[var(--accent)]/30 bg-surface/30 p-4">
                <h2 className="text-[var(--accent)]/60 font-theme-data text-[10px] tracking-widest mb-4">
                  CACHE STATS
                </h2>
                {cache ? (
                  <div className="space-y-3">
                    <ProgressBar
                      value={cache.total_entries}
                      max={cache.max_entries}
                      label="Cache Utilization"
                    />
                    <div className="grid grid-cols-2 gap-2 text-[10px] font-theme-data">
                      <div>
                        <span className="text-text-muted">Hits:</span>
                        <span className="text-[var(--accent)] ml-2">
                          {cache.hits?.toLocaleString()}
                        </span>
                      </div>
                      <div>
                        <span className="text-text-muted">Misses:</span>
                        <span className="text-[var(--acid-yellow)] ml-2">
                          {cache.misses?.toLocaleString()}
                        </span>
                      </div>
                    </div>
                    {cache.entries_by_prefix && Object.keys(cache.entries_by_prefix).length > 0 && (
                      <div className="pt-2 border-t border-[var(--accent)]/10">
                        <div className="text-text-muted/50 font-theme-data text-[9px] mb-2">
                          BY PREFIX
                        </div>
                        <div className="space-y-1">
                          {Object.entries(cache.entries_by_prefix)
                            .sort((a, b) => b[1] - a[1])
                            .slice(0, 5)
                            .map(([prefix, count]) => (
                              <div
                                key={prefix}
                                className="flex justify-between text-[10px] font-theme-data"
                              >
                                <span className="text-[var(--acid-cyan)]">{prefix}</span>
                                <span className="text-text-muted">{count}</span>
                              </div>
                            ))}
                        </div>
                      </div>
                    )}
                  </div>
                ) : (
                  <p className="text-text-muted font-theme-data text-xs">No cache data</p>
                )}
              </div>

              {/* Top Endpoints */}
              <div className="border border-[var(--accent)]/30 bg-surface/30 p-4">
                <h2 className="text-[var(--accent)]/60 font-theme-data text-[10px] tracking-widest mb-4">
                  TOP ENDPOINTS
                </h2>
                {metrics?.requests?.top_endpoints?.length ? (
                  <div className="space-y-2">
                    {metrics.requests.top_endpoints.slice(0, 8).map((ep, i) => (
                      <div key={ep.endpoint} className="flex items-center gap-2">
                        <span className="text-text-muted/40 font-theme-data text-[10px] w-4">
                          {i + 1}.
                        </span>
                        <span className="text-[var(--acid-cyan)] font-theme-data text-[10px] truncate flex-1">
                          {ep.endpoint}
                        </span>
                        <span className="text-text-muted font-theme-data text-[10px]">
                          {ep.count.toLocaleString()}
                        </span>
                      </div>
                    ))}
                  </div>
                ) : (
                  <p className="text-text-muted font-theme-data text-xs">No endpoint data</p>
                )}
              </div>

              {/* System Info */}
              <div className="border border-[var(--accent)]/30 bg-surface/30 p-4">
                <h2 className="text-[var(--accent)]/60 font-theme-data text-[10px] tracking-widest mb-4">
                  SYSTEM INFO
                </h2>
                {system ? (
                  <div className="space-y-2 text-[10px] font-theme-data">
                    <div className="flex justify-between">
                      <span className="text-text-muted">Platform</span>
                      <span className="text-text truncate max-w-[60%]">{system.platform}</span>
                    </div>
                    <div className="flex justify-between">
                      <span className="text-text-muted">Python</span>
                      <span className="text-text">{system.python_version?.split(' ')[0]}</span>
                    </div>
                    <div className="flex justify-between">
                      <span className="text-text-muted">PID</span>
                      <span className="text-text">{system.pid}</span>
                    </div>
                    {system.memory && (
                      <>
                        <div className="flex justify-between">
                          <span className="text-text-muted">Memory (RSS)</span>
                          <span className="text-[var(--acid-cyan)]">{system.memory.rss_mb} MB</span>
                        </div>
                        <div className="flex justify-between">
                          <span className="text-text-muted">Memory (VMS)</span>
                          <span className="text-[var(--acid-cyan)]">{system.memory.vms_mb} MB</span>
                        </div>
                      </>
                    )}
                  </div>
                ) : (
                  <p className="text-text-muted font-theme-data text-xs">No system data</p>
                )}
              </div>

              {/* Background Tasks */}
              <div className="border border-[var(--accent)]/30 bg-surface/30 p-4">
                <h2 className="text-[var(--accent)]/60 font-theme-data text-[10px] tracking-widest mb-4">
                  BACKGROUND TASKS
                </h2>
                {background ? (
                  <div className="space-y-3">
                    <div className="flex items-center justify-between">
                      <span className="text-text-muted font-theme-data text-[10px]">Running</span>
                      <span
                        className={`px-2 py-0.5 font-theme-data text-[10px] ${
                          background.running
                            ? 'text-[var(--accent)] bg-[var(--accent)]/10'
                            : 'text-text-muted bg-surface'
                        }`}
                      >
                        {background.running ? 'YES' : 'NO'}
                      </span>
                    </div>
                    <div className="flex items-center justify-between">
                      <span className="text-text-muted font-theme-data text-[10px]">
                        Task Count
                      </span>
                      <span className="text-[var(--acid-cyan)] font-theme-data text-[10px]">
                        {background.task_count}
                      </span>
                    </div>
                    {Object.keys(background.tasks || {}).length > 0 && (
                      <div className="pt-2 border-t border-[var(--accent)]/10">
                        <div className="text-text-muted/50 font-theme-data text-[9px] mb-2">
                          TASKS
                        </div>
                        {Object.entries(background.tasks).map(([name, task]) => (
                          <div
                            key={name}
                            className="flex justify-between text-[10px] font-theme-data py-1"
                          >
                            <span className="text-[var(--acid-cyan)] truncate">{name}</span>
                            <span
                              className={
                                task.status === 'running'
                                  ? 'text-[var(--accent)]'
                                  : task.status === 'completed'
                                    ? 'text-text-muted'
                                    : 'text-[var(--acid-yellow)]'
                              }
                            >
                              {task.status}
                            </span>
                          </div>
                        ))}
                      </div>
                    )}
                  </div>
                ) : (
                  <p className="text-text-muted font-theme-data text-xs">No background task data</p>
                )}
              </div>
            </div>

            {/* Database Sizes */}
            {metrics?.databases && Object.keys(metrics.databases).length > 0 && (
              <div className="mt-6 border border-[var(--accent)]/30 bg-surface/30 p-4">
                <h2 className="text-[var(--accent)]/60 font-theme-data text-[10px] tracking-widest mb-4">
                  DATABASE SIZES
                </h2>
                <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-6 gap-4">
                  {Object.entries(metrics.databases).map(([name, info]) => (
                    <div key={name} className="text-center p-3 border border-[var(--accent)]/20">
                      <div className="text-[var(--acid-cyan)] font-theme-data text-sm">
                        {info.human}
                      </div>
                      <div className="text-text-muted/50 font-theme-data text-[9px] mt-1 truncate">
                        {name}
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            )}

            {/* Debate Activity */}
            {dashboard && (
              <div className="mt-6 border border-[var(--accent)]/30 bg-surface/30 p-4">
                <h2 className="text-[var(--accent)]/60 font-theme-data text-[10px] tracking-widest mb-4">
                  DEBATE ACTIVITY
                </h2>
                <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
                  <div className="text-center p-3 border border-[var(--accent)]/20">
                    <div className="text-[var(--accent)] font-theme-data text-2xl">
                      {dashboard.summary.total_debates}
                    </div>
                    <div className="text-text-muted/50 font-theme-data text-[9px] mt-1">
                      TOTAL DEBATES
                    </div>
                  </div>
                  <div className="text-center p-3 border border-[var(--accent)]/20">
                    <div className="text-[var(--acid-cyan)] font-theme-data text-2xl">
                      {dashboard.summary.consensus_reached}
                    </div>
                    <div className="text-text-muted/50 font-theme-data text-[9px] mt-1">
                      CONSENSUS REACHED
                    </div>
                  </div>
                  <div className="text-center p-3 border border-[var(--accent)]/20">
                    <div className="text-[var(--acid-yellow)] font-theme-data text-2xl">
                      {((dashboard.summary.consensus_rate || 0) * 100).toFixed(0)}%
                    </div>
                    <div className="text-text-muted/50 font-theme-data text-[9px] mt-1">
                      CONSENSUS RATE
                    </div>
                  </div>
                  <div className="text-center p-3 border border-[var(--accent)]/20">
                    <div className="text-text font-theme-data text-2xl">
                      {((dashboard.summary.avg_confidence || 0) * 100).toFixed(0)}%
                    </div>
                    <div className="text-text-muted/50 font-theme-data text-[9px] mt-1">
                      AVG CONFIDENCE
                    </div>
                  </div>
                </div>
              </div>
            )}

            {/* Prometheus Link */}
            <div className="mt-8 text-center">
              <a
                href={`${backendConfig.api}/metrics`}
                target="_blank"
                rel="noopener noreferrer"
                className="inline-block px-4 py-2 border border-[var(--accent)]/30 text-[var(--acid-cyan)] font-theme-data text-xs hover:bg-[var(--accent)]/10 transition-colors"
              >
                VIEW PROMETHEUS METRICS
              </a>
            </div>
          </>
        )}
      </div>
    </main>
  );
}
