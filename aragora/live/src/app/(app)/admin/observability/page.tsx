'use client';

import { useState, useEffect, useCallback } from 'react';
import { AdminLayout } from '@/components/admin/AdminLayout';
import { useBackend } from '@/components/BackendSelector';
import { useObservabilityDashboard } from '@/hooks/useObservabilityDashboard';

function StatusDot({ status }: { status: 'green' | 'yellow' | 'red' | 'gray' }) {
  const colors = {
    green: 'bg-[var(--accent)] shadow-[0_0_6px_var(--acid-green)]',
    yellow: 'bg-acid-yellow shadow-[0_0_6px_var(--acid-yellow)]',
    red: 'bg-acid-red shadow-[0_0_6px_var(--acid-red)]',
    gray: 'bg-text-muted',
  };
  return <span className={`inline-block w-2 h-2 rounded-full ${colors[status]}`} />;
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
    <div className="card p-4">
      <div className="font-theme-data text-xs text-text-muted mb-1">{label}</div>
      <div className={`font-theme-data text-2xl text-${color}`}>{value}</div>
      {sub && <div className="font-theme-data text-xs text-text-muted mt-1">{sub}</div>}
    </div>
  );
}

function BarChart({
  value,
  max,
  color = 'acid-green',
}: {
  value: number;
  max: number;
  color?: string;
}) {
  const pct = max > 0 ? Math.min((value / max) * 100, 100) : 0;
  return (
    <div className="w-full h-3 bg-surface rounded overflow-hidden border border-border">
      <div
        className={`h-full bg-${color} transition-all duration-500`}
        style={{ width: `${pct}%` }}
      />
    </div>
  );
}

function cbStateColor(state: string): 'green' | 'yellow' | 'red' | 'gray' {
  const s = state.toLowerCase();
  if (s === 'closed' || s === 'ok') return 'green';
  if (s === 'half_open' || s === 'half-open') return 'yellow';
  if (s === 'open') return 'red';
  return 'gray';
}

function runStatusColor(status: string): string {
  if (status === 'completed') return 'text-[var(--accent)]';
  if (status === 'failed') return 'text-acid-red';
  if (status === 'running' || status === 'in_progress') return 'text-[var(--acid-yellow)]';
  return 'text-text-muted';
}

function formatPercent(value: number | null | undefined): string {
  if (value == null || Number.isNaN(value)) {
    return '-';
  }
  return `${(value * 100).toFixed(1)}%`;
}

export default function ObservabilityPage() {
  const { config: backendConfig } = useBackend();
  const [lastUpdated, setLastUpdated] = useState<Date | null>(null);
  const {
    dashboard: data,
    isLoading,
    isValidating,
    error,
    mutate,
  } = useObservabilityDashboard({ baseUrl: backendConfig.api, refreshInterval: 10000 });

  const fetchData = useCallback(async () => {
    await mutate();
  }, [mutate]);

  useEffect(() => {
    if (data) {
      setLastUpdated(new Date());
    }
  }, [data]);

  const overallHealth = (): 'green' | 'yellow' | 'red' => {
    if (!data) return 'gray' as 'green';
    const openBreakers = data.circuit_breakers.breakers.filter(
      (b) => b.state.toLowerCase() === 'open',
    ).length;
    if (openBreakers > 0 || data.error_rates.error_rate > 0.05) return 'red';
    if (
      data.error_rates.error_rate > 0.01 ||
      (data.system_health.memory_percent && data.system_health.memory_percent > 85)
    )
      return 'yellow';
    return 'green';
  };

  const healthLabel = { green: 'HEALTHY', yellow: 'DEGRADED', red: 'UNHEALTHY' };

  return (
    <AdminLayout
      title="Observability"
      description="Real-time system metrics, agent rankings, and health indicators."
      actions={
        <div className="flex items-center gap-3">
          {lastUpdated && (
            <span className="font-theme-data text-xs text-text-muted">
              Updated {lastUpdated.toLocaleTimeString()}
            </span>
          )}
          <button
            onClick={fetchData}
            disabled={isLoading || isValidating}
            className="px-4 py-2 bg-[var(--accent)]/20 border border-[var(--accent)]/40 text-[var(--accent)] font-theme-data text-sm rounded hover:bg-[var(--accent)]/30 transition-colors disabled:opacity-50"
          >
            {isLoading && !data ? 'Loading...' : 'Refresh'}
          </button>
        </div>
      }
    >
      {error && (
        <div className="card p-4 mb-6 border-acid-red/40 bg-acid-red/10">
          <p className="text-acid-red font-theme-data text-sm">
            Failed to load observability data: {error.message}
          </p>
        </div>
      )}

      {/* System Health Banner */}
      <div className="card p-4 mb-6 flex items-center justify-between">
        <div className="flex items-center gap-3">
          <StatusDot status={data ? overallHealth() : 'gray'} />
          <span className="font-theme-data text-sm text-text">
            System Status:{' '}
            <span
              className={`text-${
                overallHealth() === 'green'
                  ? 'acid-green'
                  : overallHealth() === 'yellow'
                    ? 'acid-yellow'
                    : 'acid-red'
              }`}
            >
              {data ? healthLabel[overallHealth()] : 'LOADING'}
            </span>
          </span>
        </div>
        {data && (
          <span className="font-theme-data text-xs text-text-muted">
            PID {data.system_health.pid} | Collected in {data.collection_time_ms}ms
          </span>
        )}
      </div>

      {/* KPI Cards Row */}
      <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-6 gap-4 mb-6">
        <MetricCard
          label="Total Debates"
          value={data?.debate_metrics.total_debates ?? '-'}
          color="acid-green"
        />
        <MetricCard
          label="Avg Duration"
          value={data ? `${data.debate_metrics.avg_duration_seconds}s` : '-'}
          color="acid-cyan"
        />
        <MetricCard
          label="Consensus Rate"
          value={data ? `${(data.debate_metrics.consensus_rate * 100).toFixed(1)}%` : '-'}
          color="acid-yellow"
        />
        <MetricCard
          label="Error Rate"
          value={data ? `${(data.error_rates.error_rate * 100).toFixed(2)}%` : '-'}
          color={data && data.error_rates.error_rate > 0.01 ? 'acid-red' : 'acid-green'}
        />
        <MetricCard
          label="CPU"
          value={
            data?.system_health.cpu_percent != null ? `${data.system_health.cpu_percent}%` : '-'
          }
          color="acid-magenta"
        />
        <MetricCard
          label="Memory"
          value={
            data?.system_health.memory_percent != null
              ? `${data.system_health.memory_percent}%`
              : '-'
          }
          color={
            data?.system_health.memory_percent && data.system_health.memory_percent > 85
              ? 'acid-red'
              : 'acid-cyan'
          }
        />
      </div>

      {/* Settlement + Oracle telemetry */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6 mb-6">
        <div className="card p-6">
          <h2 className="font-theme-data text-[var(--accent)] mb-4">Settlement Review</h2>
          {!data?.settlement_review.available ? (
            <p className="font-theme-data text-xs text-text-muted">
              Settlement review scheduler unavailable
            </p>
          ) : (
            <>
              <div className="flex items-center justify-between mb-3">
                <div className="flex items-center gap-2">
                  <StatusDot status={data.settlement_review.running ? 'green' : 'yellow'} />
                  <span className="font-theme-data text-sm text-text">
                    {data.settlement_review.running ? 'RUNNING' : 'NOT RUNNING'}
                  </span>
                </div>
                <span className="font-theme-data text-xs text-text-muted">
                  Every {data.settlement_review.interval_hours ?? '-'}h
                </span>
              </div>

              <div className="grid grid-cols-2 gap-3 mb-3">
                <div className="p-3 bg-bg rounded">
                  <div className="font-theme-data text-xs text-text-muted">Total Runs</div>
                  <div className="font-theme-data text-xl text-[var(--acid-cyan)]">
                    {data.settlement_review.stats?.total_runs ?? 0}
                  </div>
                </div>
                <div className="p-3 bg-bg rounded">
                  <div className="font-theme-data text-xs text-text-muted">Success Rate</div>
                  <div className="font-theme-data text-xl text-[var(--accent)]">
                    {formatPercent(data.settlement_review.stats?.success_rate)}
                  </div>
                </div>
                <div className="p-3 bg-bg rounded">
                  <div className="font-theme-data text-xs text-text-muted">Receipts Updated</div>
                  <div className="font-theme-data text-xl text-[var(--accent)]">
                    {data.settlement_review.stats?.total_receipts_updated ?? 0}
                  </div>
                </div>
                <div className="p-3 bg-bg rounded">
                  <div className="font-theme-data text-xs text-text-muted">Calibration Records</div>
                  <div className="font-theme-data text-xl text-[var(--acid-yellow)]">
                    {data.settlement_review.stats?.total_calibration_predictions ?? 0}
                  </div>
                </div>
              </div>

              {data.settlement_review.stats?.last_result && (
                <div className="pt-3 border-t border-border">
                  <div className="font-theme-data text-xs text-text-muted mb-2">Last Run</div>
                  <div className="grid grid-cols-3 gap-2 text-xs font-theme-data">
                    <div className="text-text-muted">
                      Due:{' '}
                      <span className="text-text">
                        {data.settlement_review.stats.last_result.receipts_due}
                      </span>
                    </div>
                    <div className="text-text-muted">
                      Updated:{' '}
                      <span className="text-[var(--accent)]">
                        {data.settlement_review.stats.last_result.receipts_updated}
                      </span>
                    </div>
                    <div className="text-text-muted">
                      Unresolved:{' '}
                      <span className="text-[var(--acid-yellow)]">
                        {data.settlement_review.stats.last_result.unresolved_due}
                      </span>
                    </div>
                  </div>
                </div>
              )}
            </>
          )}
        </div>

        <div className="card p-6">
          <h2 className="font-theme-data text-[var(--accent)] mb-4">Oracle Streaming</h2>
          {!data?.oracle_stream.available ? (
            <p className="font-theme-data text-xs text-text-muted">
              Oracle stream metrics unavailable
            </p>
          ) : (
            <>
              <div className="grid grid-cols-2 gap-3 mb-3">
                <div className="p-3 bg-bg rounded">
                  <div className="font-theme-data text-xs text-text-muted">Active Sessions</div>
                  <div className="font-theme-data text-xl text-[var(--acid-cyan)]">
                    {data.oracle_stream.active_sessions}
                  </div>
                </div>
                <div className="p-3 bg-bg rounded">
                  <div className="font-theme-data text-xs text-text-muted">Sessions Started</div>
                  <div className="font-theme-data text-xl text-text">
                    {data.oracle_stream.sessions_started}
                  </div>
                </div>
                <div className="p-3 bg-bg rounded">
                  <div className="font-theme-data text-xs text-text-muted">Stalls Total</div>
                  <div className="font-theme-data text-xl text-[var(--acid-yellow)]">
                    {data.oracle_stream.stalls_total}
                  </div>
                </div>
                <div className="p-3 bg-bg rounded">
                  <div className="font-theme-data text-xs text-text-muted">TTFT Avg</div>
                  <div className="font-theme-data text-xl text-[var(--accent)]">
                    {data.oracle_stream.ttft_avg_ms != null
                      ? `${Math.round(data.oracle_stream.ttft_avg_ms)}ms`
                      : '-'}
                  </div>
                </div>
              </div>
              <div className="text-xs font-theme-data text-text-muted">
                Completed: {data.oracle_stream.sessions_completed} | Errors:{' '}
                {data.oracle_stream.sessions_errors} | Waiting-first-token stalls:{' '}
                {data.oracle_stream.stalls_waiting_first_token}
              </div>
            </>
          )}
        </div>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6 mb-6">
        {/* Agent Leaderboard */}
        <div className="card p-6">
          <h2 className="font-theme-data text-[var(--accent)] mb-4">Agent Leaderboard</h2>
          {!data?.agent_rankings.available ? (
            <p className="font-theme-data text-xs text-text-muted">ELO system unavailable</p>
          ) : data.agent_rankings.top_agents.length === 0 ? (
            <p className="font-theme-data text-xs text-text-muted">No agent data yet</p>
          ) : (
            <div className="space-y-2">
              <div className="grid grid-cols-[2rem_1fr_4rem_4rem_4rem] gap-2 text-xs font-theme-data text-text-muted pb-2 border-b border-border">
                <span>#</span>
                <span>Agent</span>
                <span className="text-right">ELO</span>
                <span className="text-right">Matches</span>
                <span className="text-right">Win%</span>
              </div>
              {data.agent_rankings.top_agents.map((agent, idx) => {
                const maxRating = data.agent_rankings.top_agents[0]?.rating || 1500;
                return (
                  <div key={agent.name}>
                    <div className="grid grid-cols-[2rem_1fr_4rem_4rem_4rem] gap-2 text-sm font-theme-data items-center">
                      <span className="text-text-muted">{idx + 1}</span>
                      <span className="text-text truncate">{agent.name}</span>
                      <span className="text-right text-[var(--accent)]">
                        {Math.round(agent.rating)}
                      </span>
                      <span className="text-right text-text-muted">{agent.matches}</span>
                      <span className="text-right text-[var(--acid-cyan)]">
                        {(agent.win_rate * 100).toFixed(0)}%
                      </span>
                    </div>
                    <BarChart value={agent.rating} max={maxRating * 1.1} color="acid-green" />
                  </div>
                );
              })}
            </div>
          )}
        </div>

        {/* Circuit Breaker States */}
        <div className="card p-6">
          <h2 className="font-theme-data text-[var(--accent)] mb-4">Circuit Breakers</h2>
          {!data?.circuit_breakers.available ? (
            <p className="font-theme-data text-xs text-text-muted">
              Resilience registry unavailable
            </p>
          ) : data.circuit_breakers.breakers.length === 0 ? (
            <p className="font-theme-data text-xs text-text-muted">
              No circuit breakers registered
            </p>
          ) : (
            <div className="space-y-3">
              {data.circuit_breakers.breakers.map((cb) => (
                <div
                  key={cb.name}
                  className="flex items-center justify-between pb-2 border-b border-border last:border-0"
                >
                  <div className="flex items-center gap-2">
                    <StatusDot status={cbStateColor(cb.state)} />
                    <span className="font-theme-data text-sm text-text truncate max-w-[200px]">
                      {cb.name}
                    </span>
                  </div>
                  <div className="flex items-center gap-4">
                    <span className="font-theme-data text-xs text-text-muted">
                      {cb.state.toUpperCase()}
                    </span>
                    {cb.failure_count > 0 && (
                      <span className="font-theme-data text-xs text-acid-red">
                        {cb.failure_count} fail
                      </span>
                    )}
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>

      {/* Self-Improvement Status */}
      <div className="card p-6 mb-6">
        <h2 className="font-theme-data text-[var(--accent)] mb-4">Self-Improvement Cycles</h2>
        {!data?.self_improve.available ? (
          <p className="font-theme-data text-xs text-text-muted">Self-improve store unavailable</p>
        ) : (
          <>
            <div className="grid grid-cols-3 gap-4 mb-4">
              <div>
                <div className="font-theme-data text-xs text-text-muted">Total Cycles</div>
                <div className="font-theme-data text-xl text-[var(--acid-cyan)]">
                  {data.self_improve.total_cycles}
                </div>
              </div>
              <div>
                <div className="font-theme-data text-xs text-text-muted">Successful</div>
                <div className="font-theme-data text-xl text-[var(--accent)]">
                  {data.self_improve.successful}
                </div>
              </div>
              <div>
                <div className="font-theme-data text-xs text-text-muted">Failed</div>
                <div className="font-theme-data text-xl text-acid-red">
                  {data.self_improve.failed}
                </div>
              </div>
            </div>
            {data.self_improve.recent_runs.length > 0 && (
              <div className="space-y-2">
                <div className="font-theme-data text-xs text-text-muted border-b border-border pb-1">
                  Recent Runs
                </div>
                {data.self_improve.recent_runs.map((run) => (
                  <div
                    key={run.id}
                    className="flex items-center justify-between text-sm font-theme-data"
                  >
                    <span className="text-text truncate max-w-[60%]">{run.goal || run.id}</span>
                    <div className="flex items-center gap-3">
                      <span className={runStatusColor(run.status)}>{run.status.toUpperCase()}</span>
                      {run.started_at && (
                        <span className="text-xs text-text-muted">
                          {new Date(run.started_at).toLocaleDateString()}
                        </span>
                      )}
                    </div>
                  </div>
                ))}
              </div>
            )}
          </>
        )}
      </div>

      {/* Error Rates */}
      {data?.error_rates.available && (
        <div className="card p-6">
          <h2 className="font-theme-data text-[var(--accent)] mb-4">Request Metrics</h2>
          <div className="grid grid-cols-3 gap-4">
            <div>
              <div className="font-theme-data text-xs text-text-muted">Total Requests</div>
              <div className="font-theme-data text-xl text-text">
                {data.error_rates.total_requests.toLocaleString()}
              </div>
            </div>
            <div>
              <div className="font-theme-data text-xs text-text-muted">Total Errors</div>
              <div className="font-theme-data text-xl text-acid-red">
                {data.error_rates.total_errors.toLocaleString()}
              </div>
            </div>
            <div>
              <div className="font-theme-data text-xs text-text-muted">Error Rate</div>
              <div
                className={`font-theme-data text-xl ${
                  data.error_rates.error_rate > 0.01 ? 'text-acid-red' : 'text-[var(--accent)]'
                }`}
              >
                {(data.error_rates.error_rate * 100).toFixed(2)}%
              </div>
            </div>
          </div>
        </div>
      )}
    </AdminLayout>
  );
}
