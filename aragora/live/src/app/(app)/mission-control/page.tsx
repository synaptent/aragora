'use client';

import { useState, useCallback, useMemo } from 'react';
import { useRouter } from 'next/navigation';
import { Scanlines, CRTVignette } from '@/components/MatrixRain';
// Theme-aware effects are hidden in warm/professional via .crt-effect CSS class
import { useBackend } from '@/components/BackendSelector';
import { useToastContext } from '@/context/ToastContext';
import { useAuth } from '@/context/AuthContext';
import {
  useSystemHealth,
  useCircuitBreakers,
  useAgentPoolHealth,
  useBudgetStatus,
  type CircuitBreakerInfo,
} from '@/hooks/useSystemHealth';
import { useSWRFetch } from '@/hooks/useSWRFetch';
import { logger } from '@/utils/logger';

// ============================================================================
// Types
// ============================================================================

interface SystemEvent {
  id: string;
  type: string;
  source: string;
  message: string;
  severity: 'info' | 'warning' | 'error' | 'critical';
  timestamp: string;
  metadata?: Record<string, unknown>;
}

interface DebateSummary {
  id: string;
  task: string;
  status: 'running' | 'completed' | 'failed' | 'pending';
  agents: number;
  round: number;
  total_rounds: number;
  created_at: string;
}

interface QueueStats {
  pending: number;
  running: number;
  completed_today: number;
  failed_today: number;
}

interface HistoryEvent {
  id: string;
  event_type: string;
  agent: string | null;
  timestamp: string;
  event_data?: Record<string, unknown>;
}

// ============================================================================
// Helpers
// ============================================================================

const statusColors: Record<string, string> = {
  healthy: 'text-[var(--accent)]',
  degraded: 'text-[var(--acid-yellow)]',
  critical: 'text-[var(--crimson)]',
};

const statusBgColors: Record<string, string> = {
  healthy: 'bg-[var(--accent)]/10 border-[var(--accent)]/30',
  degraded: 'bg-[var(--acid-yellow)]/10 border-[var(--acid-yellow)]/30',
  critical: 'bg-[var(--crimson)]/10 border-[var(--crimson)]/30',
};

const eventSeverityColors: Record<string, string> = {
  info: 'text-[var(--acid-cyan)]',
  warning: 'text-[var(--acid-yellow)]',
  error: 'text-[var(--warning)]',
  critical: 'text-[var(--crimson)]',
};

const breakerStateColors: Record<string, string> = {
  closed: 'text-[var(--accent)] bg-[var(--accent)]/10 border-[var(--accent)]/30',
  open: 'text-[var(--crimson)] bg-[var(--crimson)]/10 border-[var(--crimson)]/30',
  'half-open':
    'text-[var(--acid-yellow)] bg-[var(--acid-yellow)]/10 border-[var(--acid-yellow)]/30',
};

function timeAgo(timestamp: string): string {
  const diff = Date.now() - new Date(timestamp).getTime();
  const seconds = Math.floor(diff / 1000);
  if (seconds < 60) return `${seconds}s ago`;
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours}h ago`;
  return `${Math.floor(hours / 24)}d ago`;
}

function formatPercent(value: number): string {
  return `${Math.round(value * 100)}%`;
}

function getOptionalString(value: unknown): string | null {
  return typeof value === 'string' && value.trim() ? value.trim() : null;
}

function humanizeEventType(eventType: string): string {
  return eventType
    .split('_')
    .filter(Boolean)
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
    .join(' ');
}

function inferEventSeverity(
  eventType: string,
  eventData: Record<string, unknown>,
): SystemEvent['severity'] {
  const explicitSeverity = getOptionalString(eventData.severity);
  if (
    explicitSeverity === 'critical' ||
    explicitSeverity === 'error' ||
    explicitSeverity === 'warning' ||
    explicitSeverity === 'info'
  ) {
    return explicitSeverity;
  }

  const normalized = eventType.toLowerCase();
  if (normalized.includes('critical')) return 'critical';
  if (normalized.includes('error') || normalized.includes('fail') || normalized.includes('abort'))
    return 'error';
  if (
    normalized.includes('warning') ||
    normalized.includes('retry') ||
    normalized.includes('degraded')
  )
    return 'warning';
  return 'info';
}

function mapHistoryEvent(event: HistoryEvent): SystemEvent {
  const eventData = event.event_data ?? {};
  const source =
    event.agent ||
    getOptionalString(eventData.source) ||
    getOptionalString(eventData.agent) ||
    humanizeEventType(event.event_type);
  const message =
    getOptionalString(eventData.message) ||
    getOptionalString(eventData.summary) ||
    getOptionalString(eventData.title) ||
    getOptionalString(eventData.task) ||
    humanizeEventType(event.event_type);

  return {
    id: event.id,
    type: event.event_type,
    source,
    message,
    severity: inferEventSeverity(event.event_type, eventData),
    timestamp: event.timestamp,
    metadata: eventData,
  };
}

// ============================================================================
// Sub-components
// ============================================================================

function StatusIndicator({ status }: { status: string }) {
  const color =
    status === 'healthy'
      ? 'bg-[var(--accent)]'
      : status === 'degraded'
        ? 'bg-[var(--acid-yellow)]'
        : 'bg-[var(--crimson)]';
  return (
    <span
      className={`inline-block w-2 h-2 rounded-full ${color} ${status === 'healthy' ? 'animate-pulse' : ''}`}
    />
  );
}

function MetricCard({
  label,
  value,
  subValue,
  color = 'text-[var(--accent)]',
}: {
  label: string;
  value: string | number;
  subValue?: string;
  color?: string;
}) {
  return (
    <div className="card p-4">
      <div className={`text-2xl font-theme-data font-bold ${color}`}>{value}</div>
      <div className="text-xs font-theme-data text-text-muted mt-1">{label}</div>
      {subValue && (
        <div className="text-xs font-theme-data text-text-muted/60 mt-0.5">{subValue}</div>
      )}
    </div>
  );
}

function UtilizationMeter({
  label,
  value,
  max,
  unit = '',
  warning = 0.75,
  critical = 0.9,
}: {
  label: string;
  value: number;
  max: number;
  unit?: string;
  warning?: number;
  critical?: number;
}) {
  const ratio = max > 0 ? value / max : 0;
  const color =
    ratio >= critical
      ? 'bg-[var(--crimson)]'
      : ratio >= warning
        ? 'bg-[var(--acid-yellow)]'
        : 'bg-[var(--accent)]';
  const textColor =
    ratio >= critical
      ? 'text-[var(--crimson)]'
      : ratio >= warning
        ? 'text-[var(--acid-yellow)]'
        : 'text-[var(--accent)]';

  return (
    <div className="space-y-1">
      <div className="flex items-center justify-between">
        <span className="text-xs font-theme-data text-text-muted">{label}</span>
        <span className={`text-xs font-theme-data ${textColor}`}>
          {value}
          {unit} / {max}
          {unit}
        </span>
      </div>
      <div className="h-2 bg-surface border border-border rounded-full overflow-hidden">
        <div
          className={`h-full ${color} transition-all duration-500 rounded-full`}
          style={{ width: `${Math.min(ratio * 100, 100)}%` }}
        />
      </div>
    </div>
  );
}

function QuickActionButton({
  label,
  icon,
  onClick,
  loading = false,
  variant = 'primary',
}: {
  label: string;
  icon: string;
  onClick: () => void;
  loading?: boolean;
  variant?: 'primary' | 'secondary' | 'danger';
}) {
  const variantClasses = {
    primary: 'border-[var(--accent)] text-[var(--accent)] hover:bg-[var(--accent)]/10',
    secondary: 'border-[var(--acid-cyan)] text-[var(--acid-cyan)] hover:bg-[var(--acid-cyan)]/10',
    danger: 'border-[var(--crimson)] text-[var(--crimson)] hover:bg-[var(--crimson)]/10',
  };

  return (
    <button
      onClick={onClick}
      disabled={loading}
      className={`flex items-center gap-2 px-4 py-2.5 font-theme-data text-xs border transition-colors disabled:opacity-50 ${variantClasses[variant]}`}
    >
      <span className="text-sm">{icon}</span>
      {loading ? '[WORKING...]' : label}
    </button>
  );
}

function CircuitBreakerPanel({ breakers }: { breakers: CircuitBreakerInfo[] }) {
  const openBreakers = breakers.filter((b) => b.state !== 'closed');

  if (openBreakers.length === 0) {
    return (
      <div className="text-xs font-theme-data text-text-muted text-center py-3">
        All circuit breakers closed. Systems nominal.
      </div>
    );
  }

  return (
    <div className="space-y-2">
      {openBreakers.map((breaker) => (
        <div
          key={breaker.name}
          className={`px-3 py-2 border rounded text-xs font-theme-data ${breakerStateColors[breaker.state]}`}
        >
          <div className="flex items-center justify-between">
            <span className="font-bold">{breaker.name}</span>
            <span className="uppercase">[{breaker.state}]</span>
          </div>
          <div className="mt-1 opacity-70">
            Failures: {breaker.failure_count}/{breaker.failure_threshold}
            {breaker.last_failure && ` | Last: ${timeAgo(breaker.last_failure)}`}
          </div>
        </div>
      ))}
    </div>
  );
}

function ActivityFeed({ events }: { events: SystemEvent[] }) {
  if (events.length === 0) {
    return (
      <div className="text-xs font-theme-data text-text-muted text-center py-6">
        No recent system events.
      </div>
    );
  }

  return (
    <div className="space-y-1.5 max-h-[320px] overflow-y-auto pr-1">
      {events.map((event) => (
        <div
          key={event.id}
          className="flex items-start gap-2 px-2 py-1.5 rounded hover:bg-surface/50 transition-colors"
        >
          <span className={`text-xs font-theme-data mt-0.5 ${eventSeverityColors[event.severity]}`}>
            {event.severity === 'critical'
              ? '!!!'
              : event.severity === 'error'
                ? '!!'
                : event.severity === 'warning'
                  ? '!'
                  : '>'}
          </span>
          <div className="flex-1 min-w-0">
            <div className="text-xs font-theme-data text-text truncate">{event.message}</div>
            <div className="text-xs font-theme-data text-text-muted/60 flex items-center gap-2">
              <span>{event.source}</span>
              <span>{timeAgo(event.timestamp)}</span>
            </div>
          </div>
        </div>
      ))}
    </div>
  );
}

function DebateQueuePanel({
  debates,
  queue,
}: {
  debates: DebateSummary[];
  queue: QueueStats | null;
}) {
  const debateStatusColors: Record<string, string> = {
    running: 'text-[var(--accent)]',
    completed: 'text-[var(--acid-cyan)]',
    failed: 'text-[var(--crimson)]',
    pending: 'text-text-muted',
  };

  return (
    <div className="space-y-3">
      {queue && (
        <div className="grid grid-cols-4 gap-2 text-center">
          <div>
            <div className="text-lg font-theme-data text-[var(--acid-yellow)]">{queue.pending}</div>
            <div className="text-xs font-theme-data text-text-muted">Queued</div>
          </div>
          <div>
            <div className="text-lg font-theme-data text-[var(--accent)]">{queue.running}</div>
            <div className="text-xs font-theme-data text-text-muted">Running</div>
          </div>
          <div>
            <div className="text-lg font-theme-data text-[var(--acid-cyan)]">
              {queue.completed_today}
            </div>
            <div className="text-xs font-theme-data text-text-muted">Done</div>
          </div>
          <div>
            <div className="text-lg font-theme-data text-[var(--crimson)]">
              {queue.failed_today}
            </div>
            <div className="text-xs font-theme-data text-text-muted">Failed</div>
          </div>
        </div>
      )}

      {debates.length > 0 && (
        <div className="space-y-1.5">
          {debates.slice(0, 5).map((debate) => (
            <div
              key={debate.id}
              className="flex items-center justify-between px-2 py-1.5 bg-surface/30 rounded text-xs font-theme-data"
            >
              <div className="flex-1 min-w-0 truncate text-text">{debate.task}</div>
              <div className="flex items-center gap-2 ml-2 flex-shrink-0">
                {debate.status === 'running' && (
                  <span className="text-text-muted">
                    R{debate.round}/{debate.total_rounds}
                  </span>
                )}
                <span className={debateStatusColors[debate.status]}>
                  [{debate.status.toUpperCase()}]
                </span>
              </div>
            </div>
          ))}
        </div>
      )}

      {debates.length === 0 && !queue && (
        <div className="text-xs font-theme-data text-text-muted text-center py-4">
          No active debates.
        </div>
      )}
    </div>
  );
}

// ============================================================================
// Main Page Component
// ============================================================================

export default function MissionControlPage() {
  const router = useRouter();
  const { config: backendConfig } = useBackend();
  const { showToast } = useToastContext();
  const { tokens } = useAuth();

  // ---- Data hooks ----
  const { health } = useSystemHealth();
  const { breakers } = useCircuitBreakers();
  const { agents, total: totalAgents, active: activeAgents } = useAgentPoolHealth();
  const { budget } = useBudgetStatus();

  // Active debates
  const { data: debatesData } = useSWRFetch<{ data: { debates: DebateSummary[] } }>(
    '/api/debates?status=running&limit=10',
    { refreshInterval: 10000 },
  );
  const activeDebates = useMemo(
    () => (debatesData?.data?.debates ?? []) as DebateSummary[],
    [debatesData],
  );

  // Queue stats
  const { data: queueData } = useSWRFetch<QueueStats>('/api/control-plane/queue/metrics', {
    refreshInterval: 10000,
  });
  const queueStats = queueData ?? null;

  // Recent events
  const { data: eventsData } = useSWRFetch<{ events: HistoryEvent[] }>(
    '/api/history/events?limit=10',
    { refreshInterval: 15000 },
  );
  const recentEvents = useMemo(
    () => (eventsData?.events ?? []).map(mapHistoryEvent) as SystemEvent[],
    [eventsData],
  );

  // ---- Quick actions state ----
  const [actionLoading, setActionLoading] = useState<string | null>(null);

  const executeAction = useCallback(
    async (action: string, endpoint: string, method = 'POST', body?: Record<string, unknown>) => {
      setActionLoading(action);
      try {
        const headers: HeadersInit = { 'Content-Type': 'application/json' };
        if (tokens?.access_token) {
          headers.Authorization = `Bearer ${tokens.access_token}`;
        }
        const res = await fetch(`${backendConfig.api}${endpoint}`, {
          method,
          headers,
          ...(body ? { body: JSON.stringify(body) } : {}),
        });
        if (res.ok) {
          showToast(`${action} initiated successfully`, 'success');
        } else {
          const errorText = await res
            .json()
            .then((data: unknown) => {
              if (data && typeof data === 'object') {
                const message =
                  getOptionalString((data as Record<string, unknown>).error) ||
                  getOptionalString((data as Record<string, unknown>).message);
                if (message) return message;
              }
              return null;
            })
            .catch(() => null);
          showToast(errorText || `Failed to initiate ${action}`, 'error');
        }
      } catch (err) {
        logger.error(`Quick action ${action} failed:`, err);
        showToast(`Failed to initiate ${action}`, 'error');
      } finally {
        setActionLoading(null);
      }
    },
    [backendConfig.api, showToast, tokens?.access_token],
  );

  const navigateTo = useCallback(
    (href: string) => {
      router.push(href);
    },
    [router],
  );

  const handleResetBreakers = useCallback(async () => {
    if (typeof window !== 'undefined' && !window.confirm('Reset all Nomic circuit breakers?')) {
      return;
    }
    await executeAction(
      'Circuit breaker reset',
      '/api/v1/admin/nomic/circuit-breakers/reset',
      'POST',
    );
  }, [executeAction]);

  // ---- Derived state ----
  const overallStatus = health?.overall_status ?? 'healthy';
  const failingAgents = useMemo(() => agents.filter((a) => a.status === 'failed'), [agents]);
  const openBreakers = useMemo(() => breakers.filter((b) => b.state === 'open'), [breakers]);
  const hasAlerts = failingAgents.length > 0 || openBreakers.length > 0;

  return (
    <>
      <div className="crt-effect">
        <Scanlines opacity={0.02} />
        <CRTVignette />
      </div>

      <main className="min-h-screen bg-[var(--bg)] text-[var(--text)] relative z-10">
        <div className="container mx-auto px-4 py-6">
          {/* ---- Header ---- */}
          <div className="mb-6">
            <div className="flex items-center justify-between flex-wrap gap-4">
              <div>
                <h1 className="text-xl font-theme-data text-[var(--acid-green)] mb-1">
                  {'>'} MISSION CONTROL
                </h1>
                <p className="text-xs text-[var(--text-muted)] font-theme-data">
                  Real-time system operations and agent orchestration dashboard
                </p>
              </div>
              <div className="flex items-center gap-3">
                <div
                  className={`flex items-center gap-2 px-3 py-1 border rounded-full ${statusBgColors[overallStatus]}`}
                >
                  <StatusIndicator status={overallStatus} />
                  <span className={`text-xs font-theme-data ${statusColors[overallStatus]}`}>
                    {overallStatus.toUpperCase()}
                  </span>
                </div>
                {health && (
                  <div className="text-xs font-theme-data text-[var(--text-muted)]">
                    Last check: {timeAgo(health.last_check)}
                  </div>
                )}
              </div>
            </div>
          </div>

          {/* ---- Metric Summary Cards ---- */}
          <div className="grid grid-cols-2 md:grid-cols-4 lg:grid-cols-6 gap-3 mb-6">
            <MetricCard
              label="Agents Active"
              value={activeAgents}
              subValue={`of ${totalAgents} total`}
              color={activeAgents > 0 ? 'text-[var(--accent)]' : 'text-text-muted'}
            />
            <MetricCard
              label="Debates Running"
              value={activeDebates.filter((d) => d.status === 'running').length}
              subValue={queueStats ? `${queueStats.pending} queued` : undefined}
              color="text-[var(--acid-cyan)]"
            />
            <MetricCard
              label="Queue Depth"
              value={queueStats?.pending ?? 0}
              subValue={queueStats ? `${queueStats.completed_today} today` : undefined}
              color="text-[var(--acid-yellow)]"
            />
            <MetricCard
              label="Circuit Breakers"
              value={`${breakers.filter((b) => b.state === 'closed').length}/${breakers.length}`}
              subValue={openBreakers.length > 0 ? `${openBreakers.length} OPEN` : 'all closed'}
              color={openBreakers.length > 0 ? 'text-[var(--crimson)]' : 'text-[var(--accent)]'}
            />
            <MetricCard
              label="Budget Used"
              value={budget ? formatPercent(budget.utilization) : '--'}
              subValue={budget?.forecast ? `EOM: $${budget.forecast.eom.toFixed(0)}` : undefined}
              color={
                budget
                  ? budget.utilization > 0.9
                    ? 'text-[var(--crimson)]'
                    : budget.utilization > 0.75
                      ? 'text-[var(--acid-yellow)]'
                      : 'text-[var(--accent)]'
                  : 'text-text-muted'
              }
            />
            <MetricCard
              label="Subsystems"
              value={health ? Object.keys(health.subsystems).length : '--'}
              subValue={health ? `${health.collection_time_ms}ms scan` : undefined}
              color="text-accent"
            />
          </div>

          {/* ---- Main Grid: 3-column layout ---- */}
          <div className="grid grid-cols-1 lg:grid-cols-3 gap-6 mb-6">
            {/* Column 1: Quick Actions + Debate Queue */}
            <div className="space-y-6">
              {/* Quick Actions */}
              <div className="card p-4">
                <h2 className="text-sm font-theme-data font-bold text-[var(--acid-green)] mb-4 uppercase tracking-wide">
                  {'>'} Quick Actions
                </h2>
                <div className="grid grid-cols-1 gap-2">
                  <QuickActionButton
                    label="[START DEBATE]"
                    icon="$"
                    onClick={() => navigateTo('/arena')}
                    loading={actionLoading === 'Debate'}
                    variant="primary"
                  />
                  <QuickActionButton
                    label="[RUN GAUNTLET]"
                    icon="#"
                    onClick={() => navigateTo('/gauntlet')}
                    loading={actionLoading === 'Gauntlet'}
                    variant="secondary"
                  />
                  <QuickActionButton
                    label="[SELF-IMPROVE SCAN]"
                    icon="@"
                    onClick={() => navigateTo('/self-improve')}
                    loading={actionLoading === 'Self-improvement'}
                    variant="secondary"
                  />
                  <QuickActionButton
                    label="[RESET BREAKERS]"
                    icon="!"
                    onClick={handleResetBreakers}
                    loading={actionLoading === 'Circuit breaker reset'}
                    variant="danger"
                  />
                </div>
              </div>

              {/* Debate Queue */}
              <div className="card p-4">
                <h2 className="text-sm font-theme-data font-bold text-[var(--acid-green)] mb-4 uppercase tracking-wide">
                  {'>'} Debate Queue
                </h2>
                <DebateQueuePanel debates={activeDebates} queue={queueStats} />
              </div>
            </div>

            {/* Column 2: Activity Feed */}
            <div className="card p-4">
              <h2 className="text-sm font-theme-data font-bold text-[var(--acid-green)] mb-4 uppercase tracking-wide">
                {'>'} Recent Activity
              </h2>
              <ActivityFeed events={recentEvents} />
            </div>

            {/* Column 3: Alerts + Resource Utilization */}
            <div className="space-y-6">
              {/* Alert Panel */}
              <div className={`card p-4 ${hasAlerts ? 'border-[var(--crimson)]/40' : ''}`}>
                <h2
                  className={`text-sm font-theme-data font-bold mb-4 uppercase tracking-wide ${hasAlerts ? 'text-[var(--crimson)]' : 'text-[var(--acid-green)]'}`}
                >
                  {'>'} {hasAlerts ? 'ALERTS' : 'Alert Panel'}
                </h2>

                {/* Open circuit breakers */}
                <div className="mb-4">
                  <h3 className="text-xs font-theme-data text-text-muted mb-2">Circuit Breakers</h3>
                  <CircuitBreakerPanel breakers={breakers} />
                </div>

                {/* Failing agents */}
                {failingAgents.length > 0 && (
                  <div>
                    <h3 className="text-xs font-theme-data text-text-muted mb-2">Failing Agents</h3>
                    <div className="space-y-1">
                      {failingAgents.map((agent) => (
                        <div
                          key={agent.agent_id}
                          className="flex items-center justify-between px-2 py-1.5 bg-[var(--crimson)]/10 border border-[var(--crimson)]/30 rounded text-xs font-theme-data"
                        >
                          <span className="text-[var(--crimson)]">{agent.agent_id}</span>
                          <span className="text-text-muted">
                            {agent.last_heartbeat ? timeAgo(agent.last_heartbeat) : 'no heartbeat'}
                          </span>
                        </div>
                      ))}
                    </div>
                  </div>
                )}

                {!hasAlerts && (
                  <div className="text-xs font-theme-data text-text-muted text-center py-2">
                    No active alerts. All systems operational.
                  </div>
                )}
              </div>

              {/* Resource Utilization */}
              <div className="card p-4">
                <h2 className="text-sm font-theme-data font-bold text-[var(--acid-green)] mb-4 uppercase tracking-wide">
                  {'>'} Resource Utilization
                </h2>
                <div className="space-y-3">
                  <UtilizationMeter
                    label="Agent Pool"
                    value={activeAgents}
                    max={Math.max(totalAgents, 1)}
                  />
                  {budget && (
                    <UtilizationMeter
                      label="API Budget"
                      value={Math.round(budget.spent)}
                      max={Math.round(budget.total_budget)}
                      unit="$"
                    />
                  )}
                  <UtilizationMeter
                    label="Circuit Breakers Healthy"
                    value={breakers.filter((b) => b.state === 'closed').length}
                    max={Math.max(breakers.length, 1)}
                  />
                  {health?.adapters && (
                    <UtilizationMeter
                      label="KM Adapters Active"
                      value={health.adapters.active}
                      max={health.adapters.total}
                    />
                  )}
                </div>
              </div>
            </div>
          </div>

          {/* ---- Subsystem Status Grid ---- */}
          {health?.subsystems && Object.keys(health.subsystems).length > 0 && (
            <div className="card p-4 mb-6">
              <h2 className="text-sm font-theme-data font-bold text-[var(--acid-green)] mb-4 uppercase tracking-wide">
                {'>'} Subsystem Status
              </h2>
              <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-6 gap-2">
                {Object.entries(health.subsystems).map(([name, status]) => {
                  const isHealthy = status === 'healthy' || status === 'ok';
                  const isDegraded = status === 'degraded' || status === 'warning';
                  const color = isHealthy
                    ? 'border-[var(--accent)]/30 text-[var(--accent)]'
                    : isDegraded
                      ? 'border-acid-yellow/30 text-[var(--acid-yellow)]'
                      : 'border-[var(--crimson)]/30 text-[var(--crimson)]';
                  const bg = isHealthy
                    ? 'bg-[var(--accent)]/5'
                    : isDegraded
                      ? 'bg-acid-yellow/5'
                      : 'bg-[var(--crimson)]/5';

                  return (
                    <div
                      key={name}
                      className={`px-3 py-2 border rounded text-xs font-theme-data text-center ${color} ${bg}`}
                    >
                      <div className="font-bold truncate">{name}</div>
                      <div className="opacity-70 uppercase">{status}</div>
                    </div>
                  );
                })}
              </div>
            </div>
          )}

          {/* ---- Footer ---- */}
          <footer className="text-center text-xs font-theme-data py-8 border-t border-[var(--acid-green)]/20 mt-8">
            <div className="text-[var(--acid-green)]/50 mb-2">{'='.repeat(40)}</div>
            <p className="text-[var(--text-muted)]">
              {'>'} MISSION CONTROL // REAL-TIME SYSTEM OPERATIONS
            </p>
            <div className="text-[var(--acid-green)]/50 mt-4">{'='.repeat(40)}</div>
          </footer>
        </div>
      </main>
    </>
  );
}
