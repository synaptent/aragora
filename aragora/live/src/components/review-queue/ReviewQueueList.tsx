'use client';

import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import type { ReviewQueuePR, SettlementAction } from '@/hooks/useReviewQueue';
import { useSettlePR } from '@/hooks/useReviewQueue';
import { ReviewQueueCard } from './ReviewQueueCard';
import { KeyboardHelp } from './KeyboardHelp';

export interface ReviewQueueListProps {
  prs: ReviewQueuePR[];
  onSettled?: () => void;
  /** Used in tests to bypass `window.confirm` prompts. */
  confirmFn?: (message: string) => boolean;
  /** Used in tests to bypass `window.prompt`. */
  promptFn?: (message: string, defaultValue?: string) => string | null;
}

export function ReviewQueueList({ prs, onSettled, confirmFn, promptFn }: ReviewQueueListProps) {
  const visible = useMemo(() => prs.filter((p) => !p.deferred), [prs]);
  const [selectedIndex, setSelectedIndex] = useState(0);
  const [expandedIndex, setExpandedIndex] = useState<number | null>(null);
  const [helpOpen, setHelpOpen] = useState(false);
  const [promptState, setPromptState] = useState<{
    action: Extract<SettlementAction, 'request-changes'>;
    prNumber: number;
    draft: string;
  } | null>(null);
  const containerRef = useRef<HTMLDivElement | null>(null);
  const selectionTimestampRef = useRef<number>(Date.now());

  useEffect(() => {
    // Keep selection within bounds when the queue shrinks/grows.
    if (selectedIndex >= visible.length && visible.length > 0) {
      setSelectedIndex(0);
    }
    selectionTimestampRef.current = Date.now();
  }, [visible.length, selectedIndex]);

  const settle = useSettlePR(onSettled);

  const runSettle = useCallback(
    async (
      pr: ReviewQueuePR,
      action: SettlementAction,
      options?: { note?: string; reason?: string },
    ) => {
      const startedAt = selectionTimestampRef.current;
      const decisionSeconds = Math.max(0, (Date.now() - startedAt) / 1000);
      await settle(pr.number, action, { ...options, decisionSeconds });
      selectionTimestampRef.current = Date.now();
    },
    [settle],
  );

  const selectedPr = visible[selectedIndex];

  const openDiff = useCallback((pr: ReviewQueuePR) => {
    if (typeof window !== 'undefined' && pr.url) {
      window.open(pr.url, '_blank', 'noopener,noreferrer');
    }
  }, []);

  const doApprove = useCallback(
    (pr: ReviewQueuePR) => {
      const confirmer = confirmFn ?? (typeof window !== 'undefined' ? window.confirm : () => true);
      if (!pr.brief_present) {
        if (!confirmer('No brief on file. Approve without PDB brief?')) return;
      } else if (pr.verdict && pr.verdict !== 'approve_candidate') {
        if (!confirmer(`Brief verdict is ${pr.verdict}. Approve anyway?`)) return;
      }
      void runSettle(pr, 'approve');
    },
    [confirmFn, runSettle],
  );

  const doRequestChanges = useCallback(
    (pr: ReviewQueuePR) => {
      if (promptFn) {
        const reason = promptFn('Reason for request-changes:');
        if (!reason || !reason.trim()) return;
        void runSettle(pr, 'request-changes', { reason: reason.trim() });
        return;
      }
      setPromptState({ action: 'request-changes', prNumber: pr.number, draft: '' });
    },
    [promptFn, runSettle],
  );

  const doDefer = useCallback(
    (pr: ReviewQueuePR) => {
      void runSettle(pr, 'defer', { reason: 'keyboard defer' });
    },
    [runSettle],
  );

  // Global keyboard handler.
  useEffect(() => {
    const onKey = (ev: KeyboardEvent) => {
      if (ev.defaultPrevented) return;
      const target = ev.target as HTMLElement | null;
      if (target) {
        const tag = target.tagName;
        const editable =
          tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT' || target.isContentEditable;
        if (editable) return;
      }

      if (ev.key === '?' || (ev.key === '/' && ev.shiftKey)) {
        ev.preventDefault();
        setHelpOpen((open) => !open);
        return;
      }
      if (ev.key === 'Escape') {
        if (promptState) {
          ev.preventDefault();
          setPromptState(null);
          return;
        }
        if (helpOpen) {
          ev.preventDefault();
          setHelpOpen(false);
          return;
        }
        if (expandedIndex !== null) {
          ev.preventDefault();
          setExpandedIndex(null);
          return;
        }
      }
      if (helpOpen || promptState) return;
      if (visible.length === 0) return;

      if (ev.key === 'j' || ev.key === 'ArrowDown') {
        ev.preventDefault();
        setSelectedIndex((i) => Math.min(visible.length - 1, i + 1));
        return;
      }
      if (ev.key === 'k' || ev.key === 'ArrowUp') {
        ev.preventDefault();
        setSelectedIndex((i) => Math.max(0, i - 1));
        return;
      }
      if (ev.key === 'Enter' || ev.key === ' ') {
        ev.preventDefault();
        setExpandedIndex((curr) => (curr === selectedIndex ? null : selectedIndex));
        return;
      }
      const pr = visible[selectedIndex];
      if (!pr) return;
      if (ev.key === 'a') {
        ev.preventDefault();
        doApprove(pr);
      } else if (ev.key === 'r') {
        ev.preventDefault();
        doRequestChanges(pr);
      } else if (ev.key === 'd') {
        ev.preventDefault();
        doDefer(pr);
      } else if (ev.key === 'o') {
        ev.preventDefault();
        openDiff(pr);
      }
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [
    visible,
    selectedIndex,
    helpOpen,
    expandedIndex,
    promptState,
    doApprove,
    doDefer,
    doRequestChanges,
    openDiff,
  ]);

  if (visible.length === 0) {
    return (
      <div
        data-testid="review-queue-empty"
        className="rounded border border-dashed border-slate-700 bg-slate-900/40 px-4 py-8 text-center text-sm text-slate-300"
      >
        <div className="font-theme-data text-lg text-green-400">inbox zero ✓</div>
        <p className="mt-2 text-slate-400">
          Nothing open. Kick off the next shift or rebuild the queue via{' '}
          <code className="rounded bg-slate-800 px-1">aragora review-queue build</code>.
        </p>
      </div>
    );
  }

  return (
    <div
      ref={containerRef}
      role="listbox"
      aria-label="Open PRs"
      data-testid="review-queue-list"
      className="flex flex-col"
      style={{ gap: '2rem' }}
    >
      {visible.map((pr, index) => (
        <ReviewQueueCard
          key={pr.number}
          pr={pr}
          selected={index === selectedIndex}
          expanded={expandedIndex === index}
          onSelect={() => setSelectedIndex(index)}
          onToggleExpand={() => setExpandedIndex((curr) => (curr === index ? null : index))}
          onSettle={async (action, options) => {
            await runSettle(pr, action, options);
          }}
        />
      ))}
      <div className="mt-4 text-center text-xs" style={{ color: 'var(--text-muted)' }}>
        {selectedPr ? (
          <>
            selected <span style={{ color: 'var(--text)' }}>PR #{selectedPr.number}</span>
            {' · '}
            {selectedIndex + 1} of {visible.length}
          </>
        ) : (
          'press j/k to navigate · a approve · r request-changes · d defer · o open diff · ? help'
        )}
      </div>
      <KeyboardHelp open={helpOpen} onClose={() => setHelpOpen(false)} />

      {promptState && (
        <div
          role="dialog"
          aria-modal="true"
          data-testid="review-queue-reason-prompt"
          className="fixed inset-0 z-40 flex items-center justify-center bg-black/70 p-4"
        >
          <div
            className="w-full max-w-md rounded-xl border p-6 text-sm"
            style={{
              borderColor: 'var(--border)',
              backgroundColor: 'var(--surface)',
              color: 'var(--text)',
              boxShadow: 'var(--shadow-floating)',
            }}
          >
            <h3 className="mb-3 font-theme-data text-base">
              Request changes on PR #{promptState.prNumber}
            </h3>
            <textarea
              data-testid="review-queue-reason-keyboard-input"
              autoFocus
              value={promptState.draft}
              onChange={(ev) => setPromptState((s) => (s ? { ...s, draft: ev.target.value } : s))}
              rows={3}
              className="w-full rounded-lg border px-3 py-2 focus:outline-none"
              style={{
                borderColor: 'var(--border)',
                backgroundColor: 'var(--bg)',
                color: 'var(--text)',
              }}
            />
            <div className="mt-3 flex justify-end gap-2">
              <button
                type="button"
                className="rounded-lg border px-3 py-1.5 text-xs font-theme-data uppercase tracking-wider hover:opacity-80"
                style={{ borderColor: 'var(--border)', color: 'var(--text-muted)' }}
                onClick={() => setPromptState(null)}
              >
                Cancel
              </button>
              <button
                type="button"
                data-testid="review-queue-reason-keyboard-submit"
                className="rounded-lg border px-3 py-1.5 text-xs font-theme-data uppercase tracking-wider hover:opacity-80"
                style={{
                  borderColor: 'var(--crimson)',
                  backgroundColor: 'rgba(255, 0, 64, 0.08)',
                  color: 'var(--crimson)',
                }}
                onClick={() => {
                  const reason = promptState.draft.trim();
                  if (!reason) return;
                  const pr = visible.find((p) => p.number === promptState.prNumber);
                  setPromptState(null);
                  if (pr) {
                    void runSettle(pr, 'request-changes', { reason });
                  }
                }}
              >
                Send
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
