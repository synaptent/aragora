'use client';

/**
 * useReviewQueueFromPacket — read a settlement-packet receipt (shape
 * `aragora-open-queue-settlement/1.0`) and surface its `pinned_state[]`
 * entries via the same `ReviewQueuePR[]` contract the live
 * `useReviewQueue()` hook returns.
 *
 * Why a sibling hook (not a flag on the existing one):
 *   - The live hook is server-backed via SWR + `/api/v1/review-queue/prs`.
 *     A packet receipt is static client-loaded data with no refresh
 *     interval. Mixing the two paths in one hook complicates the SWR
 *     lifecycle for no payoff.
 *   - The packet receipt schema is sparse (no title, author, labels) so
 *     the mapper applies safe defaults rather than 404-ing the hook.
 *
 * Sequencing context: this is part 2/3 of the operator-chosen refactor
 * of #7266 (standalone HTML operator UI) into enhancements to the
 * existing `/review-queue` UI:
 *   - Part 1 (#7273): add `tier?` field + `tierBadge()` helper +
 *     ReviewQueueCard badge render.
 *   - Part 2 (this PR): this hook.
 *   - Part 3: add `/review-queue/packets/[receiptId]` route that uses
 *     this hook to render the existing list components against a
 *     packet.
 */

import { useMemo } from 'react';
import type { CiSummary, ReviewQueuePR, ReviewQueueListResponse } from './useReviewQueue';

/** One entry in `pinned_state[]` of an aragora-open-queue-settlement/1.0 receipt. */
export interface SettlementPinnedStateEntry {
  number: number;
  head_sha: string;
  draft?: boolean;
  decision?: string | null;
  merge_state?: string | null;
  tier?: string | number | null;
  in_flight?: number;
  failures?: number;
  successes?: number;
  files_touched_count?: number;
  recommended_action?: string | null;
}

/** Minimum required fields the hook reads off a settlement-packet receipt. */
export interface SettlementReceipt {
  schema_version?: string;
  generated_at_utc?: string;
  repo?: string;
  pinned_state: SettlementPinnedStateEntry[];
  sha256?: string;
  hmac_sha256?: string | null;
  signed_at_utc?: string | null;
}

/** Optional per-PR metadata supplements callers can supply (titles fetched via gh, etc.). */
export interface ReviewQueuePacketSupplements {
  /** Map of PR number → title; used as fallback when the receipt has no title field. */
  titles?: Record<number, string>;
  /** Map of PR number → author; used as fallback when the receipt has no author field. */
  authors?: Record<number, string>;
  /** Map of PR number → labels array; used as fallback. */
  labels?: Record<number, string[]>;
  /** Map of PR number → `updated_at` ISO; used to derive `age_seconds` if not in receipt. */
  updatedAtIso?: Record<number, string>;
}

/**
 * Map one settlement-packet entry into the shape `ReviewQueueCard` expects.
 *
 * Defaults applied for fields the receipt does not carry:
 *   - title: "(no title in receipt)" unless supplements.titles[n] is set
 *   - author: "(unknown)" unless supplements.authors[n] is set
 *   - labels: [] unless supplements.labels[n] is set
 *   - ci: derived from receipt counts
 *   - brief_present/verdict/confidence: false/null/null (no brief from packet)
 *   - deferred: false
 *   - url: derived from repo + number if repo is provided
 *   - age_seconds: derived from supplements.updatedAtIso[n] if provided, else null
 */
export function mapSettlementEntryToReviewQueuePR(
  entry: SettlementPinnedStateEntry,
  options: {
    repo?: string;
    titles?: Record<number, string>;
    authors?: Record<number, string>;
    labels?: Record<number, string[]>;
    updatedAtIso?: Record<number, string>;
    now?: Date;
  } = {},
): ReviewQueuePR {
  const number = entry.number;
  const headSha = String(entry.head_sha || '');
  const ci: CiSummary = {
    success: Math.max(0, Number(entry.successes ?? 0)),
    failure: Math.max(0, Number(entry.failures ?? 0)),
    pending: Math.max(0, Number(entry.in_flight ?? 0)),
    total:
      Math.max(0, Number(entry.successes ?? 0)) +
      Math.max(0, Number(entry.failures ?? 0)) +
      Math.max(0, Number(entry.in_flight ?? 0)),
  };
  const tierValue = entry.tier === null || entry.tier === undefined ? null : String(entry.tier);
  const url = options.repo ? `https://github.com/${options.repo}/pull/${number}` : `#pr-${number}`;
  const title = options.titles?.[number] ?? '(no title in receipt)';
  const author = options.authors?.[number] ?? '(unknown)';
  const labels = options.labels?.[number] ?? [];
  const updatedAtIso = options.updatedAtIso?.[number] ?? new Date(0).toISOString();
  let ageSeconds: number | null = null;
  if (options.updatedAtIso?.[number]) {
    const updatedAt = new Date(options.updatedAtIso[number]);
    if (!Number.isNaN(updatedAt.getTime())) {
      const now = options.now ?? new Date();
      ageSeconds = Math.max(0, Math.floor((now.getTime() - updatedAt.getTime()) / 1000));
    }
  }
  return {
    number,
    title,
    url,
    head_sha: headSha,
    is_draft: Boolean(entry.draft),
    author,
    labels,
    additions: 0,
    deletions: 0,
    changed_files: Math.max(0, Number(entry.files_touched_count ?? 0)),
    created_at: updatedAtIso,
    updated_at: updatedAtIso,
    age_seconds: ageSeconds,
    touched_subsystems: [],
    ci,
    brief_present: false,
    verdict: null,
    confidence: null,
    deferred: false,
    tier: tierValue,
  };
}

/** Map every entry in a settlement receipt into ReviewQueuePR[]. */
export function mapReceiptToReviewQueueList(
  receipt: SettlementReceipt,
  supplements: ReviewQueuePacketSupplements = {},
  options: { now?: Date } = {},
): ReviewQueueListResponse {
  const prs = (receipt.pinned_state || []).map((entry) =>
    mapSettlementEntryToReviewQueuePR(entry, {
      repo: receipt.repo,
      titles: supplements.titles,
      authors: supplements.authors,
      labels: supplements.labels,
      updatedAtIso: supplements.updatedAtIso,
      now: options.now,
    }),
  );
  return {
    prs,
    total: prs.length,
    visible: prs.length,
    deferred_count: 0,
    degraded: false,
    reason: undefined,
  };
}

/** Verify a receipt's `sha256` field matches the canonical-payload hash of everything else.
 *
 * The receipt's `sha256` field hashes the JSON payload BEFORE the signature
 * fields (`sha256`, `hmac_sha256`, `signed_at_utc`) were added. Re-derive
 * here using `crypto.subtle.digest` (Web Crypto API) so the page can show a
 * match/mismatch indicator on load.
 *
 * This browser-side check only proves payload integrity. It intentionally does
 * not treat `hmac_sha256` as verified because the signing key is not available
 * in the packet review UI.
 */
export async function verifyReceiptSha256(
  receipt: SettlementReceipt,
): Promise<{
  claimed: string;
  recomputed: string;
  matches: boolean;
  hmacClaimed: string;
  hmacPresent: boolean;
  hmacVerified: boolean;
}> {
  const claimed = String(receipt.sha256 ?? '');
  const hmacClaimed = String(receipt.hmac_sha256 ?? '');
  // Strip signature fields the way the generator does.
  const verifyCopy: Record<string, unknown> = { ...receipt };
  delete verifyCopy.sha256;
  delete verifyCopy.hmac_sha256;
  delete verifyCopy.signed_at_utc;
  const canonical = canonicalJson(verifyCopy);
  const bytes = new TextEncoder().encode(canonical);
  const hash = await crypto.subtle.digest('SHA-256', bytes);
  const recomputed = Array.from(new Uint8Array(hash))
    .map((b) => b.toString(16).padStart(2, '0'))
    .join('');
  return {
    claimed,
    recomputed,
    matches: claimed === recomputed,
    hmacClaimed,
    hmacPresent: hmacClaimed.length > 0,
    hmacVerified: false,
  };
}

/** Canonical JSON serialization matching python's `json.dumps(obj, sort_keys=True, separators=(',', ':'))`. */
export function canonicalJson(value: unknown): string {
  if (value === null) return 'null';
  if (typeof value === 'number') return Number.isFinite(value) ? JSON.stringify(value) : 'null';
  if (typeof value === 'string') return JSON.stringify(value);
  if (typeof value === 'boolean') return value ? 'true' : 'false';
  if (Array.isArray(value)) return '[' + value.map(canonicalJson).join(',') + ']';
  if (typeof value === 'object') {
    const obj = value as Record<string, unknown>;
    const keys = Object.keys(obj).sort();
    return '{' + keys.map((k) => JSON.stringify(k) + ':' + canonicalJson(obj[k])).join(',') + '}';
  }
  return JSON.stringify(value);
}

/**
 * React hook that adapts a settlement-packet receipt into the same
 * `{prs, total, visible, deferredCount, degraded, reason, isLoading,
 * error}` shape that `useReviewQueue()` returns, so the existing
 * ReviewQueueList/Card components can render against it without changes.
 */
export function useReviewQueueFromPacket(
  receipt: SettlementReceipt | null,
  supplements: ReviewQueuePacketSupplements = {},
): {
  prs: ReviewQueuePR[];
  total: number;
  visible: number;
  deferredCount: number;
  degraded: boolean;
  reason: string | undefined;
  isLoading: boolean;
  isValidating: boolean;
  error: Error | null;
  receipt: SettlementReceipt | null;
} {
  const mapped = useMemo<ReviewQueueListResponse | null>(() => {
    if (!receipt) return null;
    return mapReceiptToReviewQueueList(receipt, supplements);
  }, [receipt, supplements]);

  return {
    prs: mapped?.prs ?? [],
    total: mapped?.total ?? 0,
    visible: mapped?.visible ?? 0,
    deferredCount: mapped?.deferred_count ?? 0,
    degraded: mapped?.degraded ?? false,
    reason: mapped?.reason,
    isLoading: false,
    isValidating: false,
    error: null,
    receipt,
  };
}
