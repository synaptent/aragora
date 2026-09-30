'use client';

import { useState, useEffect, useCallback } from 'react';
import Link from 'next/link';
import { Scanlines, CRTVignette } from '@/components/MatrixRain';
import { ThemeToggle } from '@/components/ThemeToggle';
import { BackendSelector, useBackend } from '@/components/BackendSelector';
import { useAuth } from '@/context/AuthContext';

interface NomicStatus {
  running: boolean;
  paused: boolean;
  current_phase: 'context' | 'debate' | 'design' | 'implement' | 'verify' | 'commit' | 'idle';
  cycle_count: number;
  last_cycle_at?: string;
  error?: string;
  state_machine: { state: string; transitions: number; last_transition?: string };
}

interface ImprovementMetrics {
  cycle_id: string;
  goal: string;
  improvement_score: number;
  tests_passed_delta: number;
  tests_failed_delta: number;
  lint_errors_delta: number;
  test_pass_rate_before: number;
  test_pass_rate_after: number;
  success_criteria_met: boolean;
  timestamp: string;
}

interface SpecialistAgent {
  agent_name: string;
  domain: string;
  elo_rating: number;
  match_count: number;
  win_rate: number;
  promoted_at: string;
}

interface EpistemicStats {
  total_beliefs: number;
  total_edges: number;
  domains: string[];
  avg_confidence: number;
  by_type: { consensus: number; claim: number; dissent: number };
}

interface CircuitBreakerStatus {
  name: string;
  state: 'closed' | 'open' | 'half_open';
  failures: number;
  last_failure?: string;
  last_success?: string;
  reset_timeout_seconds: number;
}

const PHASES = ['context', 'debate', 'design', 'implement', 'verify', 'commit'] as const;

function PhaseBadge({
  phase,
  current,
  paused,
}: {
  phase: string;
  current: boolean;
  paused: boolean;
}) {
  if (current && paused) {
    return (
      <span className="px-3 py-1.5 text-sm font-theme-data rounded border bg-acid-yellow/20 text-[var(--acid-yellow)] border-acid-yellow/40 animate-pulse">
        {phase.toUpperCase()} (PAUSED)
      </span>
    );
  }
  if (current) {
    return (
      <span className="px-3 py-1.5 text-sm font-theme-data rounded border bg-[var(--accent)]/20 text-[var(--accent)] border-[var(--accent)]/40 animate-pulse">
        {phase.toUpperCase()} (ACTIVE)
      </span>
    );
  }
  return (
    <span className="px-3 py-1.5 text-sm font-theme-data rounded border bg-surface text-text-muted border-border">
      {phase.toUpperCase()}
    </span>
  );
}

function CircuitBreakerBadge({ state }: { state: string }) {
  const colors: Record<string, string> = {
    closed: 'bg-[var(--accent)]/20 text-[var(--accent)] border-[var(--accent)]/40',
    open: 'bg-acid-red/20 text-acid-red border-acid-red/40',
    half_open: 'bg-acid-yellow/20 text-[var(--acid-yellow)] border-acid-yellow/40',
  };

  return (
    <span
      className={`px-2 py-0.5 text-xs font-theme-data rounded border ${colors[state] || colors.closed}`}
    >
      {state.toUpperCase().replace('_', '-')}
    </span>
  );
}

function formatTimeAgo(isoString?: string): string {
  if (!isoString) return 'Never';
  const date = new Date(isoString);
  const now = new Date();
  const seconds = Math.floor((now.getTime() - date.getTime()) / 1000);

  if (seconds < 60) return `${seconds}s ago`;
  if (seconds < 3600) return `${Math.floor(seconds / 60)}m ago`;
  if (seconds < 86400) return `${Math.floor(seconds / 3600)}h ago`;
  return `${Math.floor(seconds / 86400)}d ago`;
}

export default function NomicAdminPage() {
  const { config: backendConfig } = useBackend();
  const { tokens } = useAuth();
  const token = tokens?.access_token;

  const [status, setStatus] = useState<NomicStatus | null>(null);
  const [circuitBreakers, setCircuitBreakers] = useState<CircuitBreakerStatus[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [actionLoading, setActionLoading] = useState<string | null>(null);
  const [refreshInterval, setRefreshInterval] = useState<number>(5000);
  const [resetPhase, setResetPhase] = useState<string>('context');
  const [improvements, setImprovements] = useState<ImprovementMetrics[]>([]);
  const [specialists, setSpecialists] = useState<SpecialistAgent[]>([]);
  const [epistemicStats, setEpistemicStats] = useState<EpistemicStats | null>(null);

  const fetchData = useCallback(async () => {
    try {
      setError(null);
      const headers: HeadersInit = token ? { Authorization: `Bearer ${token}` } : {};

      // Fetch nomic status
      const statusRes = await fetch(`${backendConfig.api}/api/v1/admin/nomic/status`, { headers });
      if (statusRes.ok) {
        const data = await statusRes.json();
        setStatus(data);
      } else if (statusRes.status === 404) {
        setStatus({
          running: false,
          paused: false,
          current_phase: 'idle',
          cycle_count: 0,
          state_machine: { state: 'idle', transitions: 0 },
        });
      }

      // Fetch circuit breakers
      const cbRes = await fetch(`${backendConfig.api}/api/v1/admin/nomic/circuit-breakers`, {
        headers,
      });
      if (cbRes.ok) {
        const data = await cbRes.json();
        setCircuitBreakers(data.circuit_breakers || []);
      }

      // Fetch self-improvement metrics
      try {
        const metricsRes = await fetch(`${backendConfig.api}/api/v1/admin/nomic/improvements`, {
          headers,
        });
        if (metricsRes.ok) {
          const data = await metricsRes.json();
          setImprovements(data.improvements || []);
        }
      } catch {
        /* endpoint may not exist yet */
      }

      // Fetch specialist registry
      try {
        const specRes = await fetch(`${backendConfig.api}/api/v1/admin/nomic/specialists`, {
          headers,
        });
        if (specRes.ok) {
          const data = await specRes.json();
          setSpecialists(data.specialists || []);
        }
      } catch {
        /* endpoint may not exist yet */
      }

      // Fetch epistemic graph stats
      try {
        const epiRes = await fetch(`${backendConfig.api}/api/v1/admin/nomic/epistemic-stats`, {
          headers,
        });
        if (epiRes.ok) {
          const data = await epiRes.json();
          setEpistemicStats(data);
        }
      } catch {
        /* endpoint may not exist yet */
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to fetch nomic data');
    } finally {
      setLoading(false);
    }
  }, [backendConfig.api, token]);

  useEffect(() => {
    fetchData();
    const interval = setInterval(fetchData, refreshInterval);
    return () => clearInterval(interval);
  }, [fetchData, refreshInterval]);

  const handlePause = async () => {
    setActionLoading('pause');
    try {
      const headers: HeadersInit = {
        'Content-Type': 'application/json',
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
      };
      const res = await fetch(`${backendConfig.api}/api/v1/admin/nomic/pause`, {
        method: 'POST',
        headers,
      });
      if (res.ok) {
        fetchData();
      } else {
        const data = await res.json();
        setError(data.error || 'Failed to pause nomic');
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to pause nomic');
    } finally {
      setActionLoading(null);
    }
  };

  const handleResume = async () => {
    setActionLoading('resume');
    try {
      const headers: HeadersInit = {
        'Content-Type': 'application/json',
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
      };
      const res = await fetch(`${backendConfig.api}/api/v1/admin/nomic/resume`, {
        method: 'POST',
        headers,
      });
      if (res.ok) {
        fetchData();
      } else {
        const data = await res.json();
        setError(data.error || 'Failed to resume nomic');
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to resume nomic');
    } finally {
      setActionLoading(null);
    }
  };

  const handleReset = async () => {
    if (
      !confirm(
        `Reset nomic to ${resetPhase.toUpperCase()} phase? This will discard current progress.`,
      )
    ) {
      return;
    }
    setActionLoading('reset');
    try {
      const headers: HeadersInit = {
        'Content-Type': 'application/json',
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
      };
      const res = await fetch(`${backendConfig.api}/api/v1/admin/nomic/reset`, {
        method: 'POST',
        headers,
        body: JSON.stringify({ phase: resetPhase }),
      });
      if (res.ok) {
        fetchData();
      } else {
        const data = await res.json();
        setError(data.error || 'Failed to reset nomic');
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to reset nomic');
    } finally {
      setActionLoading(null);
    }
  };

  const handleResetCircuitBreakers = async () => {
    if (!confirm('Reset all circuit breakers? This will clear failure counts and allow retries.')) {
      return;
    }
    setActionLoading('reset-cb');
    try {
      const headers: HeadersInit = {
        'Content-Type': 'application/json',
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
      };
      const res = await fetch(`${backendConfig.api}/api/v1/admin/nomic/circuit-breakers/reset`, {
        method: 'POST',
        headers,
      });
      if (res.ok) {
        fetchData();
      } else {
        const data = await res.json();
        setError(data.error || 'Failed to reset circuit breakers');
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to reset circuit breakers');
    } finally {
      setActionLoading(null);
    }
  };

  if (loading) {
    return (
      <div className="min-h-screen flex items-center justify-center">
        <div className="text-[var(--accent)] font-theme-data animate-pulse">
          Loading Nomic Control Panel...
        </div>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-background relative">
      <Scanlines />
      <CRTVignette />

      <div className="relative z-10 p-4 md:p-6 space-y-6 max-w-7xl mx-auto">
        {/* Header */}
        <div className="flex flex-col md:flex-row md:items-center justify-between gap-4">
          <div>
            <Link
              href="/admin"
              className="text-text-muted hover:text-text mb-2 inline-block text-sm"
            >
              &larr; Back to Admin
            </Link>
            <h1 className="text-2xl font-theme-data text-[var(--accent)]">Nomic Control Panel</h1>
            <p className="text-sm text-text-muted font-theme-data">
              Self-improvement loop monitoring and control
            </p>
          </div>
          <div className="flex items-center gap-4">
            <select
              value={refreshInterval}
              onChange={(e) => setRefreshInterval(Number(e.target.value))}
              className="bg-surface border border-border rounded px-2 py-1 text-sm font-theme-data text-text"
            >
              <option value={2000}>2s</option>
              <option value={5000}>5s</option>
              <option value={10000}>10s</option>
              <option value={30000}>30s</option>
            </select>
            <BackendSelector />
            <ThemeToggle />
          </div>
        </div>

        {/* Error Banner */}
        {error && (
          <div className="card p-4 border-acid-red/40 bg-acid-red/10">
            <div className="flex items-center justify-between">
              <span className="text-acid-red font-theme-data text-sm">{error}</span>
              <button onClick={() => setError(null)} className="text-text-muted hover:text-text">
                &times;
              </button>
            </div>
          </div>
        )}

        {/* Status Overview */}
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">
          <div className="card p-4">
            <div className="text-xs font-theme-data text-text-muted mb-1">Status</div>
            <div
              className={`text-xl font-theme-data ${status?.running ? (status.paused ? 'text-[var(--acid-yellow)]' : 'text-[var(--accent)]') : 'text-text-muted'}`}
            >
              {status?.running ? (status.paused ? 'PAUSED' : 'RUNNING') : 'STOPPED'}
            </div>
          </div>
          <div className="card p-4">
            <div className="text-xs font-theme-data text-text-muted mb-1">Current Phase</div>
            <div className="text-xl font-theme-data text-[var(--acid-cyan)]">
              {(status?.current_phase || 'idle').toUpperCase()}
            </div>
          </div>
          <div className="card p-4">
            <div className="text-xs font-theme-data text-text-muted mb-1">Cycle Count</div>
            <div className="text-xl font-theme-data text-[var(--accent)]">
              {status?.cycle_count || 0}
            </div>
          </div>
          <div className="card p-4">
            <div className="text-xs font-theme-data text-text-muted mb-1">Last Cycle</div>
            <div className="text-xl font-theme-data text-text">
              {formatTimeAgo(status?.last_cycle_at)}
            </div>
          </div>
        </div>

        {/* Phase Progress */}
        <div className="card p-4">
          <h2 className="text-lg font-theme-data text-text mb-4">Phase Progress</h2>
          <div className="flex flex-wrap gap-2 items-center">
            {PHASES.map((phase, index) => (
              <div key={phase} className="flex items-center">
                <PhaseBadge
                  phase={phase}
                  current={status?.current_phase === phase}
                  paused={status?.paused || false}
                />
                {index < PHASES.length - 1 && <span className="mx-2 text-text-muted">&rarr;</span>}
              </div>
            ))}
          </div>
          {status?.error && (
            <div className="mt-4 p-3 bg-acid-red/10 border border-acid-red/40 rounded">
              <div className="text-xs font-theme-data text-text-muted mb-1">Last Error</div>
              <div className="text-sm font-theme-data text-acid-red">{status.error}</div>
            </div>
          )}
        </div>

        {/* Control Actions */}
        <div className="card p-4">
          <h2 className="text-lg font-theme-data text-text mb-4">Controls</h2>
          <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
            {/* Pause/Resume */}
            <div className="space-y-2">
              <div className="text-xs font-theme-data text-text-muted">Execution Control</div>
              {status?.paused ? (
                <button
                  onClick={handleResume}
                  disabled={actionLoading !== null}
                  className="w-full px-4 py-2 font-theme-data text-sm rounded border border-[var(--accent)]/40 bg-[var(--accent)]/10 text-[var(--accent)] hover:bg-[var(--accent)]/20 disabled:opacity-50 disabled:cursor-not-allowed"
                >
                  {actionLoading === 'resume' ? 'Resuming...' : 'Resume Loop'}
                </button>
              ) : (
                <button
                  onClick={handlePause}
                  disabled={actionLoading !== null || !status?.running}
                  className="w-full px-4 py-2 font-theme-data text-sm rounded border border-acid-yellow/40 bg-acid-yellow/10 text-[var(--acid-yellow)] hover:bg-acid-yellow/20 disabled:opacity-50 disabled:cursor-not-allowed"
                >
                  {actionLoading === 'pause' ? 'Pausing...' : 'Pause Loop'}
                </button>
              )}
            </div>

            {/* Reset Phase */}
            <div className="space-y-2">
              <div className="text-xs font-theme-data text-text-muted">Reset to Phase</div>
              <div className="flex gap-2">
                <select
                  value={resetPhase}
                  onChange={(e) => setResetPhase(e.target.value)}
                  className="flex-1 bg-surface border border-border rounded px-2 py-2 text-sm font-theme-data text-text"
                >
                  {PHASES.map((phase) => (
                    <option key={phase} value={phase}>
                      {phase.toUpperCase()}
                    </option>
                  ))}
                </select>
                <button
                  onClick={handleReset}
                  disabled={actionLoading !== null}
                  className="px-4 py-2 font-theme-data text-sm rounded border border-acid-red/40 bg-acid-red/10 text-acid-red hover:bg-acid-red/20 disabled:opacity-50 disabled:cursor-not-allowed"
                >
                  {actionLoading === 'reset' ? '...' : 'Reset'}
                </button>
              </div>
            </div>

            {/* Reset Circuit Breakers */}
            <div className="space-y-2">
              <div className="text-xs font-theme-data text-text-muted">Circuit Breakers</div>
              <button
                onClick={handleResetCircuitBreakers}
                disabled={actionLoading !== null}
                className="w-full px-4 py-2 font-theme-data text-sm rounded border border-acid-magenta/40 bg-acid-magenta/10 text-[var(--acid-magenta)] hover:bg-acid-magenta/20 disabled:opacity-50 disabled:cursor-not-allowed"
              >
                {actionLoading === 'reset-cb' ? 'Resetting...' : 'Reset All Breakers'}
              </button>
            </div>
          </div>
        </div>

        {/* Circuit Breakers */}
        <div className="card p-4">
          <h2 className="text-lg font-theme-data text-text mb-4">Circuit Breakers</h2>
          {circuitBreakers.length === 0 ? (
            <div className="text-sm font-theme-data text-text-muted">
              No circuit breakers registered
            </div>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-sm font-theme-data">
                <thead>
                  <tr className="border-b border-border">
                    <th className="text-left py-2 text-text-muted font-normal">Name</th>
                    <th className="text-left py-2 text-text-muted font-normal">State</th>
                    <th className="text-left py-2 text-text-muted font-normal">Failures</th>
                    <th className="text-left py-2 text-text-muted font-normal">Last Failure</th>
                    <th className="text-left py-2 text-text-muted font-normal">Last Success</th>
                    <th className="text-left py-2 text-text-muted font-normal">Reset Timeout</th>
                  </tr>
                </thead>
                <tbody>
                  {circuitBreakers.map((cb) => (
                    <tr key={cb.name} className="border-b border-border/50 hover:bg-surface/50">
                      <td className="py-2 text-text">{cb.name}</td>
                      <td className="py-2">
                        <CircuitBreakerBadge state={cb.state} />
                      </td>
                      <td className="py-2 text-text">{cb.failures}</td>
                      <td className="py-2 text-text-muted">{formatTimeAgo(cb.last_failure)}</td>
                      <td className="py-2 text-text-muted">{formatTimeAgo(cb.last_success)}</td>
                      <td className="py-2 text-text-muted">{cb.reset_timeout_seconds}s</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>

        {/* State Machine Info */}
        {status?.state_machine && (
          <div className="card p-4">
            <h2 className="text-lg font-theme-data text-text mb-4">State Machine</h2>
            <div className="grid grid-cols-1 md:grid-cols-3 gap-4 text-sm font-theme-data">
              <div>
                <span className="text-text-muted">Current State:</span>{' '}
                <span className="text-[var(--acid-cyan)]">{status.state_machine.state}</span>
              </div>
              <div>
                <span className="text-text-muted">Transitions:</span>{' '}
                <span className="text-text">{status.state_machine.transitions}</span>
              </div>
              <div>
                <span className="text-text-muted">Last Transition:</span>{' '}
                <span className="text-text">
                  {formatTimeAgo(status.state_machine.last_transition)}
                </span>
              </div>
            </div>
          </div>
        )}

        {/* Self-Improvement Metrics */}
        <div className="card p-4">
          <h2 className="text-lg font-theme-data text-text mb-4">Self-Improvement Metrics</h2>
          {improvements.length === 0 ? (
            <div className="text-sm font-theme-data text-text-muted">
              No improvement cycles recorded yet
            </div>
          ) : (
            <>
              <div className="grid grid-cols-1 md:grid-cols-4 gap-4 mb-4">
                <div className="p-3 bg-surface rounded border border-border">
                  <div className="text-xs font-theme-data text-text-muted mb-1">Total Cycles</div>
                  <div className="text-2xl font-theme-data text-[var(--accent)]">
                    {improvements.length}
                  </div>
                </div>
                <div className="p-3 bg-surface rounded border border-border">
                  <div className="text-xs font-theme-data text-text-muted mb-1">
                    Avg Improvement
                  </div>
                  <div className="text-2xl font-theme-data text-[var(--acid-cyan)]">
                    {(
                      (improvements.reduce((sum, m) => sum + m.improvement_score, 0) /
                        improvements.length) *
                      100
                    ).toFixed(1)}
                    %
                  </div>
                </div>
                <div className="p-3 bg-surface rounded border border-border">
                  <div className="text-xs font-theme-data text-text-muted mb-1">Success Rate</div>
                  <div className="text-2xl font-theme-data text-[var(--accent)]">
                    {(
                      (improvements.filter((m) => m.success_criteria_met).length /
                        improvements.length) *
                      100
                    ).toFixed(0)}
                    %
                  </div>
                </div>
                <div className="p-3 bg-surface rounded border border-border">
                  <div className="text-xs font-theme-data text-text-muted mb-1">
                    Net Tests Added
                  </div>
                  <div className="text-2xl font-theme-data text-[var(--acid-magenta)]">
                    +{improvements.reduce((sum, m) => sum + m.tests_passed_delta, 0)}
                  </div>
                </div>
              </div>
              <div className="overflow-x-auto">
                <table className="w-full text-sm font-theme-data">
                  <thead>
                    <tr className="border-b border-border">
                      <th className="text-left py-2 text-text-muted font-normal">Goal</th>
                      <th className="text-left py-2 text-text-muted font-normal">Score</th>
                      <th className="text-left py-2 text-text-muted font-normal">Tests</th>
                      <th className="text-left py-2 text-text-muted font-normal">Lint</th>
                      <th className="text-left py-2 text-text-muted font-normal">Criteria</th>
                      <th className="text-left py-2 text-text-muted font-normal">When</th>
                    </tr>
                  </thead>
                  <tbody>
                    {improvements
                      .slice(-10)
                      .reverse()
                      .map((m) => (
                        <tr
                          key={m.cycle_id}
                          className="border-b border-border/50 hover:bg-surface/50"
                        >
                          <td className="py-2 text-text max-w-xs truncate">{m.goal}</td>
                          <td className="py-2">
                            <span
                              className={
                                m.improvement_score > 0.5
                                  ? 'text-[var(--accent)]'
                                  : m.improvement_score > 0
                                    ? 'text-[var(--acid-yellow)]'
                                    : 'text-acid-red'
                              }
                            >
                              {(m.improvement_score * 100).toFixed(0)}%
                            </span>
                          </td>
                          <td className="py-2 text-text">
                            <span
                              className={
                                m.tests_passed_delta >= 0 ? 'text-[var(--accent)]' : 'text-acid-red'
                              }
                            >
                              {m.tests_passed_delta >= 0 ? '+' : ''}
                              {m.tests_passed_delta}
                            </span>
                          </td>
                          <td className="py-2">
                            <span
                              className={
                                m.lint_errors_delta <= 0 ? 'text-[var(--accent)]' : 'text-acid-red'
                              }
                            >
                              {m.lint_errors_delta <= 0 ? '' : '+'}
                              {m.lint_errors_delta}
                            </span>
                          </td>
                          <td className="py-2">
                            {m.success_criteria_met ? (
                              <span className="text-[var(--accent)]">MET</span>
                            ) : (
                              <span className="text-acid-red">MISS</span>
                            )}
                          </td>
                          <td className="py-2 text-text-muted">{formatTimeAgo(m.timestamp)}</td>
                        </tr>
                      ))}
                  </tbody>
                </table>
              </div>
            </>
          )}
        </div>

        {/* Specialist Registry */}
        <div className="card p-4">
          <h2 className="text-lg font-theme-data text-text mb-4">Domain Specialists</h2>
          {specialists.length === 0 ? (
            <div className="text-sm font-theme-data text-text-muted">
              No specialists promoted yet. Agents are promoted after 5+ domain matches with ELO 150+
              above baseline.
            </div>
          ) : (
            <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3">
              {specialists.map((s) => (
                <div
                  key={`${s.agent_name}-${s.domain}`}
                  className="p-3 bg-surface rounded border border-border"
                >
                  <div className="flex items-center justify-between mb-2">
                    <span className="font-theme-data text-[var(--acid-cyan)] text-sm">
                      {s.agent_name}
                    </span>
                    <span className="px-2 py-0.5 text-xs font-theme-data rounded border bg-acid-magenta/20 text-[var(--acid-magenta)] border-acid-magenta/40">
                      {s.domain}
                    </span>
                  </div>
                  <div className="grid grid-cols-3 gap-2 text-xs font-theme-data">
                    <div>
                      <span className="text-text-muted">ELO</span>
                      <div className="text-[var(--accent)]">{Math.round(s.elo_rating)}</div>
                    </div>
                    <div>
                      <span className="text-text-muted">Matches</span>
                      <div className="text-text">{s.match_count}</div>
                    </div>
                    <div>
                      <span className="text-text-muted">Win Rate</span>
                      <div className="text-text">{(s.win_rate * 100).toFixed(0)}%</div>
                    </div>
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>

        {/* Epistemic Graph */}
        {epistemicStats && (
          <div className="card p-4">
            <h2 className="text-lg font-theme-data text-text mb-4">Epistemic Graph</h2>
            <div className="grid grid-cols-2 md:grid-cols-5 gap-4">
              <div className="p-3 bg-surface rounded border border-border">
                <div className="text-xs font-theme-data text-text-muted mb-1">Total Beliefs</div>
                <div className="text-xl font-theme-data text-[var(--accent)]">
                  {epistemicStats.total_beliefs}
                </div>
              </div>
              <div className="p-3 bg-surface rounded border border-border">
                <div className="text-xs font-theme-data text-text-muted mb-1">Edges</div>
                <div className="text-xl font-theme-data text-[var(--acid-cyan)]">
                  {epistemicStats.total_edges}
                </div>
              </div>
              <div className="p-3 bg-surface rounded border border-border">
                <div className="text-xs font-theme-data text-text-muted mb-1">Avg Confidence</div>
                <div className="text-xl font-theme-data text-[var(--acid-yellow)]">
                  {(epistemicStats.avg_confidence * 100).toFixed(0)}%
                </div>
              </div>
              <div className="p-3 bg-surface rounded border border-border">
                <div className="text-xs font-theme-data text-text-muted mb-1">Consensus</div>
                <div className="text-xl font-theme-data text-[var(--accent)]">
                  {epistemicStats.by_type.consensus}
                </div>
              </div>
              <div className="p-3 bg-surface rounded border border-border">
                <div className="text-xs font-theme-data text-text-muted mb-1">Dissent</div>
                <div className="text-xl font-theme-data text-acid-red">
                  {epistemicStats.by_type.dissent}
                </div>
              </div>
            </div>
            {epistemicStats.domains.length > 0 && (
              <div className="mt-3 flex flex-wrap gap-2">
                <span className="text-xs font-theme-data text-text-muted">Domains:</span>
                {epistemicStats.domains.map((d) => (
                  <span
                    key={d}
                    className="px-2 py-0.5 text-xs font-theme-data rounded border bg-surface text-text border-border"
                  >
                    {d}
                  </span>
                ))}
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
