'use client';

import type { ReactNode } from 'react';
import { useCallback, useMemo, useState } from 'react';
import { AdminLayout } from '@/components/admin/AdminLayout';
import { useBackend } from '@/components/BackendSelector';
import { useSWRFetch } from '@/hooks/useSWRFetch';

interface LandingSummary {
  generated_at: string;
  window_seconds: number;
  total_events: number;
  unique_client_count: number;
  last_event_at: string | null;
  event_counts: Record<string, number>;
  rates: {
    preflight_selection_rate: number | null;
    preview_render_rate: number | null;
    preview_timeout_rate: number | null;
    preview_clarification_rate: number | null;
    wrong_answer_rate: number | null;
    open_full_debate_rate: number | null;
    share_rate: number | null;
    retry_rate: number | null;
  };
  question_length: { samples: number; avg: number | null; max: number | null };
  preview: { rendered_count: number; avg_participant_count: number | null };
  timeouts: { count: number; avg_timeout_seconds: number | null };
  top_options: Array<{
    option_id: string;
    selected_count: number;
    recommended_count: number;
    rewritten_count: number;
  }>;
}

interface LandingFeedbackReport {
  id: string;
  timestamp: string;
  client_tag: string;
  question: string | null;
  interpreted_question: string | null;
  final_answer_preview: string | null;
  result_warning: string | null;
  result_mode: string | null;
  debate_id: string | null;
  verdict: string | null;
  participant_count: number | null;
  rewritten: boolean;
  review_status: 'pending' | 'reviewed' | 'resolved' | 'dismissed';
  reviewed_at: string | null;
  reviewed_by: string | null;
}

interface LandingFeedbackSummary {
  generated_at: string;
  window_seconds: number;
  total_reports: number;
  returned_reports: number;
  unique_client_count: number;
  last_report_at: string | null;
  stats: {
    rewritten_count: number;
    rewritten_rate: number | null;
    preview_mode_count: number;
    preview_mode_rate: number | null;
    review_status_counts: {
      pending: number;
      reviewed: number;
      resolved: number;
      dismissed: number;
    };
  };
  reports: LandingFeedbackReport[];
}

type StatusError = Error & { status?: number };

function formatPercent(value: number | null | undefined): string {
  if (value == null || Number.isNaN(value)) return '--';
  return `${(value * 100).toFixed(1)}%`;
}

function formatNumber(value: number | null | undefined, digits = 1): string {
  if (value == null || Number.isNaN(value)) return '--';
  return value.toFixed(digits);
}

function formatTimestamp(value: string | null | undefined): string {
  if (!value) return '--';
  try {
    return new Date(value).toLocaleString();
  } catch {
    return value;
  }
}

function MetricCard({
  label,
  value,
  sublabel,
  tone = 'text-[var(--accent)]',
}: {
  label: string;
  value: string;
  sublabel?: string;
  tone?: string;
}) {
  return (
    <div className="card p-4">
      <div className="font-theme-data text-xs text-text-muted mb-1">{label}</div>
      <div className={`font-theme-data text-2xl ${tone}`}>{value}</div>
      {sublabel && <div className="font-theme-data text-xs text-text-muted mt-1">{sublabel}</div>}
    </div>
  );
}

function Badge({
  children,
  tone = 'text-[var(--acid-cyan)] border-[var(--acid-cyan)]/30 bg-[var(--acid-cyan)]/10',
}: {
  children: ReactNode;
  tone?: string;
}) {
  return (
    <span
      className={`inline-flex items-center rounded border px-2 py-0.5 font-theme-data text-[10px] uppercase tracking-wide ${tone}`}
    >
      {children}
    </span>
  );
}

function reviewStatusTone(status: LandingFeedbackReport['review_status']): string {
  switch (status) {
    case 'reviewed':
      return 'text-[var(--acid-cyan)] border-[var(--acid-cyan)]/30 bg-[var(--acid-cyan)]/10';
    case 'resolved':
      return 'text-[var(--accent)] border-[var(--accent)]/30 bg-[var(--accent)]/10';
    case 'dismissed':
      return 'text-[var(--acid-magenta)] border-acid-magenta/30 bg-acid-magenta/10';
    default:
      return 'text-[var(--acid-yellow)] border-acid-yellow/30 bg-acid-yellow/10';
  }
}

function reviewStatusLabel(status: LandingFeedbackReport['review_status']): string {
  switch (status) {
    case 'reviewed':
      return 'reviewed';
    case 'resolved':
      return 'resolved';
    case 'dismissed':
      return 'dismissed';
    default:
      return 'pending';
  }
}

export default function LandingReviewPage() {
  const { config: backendConfig } = useBackend();
  const [windowHours, setWindowHours] = useState(24);
  const [reportLimit, setReportLimit] = useState(25);
  const [updatingReportId, setUpdatingReportId] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);

  const windowSeconds = windowHours * 3600;
  const summaryEndpoint = useMemo(
    () => `/api/v1/playground/landing/events/summary?window=${windowSeconds}&limit=8`,
    [windowSeconds],
  );
  const feedbackEndpoint = useMemo(
    () => `/api/v1/playground/landing/feedback?window=${windowSeconds}&limit=${reportLimit}`,
    [reportLimit, windowSeconds],
  );

  const {
    data: summary,
    error: summaryError,
    isLoading: summaryLoading,
    isValidating: summaryValidating,
    mutate: mutateSummary,
  } = useSWRFetch<LandingSummary>(summaryEndpoint, {
    baseUrl: backendConfig.api,
    refreshInterval: 30000,
  });

  const {
    data: feedback,
    error: feedbackError,
    isLoading: feedbackLoading,
    isValidating: feedbackValidating,
    mutate: mutateFeedback,
  } = useSWRFetch<LandingFeedbackSummary>(feedbackEndpoint, {
    baseUrl: backendConfig.api,
    refreshInterval: 30000,
  });

  const refresh = useCallback(async () => {
    await Promise.all([mutateSummary(), mutateFeedback()]);
  }, [mutateFeedback, mutateSummary]);

  const updateReviewStatus = useCallback(
    async (reportId: string, reviewStatus: LandingFeedbackReport['review_status']) => {
      setUpdatingReportId(reportId);
      setActionError(null);
      try {
        const response = await fetch(
          `${backendConfig.api.replace(/\/$/, '')}/api/v1/playground/landing/feedback/review`,
          {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ id: reportId, review_status: reviewStatus }),
          },
        );

        if (!response.ok) {
          throw new Error(`Request failed with ${response.status}`);
        }

        await mutateFeedback();
      } catch (error) {
        setActionError(
          error instanceof Error ? error.message : 'Failed to update landing review status.',
        );
      } finally {
        setUpdatingReportId((current) => (current === reportId ? null : current));
      }
    },
    [backendConfig.api, mutateFeedback],
  );

  const lastUpdated = summary?.generated_at || feedback?.generated_at || null;
  const feedbackStatus = (feedbackError as StatusError | null)?.status ?? null;
  const feedbackUnavailable = Boolean(feedbackError);
  const feedbackAuthRequired = feedbackStatus === 401 || feedbackStatus === 403;
  const reports = feedback?.reports ?? [];

  return (
    <AdminLayout
      title="Landing Review"
      description="Landing funnel telemetry plus a reviewable queue of wrong-answer reports from the public preview flow."
      actions={
        <div className="flex items-center gap-3">
          <label className="flex items-center gap-2 font-theme-data text-xs text-text-muted">
            Window
            <select
              value={windowHours}
              onChange={(event) => setWindowHours(Number(event.target.value))}
              className="rounded border border-border bg-surface px-2 py-1 text-text"
            >
              <option value={1}>1h</option>
              <option value={24}>24h</option>
              <option value={168}>7d</option>
            </select>
          </label>
          <label className="flex items-center gap-2 font-theme-data text-xs text-text-muted">
            Reports
            <select
              value={reportLimit}
              onChange={(event) => setReportLimit(Number(event.target.value))}
              className="rounded border border-border bg-surface px-2 py-1 text-text"
            >
              <option value={10}>10</option>
              <option value={25}>25</option>
              <option value={50}>50</option>
            </select>
          </label>
          {lastUpdated && (
            <span className="font-theme-data text-xs text-text-muted">
              Updated {formatTimestamp(lastUpdated)}
            </span>
          )}
          <button
            onClick={() => {
              void refresh();
            }}
            disabled={summaryLoading || summaryValidating || feedbackLoading || feedbackValidating}
            className="rounded border border-[var(--accent)]/40 bg-[var(--accent)]/10 px-4 py-2 font-theme-data text-sm text-[var(--accent)] transition-colors hover:bg-[var(--accent)]/20 disabled:opacity-50"
          >
            Refresh
          </button>
        </div>
      }
    >
      {summaryError && (
        <div className="card mb-6 border-acid-red/40 bg-acid-red/10 p-4">
          <p className="font-theme-data text-sm text-acid-red">
            Failed to load landing telemetry summary.
          </p>
        </div>
      )}

      {feedbackError && (
        <div
          className={`card mb-6 p-4 ${feedbackAuthRequired ? 'border-acid-yellow/40 bg-acid-yellow/10' : 'border-acid-red/40 bg-acid-red/10'}`}
        >
          <p
            className={`font-theme-data text-sm ${feedbackAuthRequired ? 'text-[var(--acid-yellow)]' : 'text-acid-red'}`}
          >
            {feedbackAuthRequired
              ? 'Raw wrong-answer reports require admin auth. Summary cards remain visible, but the review queue is unavailable for this session.'
              : 'Failed to load raw wrong-answer reports. Summary cards remain visible, but the review queue is unavailable right now.'}
          </p>
        </div>
      )}

      <div className="grid grid-cols-2 gap-4 md:grid-cols-3 xl:grid-cols-6">
        <MetricCard
          label="Events"
          value={String(summary?.total_events ?? 0)}
          sublabel={`${summary?.unique_client_count ?? 0} unique clients`}
        />
        <MetricCard
          label="Preview Render"
          value={formatPercent(summary?.rates.preview_render_rate)}
          sublabel={`${summary?.preview.rendered_count ?? 0} rendered`}
          tone="text-[var(--acid-cyan)]"
        />
        <MetricCard
          label="Timeout Rate"
          value={formatPercent(summary?.rates.preview_timeout_rate)}
          sublabel={`${summary?.timeouts.count ?? 0} timeouts`}
          tone="text-[var(--acid-yellow)]"
        />
        <MetricCard
          label="Wrong Answer"
          value={formatPercent(summary?.rates.wrong_answer_rate)}
          sublabel={`${summary?.event_counts.wrong_answer_clicked ?? 0} clicks`}
          tone="text-acid-red"
        />
        <MetricCard
          label="Open Full Debate"
          value={formatPercent(summary?.rates.open_full_debate_rate)}
          sublabel={`${summary?.event_counts.open_full_debate_clicked ?? 0} clicks`}
          tone="text-[var(--acid-magenta)]"
        />
        <MetricCard
          label="Reports"
          value={feedbackUnavailable ? '--' : String(feedback?.total_reports ?? 0)}
          sublabel={
            feedbackUnavailable
              ? feedbackAuthRequired
                ? 'admin auth required'
                : 'load failed'
              : `${feedback?.returned_reports ?? 0} shown`
          }
          tone="text-[var(--acid-cyan)]"
        />
      </div>

      <div className="mt-6 grid gap-6 lg:grid-cols-[1.2fr_0.8fr]">
        <section className="card p-6">
          <div className="mb-4 flex items-center justify-between">
            <div>
              <h2 className="font-theme-data text-lg text-[var(--accent)]">Funnel Snapshot</h2>
              <p className="font-theme-data text-xs text-text-muted">
                Last event {formatTimestamp(summary?.last_event_at)}
              </p>
            </div>
            <Badge tone="text-[var(--acid-cyan)] border-[var(--acid-cyan)]/30 bg-[var(--acid-cyan)]/10">
              Avg question length {formatNumber(summary?.question_length.avg, 0)}
            </Badge>
          </div>

          <div className="grid gap-4 md:grid-cols-2">
            <div className="rounded border border-border bg-bg/60 p-4">
              <div className="font-theme-data text-xs text-text-muted mb-3">Rates</div>
              <div className="space-y-2 font-theme-data text-sm">
                <div className="flex items-center justify-between">
                  <span className="text-text-muted">Preflight selection</span>
                  <span className="text-[var(--accent)]">
                    {formatPercent(summary?.rates.preflight_selection_rate)}
                  </span>
                </div>
                <div className="flex items-center justify-between">
                  <span className="text-text-muted">Clarification requests</span>
                  <span className="text-[var(--acid-yellow)]">
                    {formatPercent(summary?.rates.preview_clarification_rate)}
                  </span>
                </div>
                <div className="flex items-center justify-between">
                  <span className="text-text-muted">Share rate</span>
                  <span className="text-[var(--acid-cyan)]">
                    {formatPercent(summary?.rates.share_rate)}
                  </span>
                </div>
                <div className="flex items-center justify-between">
                  <span className="text-text-muted">Retry rate</span>
                  <span className="text-[var(--acid-magenta)]">
                    {formatPercent(summary?.rates.retry_rate)}
                  </span>
                </div>
              </div>
            </div>

            <div className="rounded border border-border bg-bg/60 p-4">
              <div className="font-theme-data text-xs text-text-muted mb-3">Preview shape</div>
              <div className="space-y-2 font-theme-data text-sm">
                <div className="flex items-center justify-between">
                  <span className="text-text-muted">Avg participants</span>
                  <span className="text-[var(--acid-cyan)]">
                    {formatNumber(summary?.preview.avg_participant_count)}
                  </span>
                </div>
                <div className="flex items-center justify-between">
                  <span className="text-text-muted">Avg timeout seconds</span>
                  <span className="text-[var(--acid-yellow)]">
                    {formatNumber(summary?.timeouts.avg_timeout_seconds)}
                  </span>
                </div>
                <div className="flex items-center justify-between">
                  <span className="text-text-muted">Feedback rewritten</span>
                  <span className="text-[var(--accent)]">
                    {formatPercent(feedback?.stats.rewritten_rate)}
                  </span>
                </div>
                <div className="flex items-center justify-between">
                  <span className="text-text-muted">Preview-mode reports</span>
                  <span className="text-[var(--acid-magenta)]">
                    {formatPercent(feedback?.stats.preview_mode_rate)}
                  </span>
                </div>
              </div>
            </div>
          </div>
        </section>

        <section className="card p-6">
          <div className="mb-4">
            <h2 className="font-theme-data text-lg text-[var(--accent)]">Top Preflight Options</h2>
            <p className="font-theme-data text-xs text-text-muted">
              Which landing interpretations users actually choose in this window.
            </p>
          </div>

          {summary?.top_options?.length ? (
            <div className="space-y-3">
              {summary.top_options.map((option) => (
                <div key={option.option_id} className="rounded border border-border bg-bg/60 p-4">
                  <div className="mb-2 flex items-center justify-between gap-3">
                    <div className="font-theme-data text-sm text-text">{option.option_id}</div>
                    <Badge>{`${option.selected_count} picks`}</Badge>
                  </div>
                  <div className="grid grid-cols-2 gap-2 font-theme-data text-xs text-text-muted">
                    <div>Recommended: {option.recommended_count}</div>
                    <div>Rewritten: {option.rewritten_count}</div>
                  </div>
                </div>
              ))}
            </div>
          ) : (
            <div className="rounded border border-dashed border-border p-6 font-theme-data text-sm text-text-muted">
              No option-selection data in this window yet.
            </div>
          )}
        </section>
      </div>

      <section className="card mt-6 p-6">
        <div className="mb-4 flex items-center justify-between">
          <div>
            <h2 className="font-theme-data text-lg text-[var(--accent)]">
              Wrong-Answer Review Queue
            </h2>
            <p className="font-theme-data text-xs text-text-muted">
              Recent reports captured when visitors click “This answer seems wrong”.
            </p>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            {feedbackUnavailable ? (
              <div className="font-theme-data text-xs text-text-muted">Queue unavailable</div>
            ) : (
              <>
                <Badge tone="text-[var(--acid-yellow)] border-acid-yellow/30 bg-acid-yellow/10">
                  Pending {feedback?.stats.review_status_counts.pending ?? 0}
                </Badge>
                <Badge tone="text-[var(--acid-cyan)] border-[var(--acid-cyan)]/30 bg-[var(--acid-cyan)]/10">
                  Reviewed {feedback?.stats.review_status_counts.reviewed ?? 0}
                </Badge>
                <Badge tone="text-[var(--accent)] border-[var(--accent)]/30 bg-[var(--accent)]/10">
                  Resolved {feedback?.stats.review_status_counts.resolved ?? 0}
                </Badge>
                <Badge tone="text-[var(--acid-magenta)] border-acid-magenta/30 bg-acid-magenta/10">
                  Dismissed {feedback?.stats.review_status_counts.dismissed ?? 0}
                </Badge>
                <div className="font-theme-data text-xs text-text-muted">
                  Last report {formatTimestamp(feedback?.last_report_at)}
                </div>
              </>
            )}
          </div>
        </div>

        {actionError && (
          <div className="mb-4 rounded border border-acid-red/40 bg-acid-red/10 p-3 font-theme-data text-xs text-acid-red">
            {actionError}
          </div>
        )}

        {feedbackUnavailable ? (
          <div
            className={`rounded border border-dashed p-8 font-theme-data text-sm ${feedbackAuthRequired ? 'border-acid-yellow/40 bg-acid-yellow/10 text-[var(--acid-yellow)]' : 'border-acid-red/40 bg-acid-red/10 text-acid-red'}`}
          >
            {feedbackAuthRequired
              ? 'Wrong-answer review queue unavailable for this session.'
              : 'Wrong-answer review queue failed to load for this session.'}
          </div>
        ) : reports.length === 0 ? (
          <div className="rounded border border-dashed border-border p-8 font-theme-data text-sm text-text-muted">
            No wrong-answer reports captured in this window.
          </div>
        ) : (
          <div className="space-y-4">
            {reports.map((report) => (
              <article key={report.id} className="rounded border border-border bg-bg/60 p-5">
                <div className="mb-3 flex flex-wrap items-center gap-2">
                  <Badge tone={reviewStatusTone(report.review_status)}>
                    {reviewStatusLabel(report.review_status)}
                  </Badge>
                  <Badge tone="text-acid-red border-acid-red/30 bg-acid-red/10">
                    {report.verdict || 'needs_review'}
                  </Badge>
                  <Badge>{report.result_mode || 'preview'}</Badge>
                  {report.rewritten && (
                    <Badge tone="text-[var(--accent)] border-[var(--accent)]/30 bg-[var(--accent)]/10">
                      rewritten
                    </Badge>
                  )}
                  {report.participant_count != null && (
                    <Badge tone="text-[var(--acid-magenta)] border-acid-magenta/30 bg-acid-magenta/10">
                      {`${report.participant_count} agents`}
                    </Badge>
                  )}
                  <span className="ml-auto font-theme-data text-[11px] text-text-muted">
                    {formatTimestamp(report.timestamp)} · {report.client_tag}
                  </span>
                </div>

                <div className="grid gap-4 lg:grid-cols-3">
                  <div>
                    <div className="mb-1 font-theme-data text-[11px] uppercase tracking-wide text-text-muted">
                      User Question
                    </div>
                    <p className="font-theme-data text-sm text-text">{report.question || '—'}</p>
                  </div>
                  <div>
                    <div className="mb-1 font-theme-data text-[11px] uppercase tracking-wide text-text-muted">
                      Aragora Debated
                    </div>
                    <p className="font-theme-data text-sm text-text">
                      {report.interpreted_question || '—'}
                    </p>
                  </div>
                  <div>
                    <div className="mb-1 font-theme-data text-[11px] uppercase tracking-wide text-text-muted">
                      Answer Preview
                    </div>
                    <p className="font-theme-data text-sm text-text">
                      {report.final_answer_preview || '—'}
                    </p>
                  </div>
                </div>

                <div className="mt-4 flex flex-wrap items-center gap-2 border-t border-border pt-3">
                  <button
                    type="button"
                    onClick={() => {
                      void updateReviewStatus(report.id, 'reviewed');
                    }}
                    disabled={updatingReportId === report.id || report.review_status === 'reviewed'}
                    className="rounded border border-[var(--acid-cyan)]/40 bg-[var(--acid-cyan)]/10 px-3 py-1.5 font-theme-data text-xs text-[var(--acid-cyan)] transition-colors hover:bg-[var(--acid-cyan)]/20 disabled:cursor-not-allowed disabled:opacity-50"
                  >
                    Mark reviewed
                  </button>
                  <button
                    type="button"
                    onClick={() => {
                      void updateReviewStatus(report.id, 'resolved');
                    }}
                    disabled={updatingReportId === report.id || report.review_status === 'resolved'}
                    className="rounded border border-[var(--accent)]/40 bg-[var(--accent)]/10 px-3 py-1.5 font-theme-data text-xs text-[var(--accent)] transition-colors hover:bg-[var(--accent)]/20 disabled:cursor-not-allowed disabled:opacity-50"
                  >
                    Resolve
                  </button>
                  <button
                    type="button"
                    onClick={() => {
                      void updateReviewStatus(report.id, 'dismissed');
                    }}
                    disabled={
                      updatingReportId === report.id || report.review_status === 'dismissed'
                    }
                    className="rounded border border-acid-magenta/40 bg-acid-magenta/10 px-3 py-1.5 font-theme-data text-xs text-[var(--acid-magenta)] transition-colors hover:bg-acid-magenta/20 disabled:cursor-not-allowed disabled:opacity-50"
                  >
                    Dismiss
                  </button>
                  {updatingReportId === report.id && (
                    <span className="font-theme-data text-xs text-text-muted">Saving…</span>
                  )}
                  {(report.reviewed_by || report.reviewed_at) && (
                    <span className="ml-auto font-theme-data text-[11px] text-text-muted">
                      Reviewed {report.reviewed_by || 'admin'} ·{' '}
                      {formatTimestamp(report.reviewed_at)}
                    </span>
                  )}
                </div>

                {(report.result_warning || report.debate_id) && (
                  <div className="mt-4 flex flex-wrap items-center gap-3 border-t border-border pt-3">
                    {report.result_warning && (
                      <span className="font-theme-data text-xs text-[var(--acid-yellow)]">
                        Warning: {report.result_warning}
                      </span>
                    )}
                    {report.debate_id && (
                      <span className="font-theme-data text-xs text-text-muted">
                        Debate ID: {report.debate_id}
                      </span>
                    )}
                  </div>
                )}
              </article>
            ))}
          </div>
        )}
      </section>
    </AdminLayout>
  );
}
