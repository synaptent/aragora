'use client';

import { useCallback, useState } from 'react';
import { API_BASE_URL } from '@/config';
import { useAsyncData } from '@/hooks/useAsyncData';
import { useAuth } from '@/context/AuthContext';

/**
 * Platform Health Widget
 *
 * Displays platform integration health metrics:
 * - Platform circuit breaker states
 * - Rate limiter status
 * - Dead letter queue statistics
 * - Platform-specific metrics
 */

interface PlatformHealthData {
  status: 'healthy' | 'degraded' | 'not_configured' | 'healthy_with_warnings';
  summary: { total_components: number; healthy: number; active: number };
  components: {
    rate_limiters?: {
      healthy: boolean;
      status: string;
      platforms?: string[];
      config?: Record<string, { rpm: number; burst_size: number; daily_limit: number }>;
    };
    resilience?: {
      healthy: boolean;
      status: string;
      dlq_enabled?: boolean;
      platforms_tracked?: number;
      circuit_breakers?: Record<string, { status: string; consecutive_failures: number }>;
    };
    dead_letter_queue?: {
      healthy: boolean;
      status: string;
      pending_count?: number;
      failed_count?: number;
      processed_count?: number;
    };
    platform_circuits?: {
      healthy: boolean;
      status: string;
      circuits?: Record<string, { state: string; failure_count: number; success_count: number }>;
    };
  };
  warnings?: string[];
  response_time_ms: number;
  timestamp: string;
}

interface CircuitBadgeProps {
  state: string;
}

function CircuitBadge({ state }: CircuitBadgeProps) {
  const stateColors: Record<string, string> = {
    closed: 'bg-[var(--accent)]/20 text-[var(--accent)] border-[var(--accent)]/30',
    open: 'bg-[var(--crimson)]/20 text-[var(--crimson)] border-[var(--crimson)]/30',
    'half-open': 'bg-acid-yellow/20 text-[var(--acid-yellow)] border-acid-yellow/30',
    not_configured: 'bg-surface text-text-muted border-border',
  };

  return (
    <span
      className={`px-2 py-0.5 text-[10px] font-theme-data rounded border ${stateColors[state] || stateColors.not_configured}`}
    >
      {state.toUpperCase()}
    </span>
  );
}

interface StatBoxProps {
  label: string;
  value: string | number;
  color?: 'green' | 'cyan' | 'yellow' | 'red';
}

function StatBox({ label, value, color = 'green' }: StatBoxProps) {
  const colorClasses: Record<string, string> = {
    green: 'text-[var(--accent)]',
    cyan: 'text-[var(--acid-cyan)]',
    yellow: 'text-[var(--acid-yellow)]',
    red: 'text-[var(--crimson)]',
  };

  return (
    <div className="text-center">
      <div className={`text-lg font-theme-data ${colorClasses[color]}`}>{value}</div>
      <div className="text-[10px] text-text-muted">{label}</div>
    </div>
  );
}

export function PlatformHealthWidget() {
  const { isAuthenticated, isLoading: authLoading, tokens } = useAuth();
  const [expanded, setExpanded] = useState(false);
  const apiBase = API_BASE_URL;

  const fetcher = useCallback(async (): Promise<PlatformHealthData> => {
    // Skip if not authenticated
    if (!isAuthenticated || authLoading) {
      throw new Error('Not authenticated');
    }

    const headers: HeadersInit = { 'Content-Type': 'application/json' };
    if (tokens?.access_token) {
      headers['Authorization'] = `Bearer ${tokens.access_token}`;
    }
    const response = await fetch(`${apiBase}/api/platform/health`, { headers });
    if (!response.ok) {
      throw new Error(`Failed to fetch: ${response.status}`);
    }
    return response.json();
  }, [apiBase, isAuthenticated, authLoading, tokens?.access_token]);

  const { data, loading, error, refetch } = useAsyncData<PlatformHealthData>(fetcher, {
    immediate: isAuthenticated && !authLoading,
    refreshInterval: 30000, // Refresh every 30s
  });

  const getStatusColor = (status: string) => {
    switch (status) {
      case 'healthy':
        return 'text-[var(--accent)]';
      case 'healthy_with_warnings':
        return 'text-[var(--acid-yellow)]';
      case 'degraded':
        return 'text-[var(--crimson)]';
      default:
        return 'text-text-muted';
    }
  };

  const getStatusIcon = (status: string) => {
    switch (status) {
      case 'healthy':
        return '●';
      case 'healthy_with_warnings':
        return '◐';
      case 'degraded':
        return '○';
      default:
        return '○';
    }
  };

  if (loading && !data) {
    return (
      <div className="border border-border bg-surface rounded-lg p-4">
        <div className="animate-pulse">
          <div className="h-4 bg-border rounded w-1/3 mb-3"></div>
          <div className="h-8 bg-border rounded w-full"></div>
        </div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="border border-[var(--crimson)]/30 bg-[var(--crimson)]/5 rounded-lg p-4">
        <div className="text-[var(--crimson)] font-theme-data text-sm mb-1">
          Platform Health Error
        </div>
        <div className="text-text-muted text-xs">{error}</div>
        <button
          onClick={() => refetch()}
          className="mt-2 text-xs text-[var(--acid-cyan)] hover:underline"
        >
          Retry
        </button>
      </div>
    );
  }

  if (!data) return null;

  const platforms = ['slack', 'discord', 'teams', 'telegram', 'whatsapp', 'matrix'];
  const circuits = data.components.platform_circuits?.circuits || {};
  const dlq = data.components.dead_letter_queue;

  return (
    <div className="border border-border bg-surface rounded-lg overflow-hidden">
      {/* Header */}
      <div
        className="flex items-center justify-between p-3 cursor-pointer hover:bg-surface-elevated transition-colors"
        onClick={() => setExpanded(!expanded)}
      >
        <div className="flex items-center gap-2">
          <span className={`text-lg ${getStatusColor(data.status)}`}>
            {getStatusIcon(data.status)}
          </span>
          <span className="font-theme-data text-sm text-text">Platform Integrations</span>
        </div>
        <div className="flex items-center gap-3">
          <span className="text-[10px] text-text-muted font-theme-data">
            {data.summary.active}/{data.summary.total_components} active
          </span>
          <span className="text-text-muted text-xs">{expanded ? '▼' : '▶'}</span>
        </div>
      </div>

      {/* Summary Row (always visible) */}
      <div className="px-3 pb-3 grid grid-cols-4 gap-3 border-t border-border pt-3">
        <StatBox label="Healthy" value={data.summary.healthy} color="green" />
        <StatBox
          label="DLQ Pending"
          value={dlq?.pending_count ?? '-'}
          color={dlq?.pending_count && dlq.pending_count > 50 ? 'yellow' : 'cyan'}
        />
        <StatBox
          label="DLQ Failed"
          value={dlq?.failed_count ?? '-'}
          color={dlq?.failed_count && dlq.failed_count > 0 ? 'red' : 'cyan'}
        />
        <StatBox label="Response" value={`${data.response_time_ms}ms`} color="cyan" />
      </div>

      {/* Expanded Details */}
      {expanded && (
        <div className="border-t border-border p-3 space-y-4">
          {/* Warnings */}
          {data.warnings && data.warnings.length > 0 && (
            <div className="bg-acid-yellow/10 border border-acid-yellow/30 rounded p-2">
              <div className="text-[var(--acid-yellow)] text-xs font-theme-data mb-1">Warnings</div>
              <ul className="text-[10px] text-text-muted space-y-1">
                {data.warnings.map((warning, i) => (
                  <li key={i}>• {warning}</li>
                ))}
              </ul>
            </div>
          )}

          {/* Platform Circuit Breakers */}
          <div>
            <div className="text-xs text-text-muted mb-2 font-theme-data">Circuit Breakers</div>
            <div className="grid grid-cols-2 md:grid-cols-3 gap-2">
              {platforms.map((platform) => {
                const circuit = circuits[platform];
                return (
                  <div
                    key={platform}
                    className="flex items-center justify-between p-2 bg-background rounded border border-border"
                  >
                    <span className="text-xs text-text capitalize">{platform}</span>
                    <CircuitBadge state={circuit?.state || 'not_configured'} />
                  </div>
                );
              })}
            </div>
          </div>

          {/* Rate Limiters */}
          {data.components.rate_limiters?.config && (
            <div>
              <div className="text-xs text-text-muted mb-2 font-theme-data">Rate Limits (RPM)</div>
              <div className="grid grid-cols-3 md:grid-cols-6 gap-2">
                {Object.entries(data.components.rate_limiters.config).map(([platform, config]) => (
                  <div
                    key={platform}
                    className="text-center p-2 bg-background rounded border border-border"
                  >
                    <div className="text-[10px] text-text-muted capitalize">{platform}</div>
                    <div className="text-sm font-theme-data text-[var(--acid-cyan)]">
                      {config.rpm}
                    </div>
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* DLQ Details */}
          {dlq && dlq.status === 'active' && (
            <div>
              <div className="text-xs text-text-muted mb-2 font-theme-data">Dead Letter Queue</div>
              <div className="grid grid-cols-3 gap-3">
                <div className="p-2 bg-background rounded border border-border text-center">
                  <div className="text-[10px] text-text-muted">Pending</div>
                  <div className="text-lg font-theme-data text-[var(--acid-yellow)]">
                    {dlq.pending_count ?? 0}
                  </div>
                </div>
                <div className="p-2 bg-background rounded border border-border text-center">
                  <div className="text-[10px] text-text-muted">Processed</div>
                  <div className="text-lg font-theme-data text-[var(--accent)]">
                    {dlq.processed_count ?? 0}
                  </div>
                </div>
                <div className="p-2 bg-background rounded border border-border text-center">
                  <div className="text-[10px] text-text-muted">Failed</div>
                  <div className="text-lg font-theme-data text-[var(--crimson)]">
                    {dlq.failed_count ?? 0}
                  </div>
                </div>
              </div>
            </div>
          )}

          {/* Last Updated */}
          <div className="text-[10px] text-text-muted text-right">
            Last updated: {new Date(data.timestamp).toLocaleTimeString()}
            <button
              onClick={(e) => {
                e.stopPropagation();
                refetch();
              }}
              className="ml-2 text-[var(--acid-cyan)] hover:underline"
            >
              Refresh
            </button>
          </div>
        </div>
      )}
    </div>
  );
}

export default PlatformHealthWidget;
