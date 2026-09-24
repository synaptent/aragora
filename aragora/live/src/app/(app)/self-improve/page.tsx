'use client';

import { Suspense, useCallback, useEffect, useRef, useState } from 'react';
import Link from 'next/link';
import { useSearchParams } from 'next/navigation';
import { Scanlines, CRTVignette } from '@/components/MatrixRain';
import { API_BASE_URL } from '@/config';
import { MetaPlannerView } from '@/components/self-improve/MetaPlannerView';
import { ExecutionTimeline } from '@/components/self-improve/ExecutionTimeline';
import { LearningFeed } from '@/components/self-improve/LearningFeed';
import { BudgetTracker } from '@/components/self-improve/BudgetTracker';
import { NomicMetricsDashboard } from '@/components/self-improve/NomicMetricsDashboard';

// --- Types ---

interface RunEntry {
  run_id: string;
  goal: string;
  status: string;
  started_at: string;
  completed_at?: string;
  duration?: number;
}

interface StatusResponse {
  state: 'idle' | 'running';
  active_runs: number;
  runs: RunEntry[];
}

interface RunsResponse {
  runs: RunEntry[];
  total: number;
  limit: number;
  offset: number;
}

interface StartResponse {
  run_id: string;
  status: 'started' | 'preview';
  plan?: Record<string, unknown>;
}

interface FeedbackMetrics {
  debates_processed: number;
  agents_tracked: number;
  avg_adjustment: number;
}

interface RegressionEntry {
  cycle_id: string;
  regressed_metrics: string[];
  recommendation: string;
}

interface FeedbackState {
  regression_history: RegressionEntry[];
  selection_adjustments: Record<string, number>;
  feedback_metrics: FeedbackMetrics;
}

// --- Phase progress ---

const PHASES = ['planning', 'decomposing', 'executing', 'verifying', 'merging'] as const;

function phaseIndex(phase: string): number {
  const idx = PHASES.indexOf(phase as (typeof PHASES)[number]);
  return idx === -1 ? 0 : idx;
}

function statusBadge(status: string) {
  const colors: Record<string, string> = {
    running: 'text-amber-400 border-amber-400/40 bg-amber-400/10',
    completed: 'text-emerald-400 border-emerald-400/40 bg-emerald-400/10',
    failed: 'text-red-400 border-red-400/40 bg-red-400/10',
    cancelled: 'text-gray-400 border-gray-400/40 bg-gray-400/10',
    preview: 'text-blue-400 border-blue-400/40 bg-blue-400/10',
  };
  return (
    <span
      className={`inline-block px-2 py-0.5 text-[10px] font-theme-data border rounded ${colors[status] || colors.cancelled}`}
    >
      {status.toUpperCase()}
    </span>
  );
}

function formatDuration(seconds?: number): string {
  if (seconds == null) return '--';
  if (seconds < 60) return `${Math.round(seconds)}s`;
  const m = Math.floor(seconds / 60);
  const s = Math.round(seconds % 60);
  return `${m}m ${s}s`;
}

// --- Component ---

export default function SelfImprovePage() {
  return (
    <Suspense
      fallback={
        <div className="min-h-screen bg-bg text-text font-theme-data flex items-center justify-center">
          <span className="animate-pulse text-[var(--accent)]">Loading...</span>
        </div>
      }
    >
      <SelfImprovePageInner />
    </Suspense>
  );
}

function SelfImprovePageInner() {
  // Tab navigation
  const [activeTab, setActiveTab] = useState<
    'runs' | 'planner' | 'execution' | 'learning' | 'metrics'
  >('runs');

  // URL parameter handling for cross-page seeding
  const searchParams = useSearchParams();
  const fromSource = searchParams.get('from');
  const fromId = searchParams.get('id');

  // Start panel state
  const [goal, setGoal] = useState('');
  const [dryRun, setDryRun] = useState(false);
  const [requireApproval, setRequireApproval] = useState(true);
  const [budgetLimit, setBudgetLimit] = useState<number>(10);
  const [starting, setStarting] = useState(false);
  const [planPreview, setPlanPreview] = useState<Record<string, unknown> | null>(null);
  const [startError, setStartError] = useState('');

  // Status polling
  const [status, setStatus] = useState<StatusResponse | null>(null);

  // History
  const [runs, setRuns] = useState<RunEntry[]>([]);
  const [runsTotal, setRunsTotal] = useState(0);
  const [historyLoading, setHistoryLoading] = useState(true);

  // Feedback loop state
  const [feedback, setFeedback] = useState<FeedbackState | null>(null);

  const pollingRef = useRef<ReturnType<typeof setInterval> | null>(null);

  // --- Fetch feedback ---
  const fetchFeedback = useCallback(async () => {
    try {
      const res = await fetch(`${API_BASE_URL}/api/self-improve/feedback`);
      if (res.ok) {
        const json = await res.json();
        setFeedback(json.data ?? json);
      }
    } catch {
      /* ignore transient network errors */
    }
  }, []);

  // --- Fetch history ---
  const fetchHistory = useCallback(async () => {
    try {
      const res = await fetch(`${API_BASE_URL}/api/self-improve/runs?limit=50&offset=0`);
      if (res.ok) {
        const data: RunsResponse = await res.json();
        setRuns(data.runs || []);
        setRunsTotal(data.total ?? 0);
      }
    } finally {
      setHistoryLoading(false);
    }
  }, []);

  // --- Fetch status ---
  const fetchStatus = useCallback(async () => {
    try {
      const res = await fetch(`${API_BASE_URL}/api/self-improve/status`);
      if (res.ok) {
        const data: StatusResponse = await res.json();
        setStatus(data);
      }
    } catch {
      /* ignore transient network errors */
    }
  }, []);

  // Pre-fill goal from cross-page navigation
  useEffect(() => {
    if (fromSource && fromId && !goal) {
      const prefix = fromSource === 'debate' ? 'Improve based on debate' : 'Execute pipeline';
      setGoal(`${prefix} #${fromId}`);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [fromSource, fromId]);

  // Initial load
  useEffect(() => {
    fetchHistory();
    fetchStatus();
    fetchFeedback();
  }, [fetchHistory, fetchStatus, fetchFeedback]);

  // Poll when not idle
  useEffect(() => {
    if (status?.state === 'running') {
      if (!pollingRef.current) {
        pollingRef.current = setInterval(() => {
          fetchStatus();
          fetchHistory();
          fetchFeedback();
        }, 3000);
      }
    } else if (pollingRef.current) {
      clearInterval(pollingRef.current);
      pollingRef.current = null;
    }
    return () => {
      if (pollingRef.current) clearInterval(pollingRef.current);
    };
  }, [status?.state, fetchStatus, fetchHistory, fetchFeedback]);

  // --- Start cycle ---
  const startCycle = async () => {
    if (!goal.trim()) return;
    setStarting(true);
    setStartError('');
    setPlanPreview(null);

    try {
      const res = await fetch(`${API_BASE_URL}/api/self-improve/run`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          goal: goal.trim(),
          dry_run: dryRun,
          require_approval: requireApproval,
          budget_limit_usd: budgetLimit,
        }),
      });

      if (!res.ok) {
        const text = await res.text().catch(() => '');
        setStartError(text || `HTTP ${res.status}`);
        return;
      }

      const data: StartResponse = await res.json();

      if (data.status === 'preview' && data.plan) {
        setPlanPreview(data.plan);
      } else {
        setGoal('');
        setPlanPreview(null);
        fetchStatus();
        fetchHistory();
      }
    } catch {
      setStartError('Network error');
    } finally {
      setStarting(false);
    }
  };

  // --- Current phase from status ---
  const currentPhase = status?.runs?.[0]?.status ?? '';
  const activePhaseIdx = phaseIndex(currentPhase);

  return (
    <>
      <Scanlines opacity={0.02} />
      <CRTVignette />

      <main className="min-h-screen bg-[var(--bg)] text-[var(--text)] relative z-10">
        <div className="container mx-auto px-4 py-6">
          {/* Header */}
          <div className="mb-6">
            <div className="flex items-center gap-3 mb-2">
              <Link
                href="/dashboard"
                className="text-xs font-theme-data text-[var(--text-muted)] hover:text-[var(--acid-green)] transition-colors"
              >
                DASHBOARD
              </Link>
              <span className="text-xs font-theme-data text-[var(--text-muted)]">/</span>
              <span className="text-xs font-theme-data text-[var(--acid-green)]">SELF-IMPROVE</span>
            </div>
            <h1 className="text-xl font-theme-data text-[var(--acid-green)] mb-1">
              {'>'} SELF-IMPROVEMENT ENGINE
            </h1>
            <p className="text-xs text-[var(--text-muted)] font-theme-data">
              Autonomous Nomic Loop -- goal decomposition, execution, and verification
            </p>
          </div>

          {/* Cross-page seeding banner */}
          {fromSource && fromId && (
            <div className="card p-3 mb-4 border border-blue-400/30">
              <span className="text-xs font-theme-data text-blue-400">
                Seeded from {fromSource === 'debate' ? 'Debate' : 'Pipeline'} #{fromId}
              </span>
            </div>
          )}

          {/* Tab Navigation */}
          <div className="flex gap-1 mb-4 border-b border-[var(--text-muted)]/20 pb-2">
            {(['runs', 'planner', 'execution', 'learning', 'metrics'] as const).map((tab) => (
              <button
                key={tab}
                onClick={() => setActiveTab(tab)}
                className={`px-3 py-1.5 text-xs font-theme-data rounded-t transition-colors ${
                  activeTab === tab
                    ? 'text-[var(--acid-green)] border-b-2 border-[var(--acid-green)]'
                    : 'text-[var(--text-muted)] hover:text-[var(--text)]'
                }`}
              >
                {tab.charAt(0).toUpperCase() + tab.slice(1)}
              </button>
            ))}
          </div>

          {/* Tab Content */}
          {activeTab === 'planner' && <MetaPlannerView />}
          {activeTab === 'execution' && (
            <>
              <BudgetTracker />
              <ExecutionTimeline />
            </>
          )}
          {activeTab === 'learning' && <LearningFeed />}
          {activeTab === 'metrics' && <NomicMetricsDashboard />}

          {activeTab === 'runs' && (
            <>
              {/* Start Panel */}
              <div className="bg-[var(--surface)] border border-[var(--border)] p-4 mb-6">
                <h2 className="text-sm font-theme-data text-[var(--acid-green)] mb-3">
                  START CYCLE
                </h2>

                <div className="space-y-3">
                  <div>
                    <label className="block text-xs font-theme-data text-[var(--text-muted)] mb-1">
                      Objective
                    </label>
                    <input
                      type="text"
                      value={goal}
                      onChange={(e) => setGoal(e.target.value)}
                      placeholder="e.g. Improve test coverage for debate module"
                      className="w-full bg-[var(--bg)] border border-[var(--border)] rounded px-2 py-1 text-sm font-theme-data text-[var(--text)] placeholder:text-[var(--text-muted)]/50 focus:border-[var(--acid-green)]/50 focus:outline-none"
                      onKeyDown={(e) => e.key === 'Enter' && startCycle()}
                    />
                  </div>

                  <div className="flex items-center gap-6 flex-wrap">
                    {/* Dry run toggle */}
                    <label className="flex items-center gap-2 cursor-pointer">
                      <input
                        type="checkbox"
                        checked={dryRun}
                        onChange={(e) => setDryRun(e.target.checked)}
                        className="accent-[var(--acid-green)]"
                      />
                      <span className="text-xs font-theme-data text-[var(--text-muted)]">
                        Dry run
                      </span>
                    </label>

                    {/* Require approval toggle */}
                    <label className="flex items-center gap-2 cursor-pointer">
                      <input
                        type="checkbox"
                        checked={requireApproval}
                        onChange={(e) => setRequireApproval(e.target.checked)}
                        className="accent-[var(--acid-green)]"
                      />
                      <span className="text-xs font-theme-data text-[var(--text-muted)]">
                        Require approval
                      </span>
                    </label>

                    {/* Budget limit */}
                    <div className="flex items-center gap-2">
                      <label className="text-xs font-theme-data text-[var(--text-muted)]">
                        Budget $
                      </label>
                      <input
                        type="number"
                        min={0}
                        step={1}
                        value={budgetLimit}
                        onChange={(e) => setBudgetLimit(Number(e.target.value))}
                        className="w-20 bg-[var(--bg)] border border-[var(--border)] rounded px-2 py-1 text-sm font-theme-data text-[var(--text)] focus:border-[var(--acid-green)]/50 focus:outline-none"
                      />
                    </div>
                  </div>

                  <div className="flex items-center gap-3">
                    <button
                      onClick={startCycle}
                      disabled={starting || !goal.trim()}
                      className={`px-4 py-1.5 text-xs font-theme-data border transition-colors ${
                        starting || !goal.trim()
                          ? 'bg-[var(--surface)] text-[var(--text-muted)] border-[var(--border)] cursor-not-allowed'
                          : 'bg-[var(--acid-green)]/20 text-[var(--acid-green)] border-[var(--acid-green)]/50 hover:bg-[var(--acid-green)]/30'
                      }`}
                    >
                      {starting ? 'STARTING...' : dryRun ? 'PREVIEW PLAN' : 'START CYCLE'}
                    </button>

                    {startError && (
                      <span className="text-xs font-theme-data text-red-400">{startError}</span>
                    )}
                  </div>
                </div>

                {/* Plan preview (dry run result) */}
                {planPreview && (
                  <div className="mt-4 bg-[var(--bg)] border border-[var(--acid-green)]/30 rounded p-3">
                    <h3 className="text-xs font-theme-data text-[var(--acid-green)] mb-2">
                      PLAN PREVIEW
                    </h3>
                    <pre className="text-xs font-theme-data text-[var(--text-muted)] whitespace-pre-wrap overflow-auto max-h-64">
                      {JSON.stringify(planPreview, null, 2)}
                    </pre>
                  </div>
                )}
              </div>

              {/* Active Cycle Monitor */}
              <div className="bg-[var(--surface)] border border-[var(--border)] p-4 mb-6">
                <div className="flex items-center justify-between mb-3">
                  <h2 className="text-sm font-theme-data text-[var(--acid-green)]">ACTIVE CYCLE</h2>
                  <span className="text-xs font-theme-data text-[var(--text-muted)]">
                    {status?.state === 'running'
                      ? `${status.active_runs} active run${status.active_runs !== 1 ? 's' : ''}`
                      : 'IDLE'}
                  </span>
                </div>

                {/* Phase progress bar */}
                <div className="flex items-center gap-1">
                  {PHASES.map((phase, idx) => {
                    const isActive = status?.state === 'running' && idx === activePhaseIdx;
                    const isComplete = status?.state === 'running' && idx < activePhaseIdx;

                    return (
                      <div key={phase} className="flex-1 flex flex-col items-center gap-1">
                        <div
                          className={`w-full h-1.5 rounded-sm transition-colors ${
                            isActive
                              ? 'bg-[var(--acid-green)] animate-pulse'
                              : isComplete
                                ? 'bg-[var(--acid-green)]/60'
                                : 'bg-[var(--border)]'
                          }`}
                        />
                        <span
                          className={`text-[10px] font-theme-data ${
                            isActive
                              ? 'text-[var(--acid-green)]'
                              : isComplete
                                ? 'text-[var(--acid-green)]/60'
                                : 'text-[var(--text-muted)]'
                          }`}
                        >
                          {phase.toUpperCase()}
                        </span>
                      </div>
                    );
                  })}
                </div>

                {status?.state !== 'running' && (
                  <p className="text-xs font-theme-data text-[var(--text-muted)] mt-3 text-center">
                    No active cycles. Start one above.
                  </p>
                )}
              </div>

              {/* Feedback Loop Metrics */}
              {feedback && (
                <div className="bg-[var(--surface)] border border-[var(--border)] p-4 mb-6">
                  <h2 className="text-sm font-theme-data text-[var(--acid-green)] mb-3">
                    FEEDBACK LOOP METRICS
                  </h2>
                  <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-4">
                    <div>
                      <span className="block text-[10px] font-theme-data text-[var(--text-muted)]">
                        DEBATES PROCESSED
                      </span>
                      <span className="text-lg font-theme-data text-[var(--text)]">
                        {feedback.feedback_metrics.debates_processed}
                      </span>
                    </div>
                    <div>
                      <span className="block text-[10px] font-theme-data text-[var(--text-muted)]">
                        AGENTS TRACKED
                      </span>
                      <span className="text-lg font-theme-data text-[var(--text)]">
                        {feedback.feedback_metrics.agents_tracked}
                      </span>
                    </div>
                    <div>
                      <span className="block text-[10px] font-theme-data text-[var(--text-muted)]">
                        AVG ADJUSTMENT
                      </span>
                      <span
                        className={`text-lg font-theme-data ${feedback.feedback_metrics.avg_adjustment >= 0 ? 'text-emerald-400' : 'text-red-400'}`}
                      >
                        {feedback.feedback_metrics.avg_adjustment >= 0 ? '+' : ''}
                        {feedback.feedback_metrics.avg_adjustment.toFixed(4)}
                      </span>
                    </div>
                    <div>
                      <span className="block text-[10px] font-theme-data text-[var(--text-muted)]">
                        RECENT REGRESSIONS
                      </span>
                      <span
                        className={`text-lg font-theme-data ${feedback.regression_history.length > 0 ? 'text-red-400' : 'text-emerald-400'}`}
                      >
                        {feedback.regression_history.length}
                      </span>
                    </div>
                  </div>

                  {/* Agent Selection Weights */}
                  {Object.keys(feedback.selection_adjustments).length > 0 && (
                    <div className="mb-3">
                      <span className="block text-[10px] font-theme-data text-[var(--text-muted)] mb-1">
                        AGENT SELECTION WEIGHTS
                      </span>
                      <div className="flex flex-wrap gap-2">
                        {Object.entries(feedback.selection_adjustments).map(([agent, adj]) => (
                          <span
                            key={agent}
                            className={`inline-block px-2 py-0.5 text-[10px] font-theme-data border rounded ${
                              adj >= 0
                                ? 'text-emerald-400 border-emerald-400/40 bg-emerald-400/10'
                                : 'text-red-400 border-red-400/40 bg-red-400/10'
                            }`}
                          >
                            {agent}: {adj >= 0 ? '+' : ''}
                            {adj.toFixed(3)}
                          </span>
                        ))}
                      </div>
                    </div>
                  )}
                </div>
              )}

              {/* History Table */}
              <div className="bg-[var(--surface)] border border-[var(--border)] p-4">
                <div className="flex items-center justify-between mb-3">
                  <h2 className="text-sm font-theme-data text-[var(--acid-green)]">RUN HISTORY</h2>
                  <span className="text-xs font-theme-data text-[var(--text-muted)]">
                    {runsTotal} total
                  </span>
                </div>

                {historyLoading ? (
                  <p className="text-xs font-theme-data text-[var(--text-muted)]">Loading...</p>
                ) : runs.length === 0 ? (
                  <p className="text-xs font-theme-data text-[var(--text-muted)] text-center py-6">
                    No runs yet. Start your first self-improvement cycle.
                  </p>
                ) : (
                  <div className="overflow-x-auto">
                    <table className="w-full text-xs font-theme-data">
                      <thead>
                        <tr className="text-[var(--text-muted)] border-b border-[var(--border)]">
                          <th className="text-left py-2 pr-4">RUN ID</th>
                          <th className="text-left py-2 pr-4">GOAL</th>
                          <th className="text-left py-2 pr-4">STATUS</th>
                          <th className="text-left py-2 pr-4">STARTED</th>
                          <th className="text-left py-2">DURATION</th>
                        </tr>
                      </thead>
                      <tbody>
                        {runs.map((run) => (
                          <tr
                            key={run.run_id}
                            className="border-b border-[var(--border)]/50 hover:bg-[var(--bg)]/50"
                          >
                            <td className="py-2 pr-4 text-[var(--text-muted)]">
                              {run.run_id.slice(0, 8)}
                            </td>
                            <td className="py-2 pr-4 text-[var(--text)] max-w-xs truncate">
                              {run.goal}
                            </td>
                            <td className="py-2 pr-4">
                              {statusBadge(run.status)}
                              {feedback?.regression_history.some(
                                (r) => r.cycle_id === run.run_id,
                              ) && (
                                <span className="ml-1 inline-block px-1 py-0.5 text-[9px] font-theme-data text-red-400 border border-red-400/40 bg-red-400/10 rounded">
                                  REGRESSED
                                </span>
                              )}
                            </td>
                            <td className="py-2 pr-4 text-[var(--text-muted)]">
                              {new Date(run.started_at).toLocaleString()}
                            </td>
                            <td className="py-2 text-[var(--text-muted)]">
                              {formatDuration(run.duration)}
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                )}
              </div>

              {/* Navigation */}
              <div className="mt-8 flex items-center gap-2 pt-4 border-t border-[var(--border)]">
                <span className="text-xs font-theme-data text-[var(--text-muted)]">Navigate:</span>
                <Link
                  href="/dashboard"
                  className="px-3 py-1 text-xs font-theme-data bg-[var(--surface)] text-[var(--text-muted)] border border-[var(--border)] hover:border-[var(--acid-green)]/30 transition-colors"
                >
                  DASHBOARD
                </Link>
                <Link
                  href="/arena"
                  className="px-3 py-1 text-xs font-theme-data bg-[var(--acid-green)]/10 text-[var(--acid-green)] border border-[var(--acid-green)]/30 hover:bg-[var(--acid-green)]/20 transition-colors"
                >
                  NEW DEBATE
                </Link>
                <Link
                  href="/nomic-control"
                  className="px-3 py-1 text-xs font-theme-data bg-[var(--surface)] text-[var(--text-muted)] border border-[var(--border)] hover:border-[var(--acid-green)]/30 transition-colors"
                >
                  NOMIC CONTROL
                </Link>
              </div>
            </>
          )}
        </div>
      </main>
    </>
  );
}
