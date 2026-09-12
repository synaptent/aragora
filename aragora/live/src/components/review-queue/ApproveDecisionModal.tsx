'use client';

import { useCallback, useEffect, useRef } from 'react';
import type { BriefLifecycleState } from '@/hooks/useReviewQueue';

export interface ApproveDecisionModalProps {
  /** PR number for the modal header. */
  prNumber: number;
  /** Current lifecycle state for this PR. */
  state: BriefLifecycleState;
  /** Brief verdict, when present. Shown as context for disagreement. */
  verdict?: string | null;
  /**
   * Kick off a brief generation. Modal stays mounted while the caller
   * awaits the promise — callers should close the modal on resolution.
   */
  onGenerate: () => void;
  /** User chose "approve anyway" — modal should close. */
  onApproveAnyway: () => void;
  /** User cancelled the modal without approving. */
  onClose: () => void;
  /**
   * Optional override for the testable `typeof window` guard so the
   * keyboard handler can be exercised without a DOM.
   */
  portalDisabled?: boolean;
}

/**
 * Three-way decision modal shown when the user clicks Approve on a PR
 * whose brief state is not `ready` (or is ready but the verdict
 * disagrees with the approve intent).
 *
 * Replaces the ambient `window.confirm("Approve without PDB brief?")`
 * path with explicit, keyboard-driven choices:
 *
 * - ``g`` → Generate brief first (primary)
 * - ``a`` → Approve anyway (secondary)
 * - ``Esc`` → Cancel (tertiary)
 *
 * Callers can bypass the modal entirely by tracking a rapid
 * double-press of ``a``; the modal itself doesn't own that flow, but
 * it surfaces the hint in the help text per the design spec.
 */
export function ApproveDecisionModal({
  prNumber,
  state,
  verdict,
  onGenerate,
  onApproveAnyway,
  onClose,
}: ApproveDecisionModalProps) {
  const dialogRef = useRef<HTMLDivElement | null>(null);

  const handleKeyDown = useCallback(
    (ev: KeyboardEvent) => {
      // Ignore keys when the user is typing in an input/textarea, so the
      // shortcuts never swallow keystrokes in nested forms.
      const target = ev.target as HTMLElement | null;
      const tag = target?.tagName;
      if (tag === 'INPUT' || tag === 'TEXTAREA' || target?.isContentEditable) {
        return;
      }
      if (ev.key === 'Escape') {
        ev.preventDefault();
        onClose();
        return;
      }
      if (ev.key === 'g' || ev.key === 'G') {
        ev.preventDefault();
        onGenerate();
        return;
      }
      if (ev.key === 'a' || ev.key === 'A') {
        ev.preventDefault();
        onApproveAnyway();
        return;
      }
    },
    [onApproveAnyway, onClose, onGenerate],
  );

  useEffect(() => {
    if (typeof window === 'undefined') return;
    window.addEventListener('keydown', handleKeyDown);
    return () => {
      window.removeEventListener('keydown', handleKeyDown);
    };
  }, [handleKeyDown]);

  useEffect(() => {
    dialogRef.current?.focus();
  }, []);

  const isVerdictDisagree =
    state === 'ready' &&
    verdict !== null &&
    verdict !== undefined &&
    verdict !== 'approve_candidate';

  let bodyLines: string[];
  if (isVerdictDisagree) {
    bodyLines = [
      `The PDB panel brief for PR #${prNumber} returned verdict "${verdict}".`,
      'Approving now will record your decision against that recommendation.',
    ];
  } else if (state === 'running' || state === 'queued') {
    bodyLines = [
      `A brief is currently ${state} for PR #${prNumber}.`,
      'You can wait for it to finish, approve anyway, or cancel.',
    ];
  } else if (state === 'failed') {
    bodyLines = [
      `The previous brief generation for PR #${prNumber} failed.`,
      'Retry generation, approve anyway, or cancel.',
    ];
  } else if (state === 'stale') {
    bodyLines = [
      `The brief for PR #${prNumber} is stale (head moved to a new commit).`,
      'Regenerate for the current commit, approve anyway, or cancel.',
    ];
  } else {
    bodyLines = [
      `No brief exists for PR #${prNumber} yet.`,
      'Generate a panel brief (~2 min) first, or approve without one.',
    ];
  }

  let primaryLabel = 'Generate brief first';
  if (state === 'failed') primaryLabel = 'Retry generation';
  else if (state === 'stale') primaryLabel = 'Regenerate for current commit';
  else if (state === 'running' || state === 'queued') primaryLabel = 'Wait for brief';

  return (
    <div
      data-testid="approve-decision-backdrop"
      className="fixed inset-0 z-50 flex items-center justify-center"
      style={{ backgroundColor: 'rgba(0, 0, 0, 0.45)' }}
      onClick={(ev) => {
        // Close only when the backdrop itself is clicked.
        if (ev.target === ev.currentTarget) onClose();
      }}
    >
      <div
        ref={dialogRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby={`approve-decision-title-${prNumber}`}
        data-testid={`approve-decision-modal-${prNumber}`}
        tabIndex={-1}
        className="w-[min(32rem,90vw)] rounded-xl border p-6 shadow-lg outline-none"
        style={{
          backgroundColor: 'var(--surface)',
          borderColor: 'var(--border)',
          color: 'var(--text)',
        }}
      >
        <h2 id={`approve-decision-title-${prNumber}`} className="text-base font-semibold">
          Approve PR #{prNumber}?
        </h2>
        <div className="mt-3 space-y-2 text-sm" style={{ color: 'var(--text-muted)' }}>
          {bodyLines.map((line) => (
            <p key={line}>{line}</p>
          ))}
        </div>
        <div className="mt-5 flex flex-col gap-2">
          <button
            type="button"
            data-testid={`approve-decision-generate-${prNumber}`}
            onClick={onGenerate}
            className="rounded-lg border px-3 py-2 font-theme-data uppercase tracking-wider hover:opacity-80"
            style={{
              fontSize: '11px',
              borderColor: 'var(--accent)',
              backgroundColor: 'rgba(57, 255, 20, 0.14)',
              color: 'var(--accent)',
            }}
          >
            {primaryLabel}{' '}
            <span aria-hidden="true" className="ml-1 opacity-70">
              (g)
            </span>
          </button>
          <button
            type="button"
            data-testid={`approve-decision-approve-anyway-${prNumber}`}
            onClick={onApproveAnyway}
            className="rounded-lg border px-3 py-2 font-theme-data uppercase tracking-wider hover:opacity-80"
            style={{
              fontSize: '11px',
              borderColor: 'var(--border)',
              backgroundColor: 'var(--surface-elevated)',
              color: 'var(--text)',
            }}
          >
            Approve anyway{' '}
            <span aria-hidden="true" className="ml-1 opacity-70">
              (a)
            </span>
          </button>
          <button
            type="button"
            data-testid={`approve-decision-cancel-${prNumber}`}
            onClick={onClose}
            className="text-xs underline-offset-4 hover:underline"
            style={{ color: 'var(--text-muted)' }}
          >
            Cancel{' '}
            <span aria-hidden="true" className="ml-1 opacity-70">
              (Esc)
            </span>
          </button>
        </div>
        <p className="mt-4 text-[11px]" style={{ color: 'var(--text-muted)' }}>
          Tip: press <kbd className="font-theme-data">a</kbd> twice quickly to bypass this check on
          trusted PRs.
        </p>
      </div>
    </div>
  );
}
