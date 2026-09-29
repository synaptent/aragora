'use client';

import { useState, useEffect, useCallback, useRef, useMemo } from 'react';
import { ErrorWithRetry } from './RetryButton';
import { fetchWithRetry } from '@/utils/retry';
import { API_BASE_URL } from '@/config';
import { useAuth } from '@/context/AuthContext';

interface MetricsData {
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

interface HealthData {
  status: 'healthy' | 'degraded' | 'unhealthy';
  checks: Record<string, { status: string; error?: string; path?: string }>;
}

interface CacheData {
  total_entries: number;
  max_entries: number;
  hit_rate: number;
  hits: number;
  misses: number;
  entries_by_prefix: Record<string, number>;
  oldest_entry_age_seconds: number;
  newest_entry_age_seconds: number;
}

interface SystemData {
  python_version: string;
  platform: string;
  machine: string;
  processor: string;
  pid: number;
  memory?: { rss_mb: number; vms_mb: number } | { available: false; reason: string };
}

interface MetricsPanelProps {
  apiBase?: string;
}

const DEFAULT_API_BASE = API_BASE_URL;

export function MetricsPanel({ apiBase = DEFAULT_API_BASE }: MetricsPanelProps) {
  const { tokens } = useAuth();
  const [metrics, setMetrics] = useState<MetricsData | null>(null);
  const [health, setHealth] = useState<HealthData | null>(null);
  const [cache, setCache] = useState<CacheData | null>(null);
  const [system, setSystem] = useState<SystemData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [activeTab, setActiveTab] = useState<'overview' | 'health' | 'cache' | 'system'>(
    'overview',
  );
  const [expanded, setExpanded] = useState(true);

  // Memoize sorted cache entries to prevent re-sorting on every render
  const sortedCacheEntries = useMemo(() => {
    if (!cache?.entries_by_prefix) return [];
    return Object.entries(cache.entries_by_prefix).sort(([, a], [, b]) => b - a);
  }, [cache?.entries_by_prefix]);

  const fetchData = useCallback(async () => {
    setLoading(true);
    setError(null);

    const headers: HeadersInit = { 'Content-Type': 'application/json' };
    if (tokens?.access_token) {
      headers['Authorization'] = `Bearer ${tokens.access_token}`;
    }

    const results = await Promise.allSettled([
      fetchWithRetry(`${apiBase}/api/metrics`, { headers }, { maxRetries: 2 }),
      fetchWithRetry(`${apiBase}/api/metrics/health`, { headers }, { maxRetries: 2 }),
      fetchWithRetry(`${apiBase}/api/metrics/cache`, { headers }, { maxRetries: 2 }),
      fetchWithRetry(`${apiBase}/api/metrics/system`, { headers }, { maxRetries: 2 }),
    ]);

    const [metricsResult, healthResult, cacheResult, systemResult] = results;
    let hasError = false;

    if (metricsResult.status === 'fulfilled' && metricsResult.value.ok) {
      const data = await metricsResult.value.json();
      setMetrics(data);
    } else {
      hasError = true;
    }

    if (healthResult.status === 'fulfilled' && healthResult.value.ok) {
      const data = await healthResult.value.json();
      setHealth(data);
    } else {
      hasError = true;
    }

    if (cacheResult.status === 'fulfilled' && cacheResult.value.ok) {
      const data = await cacheResult.value.json();
      setCache(data);
    } else {
      hasError = true;
    }

    if (systemResult.status === 'fulfilled' && systemResult.value.ok) {
      const data = await systemResult.value.json();
      setSystem(data);
    } else {
      hasError = true;
    }

    if (hasError) {
      setError('Some metrics failed to load. Partial results shown.');
    }
    setLoading(false);
  }, [apiBase, tokens?.access_token]);

  const fetchDataRef = useRef(fetchData);
  fetchDataRef.current = fetchData;

  useEffect(() => {
    fetchData();
  }, [fetchData]);

  useEffect(() => {
    const interval = setInterval(() => {
      fetchDataRef.current();
    }, 30000); // 30 second refresh
    return () => clearInterval(interval);
  }, []);

  const getStatusColor = (status: string): string => {
    if (status === 'healthy') return 'text-green-400';
    if (status === 'degraded') return 'text-yellow-400';
    if (status === 'unhealthy') return 'text-red-400';
    return 'text-zinc-500 dark:text-zinc-400';
  };

  const formatAge = (seconds: number): string => {
    if (seconds < 60) return `${Math.round(seconds)}s`;
    if (seconds < 3600) return `${Math.round(seconds / 60)}m`;
    return `${Math.round(seconds / 3600)}h`;
  };

  return (
    <div className="panel">
      <div className="panel-header mb-4">
        <h3 className="panel-title font-theme-data">Server Metrics</h3>
        <div className="flex items-center gap-2">
          <button
            onClick={fetchData}
            disabled={loading}
            className="text-xs font-theme-data text-text-muted hover:text-[var(--accent)] disabled:opacity-50"
          >
            [REFRESH]
          </button>
          <button
            onClick={() => setExpanded(!expanded)}
            className="text-xs font-theme-data text-text-muted hover:text-text"
          >
            [{expanded ? '-' : '+'}]
          </button>
        </div>
      </div>

      {/* Summary Stats */}
      <div className="flex items-center gap-4 text-xs font-theme-data text-text-muted mb-4 border-b border-border pb-3 flex-wrap">
        <span>
          Uptime: <span className="text-[var(--acid-cyan)]">{metrics?.uptime_human || '-'}</span>
        </span>
        <span>
          Requests:{' '}
          <span className="text-[var(--accent)]">
            {metrics?.requests.total.toLocaleString() || 0}
          </span>
        </span>
        <span>
          Error Rate:{' '}
          <span
            className={
              metrics?.requests.error_rate && metrics.requests.error_rate > 0.01
                ? 'text-red-400'
                : 'text-green-400'
            }
          >
            {((metrics?.requests.error_rate || 0) * 100).toFixed(2)}%
          </span>
        </span>
        <span>
          Cache:{' '}
          <span className="text-purple-400">
            {cache?.hit_rate ? `${(cache.hit_rate * 100).toFixed(1)}% hit` : '-'}
          </span>
        </span>
        {health && (
          <span>
            Health:{' '}
            <span className={getStatusColor(health.status)}>{health.status.toUpperCase()}</span>
          </span>
        )}
      </div>

      {error && <ErrorWithRetry error={error} onRetry={fetchData} className="mb-4" />}

      {expanded && (
        <>
          {/* Tab Navigation */}
          <div className="panel-tabs mb-4">
            <button
              onClick={() => setActiveTab('overview')}
              className={`px-3 py-1 rounded text-sm font-theme-data transition-colors flex-1 ${
                activeTab === 'overview'
                  ? 'bg-[var(--acid-cyan)] text-bg font-medium'
                  : 'text-text-muted hover:text-text'
              }`}
            >
              OVERVIEW
            </button>
            <button
              onClick={() => setActiveTab('health')}
              className={`px-3 py-1 rounded text-sm font-theme-data transition-colors flex-1 ${
                activeTab === 'health'
                  ? 'bg-green-500 text-bg font-medium'
                  : 'text-text-muted hover:text-text'
              }`}
            >
              HEALTH
            </button>
            <button
              onClick={() => setActiveTab('cache')}
              className={`px-3 py-1 rounded text-sm font-theme-data transition-colors flex-1 ${
                activeTab === 'cache'
                  ? 'bg-purple-500 text-bg font-medium'
                  : 'text-text-muted hover:text-text'
              }`}
            >
              CACHE
            </button>
            <button
              onClick={() => setActiveTab('system')}
              className={`px-3 py-1 rounded text-sm font-theme-data transition-colors flex-1 ${
                activeTab === 'system'
                  ? 'bg-yellow-500 text-bg font-medium'
                  : 'text-text-muted hover:text-text'
              }`}
            >
              SYSTEM
            </button>
          </div>

          {/* Overview Tab */}
          {activeTab === 'overview' && (
            <div className="space-y-4 max-h-80 overflow-y-auto">
              {loading && !metrics && (
                <div className="text-center text-text-muted py-4 font-theme-data text-sm">
                  Loading metrics...
                </div>
              )}

              {metrics && (
                <>
                  {/* Top Endpoints */}
                  {metrics.requests.top_endpoints.length > 0 && (
                    <div className="p-3 bg-bg border border-border rounded-lg">
                      <div className="text-sm font-theme-data text-text-muted mb-3">
                        Top Endpoints
                      </div>
                      <div className="space-y-2">
                        {metrics.requests.top_endpoints.slice(0, 5).map((ep) => (
                          <div
                            key={ep.endpoint}
                            className="flex items-center justify-between text-xs font-theme-data"
                          >
                            <span className="text-text truncate max-w-[200px]">{ep.endpoint}</span>
                            <span className="text-[var(--acid-cyan)]">
                              {ep.count.toLocaleString()}
                            </span>
                          </div>
                        ))}
                      </div>
                    </div>
                  )}

                  {/* Database Sizes */}
                  {Object.keys(metrics.databases).length > 0 && (
                    <div className="p-3 bg-bg border border-border rounded-lg">
                      <div className="text-sm font-theme-data text-text-muted mb-3">
                        Database Sizes
                      </div>
                      <div className="space-y-2">
                        {Object.entries(metrics.databases).map(([name, info]) => (
                          <div
                            key={name}
                            className="flex items-center justify-between text-xs font-theme-data"
                          >
                            <span className="text-text">{name.replace('.db', '')}</span>
                            <span className="text-yellow-400">{info.human}</span>
                          </div>
                        ))}
                      </div>
                    </div>
                  )}
                </>
              )}
            </div>
          )}

          {/* Health Tab */}
          {activeTab === 'health' && (
            <div className="space-y-3 max-h-80 overflow-y-auto">
              {loading && !health && (
                <div className="text-center text-text-muted py-4 font-theme-data text-sm">
                  Checking health...
                </div>
              )}

              {health && (
                <>
                  <div className="grid grid-cols-3 gap-3">
                    {Object.entries(health.checks).map(([name, check]) => (
                      <div
                        key={name}
                        className="p-3 bg-bg border border-border rounded-lg text-center"
                      >
                        <div className={`text-lg font-theme-data ${getStatusColor(check.status)}`}>
                          {check.status === 'healthy'
                            ? 'OK'
                            : check.status === 'unavailable'
                              ? 'N/A'
                              : 'ERR'}
                        </div>
                        <div className="text-xs text-text-muted capitalize">
                          {name.replace('_', ' ')}
                        </div>
                        {check.error && (
                          <div className="text-xs text-red-400 mt-1 truncate" title={check.error}>
                            {check.error.slice(0, 20)}...
                          </div>
                        )}
                      </div>
                    ))}
                  </div>

                  <div className="flex items-center justify-between p-2 bg-bg border border-border rounded-lg text-xs font-theme-data">
                    <span className="text-text-muted">Overall Status</span>
                    <span className={getStatusColor(health.status)}>
                      {health.status.toUpperCase()}
                    </span>
                  </div>
                </>
              )}
            </div>
          )}

          {/* Cache Tab */}
          {activeTab === 'cache' && (
            <div className="space-y-4 max-h-80 overflow-y-auto">
              {loading && !cache && (
                <div className="text-center text-text-muted py-4 font-theme-data text-sm">
                  Loading cache stats...
                </div>
              )}

              {cache && (
                <>
                  <div className="grid grid-cols-3 gap-3">
                    <div className="p-3 bg-bg border border-border rounded-lg text-center">
                      <div className="text-2xl font-theme-data text-purple-400">
                        {(cache.hit_rate * 100).toFixed(1)}%
                      </div>
                      <div className="text-xs text-text-muted">Hit Rate</div>
                    </div>
                    <div className="p-3 bg-bg border border-border rounded-lg text-center">
                      <div className="text-2xl font-theme-data text-green-400">{cache.hits}</div>
                      <div className="text-xs text-text-muted">Hits</div>
                    </div>
                    <div className="p-3 bg-bg border border-border rounded-lg text-center">
                      <div className="text-2xl font-theme-data text-red-400">{cache.misses}</div>
                      <div className="text-xs text-text-muted">Misses</div>
                    </div>
                  </div>

                  <div className="p-3 bg-bg border border-border rounded-lg">
                    <div className="flex items-center justify-between mb-2">
                      <span className="text-sm font-theme-data text-text-muted">Entries</span>
                      <span className="text-sm font-theme-data text-[var(--acid-cyan)]">
                        {cache.total_entries} / {cache.max_entries}
                      </span>
                    </div>
                    <div className="w-full h-2 bg-surface rounded-full overflow-hidden">
                      <div
                        className="h-full bg-purple-400"
                        style={{ width: `${(cache.total_entries / cache.max_entries) * 100}%` }}
                      />
                    </div>
                  </div>

                  {sortedCacheEntries.length > 0 && (
                    <div className="p-3 bg-bg border border-border rounded-lg">
                      <div className="text-sm font-theme-data text-text-muted mb-3">
                        Entries by Type
                      </div>
                      <div className="space-y-2">
                        {sortedCacheEntries.map(([prefix, count]) => (
                          <div
                            key={prefix}
                            className="flex items-center justify-between text-xs font-theme-data"
                          >
                            <span className="text-text">{prefix}</span>
                            <span className="text-purple-400">{count}</span>
                          </div>
                        ))}
                      </div>
                    </div>
                  )}

                  <div className="flex items-center justify-between p-2 bg-bg border border-border rounded-lg text-xs font-theme-data">
                    <span className="text-text-muted">Entry Age Range</span>
                    <span className="text-text">
                      {formatAge(cache.newest_entry_age_seconds)} -{' '}
                      {formatAge(cache.oldest_entry_age_seconds)}
                    </span>
                  </div>
                </>
              )}
            </div>
          )}

          {/* System Tab */}
          {activeTab === 'system' && (
            <div className="space-y-4 max-h-80 overflow-y-auto">
              {loading && !system && (
                <div className="text-center text-text-muted py-4 font-theme-data text-sm">
                  Loading system info...
                </div>
              )}

              {system && (
                <>
                  {/* Memory Usage */}
                  {system.memory && 'rss_mb' in system.memory && (
                    <div className="grid grid-cols-2 gap-3">
                      <div className="p-3 bg-bg border border-border rounded-lg text-center">
                        <div className="text-2xl font-theme-data text-[var(--acid-cyan)]">
                          {system.memory.rss_mb}
                        </div>
                        <div className="text-xs text-text-muted">RSS (MB)</div>
                      </div>
                      <div className="p-3 bg-bg border border-border rounded-lg text-center">
                        <div className="text-2xl font-theme-data text-yellow-400">
                          {system.memory.vms_mb}
                        </div>
                        <div className="text-xs text-text-muted">VMS (MB)</div>
                      </div>
                    </div>
                  )}

                  <div className="p-3 bg-bg border border-border rounded-lg space-y-2">
                    <div className="flex items-center justify-between text-xs font-theme-data">
                      <span className="text-text-muted">Python</span>
                      <span className="text-text truncate max-w-[200px]">
                        {system.python_version.split(' ')[0]}
                      </span>
                    </div>
                    <div className="flex items-center justify-between text-xs font-theme-data">
                      <span className="text-text-muted">Platform</span>
                      <span className="text-text truncate max-w-[200px]">{system.platform}</span>
                    </div>
                    <div className="flex items-center justify-between text-xs font-theme-data">
                      <span className="text-text-muted">Machine</span>
                      <span className="text-text">{system.machine}</span>
                    </div>
                    <div className="flex items-center justify-between text-xs font-theme-data">
                      <span className="text-text-muted">PID</span>
                      <span className="text-[var(--accent)]">{system.pid}</span>
                    </div>
                  </div>
                </>
              )}
            </div>
          )}
        </>
      )}

      {/* Help text when collapsed */}
      {!expanded && (
        <div className="text-xs font-theme-data text-text-muted">
          <p>
            <span className="text-[var(--acid-cyan)]">Uptime:</span> {metrics?.uptime_human || '-'}{' '}
            | <span className="text-[var(--accent)]">Requests:</span>{' '}
            {metrics?.requests.total.toLocaleString() || 0} |{' '}
            <span className="text-purple-400">Cache:</span>{' '}
            {cache?.hit_rate ? `${(cache.hit_rate * 100).toFixed(1)}%` : '-'}
          </p>
        </div>
      )}
    </div>
  );
}
