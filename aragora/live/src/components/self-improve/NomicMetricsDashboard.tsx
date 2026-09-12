'use client';

import { useSWRFetch } from '@/hooks/useSWRFetch';
import { PanelErrorBoundary } from '@/components/PanelErrorBoundary';
import { HealthScoreGauge } from '@/components/nomic/HealthScoreGauge';
import { RegressionGuard } from './RegressionGuard';

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface MetricsSummary {
  health_score: number;
  cycle_success_rate: number;
  goal_completion_rate: number;
  test_pass_rate: number;
  total_cycles: number;
  completed_cycles: number;
  failed_cycles: number;
  total_subtasks: number;
  completed_subtasks: number;
  total_goals_queued: number;
  recent_activity: ActivityEntry[];
  autopilot_worktrees?: AutopilotWorktreeSummary;
}

interface ActivityEntry {
  type: string;
  message: string;
  timestamp: string;
  run_id?: string;
  status?: string;
}

interface AutopilotWorktreeSummary {
  ok?: boolean;
  managed_dir?: string;
  sessions_total?: number;
  sessions_active?: number;
  error?: string;
  stderr?: string;
}

interface GoalEntry {
  goal: string;
  source: string;
  priority: number;
  context: Record<string, unknown>;
  estimated_impact: string;
  track: string;
  status: string;
}

interface RunEntry {
  run_id: string;
  goal: string;
  status: string;
  started_at: string;
  completed_at?: string;
  duration?: number;
  total_subtasks?: number;
  completed_subtasks?: number;
  failed_subtasks?: number;
  summary?: string;
}

interface MetricsResponse {
  data: MetricsSummary;
}

interface GoalsResponse {
  data: { goals: GoalEntry[]; total: number };
}

interface RunsResponse {
  runs: RunEntry[];
  total: number;
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function formatRelativeTime(isoString: string): string {
  if (!isoString) return '--';
  try {
    const date = new Date(isoString);
    const now = new Date();
    const diffMs = now.getTime() - date.getTime();
    const diffSec = Math.floor(diffMs / 1000);
    if (diffSec < 60) return `${diffSec}s ago`;
    const diffMin = Math.floor(diffSec / 60);
    if (diffMin < 60) return `${diffMin}m ago`;
    const diffHrs = Math.floor(diffMin / 60);
    if (diffHrs < 24) return `${diffHrs}h ago`;
    const diffDays = Math.floor(diffHrs / 24);
    return `${diffDays}d ago`;
  } catch {
    return '--';
  }
}

function formatDuration(seconds?: number): string {
  if (seconds == null) return '--';
  if (seconds < 60) return `${Math.round(seconds)}s`;
  const m = Math.floor(seconds / 60);
  const s = Math.round(seconds % 60);
  return `${m}m ${s}s`;
}

function sourceLabel(source: string): string {
  const labels: Record<string, string> = {
    gauntlet_finding: 'GAUNTLET',
    introspection_gap: 'INTROSPECT',
    pulse_trending: 'PULSE',
    km_contradiction: 'KM CONFLICT',
    user_feedback: 'USER',
    manual: 'MANUAL',
  };
  return labels[source] || source.toUpperCase().replace(/_/g, ' ');
}

function sourceColor(source: string): string {
  const colors: Record<string, string> = {
    gauntlet_finding: 'text-red-400 border-red-400/30 bg-red-400/10',
    introspection_gap: 'text-blue-400 border-blue-400/30 bg-blue-400/10',
    pulse_trending: 'text-purple-400 border-purple-400/30 bg-purple-400/10',
    km_contradiction: 'text-amber-400 border-amber-400/30 bg-amber-400/10',
    user_feedback: 'text-emerald-400 border-emerald-400/30 bg-emerald-400/10',
    manual: 'text-cyan-400 border-cyan-400/30 bg-cyan-400/10',
  };
  return colors[source] || 'text-[var(--text-muted)] border-[var(--border)] bg-[var(--surface)]';
}

function impactBadge(impact: string): string {
  const styles: Record<string, string> = {
    high: 'text-red-400 border-red-400/30',
    medium: 'text-amber-400 border-amber-400/30',
    low: 'text-emerald-400 border-emerald-400/30',
  };
  return styles[impact] || 'text-[var(--text-muted)] border-[var(--border)]';
}

function activityIcon(type: string): string {
  const icons: Record<string, string> = {
    cycle_completed: '[OK]',
    cycle_failed: '[!!]',
    goal_queued: '[+G]',
    gauntlet_finding: '[GN]',
    regression_detected: '[RG]',
  };
  return icons[type] || '[--]';
}

function activityColor(type: string): string {
  const colors: Record<string, string> = {
    cycle_completed: 'text-emerald-400',
    cycle_failed: 'text-red-400',
    goal_queued: 'text-blue-400',
    gauntlet_finding: 'text-amber-400',
    regression_detected: 'text-red-400',
  };
  return colors[type] || 'text-[var(--text-muted)]';
}

function outcomeLabel(status: string): { text: string; color: string } {
  const map: Record<string, { text: string; color: string }> = {
    completed: {
      text: 'SUCCESS',
      color: 'text-emerald-400 border-emerald-400/40 bg-emerald-400/10',
    },
    failed: { text: 'FAILED', color: 'text-red-400 border-red-400/40 bg-red-400/10' },
    cancelled: { text: 'CANCELLED', color: 'text-gray-400 border-gray-400/40 bg-gray-400/10' },
    running: { text: 'RUNNING', color: 'text-amber-400 border-amber-400/40 bg-amber-400/10' },
    pending: { text: 'PENDING', color: 'text-blue-400 border-blue-400/40 bg-blue-400/10' },
  };
  return (
    map[status] || {
      text: status.toUpperCase(),
      color: 'text-[var(--text-muted)] border-[var(--border)]',
    }
  );
}

function autopilotStatus(summary?: AutopilotWorktreeSummary): { text: string; color: string } {
  if (!summary) {
    return {
      text: 'UNAVAILABLE',
      color: 'text-[var(--text-muted)] border-[var(--border)] bg-[var(--bg)]',
    };
  }
  if (summary.error || summary.ok === false) {
    return { text: 'DEGRADED', color: 'text-red-400 border-red-400/40 bg-red-400/10' };
  }
  const active = summary.sessions_active ?? 0;
  if (active > 0) {
    return { text: 'ACTIVE', color: 'text-emerald-400 border-emerald-400/40 bg-emerald-400/10' };
  }
  return { text: 'IDLE', color: 'text-cyan-400 border-cyan-400/40 bg-cyan-400/10' };
}

// ---------------------------------------------------------------------------
// Sub-components
// ---------------------------------------------------------------------------

/** Stat card with label and value */
function StatCard({
  label,
  value,
  subtext,
  color,
}: {
  label: string;
  value: string | number;
  subtext?: string;
  color?: string;
}) {
  return (
    <div className="bg-[var(--surface)] border border-[var(--border)] p-3 rounded">
      <div className="text-[10px] font-theme-data text-[var(--text-muted)] uppercase tracking-wider mb-1">
        {label}
      </div>
      <div className={`text-xl font-theme-data font-bold ${color || 'text-[var(--text)]'}`}>
        {value}
      </div>
      {subtext && (
        <div className="text-[10px] font-theme-data text-[var(--text-muted)] mt-0.5">{subtext}</div>
      )}
    </div>
  );
}

/** Mini progress bar */
function MiniBar({ value, color }: { value: number; color: string }) {
  const pct = Math.max(0, Math.min(100, value * 100));
  return (
    <div className="h-1.5 bg-[var(--bg)] rounded-full overflow-hidden">
      <div
        className={`h-full rounded-full transition-all duration-500 ${color}`}
        style={{ width: `${pct}%` }}
      />
    </div>
  );
}

// ---------------------------------------------------------------------------
// Section: Health Score + Key Metrics
// ---------------------------------------------------------------------------

function HealthAndMetricsSection({ summary }: { summary: MetricsSummary }) {
  const healthPct = Math.round(summary.health_score * 100);
  const healthLabel = healthPct >= 80 ? 'Excellent' : healthPct >= 50 ? 'Fair' : 'Needs Attention';

  return (
    <div className="bg-[var(--surface)] border border-[var(--border)] p-5">
      <div className="flex items-center justify-between mb-4">
        <h2 className="text-sm font-theme-data text-[var(--acid-green)]">
          SELF-IMPROVEMENT HEALTH
        </h2>
        <span className="text-[10px] font-theme-data text-[var(--text-muted)]">{healthLabel}</span>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-5 gap-4 items-center">
        {/* Health Gauge */}
        <div className="md:col-span-1 flex justify-center">
          <HealthScoreGauge score={summary.health_score} label="Health" />
        </div>

        {/* Metric rates */}
        <div className="md:col-span-4 grid grid-cols-2 md:grid-cols-4 gap-3">
          <div>
            <div className="flex items-center justify-between mb-1">
              <span className="text-[10px] font-theme-data text-[var(--text-muted)]">
                Cycle Success
              </span>
              <span className="text-[10px] font-theme-data text-[var(--text)]">
                {(summary.cycle_success_rate * 100).toFixed(0)}%
              </span>
            </div>
            <MiniBar
              value={summary.cycle_success_rate}
              color={
                summary.cycle_success_rate >= 0.7
                  ? 'bg-emerald-400'
                  : summary.cycle_success_rate >= 0.4
                    ? 'bg-amber-400'
                    : 'bg-red-400'
              }
            />
            <div className="text-[9px] font-theme-data text-[var(--text-muted)] mt-0.5">
              {summary.completed_cycles}/{summary.total_cycles} cycles
            </div>
          </div>

          <div>
            <div className="flex items-center justify-between mb-1">
              <span className="text-[10px] font-theme-data text-[var(--text-muted)]">
                Goal Completion
              </span>
              <span className="text-[10px] font-theme-data text-[var(--text)]">
                {(summary.goal_completion_rate * 100).toFixed(0)}%
              </span>
            </div>
            <MiniBar
              value={summary.goal_completion_rate}
              color={
                summary.goal_completion_rate >= 0.7
                  ? 'bg-emerald-400'
                  : summary.goal_completion_rate >= 0.4
                    ? 'bg-amber-400'
                    : 'bg-red-400'
              }
            />
            <div className="text-[9px] font-theme-data text-[var(--text-muted)] mt-0.5">
              {summary.completed_subtasks}/{summary.total_subtasks} subtasks
            </div>
          </div>

          <div>
            <div className="flex items-center justify-between mb-1">
              <span className="text-[10px] font-theme-data text-[var(--text-muted)]">
                Test Health
              </span>
              <span className="text-[10px] font-theme-data text-[var(--text)]">
                {(summary.test_pass_rate * 100).toFixed(0)}%
              </span>
            </div>
            <MiniBar
              value={summary.test_pass_rate}
              color={
                summary.test_pass_rate >= 0.8
                  ? 'bg-emerald-400'
                  : summary.test_pass_rate >= 0.5
                    ? 'bg-amber-400'
                    : 'bg-red-400'
              }
            />
            <div className="text-[9px] font-theme-data text-[var(--text-muted)] mt-0.5">
              inferred from findings
            </div>
          </div>

          <StatCard
            label="Goals Queued"
            value={summary.total_goals_queued}
            subtext="awaiting next cycle"
            color={
              summary.total_goals_queued > 0
                ? 'text-[var(--acid-green)]'
                : 'text-[var(--text-muted)]'
            }
          />
        </div>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Section: Cycle History Timeline
// ---------------------------------------------------------------------------

function CycleHistorySection({ runs }: { runs: RunEntry[] }) {
  // Take the last 15 runs, most recent first
  const recentRuns = [...runs]
    .sort((a, b) => {
      const ta = a.completed_at || a.started_at || '';
      const tb = b.completed_at || b.started_at || '';
      return tb.localeCompare(ta);
    })
    .slice(0, 15);

  return (
    <div className="bg-[var(--surface)] border border-[var(--border)] p-4">
      <div className="flex items-center justify-between mb-3">
        <h2 className="text-sm font-theme-data text-[var(--acid-green)]">CYCLE HISTORY</h2>
        <span className="text-[10px] font-theme-data text-[var(--text-muted)]">
          {runs.length} total
        </span>
      </div>

      {recentRuns.length === 0 ? (
        <div className="text-center py-8">
          <div className="text-[var(--text-muted)] font-theme-data text-sm mb-2">
            No cycles recorded yet
          </div>
          <div className="text-[var(--text-muted)] font-theme-data text-xs">
            Start a self-improvement cycle to see history here.
          </div>
        </div>
      ) : (
        <div className="relative pl-6 space-y-3 max-h-[400px] overflow-y-auto pr-1">
          {/* Vertical timeline line */}
          <div className="absolute left-[9px] top-2 bottom-2 w-px bg-[var(--border)]" />

          {recentRuns.map((run) => {
            const outcome = outcomeLabel(run.status);
            const ts = run.completed_at || run.started_at || '';
            const goalsInfo = run.total_subtasks
              ? `${run.completed_subtasks ?? 0}/${run.total_subtasks} goals`
              : null;

            return (
              <div key={run.run_id} className="relative">
                {/* Timeline dot */}
                <div
                  className={`absolute -left-6 top-2 w-[10px] h-[10px] rounded-full border-2 ${
                    run.status === 'completed'
                      ? 'bg-emerald-400 border-emerald-400'
                      : run.status === 'failed'
                        ? 'bg-red-400 border-red-400'
                        : run.status === 'running'
                          ? 'bg-amber-400 border-amber-400 animate-pulse'
                          : 'bg-gray-500 border-gray-500'
                  }`}
                />

                <div className="bg-[var(--bg)] border border-[var(--border)] rounded p-3">
                  {/* Header row */}
                  <div className="flex items-start justify-between gap-2 mb-1.5">
                    <div className="min-w-0 flex-1">
                      <div className="text-xs font-theme-data text-[var(--text)] truncate">
                        {run.goal}
                      </div>
                    </div>
                    <span
                      className={`shrink-0 inline-block px-1.5 py-0.5 text-[9px] font-theme-data border rounded ${outcome.color}`}
                    >
                      {outcome.text}
                    </span>
                  </div>

                  {/* Details row */}
                  <div className="flex flex-wrap gap-x-4 gap-y-0.5 text-[10px] font-theme-data text-[var(--text-muted)]">
                    <span>{run.run_id.slice(0, 8)}</span>
                    {ts && <span>{formatRelativeTime(ts)}</span>}
                    {run.duration != null && <span>{formatDuration(run.duration)}</span>}
                    {goalsInfo && <span>{goalsInfo}</span>}
                  </div>

                  {/* Summary if available */}
                  {run.summary && (
                    <div className="text-[10px] font-theme-data text-[var(--text-muted)] mt-1 truncate">
                      {run.summary}
                    </div>
                  )}
                </div>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Section: Improvement Goal Queue
// ---------------------------------------------------------------------------

function GoalQueueSection({ goals }: { goals: GoalEntry[] }) {
  return (
    <div className="bg-[var(--surface)] border border-[var(--border)] p-4">
      <div className="flex items-center justify-between mb-3">
        <h2 className="text-sm font-theme-data text-[var(--acid-green)]">IMPROVEMENT QUEUE</h2>
        <span className="text-[10px] font-theme-data text-[var(--text-muted)]">
          {goals.length} pending
        </span>
      </div>

      {goals.length === 0 ? (
        <div className="text-center py-6">
          <div className="text-[var(--text-muted)] font-theme-data text-sm mb-2">
            Queue is empty
          </div>
          <div className="text-[var(--text-muted)] font-theme-data text-xs">
            Goals are auto-generated from gauntlet scans, introspection, and pulse trending topics.
          </div>
        </div>
      ) : (
        <div className="space-y-2 max-h-[350px] overflow-y-auto pr-1">
          {goals.map((goal, idx) => (
            <div
              key={`${goal.goal.slice(0, 30)}-${idx}`}
              className="bg-[var(--bg)] border border-[var(--border)] rounded p-3"
            >
              {/* Top row: priority bar + source + impact */}
              <div className="flex items-center justify-between gap-2 mb-1.5">
                <div className="flex items-center gap-2">
                  {/* Priority indicator */}
                  <div className="flex gap-px">
                    {[0.2, 0.4, 0.6, 0.8, 1.0].map((threshold) => (
                      <div
                        key={threshold}
                        className={`w-1.5 h-3 rounded-sm ${
                          goal.priority >= threshold
                            ? goal.priority >= 0.8
                              ? 'bg-red-400'
                              : goal.priority >= 0.5
                                ? 'bg-amber-400'
                                : 'bg-emerald-400'
                            : 'bg-[var(--border)]'
                        }`}
                      />
                    ))}
                  </div>

                  {/* Source badge */}
                  <span
                    className={`inline-block px-1.5 py-0.5 text-[9px] font-theme-data border rounded ${sourceColor(goal.source)}`}
                  >
                    {sourceLabel(goal.source)}
                  </span>
                </div>

                {/* Impact badge */}
                <span
                  className={`inline-block px-1.5 py-0.5 text-[9px] font-theme-data border rounded ${impactBadge(goal.estimated_impact)}`}
                >
                  {goal.estimated_impact.toUpperCase()}
                </span>
              </div>

              {/* Goal description */}
              <div className="text-xs font-theme-data text-[var(--text)] leading-relaxed">
                {goal.goal}
              </div>

              {/* Track */}
              <div className="text-[9px] font-theme-data text-[var(--text-muted)] mt-1">
                Track: {goal.track}
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Section: Recent Activity Feed
// ---------------------------------------------------------------------------

function ActivityFeedSection({ activity }: { activity: ActivityEntry[] }) {
  return (
    <div className="bg-[var(--surface)] border border-[var(--border)] p-4">
      <div className="flex items-center justify-between mb-3">
        <h2 className="text-sm font-theme-data text-[var(--acid-green)]">RECENT ACTIVITY</h2>
        <span className="text-[10px] font-theme-data text-[var(--text-muted)]">
          last {activity.length} events
        </span>
      </div>

      {activity.length === 0 ? (
        <div className="text-center py-6">
          <div className="text-[var(--text-muted)] font-theme-data text-sm mb-2">
            No recent activity
          </div>
          <div className="text-[var(--text-muted)] font-theme-data text-xs">
            Activity will appear here as the Nomic Loop runs.
          </div>
        </div>
      ) : (
        <div className="space-y-1.5 max-h-[350px] overflow-y-auto pr-1">
          {activity.map((entry, idx) => (
            <div
              key={`${entry.timestamp}-${idx}`}
              className="flex items-start gap-2 py-1.5 border-b border-[var(--border)]/30 last:border-0"
            >
              {/* Icon */}
              <span
                className={`text-[10px] font-theme-data shrink-0 mt-0.5 ${activityColor(entry.type)}`}
              >
                {activityIcon(entry.type)}
              </span>

              {/* Content */}
              <div className="min-w-0 flex-1">
                <div className="text-xs font-theme-data text-[var(--text)] leading-relaxed">
                  {entry.message}
                </div>
                <div className="flex items-center gap-3 text-[9px] font-theme-data text-[var(--text-muted)] mt-0.5">
                  {entry.timestamp && <span>{formatRelativeTime(entry.timestamp)}</span>}
                  {entry.run_id && <span>run:{entry.run_id.slice(0, 8)}</span>}
                </div>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Section: Autopilot Worktree Health
// ---------------------------------------------------------------------------

function AutopilotWorktreesSection({ summary }: { summary?: AutopilotWorktreeSummary }) {
  const status = autopilotStatus(summary);
  const total = summary?.sessions_total ?? 0;
  const active = summary?.sessions_active ?? 0;
  const activeRatio = total > 0 ? active / total : 0;

  return (
    <div className="bg-[var(--surface)] border border-[var(--border)] p-4">
      <div className="flex items-center justify-between mb-3">
        <h2 className="text-sm font-theme-data text-[var(--acid-green)]">AUTOPILOT WORKTREES</h2>
        <span
          className={`inline-block px-1.5 py-0.5 text-[9px] font-theme-data border rounded ${status.color}`}
        >
          {status.text}
        </span>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-3 gap-3 mb-3">
        <div className="bg-[var(--bg)] border border-[var(--border)] rounded p-3">
          <div className="text-[10px] font-theme-data text-[var(--text-muted)] uppercase tracking-wider mb-1">
            Managed Dir
          </div>
          <div className="text-xs font-theme-data text-[var(--text)] truncate">
            {summary?.managed_dir || '--'}
          </div>
        </div>
        <StatCard
          label="Active Sessions"
          value={active}
          subtext={total > 0 ? `${Math.round(activeRatio * 100)}% in use` : 'no active sessions'}
          color={active > 0 ? 'text-emerald-400' : 'text-[var(--text-muted)]'}
        />
        <StatCard
          label="Total Sessions"
          value={total}
          subtext="tracked by autopilot"
          color={total > 0 ? 'text-[var(--acid-cyan)]' : 'text-[var(--text-muted)]'}
        />
      </div>

      <div className="space-y-1">
        <MiniBar value={activeRatio} color={active > 0 ? 'bg-emerald-400' : 'bg-[var(--border)]'} />
        {summary?.error && (
          <div className="text-[10px] font-theme-data text-red-400">error: {summary.error}</div>
        )}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Main Dashboard Component
// ---------------------------------------------------------------------------

export function NomicMetricsDashboard() {
  // Fetch metrics summary
  const { data: metricsRaw, isLoading: metricsLoading } = useSWRFetch<MetricsResponse>(
    '/api/self-improve/metrics/summary',
    {
      refreshInterval: 15000, // Refresh every 15 seconds
    },
  );

  // Fetch goal queue
  const { data: goalsRaw, isLoading: goalsLoading } = useSWRFetch<GoalsResponse>(
    '/api/self-improve/goals?limit=20',
    { refreshInterval: 30000 },
  );

  // Fetch run history for the timeline
  const { data: runsRaw, isLoading: runsLoading } = useSWRFetch<RunsResponse>(
    '/api/self-improve/runs?limit=50',
    { refreshInterval: 15000 },
  );

  const summary = metricsRaw?.data ?? null;
  const goals = goalsRaw?.data?.goals ?? [];
  const runs = (runsRaw as RunsResponse | null)?.runs ?? [];

  const isLoading = metricsLoading || goalsLoading || runsLoading;

  if (isLoading && !summary && goals.length === 0 && runs.length === 0) {
    return (
      <div className="space-y-4">
        <div className="bg-[var(--surface)] border border-[var(--border)] p-8 text-center">
          <div className="animate-pulse font-theme-data text-[var(--text-muted)]">
            Loading Nomic Loop metrics...
          </div>
        </div>
      </div>
    );
  }

  // Fallback summary when API is unavailable
  const safeSummary: MetricsSummary = summary ?? {
    health_score: 0,
    cycle_success_rate: 0,
    goal_completion_rate: 0,
    test_pass_rate: 1.0,
    total_cycles: runs.length,
    completed_cycles: runs.filter((r) => r.status === 'completed').length,
    failed_cycles: runs.filter((r) => r.status === 'failed').length,
    total_subtasks: 0,
    completed_subtasks: 0,
    total_goals_queued: goals.length,
    recent_activity: [],
    autopilot_worktrees: undefined,
  };

  // If we have runs but no summary, compute a basic health score
  if (!summary && runs.length > 0) {
    const total = runs.length;
    const completed = runs.filter((r) => r.status === 'completed').length;
    safeSummary.cycle_success_rate = total > 0 ? completed / total : 0;
    safeSummary.health_score = safeSummary.cycle_success_rate * 0.7 + 0.3;
  }

  // Build activity feed from runs if API doesn't return activity
  const activity: ActivityEntry[] =
    safeSummary.recent_activity.length > 0
      ? safeSummary.recent_activity
      : runs
          .filter((r) => r.status === 'completed' || r.status === 'failed')
          .sort((a, b) => {
            const ta = a.completed_at || a.started_at || '';
            const tb = b.completed_at || b.started_at || '';
            return tb.localeCompare(ta);
          })
          .slice(0, 10)
          .map((r) => ({
            type: r.status === 'completed' ? 'cycle_completed' : 'cycle_failed',
            message: r.summary || `Cycle "${r.goal}" ${r.status}`,
            timestamp: r.completed_at || r.started_at || '',
            run_id: r.run_id,
            status: r.status,
          }));

  return (
    <div className="space-y-6">
      {/* Health Score + Key Metrics - Full Width */}
      <PanelErrorBoundary panelName="HealthMetrics">
        <HealthAndMetricsSection summary={safeSummary} />
      </PanelErrorBoundary>

      {/* Managed worktree autopilot telemetry */}
      <PanelErrorBoundary panelName="AutopilotWorktrees">
        <AutopilotWorktreesSection summary={safeSummary.autopilot_worktrees} />
      </PanelErrorBoundary>

      {/* Two-column layout: Timeline + Goals */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {/* Cycle History Timeline */}
        <PanelErrorBoundary panelName="CycleHistory">
          <CycleHistorySection runs={runs} />
        </PanelErrorBoundary>

        {/* Improvement Goal Queue */}
        <PanelErrorBoundary panelName="GoalQueue">
          <GoalQueueSection goals={goals} />
        </PanelErrorBoundary>
      </div>

      {/* Two-column layout: Activity Feed + Regression Guard */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {/* Recent Activity Feed */}
        <PanelErrorBoundary panelName="ActivityFeed">
          <ActivityFeedSection activity={activity} />
        </PanelErrorBoundary>

        {/* Regression Guard (existing component) */}
        <PanelErrorBoundary panelName="RegressionGuard">
          <div className="bg-[var(--surface)] border border-[var(--border)] p-4">
            <h2 className="text-sm font-theme-data text-[var(--acid-green)] mb-3">
              REGRESSION MONITOR
            </h2>
            <RegressionGuard />
          </div>
        </PanelErrorBoundary>
      </div>
    </div>
  );
}
