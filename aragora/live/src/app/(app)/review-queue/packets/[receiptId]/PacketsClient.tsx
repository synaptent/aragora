'use client';

/**
 * PacketsClient — client component that powers the
 * `/review-queue/packets/[receiptId]` route. It loads a
 * settlement-packet receipt (shape `aragora-open-queue-settlement/1.0`)
 * via a file picker, verifies its SHA-256 binding, renders one
 * `PacketDecisionCard` per PR, and lets the operator download a
 * signed decisions JSON when finished.
 *
 * Keyboard-driven sign-off (mirrors `/review-queue` `ReviewQueueList`):
 *   j / ArrowDown   next card
 *   k / ArrowUp     prev card
 *   1..5            pick decision option in PACKET_DECISION_OPTIONS
 *                   order: 1=approve_tier, 2=approve_downgrade,
 *                   3=request_changes, 4=reject, 5=hold_operator
 *   ? (or Shift-/)  toggle the keyboard-help overlay
 *   Escape          close the help overlay
 * Key handling is suppressed when focus is already in an editable
 * input (so typing in the comment textarea is unaffected).
 *
 * Per-decision timing: when a card first becomes the keyboard focus
 * target we capture `first_focused_at_utc`; when the operator picks a
 * decision we capture `decided_at_utc`. Both flow into each entry of
 * the downloaded `aragora-operator-decisions/1.0` JSON so future
 * sessions can measure seconds-per-decision empirically without
 * re-instrumenting the page.
 *
 * No network mutation. No live API calls. Decisions never leave the
 * browser unless the operator explicitly clicks Download.
 */

import { useCallback, useEffect, useMemo, useState } from 'react';
import { useParams } from 'next/navigation';
import { Scanlines, CRTVignette } from '@/components/MatrixRain';
import {
  PACKET_DECISION_OPTIONS,
  PacketDecisionCard,
  type PacketDecisionId,
} from '@/components/review-queue/PacketDecisionCard';
import {
  canonicalJson,
  mapReceiptToReviewQueueList,
  useReviewQueueFromPacket,
  verifyReceiptSha256,
  type SettlementReceipt,
} from '@/hooks/useReviewQueueFromPacket';

interface ShaCheck {
  matches: boolean;
  claimed: string;
  recomputed: string;
  hmacClaimed: string;
  hmacPresent: boolean;
  hmacVerified: boolean;
}

function isEditableKeyboardTarget(target: EventTarget | null): boolean {
  if (!(target instanceof HTMLElement)) return false;
  return (
    target.tagName === 'INPUT' ||
    target.tagName === 'TEXTAREA' ||
    target.tagName === 'SELECT' ||
    target.isContentEditable
  );
}

export default function PacketsClient() {
  const params = useParams();
  const receiptIdRaw = params?.receiptId;
  const receiptIdHint = Array.isArray(receiptIdRaw) ? receiptIdRaw[0] : (receiptIdRaw ?? '');

  const [receipt, setReceipt] = useState<SettlementReceipt | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [shaCheck, setShaCheck] = useState<ShaCheck | null>(null);
  const [decisions, setDecisions] = useState<Record<number, PacketDecisionId>>({});
  const [comments, setComments] = useState<Record<number, string>>({});
  const [downloadStatus, setDownloadStatus] = useState<string | null>(null);
  const [selectedIndex, setSelectedIndex] = useState<number | null>(null);
  const [helpOpen, setHelpOpen] = useState(false);
  // ISO timestamps keyed by PR number. `focusedAt` records the first
  // time a card became the keyboard focus target; `decidedAt` records
  // the moment a decision was picked. Both are persisted in the
  // download payload so seconds-per-decision is recoverable
  // post-hoc without re-instrumentation.
  const [focusedAtByPr, setFocusedAtByPr] = useState<Record<number, string>>({});
  const [decidedAtByPr, setDecidedAtByPr] = useState<Record<number, string>>({});

  const queue = useReviewQueueFromPacket(receipt);

  const handleFileChosen = useCallback(async (file: File) => {
    setLoadError(null);
    setShaCheck(null);
    setReceipt(null);
    setDecisions({});
    setComments({});
    setDownloadStatus(null);
    setSelectedIndex(null);
    setFocusedAtByPr({});
    setDecidedAtByPr({});
    try {
      const text = await file.text();
      const parsed = JSON.parse(text) as SettlementReceipt;
      if (!parsed || typeof parsed !== 'object' || !Array.isArray(parsed.pinned_state)) {
        setLoadError('Invalid receipt: expected pinned_state[] array');
        return;
      }
      setReceipt(parsed);
      // Lightweight sanity render before SHA — exception-safe noop on
      // malformed entries, since the mapper applies defaults.
      mapReceiptToReviewQueueList(parsed);
      try {
        const verification = await verifyReceiptSha256(parsed);
        setShaCheck(verification);
      } catch (err) {
        setShaCheck({
          matches: false,
          claimed: String(parsed.sha256 ?? ''),
          recomputed: `(verify-failed: ${(err as Error).message})`,
          hmacClaimed: String(parsed.hmac_sha256 ?? ''),
          hmacPresent: Boolean(parsed.hmac_sha256),
          hmacVerified: false,
        });
      }
    } catch (err) {
      setLoadError(`Failed to parse receipt: ${(err as Error).message}`);
    }
  }, []);

  const onPickFile = useCallback(
    (ev: React.ChangeEvent<HTMLInputElement>) => {
      const file = ev.target.files?.[0];
      if (!file) return;
      void handleFileChosen(file);
    },
    [handleFileChosen],
  );

  const setDecisionFor = useCallback((prNumber: number, decision: PacketDecisionId) => {
    setDecisions((prev) => ({ ...prev, [prNumber]: decision }));
    // Always overwrite — re-deciding is a real event the receipt should
    // reflect (operators may flip a decision during a single sign-off
    // pass, and the latest pick is the one that ships).
    setDecidedAtByPr((prev) => ({ ...prev, [prNumber]: new Date().toISOString() }));
  }, []);

  const setCommentFor = useCallback((prNumber: number, comment: string) => {
    setComments((prev) => ({ ...prev, [prNumber]: comment }));
  }, []);

  // Auto-select the first card whenever the queue resolves a fresh
  // receipt so j/k navigation has a starting anchor without forcing
  // the operator to click.
  useEffect(() => {
    if (queue.prs.length === 0) {
      setSelectedIndex(null);
      return;
    }
    setSelectedIndex((prev) => {
      if (prev === null) return 0;
      if (prev >= queue.prs.length) return queue.prs.length - 1;
      return prev;
    });
  }, [queue.prs.length]);

  // Stamp `focusedAtByPr` the first time a given PR becomes the focus
  // target. Subsequent re-focuses do not move the timestamp — the
  // measurement we want is "time from first eyeball → decision."
  useEffect(() => {
    if (selectedIndex === null) return;
    const pr = queue.prs[selectedIndex];
    if (!pr) return;
    setFocusedAtByPr((prev) => {
      if (prev[pr.number]) return prev;
      return { ...prev, [pr.number]: new Date().toISOString() };
    });
  }, [selectedIndex, queue.prs]);

  // Single global keyboard handler — placed on window so it survives
  // selection changes without re-binding per card.
  useEffect(() => {
    if (!receipt) return undefined;
    const onKey = (ev: KeyboardEvent) => {
      if (ev.defaultPrevented) return;
      const inEditable = isEditableKeyboardTarget(ev.target);

      if (inEditable) return;
      if (ev.key === '?' || (ev.key === '/' && ev.shiftKey)) {
        ev.preventDefault();
        setHelpOpen((open) => !open);
        return;
      }
      if (ev.key === 'Escape') {
        if (helpOpen) {
          ev.preventDefault();
          setHelpOpen(false);
          return;
        }
      }
      if (helpOpen) return;
      if (queue.prs.length === 0) return;
      const current = selectedIndex ?? 0;

      if (ev.key === 'j' || ev.key === 'ArrowDown') {
        ev.preventDefault();
        setSelectedIndex(Math.min(queue.prs.length - 1, current + 1));
        return;
      }
      if (ev.key === 'k' || ev.key === 'ArrowUp') {
        ev.preventDefault();
        setSelectedIndex(Math.max(0, current - 1));
        return;
      }
      // Digit shortcuts 1..5 map to PACKET_DECISION_OPTIONS in order.
      const digitMatch = /^[1-5]$/.test(ev.key) ? Number(ev.key) : null;
      if (digitMatch !== null) {
        const pr = queue.prs[current];
        const opt = PACKET_DECISION_OPTIONS[digitMatch - 1];
        if (pr && opt) {
          ev.preventDefault();
          setDecisionFor(pr.number, opt.id);
        }
        return;
      }
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [receipt, queue.prs, selectedIndex, helpOpen, setDecisionFor]);

  const decidedCount = useMemo(() => Object.keys(decisions).length, [decisions]);
  const totalCount = queue.total;
  const remainingCount = Math.max(0, totalCount - decidedCount);

  // Median seconds-per-decision (live) — useful as an in-session
  // signal and also documented in the receipt-side numbers.
  const medianDecisionSeconds = useMemo<number | null>(() => {
    const samples: number[] = [];
    for (const [prStr, decidedAt] of Object.entries(decidedAtByPr)) {
      const prNum = Number(prStr);
      const focusedAt = focusedAtByPr[prNum];
      if (!focusedAt) continue;
      const start = new Date(focusedAt).getTime();
      const end = new Date(decidedAt).getTime();
      if (Number.isNaN(start) || Number.isNaN(end)) continue;
      const dt = (end - start) / 1000;
      if (dt < 0) continue;
      samples.push(dt);
    }
    if (samples.length === 0) return null;
    samples.sort((a, b) => a - b);
    const mid = Math.floor(samples.length / 2);
    return samples.length % 2 === 0 ? (samples[mid - 1] + samples[mid]) / 2 : samples[mid];
  }, [focusedAtByPr, decidedAtByPr]);

  const onDownload = useCallback(async () => {
    if (!receipt) return;
    setDownloadStatus(null);
    const generatedAt = new Date().toISOString();
    const entries = (receipt.pinned_state || []).map((entry) => {
      const focusedAt = focusedAtByPr[entry.number] ?? null;
      const decidedAt = decidedAtByPr[entry.number] ?? null;
      let decisionSeconds: number | null = null;
      if (focusedAt && decidedAt) {
        const dt = (new Date(decidedAt).getTime() - new Date(focusedAt).getTime()) / 1000;
        decisionSeconds = Number.isFinite(dt) && dt >= 0 ? dt : null;
      }
      return {
        pr_number: entry.number,
        head_sha: String(entry.head_sha || ''),
        tier: entry.tier === null || entry.tier === undefined ? null : String(entry.tier),
        decision: decisions[entry.number] ?? null,
        comment: comments[entry.number] ?? '',
        first_focused_at_utc: focusedAt,
        decided_at_utc: decidedAt,
        decision_seconds: decisionSeconds,
      };
    });
    const payload = {
      schema_version: 'aragora-operator-decisions/1.0',
      generated_at_utc: generatedAt,
      receipt_id_hint: String(receiptIdHint || ''),
      receipt_repo: String(receipt.repo ?? ''),
      receipt_sha256: String(receipt.sha256 ?? ''),
      receipt_sha256_verified: Boolean(shaCheck?.matches),
      receipt_hmac_sha256_present: Boolean(shaCheck?.hmacPresent),
      receipt_hmac_sha256_verified: Boolean(shaCheck?.hmacVerified),
      decisions: entries,
    };
    const canonical = canonicalJson(payload);
    try {
      const bytes = new TextEncoder().encode(canonical);
      const hash = await crypto.subtle.digest('SHA-256', bytes);
      const payloadSha = Array.from(new Uint8Array(hash))
        .map((b) => b.toString(16).padStart(2, '0'))
        .join('');
      const signed = { ...payload, payload_sha256: payloadSha };
      const body = JSON.stringify(signed, null, 2);
      const blob = new Blob([body], { type: 'application/json' });
      const url = URL.createObjectURL(blob);
      const ts = generatedAt.replace(/[:.]/g, '-').replace(/-\d{3}Z$/, 'Z');
      const anchor = document.createElement('a');
      anchor.href = url;
      anchor.download = `operator-decisions-${ts}.json`;
      document.body.appendChild(anchor);
      anchor.click();
      document.body.removeChild(anchor);
      URL.revokeObjectURL(url);
      setDownloadStatus(
        `downloaded operator-decisions-${ts}.json (sha256 ${payloadSha.slice(0, 10)}…)`,
      );
    } catch (err) {
      setDownloadStatus(`download failed: ${(err as Error).message}`);
    }
  }, [receipt, decisions, comments, focusedAtByPr, decidedAtByPr, receiptIdHint, shaCheck]);

  return (
    <div className="min-h-screen bg-bg text-text relative overflow-hidden">
      <Scanlines />
      <CRTVignette />
      <div className="max-w-6xl mx-auto px-4 py-8 relative z-10">
        <div className="mb-6">
          <div className="flex items-baseline gap-3 mb-2">
            <h1 className="text-xl font-theme-data font-bold text-[var(--accent)]">
              Settlement packet sign-off
            </h1>
            <span
              data-testid="packets-receipt-hint"
              className="text-xs font-theme-data"
              style={{
                letterSpacing: '0.08em',
                textTransform: 'uppercase',
                color: 'var(--text-muted)',
              }}
            >
              {receiptIdHint || '(no receipt id)'}
            </span>
            <span
              className="text-xs font-mono ml-2"
              style={{ color: 'var(--text-muted)' }}
              data-testid="packets-keyboard-hint"
            >
              keys: j/k · 1-5 · ?
            </span>
          </div>
          <p className="text-text-muted font-theme-data text-sm">
            Load a settlement-packet receipt, record per-PR decisions, then download a SHA-256-bound
            JSON. Read-only — nothing is sent.
          </p>
        </div>

        <div
          className="mb-6 rounded-xl border p-4"
          style={{ borderColor: 'var(--border)', background: 'var(--panel)' }}
        >
          <label
            htmlFor="packets-file-input"
            className="block text-xs font-theme-data mb-2"
            style={{ color: 'var(--text-muted)' }}
          >
            Receipt JSON file
          </label>
          <input
            id="packets-file-input"
            data-testid="packets-file-input"
            type="file"
            accept="application/json,.json"
            onChange={onPickFile}
            className="text-sm"
            style={{ color: 'var(--text)' }}
          />
          {loadError && (
            <div
              role="alert"
              data-testid="packets-load-error"
              className="mt-3 text-xs"
              style={{ color: 'var(--crimson)' }}
            >
              {loadError}
            </div>
          )}
        </div>

        {receipt && (
          <div
            data-testid="packets-receipt-summary"
            className="mb-6 rounded-xl border p-4 text-xs font-theme-data"
            style={{
              borderColor: 'var(--border)',
              background: 'var(--panel)',
              color: 'var(--text-muted)',
            }}
          >
            <div className="flex flex-wrap gap-x-6 gap-y-1">
              <span>
                schema:{' '}
                <span style={{ color: 'var(--text)' }}>{receipt.schema_version ?? '—'}</span>
              </span>
              <span>
                repo: <span style={{ color: 'var(--text)' }}>{receipt.repo ?? '—'}</span>
              </span>
              <span>
                generated:{' '}
                <span style={{ color: 'var(--text)' }}>{receipt.generated_at_utc ?? '—'}</span>
              </span>
              <span>
                PRs:{' '}
                <span style={{ color: 'var(--text)' }} data-testid="packets-pr-count">
                  {totalCount}
                </span>
              </span>
              <span>
                decided:{' '}
                <span style={{ color: 'var(--text)' }} data-testid="packets-decided-count">
                  {decidedCount}/{totalCount}
                </span>
              </span>
              {medianDecisionSeconds !== null && (
                <span data-testid="packets-median-decision-seconds">
                  median:{' '}
                  <span style={{ color: 'var(--text)' }}>{medianDecisionSeconds.toFixed(1)}s</span>
                </span>
              )}
            </div>
            {shaCheck && (
              <div
                data-testid="packets-sha-check"
                className="mt-2"
                style={{ color: shaCheck.matches ? 'var(--accent)' : 'var(--crimson)' }}
              >
                sha256 payload {shaCheck.matches ? 'match ✓' : 'mismatch ✗'} —{' '}
                {shaCheck.claimed.slice(0, 10) || '(none)'} vs {shaCheck.recomputed.slice(0, 10)}
                <div
                  data-testid="packets-hmac-check"
                  className="mt-1"
                  style={{ color: 'var(--text-muted)' }}
                >
                  {shaCheck.hmacPresent
                    ? 'hmac_sha256 present; not verified in browser'
                    : 'hmac_sha256 absent; hash-only receipt'}
                </div>
              </div>
            )}
          </div>
        )}

        {receipt && queue.prs.length === 0 && (
          <div
            data-testid="packets-empty"
            className="rounded border border-dashed border-slate-700 bg-slate-900/40 px-4 py-8 text-center text-sm text-slate-300"
          >
            Receipt has no PRs in <code>pinned_state[]</code>.
          </div>
        )}

        {receipt && queue.prs.length > 0 && (
          <div
            data-testid="packets-decision-list"
            role="listbox"
            aria-label="Settlement packet PRs"
          >
            {queue.prs.map((pr, index) => {
              const recommended =
                receipt.pinned_state.find((e) => e.number === pr.number)?.recommended_action ??
                null;
              return (
                <PacketDecisionCard
                  key={pr.number}
                  pr={pr}
                  decision={decisions[pr.number] ?? null}
                  comment={comments[pr.number] ?? ''}
                  recommendedAction={recommended}
                  selected={selectedIndex === index}
                  onSelect={() => setSelectedIndex(index)}
                  onDecisionChange={(decision) => setDecisionFor(pr.number, decision)}
                  onCommentChange={(comment) => setCommentFor(pr.number, comment)}
                />
              );
            })}

            <div
              className="mt-6 flex flex-wrap items-center gap-4 text-sm"
              style={{ color: 'var(--text-muted)' }}
            >
              <button
                type="button"
                data-testid="packets-download-button"
                onClick={() => void onDownload()}
                disabled={decidedCount === 0}
                className="rounded-lg border px-4 py-2 font-theme-data uppercase tracking-wider hover:opacity-80 disabled:opacity-40"
                style={{
                  borderColor: 'var(--accent)',
                  color: 'var(--accent)',
                  background: 'rgba(79,182,255,0.10)',
                }}
              >
                Download decisions JSON
              </button>
              <span data-testid="packets-remaining-count">
                {remainingCount} PR{remainingCount === 1 ? '' : 's'} undecided
              </span>
              {downloadStatus && (
                <span data-testid="packets-download-status" style={{ color: 'var(--text)' }}>
                  {downloadStatus}
                </span>
              )}
            </div>
          </div>
        )}

        {!receipt && !loadError && (
          <div
            data-testid="packets-placeholder"
            className="rounded border border-dashed border-slate-700 bg-slate-900/40 px-4 py-8 text-center text-sm text-slate-300"
          >
            Pick a receipt JSON to begin. Receipts live under{' '}
            <code className="rounded bg-slate-800 px-1">docs/receipts/</code>.
          </div>
        )}

        {helpOpen && (
          <div
            role="dialog"
            aria-modal="true"
            data-testid="packets-help-overlay"
            className="fixed inset-0 z-40 flex items-center justify-center bg-black/70 p-4"
            onClick={() => setHelpOpen(false)}
          >
            <div
              className="w-full max-w-md rounded-xl border p-6 text-sm"
              style={{
                borderColor: 'var(--border)',
                backgroundColor: 'var(--surface)',
                color: 'var(--text)',
                boxShadow: 'var(--shadow-floating)',
              }}
              onClick={(e) => e.stopPropagation()}
            >
              <h3 className="mb-3 font-theme-data text-base">Keyboard sign-off</h3>
              <table className="w-full text-xs font-mono">
                <tbody>
                  <tr>
                    <td className="pr-3 py-0.5" style={{ color: 'var(--accent)' }}>
                      j / ↓
                    </td>
                    <td>next PR card</td>
                  </tr>
                  <tr>
                    <td className="pr-3 py-0.5" style={{ color: 'var(--accent)' }}>
                      k / ↑
                    </td>
                    <td>prev PR card</td>
                  </tr>
                  <tr>
                    <td className="pr-3 py-0.5" style={{ color: 'var(--accent)' }}>
                      1
                    </td>
                    <td>APPROVE this tier</td>
                  </tr>
                  <tr>
                    <td className="pr-3 py-0.5" style={{ color: 'var(--accent)' }}>
                      2
                    </td>
                    <td>APPROVE downgraded</td>
                  </tr>
                  <tr>
                    <td className="pr-3 py-0.5" style={{ color: 'var(--accent)' }}>
                      3
                    </td>
                    <td>REQUEST changes</td>
                  </tr>
                  <tr>
                    <td className="pr-3 py-0.5" style={{ color: 'var(--accent)' }}>
                      4
                    </td>
                    <td>REJECT</td>
                  </tr>
                  <tr>
                    <td className="pr-3 py-0.5" style={{ color: 'var(--accent)' }}>
                      5
                    </td>
                    <td>HOLD (operator-only)</td>
                  </tr>
                  <tr>
                    <td className="pr-3 py-0.5" style={{ color: 'var(--accent)' }}>
                      ?
                    </td>
                    <td>toggle this help</td>
                  </tr>
                  <tr>
                    <td className="pr-3 py-0.5" style={{ color: 'var(--accent)' }}>
                      Esc
                    </td>
                    <td>close help</td>
                  </tr>
                </tbody>
              </table>
              <div className="mt-3 text-xs" style={{ color: 'var(--text-muted)' }}>
                Every decision records the time from first-focused → decided. Median shown live;
                per-PR timings exported in the JSON.
              </div>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
