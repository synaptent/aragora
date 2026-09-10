'use client';

import Link from 'next/link';
import { AsciiBannerCompact } from '@/components/AsciiBanner';
import { BackendSelector, useBackend } from '@/components/BackendSelector';
import { ErrorWithRetry } from '@/components/ErrorWithRetry';
import { Scanlines, CRTVignette } from '@/components/MatrixRain';
import { PanelErrorBoundary } from '@/components/PanelErrorBoundary';
import { ThemeToggle } from '@/components/ThemeToggle';
import { useSWRFetch } from '@/hooks/useSWRFetch';

interface SwarmBlocker {
  issue_number: number | null;
  terminal_class: string;
  failure_reason: string | null;
  blocker_kind: string | null;
  blocker_evidence: string | null;
  issue_title: string | null;
}

interface SwarmLatestTick {
  timestamp: string;
  issue_number: number | null;
  terminal_class: string;
  elapsed_seconds: number | null;
}

interface SwarmStatusResponse {
  status: 'active' | 'no_data' | string;
  metrics_path: string;
  window: number;
  total_ticks: number;
  unique_issues_attempted?: number;
  unique_issues_succeeded?: number;
  success_rate?: number;
  tick_success_rate?: number;
  terminal_class_distribution?: Record<string, number>;
  outcome_distribution?: Record<string, number>;
  failure_reason_distribution?: Record<string, number>;
  rescue_class_summary?: Record<string, number>;
  recent_blockers?: SwarmBlocker[];
  latest_tick?: SwarmLatestTick;
}

function percent(value: number | undefined): string {
  if (typeof value !== 'number' || Number.isNaN(value)) {
    return '0.0%';
  }
  return `${(value * 100).toFixed(1)}%`;
}

function formatElapsed(seconds: number | null | undefined): string {
  if (typeof seconds !== 'number' || Number.isNaN(seconds)) {
    return 'n/a';
  }
  if (seconds < 60) {
    return `${seconds.toFixed(0)}s`;
  }
  return `${(seconds / 60).toFixed(1)}m`;
}

function formatTimestamp(value: string | null | undefined): string {
  if (!value) return 'unknown';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleString();
}

function toneForTerminalClass(name: string): string {
  if (name.startsWith('success') || name.startsWith('deliverable')) {
    return 'text-emerald-300 border-emerald-500/30 bg-emerald-500/10';
  }
  if (name.includes('blocked') || name.includes('needs_human')) {
    return 'text-amber-300 border-amber-500/30 bg-amber-500/10';
  }
  return 'text-red-300 border-red-500/30 bg-red-500/10';
}

function metricEntries(metrics: Record<string, number> | undefined): Array<[string, number]> {
  return Object.entries(metrics ?? {});
}

function StatCard({ label, value, sublabel }: { label: string; value: string; sublabel: string }) {
  return (
    <div className="rounded-lg border border-[var(--accent)]/20 bg-surface/70 p-4">
      <div className="text-[10px] font-theme-data uppercase tracking-[0.25em] text-text-muted">
        {label}
      </div>
      <div className="mt-3 text-3xl font-theme-display text-[var(--accent)]">{value}</div>
      <div className="mt-2 text-xs font-theme-data text-text-muted">{sublabel}</div>
    </div>
  );
}

function DistributionList({ title, items }: { title: string; items: Array<[string, number]> }) {
  return (
    <section className="rounded-lg border border-[var(--accent)]/20 bg-surface/60 p-4">
      <div className="text-xs font-theme-data uppercase tracking-[0.25em] text-text-muted">
        {title}
      </div>
      <div className="mt-4 space-y-3">
        {items.length === 0 ? (
          <div className="text-sm font-theme-data text-text-muted">No data in current window.</div>
        ) : (
          items.map(([name, count]) => (
            <div key={name} className="flex items-center justify-between gap-4">
              <div className="min-w-0 flex-1">
                <div className="truncate text-sm font-theme-data text-text">{name}</div>
              </div>
              <div className="rounded border border-[var(--accent)]/20 px-2 py-1 text-xs font-theme-data text-[var(--accent)]">
                {count}
              </div>
            </div>
          ))
        )}
      </div>
    </section>
  );
}

function BlockerRow({ blocker }: { blocker: SwarmBlocker }) {
  return (
    <div className="rounded-lg border border-[var(--accent)]/15 bg-bg/40 p-3">
      <div className="flex flex-wrap items-center gap-2">
        <span className="text-xs font-theme-data text-[var(--accent)]">
          #{blocker.issue_number ?? 'unknown'}
        </span>
        <span
          className={`rounded border px-2 py-0.5 text-[10px] font-theme-data uppercase ${toneForTerminalClass(blocker.terminal_class)}`}
        >
          {blocker.terminal_class || 'unknown'}
        </span>
        {blocker.blocker_kind ? (
          <span className="rounded border border-border px-2 py-0.5 text-[10px] font-theme-data uppercase text-text-muted">
            {blocker.blocker_kind}
          </span>
        ) : null}
      </div>
      <div className="mt-2 text-sm font-theme-data text-text">
        {blocker.issue_title ?? 'Untitled issue'}
      </div>
      <div className="mt-2 text-xs font-theme-data text-text-muted">
        {blocker.failure_reason ?? 'No explicit failure reason recorded.'}
      </div>
      {blocker.blocker_evidence ? (
        <div className="mt-2 rounded border border-amber-500/20 bg-amber-500/5 px-2 py-2 text-xs font-theme-data text-amber-100">
          {blocker.blocker_evidence}
        </div>
      ) : null}
    </div>
  );
}

export default function SwarmStatusPage() {
  const { config } = useBackend();
  const { data, error, isLoading, mutate } = useSWRFetch<SwarmStatusResponse>(
    '/api/v1/swarm/status',
    { baseUrl: config.api, refreshInterval: 30000 },
  );

  const status = data?.status ?? 'no_data';
  const terminalClasses = metricEntries(data?.terminal_class_distribution);
  const failureReasons = metricEntries(data?.failure_reason_distribution);
  const rescueClasses = metricEntries(data?.rescue_class_summary);
  const blockers = data?.recent_blockers ?? [];
  const latestTick = data?.latest_tick;

  return (
    <>
      <Scanlines opacity={0.02} />
      <CRTVignette />

      <main className="min-h-screen bg-bg text-text relative z-10">
        <header className="sticky top-0 z-50 border-b border-[var(--accent)]/30 bg-surface/80 backdrop-blur-sm">
          <div className="container mx-auto flex items-center justify-between gap-4 px-4 py-3">
            <Link href="/">
              <AsciiBannerCompact connected={true} />
            </Link>
            <div className="flex items-center gap-3">
              <Link
                href="/system-intelligence"
                className="text-xs font-theme-data text-text-muted transition-colors hover:text-[var(--accent)]"
              >
                [SYSTEM]
              </Link>
              <Link
                href="/quality"
                className="text-xs font-theme-data text-text-muted transition-colors hover:text-[var(--accent)]"
              >
                [QUALITY]
              </Link>
              <BackendSelector compact />
              <ThemeToggle />
            </div>
          </div>
        </header>

        <div className="container mx-auto px-4 py-6">
          <div className="mb-6 flex flex-col gap-3 md:flex-row md:items-end md:justify-between">
            <div>
              <div className="text-xs font-theme-data uppercase tracking-[0.35em] text-text-muted">
                Thin Operator Surface
              </div>
              <h1 className="mt-2 text-3xl font-theme-display text-[var(--accent)]">
                Swarm Status
              </h1>
              <p className="mt-2 max-w-3xl text-sm font-theme-data text-text-muted">
                Live boss-loop health from the recent metrics window, with blocker evidence and
                terminal-class distribution.
              </p>
            </div>
            <div className="rounded-lg border border-[var(--accent)]/20 bg-surface/60 px-4 py-3 text-right">
              <div className="text-[10px] font-theme-data uppercase tracking-[0.25em] text-text-muted">
                Source
              </div>
              <div className="mt-2 text-xs font-theme-data text-text">
                {data?.metrics_path ?? '.aragora/overnight/boss_metrics.jsonl'}
              </div>
              <div className="mt-1 text-xs font-theme-data text-text-muted">
                Window: {data?.window ?? 0} ticks
              </div>
            </div>
          </div>

          <PanelErrorBoundary panelName="Swarm Status">
            {error ? (
              <ErrorWithRetry
                error={error.message || 'Failed to load swarm status'}
                onRetry={() => void mutate()}
              />
            ) : (
              <div className="space-y-6">
                <section className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
                  <StatCard
                    label="Session State"
                    value={status === 'active' ? 'ACTIVE' : 'NO DATA'}
                    sublabel={
                      isLoading ? 'Loading current metrics window…' : 'Swarm status endpoint'
                    }
                  />
                  <StatCard
                    label="Issue Success"
                    value={percent(data?.success_rate)}
                    sublabel={`${data?.unique_issues_succeeded ?? 0} of ${data?.unique_issues_attempted ?? 0} issues`}
                  />
                  <StatCard
                    label="Tick Success"
                    value={percent(data?.tick_success_rate)}
                    sublabel={`${data?.total_ticks ?? 0} total ticks in window`}
                  />
                  <StatCard
                    label="Latest Tick"
                    value={latestTick?.issue_number ? `#${latestTick.issue_number}` : 'n/a'}
                    sublabel={
                      latestTick
                        ? `${latestTick.terminal_class || 'unknown'} in ${formatElapsed(latestTick.elapsed_seconds)}`
                        : 'No recent tick recorded'
                    }
                  />
                </section>

                <section className="grid gap-6 xl:grid-cols-[1.35fr_0.95fr]">
                  <section className="rounded-lg border border-[var(--accent)]/20 bg-surface/60 p-5">
                    <div className="flex items-center justify-between gap-4">
                      <div>
                        <div className="text-xs font-theme-data uppercase tracking-[0.25em] text-text-muted">
                          Recent Blockers
                        </div>
                        <div className="mt-2 text-sm font-theme-data text-text-muted">
                          The latest non-success terminal classes from the metrics window.
                        </div>
                      </div>
                      <div className="rounded border border-[var(--accent)]/20 px-3 py-1 text-xs font-theme-data text-[var(--accent)]">
                        {blockers.length} shown
                      </div>
                    </div>
                    <div className="mt-4 space-y-3">
                      {blockers.length === 0 ? (
                        <div className="rounded-lg border border-dashed border-[var(--accent)]/20 bg-bg/30 px-4 py-8 text-center text-sm font-theme-data text-text-muted">
                          No blockers recorded in the current metrics window.
                        </div>
                      ) : (
                        blockers.map((blocker) => (
                          <BlockerRow
                            key={`${blocker.issue_number ?? 'unknown'}-${blocker.terminal_class}-${blocker.failure_reason ?? 'none'}`}
                            blocker={blocker}
                          />
                        ))
                      )}
                    </div>
                  </section>

                  <section className="space-y-6">
                    <DistributionList title="Terminal Classes" items={terminalClasses} />
                    <DistributionList title="Failure Reasons" items={failureReasons} />
                    <DistributionList title="Rescue Classes" items={rescueClasses} />
                  </section>
                </section>

                <section className="rounded-lg border border-[var(--accent)]/20 bg-surface/60 p-5">
                  <div className="text-xs font-theme-data uppercase tracking-[0.25em] text-text-muted">
                    Latest Tick Detail
                  </div>
                  {latestTick ? (
                    <div className="mt-4 grid gap-4 md:grid-cols-4">
                      <div>
                        <div className="text-[10px] font-theme-data uppercase tracking-[0.2em] text-text-muted">
                          Timestamp
                        </div>
                        <div className="mt-2 text-sm font-theme-data text-text">
                          {formatTimestamp(latestTick.timestamp)}
                        </div>
                      </div>
                      <div>
                        <div className="text-[10px] font-theme-data uppercase tracking-[0.2em] text-text-muted">
                          Issue
                        </div>
                        <div className="mt-2 text-sm font-theme-data text-text">
                          {latestTick.issue_number ? `#${latestTick.issue_number}` : 'n/a'}
                        </div>
                      </div>
                      <div>
                        <div className="text-[10px] font-theme-data uppercase tracking-[0.2em] text-text-muted">
                          Terminal Class
                        </div>
                        <div className="mt-2 text-sm font-theme-data text-text">
                          {latestTick.terminal_class || 'unknown'}
                        </div>
                      </div>
                      <div>
                        <div className="text-[10px] font-theme-data uppercase tracking-[0.2em] text-text-muted">
                          Elapsed
                        </div>
                        <div className="mt-2 text-sm font-theme-data text-text">
                          {formatElapsed(latestTick.elapsed_seconds)}
                        </div>
                      </div>
                    </div>
                  ) : (
                    <div className="mt-4 text-sm font-theme-data text-text-muted">
                      No latest tick metadata available yet.
                    </div>
                  )}
                </section>
              </div>
            )}
          </PanelErrorBoundary>
        </div>
      </main>
    </>
  );
}
