'use client';

import { useState, useEffect, useCallback } from 'react';
import Link from 'next/link';
import { Scanlines, CRTVignette } from '@/components/MatrixRain';
import { AsciiBannerCompact } from '@/components/AsciiBanner';
import { ThemeToggle } from '@/components/ThemeToggle';
import { BackendSelector } from '@/components/BackendSelector';
import { PanelErrorBoundary } from '@/components/PanelErrorBoundary';
import {
  usePulseScheduler,
  SchedulerStatus,
  ScheduledDebate,
  SchedulerConfig,
  SchedulerMetrics,
} from '@/hooks/usePulseScheduler';

// ---------------------------------------------------------------------------
// Demo / fallback data
// ---------------------------------------------------------------------------

const DEMO_STATUS: SchedulerStatus = {
  state: 'running',
  run_id: 'run-demo-abc123',
  config: {
    poll_interval_seconds: 300,
    platforms: ['hackernews', 'reddit', 'twitter'],
    max_debates_per_hour: 5,
    min_interval_between_debates: 600,
    min_volume_threshold: 50,
    min_controversy_score: 0.4,
    allowed_categories: [],
    blocked_categories: ['spam', 'nsfw'],
    dedup_window_hours: 24,
    debate_rounds: 3,
    consensus_threshold: 0.7,
  },
  metrics: {
    polls_completed: 142,
    topics_evaluated: 1283,
    topics_filtered: 1091,
    debates_created: 47,
    debates_failed: 3,
    duplicates_skipped: 89,
    last_poll_at: Date.now() / 1000 - 120,
    last_debate_at: Date.now() / 1000 - 1800,
    uptime_seconds: 86400 * 3 + 7200,
  },
  store_analytics: {
    total_debates: 47,
    consensus_rate: 0.72,
    avg_confidence: 0.81,
    by_platform: { hackernews: 22, reddit: 18, twitter: 7 },
  },
};

const DEMO_HISTORY: ScheduledDebate[] = [
  {
    id: 'sd-001',
    topic: 'AI regulation in the EU: latest proposals',
    platform: 'hackernews',
    category: 'policy',
    volume: 312,
    debate_id: 'dbt-a1',
    created_at: Date.now() / 1000 - 1800,
    hours_ago: 0.5,
    consensus_reached: true,
    confidence: 0.89,
    rounds_used: 3,
    scheduler_run_id: 'run-demo-abc123',
  },
  {
    id: 'sd-002',
    topic: 'Rust vs Zig for systems programming in 2026',
    platform: 'reddit',
    category: 'technology',
    volume: 287,
    debate_id: 'dbt-a2',
    created_at: Date.now() / 1000 - 5400,
    hours_ago: 1.5,
    consensus_reached: true,
    confidence: 0.74,
    rounds_used: 3,
    scheduler_run_id: 'run-demo-abc123',
  },
  {
    id: 'sd-003',
    topic: 'Should open-source LLMs require safety evals?',
    platform: 'twitter',
    category: 'ai-safety',
    volume: 523,
    debate_id: 'dbt-a3',
    created_at: Date.now() / 1000 - 10800,
    hours_ago: 3.0,
    consensus_reached: false,
    confidence: 0.51,
    rounds_used: 3,
    scheduler_run_id: 'run-demo-abc123',
  },
  {
    id: 'sd-004',
    topic: 'Supply chain attacks via npm: new mitigations',
    platform: 'hackernews',
    category: 'security',
    volume: 198,
    debate_id: 'dbt-a4',
    created_at: Date.now() / 1000 - 18000,
    hours_ago: 5.0,
    consensus_reached: true,
    confidence: 0.92,
    rounds_used: 2,
    scheduler_run_id: 'run-demo-abc123',
  },
  {
    id: 'sd-005',
    topic: 'Postgres 18 performance benchmarks',
    platform: 'reddit',
    category: 'databases',
    volume: 156,
    debate_id: 'dbt-a5',
    created_at: Date.now() / 1000 - 28800,
    hours_ago: 8.0,
    consensus_reached: true,
    confidence: 0.85,
    rounds_used: 3,
    scheduler_run_id: 'run-demo-abc123',
  },
  {
    id: 'sd-006',
    topic: 'Is remote work productivity declining?',
    platform: 'twitter',
    category: 'culture',
    volume: 845,
    debate_id: null,
    created_at: Date.now() / 1000 - 36000,
    hours_ago: 10.0,
    consensus_reached: null,
    confidence: null,
    rounds_used: 0,
    scheduler_run_id: 'run-demo-abc123',
  },
];

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

const stateColor = (state: string) => {
  switch (state) {
    case 'running':
      return 'text-[var(--accent)]';
    case 'paused':
      return 'text-[var(--acid-yellow)]';
    case 'stopped':
      return 'text-[var(--crimson)]';
    default:
      return 'text-text-muted';
  }
};

const stateBg = (state: string) => {
  switch (state) {
    case 'running':
      return 'bg-[var(--accent)]/20 border-[var(--accent)]';
    case 'paused':
      return 'bg-acid-yellow/20 border-acid-yellow';
    case 'stopped':
      return 'bg-[var(--crimson)]/20 border-[var(--crimson)]';
    default:
      return 'bg-surface border-border';
  }
};

const platformIcon = (platform: string) => {
  switch (platform) {
    case 'hackernews':
      return 'HN';
    case 'reddit':
      return 'RD';
    case 'twitter':
      return 'TW';
    default:
      return platform.slice(0, 2).toUpperCase();
  }
};

const platformColor = (platform: string) => {
  switch (platform) {
    case 'hackernews':
      return 'text-orange-400 bg-orange-400/20';
    case 'reddit':
      return 'text-blue-400 bg-blue-400/20';
    case 'twitter':
      return 'text-[var(--acid-cyan)] bg-[var(--acid-cyan)]/20';
    default:
      return 'text-text-muted bg-surface';
  }
};

const formatUptime = (seconds: number | null) => {
  if (!seconds) return '--';
  const d = Math.floor(seconds / 86400);
  const h = Math.floor((seconds % 86400) / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  const parts: string[] = [];
  if (d) parts.push(`${d}d`);
  if (h) parts.push(`${h}h`);
  parts.push(`${m}m`);
  return parts.join(' ');
};

const formatAgo = (ts: number | null) => {
  if (!ts) return 'never';
  const secs = Math.floor(Date.now() / 1000 - ts);
  if (secs < 60) return `${secs}s ago`;
  if (secs < 3600) return `${Math.floor(secs / 60)}m ago`;
  return `${Math.floor(secs / 3600)}h ago`;
};

// ---------------------------------------------------------------------------
// Source Health Card
// ---------------------------------------------------------------------------

function SourceHealthCard({
  platform,
  metrics,
  config,
}: {
  platform: string;
  metrics: SchedulerMetrics;
  config: SchedulerConfig;
}) {
  const isEnabled = config.platforms.includes(platform);
  const debateCount = DEMO_STATUS.store_analytics?.by_platform[platform] ?? 0;

  return (
    <div className={`card p-4 ${isEnabled ? '' : 'opacity-50'}`}>
      <div className="flex items-center justify-between mb-2">
        <span
          className={`font-theme-data text-xs font-bold px-2 py-0.5 rounded ${platformColor(platform)}`}
        >
          {platformIcon(platform)}
        </span>
        <span
          className={`w-2 h-2 rounded-full ${isEnabled ? 'bg-success animate-pulse' : 'bg-text-muted'}`}
        />
      </div>
      <div className="font-theme-data text-sm capitalize mb-1">{platform}</div>
      <div className="text-xs font-theme-data text-text-muted">
        {isEnabled ? 'Active' : 'Disabled'}
      </div>
      <div className="mt-2 text-xs font-theme-data">
        <span className="text-text-muted">Debates:</span>{' '}
        <span className="text-[var(--acid-cyan)]">{debateCount}</span>
      </div>
      <div className="text-xs font-theme-data">
        <span className="text-text-muted">Last poll:</span>{' '}
        <span>{formatAgo(metrics.last_poll_at)}</span>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export default function PulseSchedulerPage() {
  const scheduler = usePulseScheduler();
  const {
    status,
    statusLoading,
    statusError,
    history,
    historyLoading,
    historyError,
    actionLoading,
    actionError,
    isRunning,
    isPaused,
    config: liveConfig,
    metrics: liveMetrics,
    fetchStatus,
    fetchHistory,
    start,
    stop,
    pause,
    resume,
    startPolling,
    stopPolling,
  } = scheduler;

  const [initialLoad, setInitialLoad] = useState(true);
  const [platformFilter, setPlatformFilter] = useState<string>('all');

  const loadData = useCallback(async () => {
    await Promise.all([fetchStatus(), fetchHistory()]);
    setInitialLoad(false);
  }, [fetchStatus, fetchHistory]);

  useEffect(() => {
    loadData();
    startPolling(30000);
    return () => stopPolling();
  }, [loadData, startPolling, stopPolling]);

  // Prefer live data, fall back to demo
  const displayStatus = status ?? DEMO_STATUS;
  const displayConfig = liveConfig ?? DEMO_STATUS.config;
  const displayMetrics = liveMetrics ?? DEMO_STATUS.metrics;
  const displayHistory = history.length > 0 ? history : DEMO_HISTORY;
  const displayAnalytics = displayStatus.store_analytics ?? DEMO_STATUS.store_analytics;
  const usingDemo = !status;

  const filteredHistory =
    platformFilter === 'all'
      ? displayHistory
      : displayHistory.filter((d) => d.platform === platformFilter);

  const acceptedTopics = displayMetrics.topics_evaluated - displayMetrics.topics_filtered;
  const rejectedTopics = displayMetrics.topics_filtered;

  const allPlatforms = ['hackernews', 'reddit', 'twitter'];

  return (
    <>
      <Scanlines opacity={0.02} />
      <CRTVignette />

      <main className="min-h-screen bg-bg text-text relative z-10">
        {/* Header */}
        <header className="border-b border-[var(--accent)]/30 bg-surface/80 backdrop-blur-sm sticky top-0 z-50">
          <div className="container mx-auto px-4 py-3 flex items-center justify-between">
            <Link href="/">
              <AsciiBannerCompact connected={true} />
            </Link>
            <div className="flex items-center gap-4">
              <Link
                href="/pulse"
                className="text-xs font-theme-data text-text-muted hover:text-[var(--accent)]"
              >
                [PULSE]
              </Link>
              <BackendSelector compact />
              <ThemeToggle />
            </div>
          </div>
        </header>

        <div className="container mx-auto px-4 py-6">
          <PanelErrorBoundary panelName="PulseScheduler">
            {/* Page Header */}
            <div className="flex items-center justify-between mb-6">
              <div>
                <div className="text-xs font-theme-data text-text-muted mb-1">
                  <Link href="/pulse" className="hover:text-[var(--accent)]">
                    Pulse
                  </Link>
                  <span className="mx-2">/</span>
                  <span className="text-[var(--accent)]">Scheduler</span>
                </div>
                <h1 className="text-2xl font-theme-data text-[var(--accent)]">Pulse Scheduler</h1>
                <p className="text-text-muted font-theme-data text-sm mt-1">
                  Trending topic ingestion and automated debate scheduling
                </p>
              </div>
              <div className="flex gap-2 items-center">
                <div
                  className={`px-3 py-1.5 border rounded font-theme-data text-xs ${stateBg(displayStatus.state)} ${stateColor(displayStatus.state)}`}
                >
                  {displayStatus.state.toUpperCase()}
                </div>
                {isRunning || (!status && displayStatus.state === 'running') ? (
                  <>
                    <button
                      onClick={() => pause()}
                      disabled={actionLoading}
                      className="px-3 py-1.5 bg-acid-yellow/20 border border-acid-yellow text-[var(--acid-yellow)] font-theme-data text-xs rounded hover:bg-acid-yellow/30 disabled:opacity-50"
                    >
                      Pause
                    </button>
                    <button
                      onClick={() => stop()}
                      disabled={actionLoading}
                      className="px-3 py-1.5 bg-[var(--crimson)]/20 border border-[var(--crimson)] text-[var(--crimson)] font-theme-data text-xs rounded hover:bg-[var(--crimson)]/30 disabled:opacity-50"
                    >
                      Stop
                    </button>
                  </>
                ) : isPaused ? (
                  <>
                    <button
                      onClick={() => resume()}
                      disabled={actionLoading}
                      className="px-3 py-1.5 bg-[var(--accent)]/20 border border-[var(--accent)] text-[var(--accent)] font-theme-data text-xs rounded hover:bg-[var(--accent)]/30 disabled:opacity-50"
                    >
                      Resume
                    </button>
                    <button
                      onClick={() => stop()}
                      disabled={actionLoading}
                      className="px-3 py-1.5 bg-[var(--crimson)]/20 border border-[var(--crimson)] text-[var(--crimson)] font-theme-data text-xs rounded hover:bg-[var(--crimson)]/30 disabled:opacity-50"
                    >
                      Stop
                    </button>
                  </>
                ) : (
                  <button
                    onClick={() => start()}
                    disabled={actionLoading}
                    className="px-3 py-1.5 bg-[var(--accent)]/20 border border-[var(--accent)] text-[var(--accent)] font-theme-data text-xs rounded hover:bg-[var(--accent)]/30 disabled:opacity-50"
                  >
                    Start
                  </button>
                )}
              </div>
            </div>

            {/* Errors */}
            {(statusError || actionError || usingDemo) && (
              <div className="mb-4 p-3 bg-[var(--crimson)]/20 border border-[var(--crimson)]/30 rounded text-[var(--crimson)] font-theme-data text-sm">
                {statusError || actionError || 'Backend unavailable'}
                <span className="ml-2 text-text-muted">(showing demo data)</span>
              </div>
            )}

            {initialLoad && statusLoading ? (
              <div className="card p-8 text-center">
                <div className="animate-pulse font-theme-data text-text-muted">
                  Fetching scheduler status...
                </div>
              </div>
            ) : (
              <>
                {/* Metrics Overview */}
                <div className="grid grid-cols-2 md:grid-cols-6 gap-4 mb-6">
                  <div className="card p-4">
                    <div className="text-xs font-theme-data text-text-muted mb-1">UPTIME</div>
                    <div className="text-xl font-theme-data text-[var(--accent)]">
                      {formatUptime(displayMetrics.uptime_seconds)}
                    </div>
                  </div>
                  <div className="card p-4">
                    <div className="text-xs font-theme-data text-text-muted mb-1">POLLS</div>
                    <div className="text-xl font-theme-data text-[var(--acid-cyan)]">
                      {displayMetrics.polls_completed.toLocaleString()}
                    </div>
                  </div>
                  <div className="card p-4">
                    <div className="text-xs font-theme-data text-text-muted mb-1">TOPICS SEEN</div>
                    <div className="text-xl font-theme-data text-purple-400">
                      {displayMetrics.topics_evaluated.toLocaleString()}
                    </div>
                  </div>
                  <div className="card p-4">
                    <div className="text-xs font-theme-data text-text-muted mb-1">
                      DEBATES CREATED
                    </div>
                    <div className="text-xl font-theme-data text-[var(--accent)]">
                      {displayMetrics.debates_created}
                    </div>
                  </div>
                  <div className="card p-4">
                    <div className="text-xs font-theme-data text-text-muted mb-1">
                      DEBATES FAILED
                    </div>
                    <div className="text-xl font-theme-data text-[var(--crimson)]">
                      {displayMetrics.debates_failed}
                    </div>
                  </div>
                  <div className="card p-4">
                    <div className="text-xs font-theme-data text-text-muted mb-1">
                      DUPES SKIPPED
                    </div>
                    <div className="text-xl font-theme-data text-[var(--acid-yellow)]">
                      {displayMetrics.duplicates_skipped}
                    </div>
                  </div>
                </div>

                {/* Source Health + Quality Filtering */}
                <div className="grid grid-cols-1 md:grid-cols-2 gap-4 mb-6">
                  {/* Source Health */}
                  <div className="card p-4">
                    <h3 className="font-theme-data text-sm text-[var(--accent)] mb-3">
                      Pulse Sources
                    </h3>
                    <div className="grid grid-cols-3 gap-3">
                      {allPlatforms.map((platform) => (
                        <SourceHealthCard
                          key={platform}
                          platform={platform}
                          metrics={displayMetrics}
                          config={displayConfig}
                        />
                      ))}
                    </div>
                  </div>

                  {/* Quality Filtering Stats */}
                  <div className="card p-4">
                    <h3 className="font-theme-data text-sm text-[var(--accent)] mb-3">
                      Quality Filtering
                    </h3>
                    <div className="space-y-4">
                      <div>
                        <div className="flex justify-between text-xs font-theme-data text-text-muted mb-1">
                          <span>Accepted Topics</span>
                          <span className="text-[var(--accent)]">{acceptedTopics}</span>
                        </div>
                        <div className="h-3 bg-surface rounded overflow-hidden">
                          <div
                            className="h-full bg-[var(--accent)] transition-all"
                            style={{
                              width: `${displayMetrics.topics_evaluated > 0 ? (acceptedTopics / displayMetrics.topics_evaluated) * 100 : 0}%`,
                            }}
                          />
                        </div>
                      </div>
                      <div>
                        <div className="flex justify-between text-xs font-theme-data text-text-muted mb-1">
                          <span>Rejected Topics</span>
                          <span className="text-[var(--crimson)]">{rejectedTopics}</span>
                        </div>
                        <div className="h-3 bg-surface rounded overflow-hidden">
                          <div
                            className="h-full bg-[var(--crimson)] transition-all"
                            style={{
                              width: `${displayMetrics.topics_evaluated > 0 ? (rejectedTopics / displayMetrics.topics_evaluated) * 100 : 0}%`,
                            }}
                          />
                        </div>
                      </div>
                      <div className="grid grid-cols-2 gap-3 mt-3 pt-3 border-t border-border">
                        <div>
                          <div className="text-xs font-theme-data text-text-muted">Min Volume</div>
                          <div className="font-theme-data text-sm">
                            {displayConfig.min_volume_threshold}
                          </div>
                        </div>
                        <div>
                          <div className="text-xs font-theme-data text-text-muted">
                            Min Controversy
                          </div>
                          <div className="font-theme-data text-sm">
                            {displayConfig.min_controversy_score}
                          </div>
                        </div>
                        <div>
                          <div className="text-xs font-theme-data text-text-muted">
                            Dedup Window
                          </div>
                          <div className="font-theme-data text-sm">
                            {displayConfig.dedup_window_hours}h
                          </div>
                        </div>
                        <div>
                          <div className="text-xs font-theme-data text-text-muted">
                            Consensus Threshold
                          </div>
                          <div className="font-theme-data text-sm">
                            {displayConfig.consensus_threshold}
                          </div>
                        </div>
                      </div>
                    </div>
                  </div>
                </div>

                {/* Scheduled Ingestion Config */}
                <div className="card p-4 mb-6">
                  <h3 className="font-theme-data text-sm text-[var(--accent)] mb-3">
                    Scheduled Ingestion
                  </h3>
                  <div className="grid grid-cols-1 md:grid-cols-4 gap-4">
                    <div>
                      <div className="text-xs font-theme-data text-text-muted mb-1">
                        Poll Interval
                      </div>
                      <div className="font-theme-data text-sm">
                        Every {displayConfig.poll_interval_seconds}s (
                        {Math.round(displayConfig.poll_interval_seconds / 60)}m)
                      </div>
                    </div>
                    <div>
                      <div className="text-xs font-theme-data text-text-muted mb-1">
                        Max Debates / Hour
                      </div>
                      <div className="font-theme-data text-sm">
                        {displayConfig.max_debates_per_hour}
                      </div>
                    </div>
                    <div>
                      <div className="text-xs font-theme-data text-text-muted mb-1">
                        Min Interval Between
                      </div>
                      <div className="font-theme-data text-sm">
                        {displayConfig.min_interval_between_debates}s
                      </div>
                    </div>
                    <div>
                      <div className="text-xs font-theme-data text-text-muted mb-1">
                        Debate Rounds
                      </div>
                      <div className="font-theme-data text-sm">{displayConfig.debate_rounds}</div>
                    </div>
                  </div>
                  <div className="mt-3 pt-3 border-t border-border grid grid-cols-1 md:grid-cols-2 gap-4">
                    <div>
                      <div className="text-xs font-theme-data text-text-muted mb-1">Last Poll</div>
                      <div className="font-theme-data text-sm">
                        {formatAgo(displayMetrics.last_poll_at)}
                      </div>
                    </div>
                    <div>
                      <div className="text-xs font-theme-data text-text-muted mb-1">
                        Last Debate Created
                      </div>
                      <div className="font-theme-data text-sm">
                        {formatAgo(displayMetrics.last_debate_at)}
                      </div>
                    </div>
                  </div>
                  {displayConfig.blocked_categories.length > 0 && (
                    <div className="mt-3 pt-3 border-t border-border">
                      <div className="text-xs font-theme-data text-text-muted mb-1">
                        Blocked Categories
                      </div>
                      <div className="flex gap-1 flex-wrap">
                        {displayConfig.blocked_categories.map((cat) => (
                          <span
                            key={cat}
                            className="font-theme-data text-xs px-2 py-0.5 rounded bg-[var(--crimson)]/20 text-[var(--crimson)]"
                          >
                            {cat}
                          </span>
                        ))}
                      </div>
                    </div>
                  )}
                </div>

                {/* Analytics */}
                {displayAnalytics && (
                  <div className="card p-4 mb-6">
                    <h3 className="font-theme-data text-sm text-[var(--accent)] mb-3">
                      Store Analytics
                    </h3>
                    <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
                      <div>
                        <div className="text-xs font-theme-data text-text-muted mb-1">
                          Total Debates
                        </div>
                        <div className="text-xl font-theme-data text-[var(--accent)]">
                          {displayAnalytics.total_debates}
                        </div>
                      </div>
                      <div>
                        <div className="text-xs font-theme-data text-text-muted mb-1">
                          Consensus Rate
                        </div>
                        <div className="text-xl font-theme-data text-[var(--acid-cyan)]">
                          {(displayAnalytics.consensus_rate * 100).toFixed(0)}%
                        </div>
                      </div>
                      <div>
                        <div className="text-xs font-theme-data text-text-muted mb-1">
                          Avg Confidence
                        </div>
                        <div className="text-xl font-theme-data text-purple-400">
                          {(displayAnalytics.avg_confidence * 100).toFixed(0)}%
                        </div>
                      </div>
                      <div>
                        <div className="text-xs font-theme-data text-text-muted mb-1">
                          By Platform
                        </div>
                        <div className="flex gap-2 mt-1">
                          {Object.entries(displayAnalytics.by_platform).map(([p, count]) => (
                            <span
                              key={p}
                              className={`font-theme-data text-xs px-1.5 py-0.5 rounded ${platformColor(p)}`}
                            >
                              {platformIcon(p)}: {count}
                            </span>
                          ))}
                        </div>
                      </div>
                    </div>
                  </div>
                )}

                {/* Trending Topic Feed */}
                <div className="card p-4">
                  <div className="flex items-center justify-between mb-3">
                    <h3 className="font-theme-data text-sm text-[var(--accent)]">
                      Recent Debates ({filteredHistory.length})
                    </h3>
                    <div className="flex gap-1">
                      <button
                        onClick={() => setPlatformFilter('all')}
                        className={`px-2 py-1 font-theme-data text-xs rounded border ${
                          platformFilter === 'all'
                            ? 'border-[var(--accent)] text-[var(--accent)] bg-[var(--accent)]/20'
                            : 'border-border text-text-muted hover:border-[var(--accent)]/50'
                        }`}
                      >
                        ALL
                      </button>
                      {allPlatforms.map((p) => (
                        <button
                          key={p}
                          onClick={() => setPlatformFilter(p)}
                          className={`px-2 py-1 font-theme-data text-xs rounded border ${
                            platformFilter === p
                              ? 'border-[var(--accent)] text-[var(--accent)] bg-[var(--accent)]/20'
                              : 'border-border text-text-muted hover:border-[var(--accent)]/50'
                          }`}
                        >
                          {platformIcon(p)}
                        </button>
                      ))}
                    </div>
                  </div>

                  {historyLoading && history.length === 0 ? (
                    <div className="py-6 text-center animate-pulse font-theme-data text-text-muted">
                      Loading history...
                    </div>
                  ) : (
                    <div className="overflow-x-auto">
                      <table className="w-full text-sm font-theme-data">
                        <thead>
                          <tr className="border-b border-border">
                            <th className="text-left py-2 pr-4 text-text-muted text-xs">SOURCE</th>
                            <th className="text-left py-2 pr-4 text-text-muted text-xs">TOPIC</th>
                            <th className="text-left py-2 pr-4 text-text-muted text-xs">
                              CATEGORY
                            </th>
                            <th className="text-center py-2 pr-4 text-text-muted text-xs">
                              VOLUME
                            </th>
                            <th className="text-center py-2 pr-4 text-text-muted text-xs">
                              CONSENSUS
                            </th>
                            <th className="text-center py-2 pr-4 text-text-muted text-xs">
                              CONFIDENCE
                            </th>
                            <th className="text-center py-2 pr-4 text-text-muted text-xs">
                              ROUNDS
                            </th>
                            <th className="text-right py-2 text-text-muted text-xs">AGE</th>
                          </tr>
                        </thead>
                        <tbody>
                          {filteredHistory.map((debate) => (
                            <tr
                              key={debate.id}
                              className="border-b border-border/50 hover:bg-surface/50"
                            >
                              <td className="py-2 pr-4">
                                <span
                                  className={`font-theme-data text-xs px-1.5 py-0.5 rounded ${platformColor(debate.platform)}`}
                                >
                                  {platformIcon(debate.platform)}
                                </span>
                              </td>
                              <td className="py-2 pr-4 max-w-sm truncate" title={debate.topic}>
                                {debate.debate_id ? (
                                  <Link
                                    href={`/debates/${debate.debate_id}`}
                                    className="hover:text-[var(--accent)]"
                                  >
                                    {debate.topic}
                                  </Link>
                                ) : (
                                  <span className="text-text-muted">{debate.topic}</span>
                                )}
                              </td>
                              <td className="py-2 pr-4 text-xs text-text-muted">
                                {debate.category}
                              </td>
                              <td className="py-2 pr-4 text-center text-[var(--acid-cyan)]">
                                {debate.volume}
                              </td>
                              <td className="py-2 pr-4 text-center">
                                {debate.consensus_reached === null ? (
                                  <span className="text-text-muted">--</span>
                                ) : debate.consensus_reached ? (
                                  <span className="text-[var(--accent)]">YES</span>
                                ) : (
                                  <span className="text-[var(--crimson)]">NO</span>
                                )}
                              </td>
                              <td className="py-2 pr-4 text-center">
                                {debate.confidence !== null ? (
                                  <span
                                    className={
                                      debate.confidence >= 0.7
                                        ? 'text-[var(--accent)]'
                                        : debate.confidence >= 0.5
                                          ? 'text-[var(--acid-yellow)]'
                                          : 'text-[var(--crimson)]'
                                    }
                                  >
                                    {(debate.confidence * 100).toFixed(0)}%
                                  </span>
                                ) : (
                                  <span className="text-text-muted">--</span>
                                )}
                              </td>
                              <td className="py-2 pr-4 text-center text-text-muted">
                                {debate.rounds_used || '--'}
                              </td>
                              <td className="py-2 text-right text-text-muted text-xs">
                                {debate.hours_ago < 1
                                  ? `${Math.round(debate.hours_ago * 60)}m`
                                  : `${debate.hours_ago.toFixed(1)}h`}
                              </td>
                            </tr>
                          ))}
                          {filteredHistory.length === 0 && (
                            <tr>
                              <td colSpan={8} className="py-8 text-center text-text-muted">
                                No debates found
                                {platformFilter !== 'all' ? ` for ${platformFilter}` : ''}
                              </td>
                            </tr>
                          )}
                        </tbody>
                      </table>
                    </div>
                  )}
                </div>

                {historyError && (
                  <div className="mt-2 text-xs font-theme-data text-[var(--crimson)]">
                    {historyError}
                  </div>
                )}
              </>
            )}
          </PanelErrorBoundary>
        </div>

        {/* Footer */}
        <footer className="text-center text-xs font-theme-data py-8 border-t border-[var(--accent)]/20 mt-8">
          <div className="text-[var(--accent)]/50 mb-2">{'='.repeat(40)}</div>
          <p className="text-text-muted">{'>'} ARAGORA // PULSE SCHEDULER</p>
        </footer>
      </main>
    </>
  );
}
