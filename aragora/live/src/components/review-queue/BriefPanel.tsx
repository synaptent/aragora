'use client';

import type {
  BriefLifecycleState,
  BriefStateSnapshot,
  ReviewQueueBrief,
} from '@/hooks/useReviewQueue';

export interface BriefPanelProps {
  brief: ReviewQueueBrief | null;
  loading?: boolean;
  error?: string | null;
  /**
   * Mode 3 lifecycle snapshot. When present, takes precedence over
   * ``brief``/``loading``/``error`` for choosing the rendered state —
   * the panel renders a dedicated progress/failed/stale view instead
   * of the legacy empty-slate text.
   *
   * When omitted, the panel preserves its pre-PR4 behavior so callers
   * that haven't opted into lifecycle polling keep working.
   */
  state?: BriefStateSnapshot | null;
  /**
   * Whether the Mode 3 generation surface is available. When false
   * (backend feature flag off), the generate/regenerate/retry CTAs are
   * hidden and the panel falls back to the legacy empty-slate text.
   */
  generationEnabled?: boolean;
  /** Invoked from the absent/stale CTA. */
  onGenerate?: () => void;
  /** Invoked from the failed-state "Retry" CTA. */
  onRetry?: () => void;
}

const panelStyle = { borderColor: 'var(--border)', backgroundColor: 'var(--surface-elevated)' };

function ProgressRow({
  state,
  phase,
  rolesComplete,
  rolesTotal,
  elapsedSeconds,
  costUsdSoFar,
}: {
  state: BriefLifecycleState;
  phase?: string;
  rolesComplete?: number;
  rolesTotal?: number;
  elapsedSeconds?: number;
  costUsdSoFar?: number;
}) {
  const parts: string[] = [];
  if (phase) parts.push(`${phase} phase`);
  if (typeof rolesComplete === 'number' && typeof rolesTotal === 'number' && rolesTotal > 0) {
    parts.push(`${rolesComplete}/${rolesTotal} roles done`);
  }
  if (typeof elapsedSeconds === 'number' && elapsedSeconds > 0) {
    parts.push(`~${elapsedSeconds}s elapsed`);
  }
  if (typeof costUsdSoFar === 'number' && costUsdSoFar > 0) {
    parts.push(`$${costUsdSoFar.toFixed(2)}`);
  }
  const detail = parts.join(' · ') || 'starting…';
  return (
    <div className="flex items-center gap-3 text-xs" style={{ color: 'var(--text-muted)' }}>
      <span
        data-testid="brief-panel-spinner"
        aria-hidden="true"
        className="inline-block h-3 w-3 animate-spin rounded-full border-2"
        style={{ borderColor: 'var(--border)', borderTopColor: 'var(--accent)' }}
      />
      <span data-testid="brief-panel-progress-detail">
        {state === 'queued' ? 'Queued — starting soon' : detail}
      </span>
    </div>
  );
}

function EmptyPanelLegacy() {
  return (
    <div
      data-testid="brief-panel-empty"
      className="rounded-lg border px-4 py-3 text-xs italic"
      style={{ ...panelStyle, color: 'var(--text-muted)' }}
    >
      Brief generation is not enabled yet. The PDB pipeline — heterogeneous debate, synthesis, and
      signed brief output — is on the roadmap (see
      <code className="font-theme-data not-italic"> #6306 </code>). Approve decisions currently rely
      on CI status + your own reading of the diff.
    </div>
  );
}

function AbsentWithCTA({ onGenerate }: { onGenerate?: () => void }) {
  return (
    <div
      data-testid="brief-panel-absent"
      className="rounded-lg border px-4 py-4 text-sm"
      style={{ ...panelStyle, color: 'var(--text)' }}
    >
      <div className="mb-3 text-xs" style={{ color: 'var(--text-muted)' }}>
        No brief yet. Click Generate brief to start a panel debate (~2 min).
      </div>
      {onGenerate && (
        <button
          type="button"
          data-testid="brief-panel-generate"
          onClick={onGenerate}
          className="rounded-lg border px-3 py-1.5 font-theme-data uppercase tracking-wider hover:opacity-80"
          style={{
            fontSize: '11px',
            borderColor: 'var(--accent)',
            backgroundColor: 'rgba(57, 255, 20, 0.14)',
            color: 'var(--accent)',
          }}
        >
          Generate brief
        </button>
      )}
    </div>
  );
}

function QueuedPanel({ snapshot }: { snapshot: BriefStateSnapshot }) {
  return (
    <div
      data-testid="brief-panel-queued"
      className="rounded-lg border px-4 py-3"
      style={{ ...panelStyle, color: 'var(--text)' }}
    >
      <ProgressRow
        state={snapshot.state}
        phase={snapshot.phase}
        rolesComplete={snapshot.rolesComplete}
        rolesTotal={snapshot.rolesTotal}
        elapsedSeconds={snapshot.elapsedSeconds}
        costUsdSoFar={snapshot.costUsdSoFar}
      />
    </div>
  );
}

function RunningPanel({ snapshot }: { snapshot: BriefStateSnapshot }) {
  return (
    <div
      data-testid="brief-panel-running"
      className="rounded-lg border px-4 py-3"
      style={{ ...panelStyle, color: 'var(--text)' }}
    >
      <ProgressRow
        state={snapshot.state}
        phase={snapshot.phase ?? 'running'}
        rolesComplete={snapshot.rolesComplete}
        rolesTotal={snapshot.rolesTotal}
        elapsedSeconds={snapshot.elapsedSeconds}
        costUsdSoFar={snapshot.costUsdSoFar}
      />
    </div>
  );
}

function FailedPanel({
  snapshot,
  onRetry,
}: {
  snapshot: BriefStateSnapshot;
  onRetry?: () => void;
}) {
  const cost =
    typeof snapshot.costUsdSoFar === 'number' && snapshot.costUsdSoFar > 0
      ? `$${snapshot.costUsdSoFar.toFixed(2)}`
      : '$0.00';
  return (
    <div
      data-testid="brief-panel-failed"
      role="alert"
      className="rounded-lg border px-4 py-3 text-xs"
      style={{
        borderColor: 'var(--crimson)',
        backgroundColor: 'rgba(255, 0, 64, 0.08)',
        color: 'var(--crimson)',
      }}
    >
      <div>
        Brief generation failed{snapshot.phase ? ` at ${snapshot.phase}` : ''}.
        {snapshot.reason && (
          <>
            {' '}
            Reason: <span data-testid="brief-panel-failed-reason">{snapshot.reason}</span>.
          </>
        )}{' '}
        Cost so far: <span data-testid="brief-panel-failed-cost">{cost}</span>.
      </div>
      {onRetry && (
        <button
          type="button"
          data-testid="brief-panel-retry"
          onClick={onRetry}
          className="mt-3 rounded-lg border px-3 py-1.5 font-theme-data uppercase tracking-wider hover:opacity-80"
          style={{
            fontSize: '11px',
            borderColor: 'var(--crimson)',
            backgroundColor: 'rgba(255, 0, 64, 0.12)',
            color: 'var(--crimson)',
          }}
        >
          Retry
        </button>
      )}
    </div>
  );
}

function StalePanel({
  brief,
  snapshot,
  onRegenerate,
}: {
  brief: ReviewQueueBrief | null;
  snapshot: BriefStateSnapshot;
  onRegenerate?: () => void;
}) {
  const oldSha = brief?.head_sha?.slice(0, 12) ?? '(unknown)';
  const newSha = snapshot.headSha?.slice(0, 12) ?? '(new)';
  return (
    <div
      data-testid="brief-panel-stale"
      className="rounded-lg border px-4 py-3 text-xs"
      style={{
        borderColor: 'var(--warning)',
        backgroundColor: 'rgba(218, 165, 32, 0.10)',
        color: 'var(--warning)',
      }}
    >
      <div>
        Brief is for a previous commit (<code className="font-theme-data">{oldSha}</code> ≠ current{' '}
        <code className="font-theme-data">{newSha}</code>). Regenerate for the current commit?
      </div>
      {onRegenerate && (
        <button
          type="button"
          data-testid="brief-panel-regenerate"
          onClick={onRegenerate}
          className="mt-3 rounded-lg border px-3 py-1.5 font-theme-data uppercase tracking-wider hover:opacity-80"
          style={{
            fontSize: '11px',
            borderColor: 'var(--warning)',
            backgroundColor: 'rgba(218, 165, 32, 0.14)',
            color: 'var(--warning)',
          }}
        >
          Regenerate
        </button>
      )}
    </div>
  );
}

function ReadyPanel({ brief }: { brief: ReviewQueueBrief }) {
  const sections: Array<{ key: keyof ReviewQueueBrief; label: string }> = [
    { key: 'logic', label: 'Logic' },
    { key: 'security', label: 'Security' },
    { key: 'maintainability', label: 'Maintainability' },
    { key: 'skeptic', label: 'Skeptic' },
  ];

  return (
    <div
      data-testid="brief-panel"
      className="rounded-lg border px-4 py-4 text-sm"
      style={{ ...panelStyle, color: 'var(--text)' }}
    >
      <div
        className="flex flex-wrap items-center gap-3 border-b pb-3"
        style={{ borderColor: 'var(--border)' }}
      >
        <span
          className="font-theme-data uppercase tracking-wider"
          style={{ fontSize: '10px', color: 'var(--text-muted)' }}
        >
          Verdict
        </span>
        <span className="font-theme-data text-sm" data-testid="brief-verdict">
          {brief.verdict || '—'}
        </span>
        {brief.confidence !== null && brief.confidence !== undefined && (
          <span
            className="text-xs"
            style={{ color: 'var(--text-muted)' }}
            data-testid="brief-confidence"
          >
            confidence {brief.confidence}/5
          </span>
        )}
        <span className="ml-auto font-theme-data text-xs" style={{ color: 'var(--text-muted)' }}>
          head {brief.head_sha?.slice(0, 12) || '—'}
        </span>
      </div>
      <div className="mt-3 space-y-4">
        {sections.map(({ key, label }) => {
          const value = brief[key];
          const text = typeof value === 'string' && value.trim() ? value : '—';
          return (
            <div key={key} data-testid={`brief-section-${key}`}>
              <div
                className="mb-1 font-theme-data uppercase tracking-wider"
                style={{ fontSize: '10px', color: 'var(--text-muted)' }}
              >
                {label}
              </div>
              <div className="whitespace-pre-wrap leading-relaxed">{text}</div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

/**
 * Renders the role-structured synthesis sections from a PDB brief.
 *
 * Two modes:
 *
 * - **Legacy**: callers pass only ``brief``/``loading``/``error``.
 *   The panel renders the pre-PR4 behavior (present vs. absent) and
 *   shows the "brief generation not enabled yet" empty-slate.
 *
 * - **Mode 3**: callers pass ``state`` (+ ``generationEnabled`` +
 *   ``onGenerate``/``onRetry``). The panel then routes on the six
 *   lifecycle states from :mod:`aragora.pdb.brief_state`.
 *
 * Missing string fields render as "—" rather than breaking the layout.
 */
export function BriefPanel({
  brief,
  loading,
  error,
  state,
  generationEnabled = false,
  onGenerate,
  onRetry,
}: BriefPanelProps) {
  // Mode 3 state-driven rendering takes precedence when a snapshot is
  // provided. Absent state + ready brief still renders the role
  // sections; this keeps the "brief arrived after polling" path cheap.
  if (state) {
    switch (state.state) {
      case 'queued':
        return <QueuedPanel snapshot={state} />;
      case 'running':
        return <RunningPanel snapshot={state} />;
      case 'failed':
        return <FailedPanel snapshot={state} onRetry={onRetry} />;
      case 'stale':
        return <StalePanel brief={brief} snapshot={state} onRegenerate={onGenerate} />;
      case 'ready':
        if (brief) return <ReadyPanel brief={brief} />;
        if (loading) {
          return (
            <div
              data-testid="brief-panel-loading"
              className="rounded-lg border px-4 py-3 text-xs"
              style={{ ...panelStyle, color: 'var(--text-muted)' }}
            >
              Loading brief…
            </div>
          );
        }
        // Ready state with no loaded body yet — show loading hint so the
        // UI never ends up silent.
        return (
          <div
            data-testid="brief-panel-loading"
            className="rounded-lg border px-4 py-3 text-xs"
            style={{ ...panelStyle, color: 'var(--text-muted)' }}
          >
            Loading brief…
          </div>
        );
      case 'absent':
      default:
        if (generationEnabled) {
          return <AbsentWithCTA onGenerate={onGenerate} />;
        }
        return <EmptyPanelLegacy />;
    }
  }

  // Legacy path — matches pre-PR4 behavior exactly.
  if (loading) {
    return (
      <div
        data-testid="brief-panel-loading"
        className="rounded-lg border px-4 py-3 text-xs"
        style={{ ...panelStyle, color: 'var(--text-muted)' }}
      >
        Loading brief…
      </div>
    );
  }

  if (error) {
    return (
      <div
        data-testid="brief-panel-error"
        role="alert"
        className="rounded-lg border px-4 py-3 text-xs"
        style={{
          borderColor: 'var(--crimson)',
          backgroundColor: 'rgba(255, 0, 64, 0.08)',
          color: 'var(--crimson)',
        }}
      >
        {error}
      </div>
    );
  }

  if (!brief) {
    if (generationEnabled && onGenerate) {
      return <AbsentWithCTA onGenerate={onGenerate} />;
    }
    return <EmptyPanelLegacy />;
  }

  return <ReadyPanel brief={brief} />;
}
