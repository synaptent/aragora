'use client';

import { useCallback, useEffect, useRef, useState } from 'react';
import { useSWRFetch } from './useSWRFetch';
import { API_BASE_URL } from '@/config';

// ---------------------------------------------------------------------------
// Types (mirror the backend shapes from aragora/server/handlers/review_queue.py)
// ---------------------------------------------------------------------------

export interface CiSummary {
  success: number;
  failure: number;
  pending: number;
  total: number;
}

export interface ReviewQueuePR {
  number: number;
  title: string;
  url: string;
  head_sha: string;
  is_draft: boolean;
  author: string;
  labels: string[];
  additions: number;
  deletions: number;
  changed_files: number;
  created_at: string;
  updated_at: string;
  age_seconds: number | null;
  touched_subsystems: string[];
  ci: CiSummary;
  brief_present: boolean;
  verdict: string | null;
  confidence: number | null;
  deferred: boolean;
  /**
   * Optional tier classification per `docs/REVIEW_AUTHORITY_PRINCIPLES.md`
   * (string '0'..'4'). When absent, downstream UI hides the badge. Set by
   * `useReviewQueueFromPacket()` when sourcing the queue from a
   * settlement-packet receipt. (Same field PR #7273 adds to support
   * inline tier badges; both PRs converge on the same shape.)
   */
  tier?: string | null;
}

export interface ReviewQueueListResponse {
  prs: ReviewQueuePR[];
  total: number;
  visible: number;
  deferred_count: number;
  degraded: boolean;
  reason?: string;
}

export interface ReviewQueueBrief {
  pr_number: number;
  head_sha: string;
  verdict: string;
  confidence: number | null;
  logic?: string | null;
  security?: string | null;
  maintainability?: string | null;
  skeptic?: string | null;
  [key: string]: unknown;
}

export interface ReviewQueueStats {
  date: string | null;
  approved: number;
  request_changes: number;
  deferred: number;
  streak: number;
  decision_count: number;
  median_decision_seconds: number | null;
}

// ---------------------------------------------------------------------------
// Hooks
// ---------------------------------------------------------------------------

function getAccessToken(): string | null {
  if (typeof window === 'undefined') return null;
  const stored = localStorage.getItem('aragora_tokens');
  if (!stored) return null;
  try {
    const parsed = JSON.parse(stored) as { access_token?: string };
    return parsed.access_token || null;
  } catch {
    return null;
  }
}

export function useReviewQueue() {
  const { data, error, isLoading, isValidating, mutate } = useSWRFetch<ReviewQueueListResponse>(
    '/api/v1/review-queue/prs',
    { refreshInterval: 60000 },
  );

  return {
    prs: data?.prs ?? [],
    total: data?.total ?? 0,
    visible: data?.visible ?? 0,
    deferredCount: data?.deferred_count ?? 0,
    degraded: data?.degraded ?? false,
    reason: data?.reason,
    isLoading,
    isValidating,
    error,
    mutate,
  };
}

export function useReviewQueueStats() {
  const { data, isLoading, mutate } = useSWRFetch<{ stats: ReviewQueueStats }>(
    '/api/v1/review-queue/stats',
    { refreshInterval: 30000 },
  );
  return { stats: data?.stats ?? null, isLoading, mutate };
}

export async function fetchBrief(prNumber: number): Promise<ReviewQueueBrief | null> {
  const token = getAccessToken();
  const headers: HeadersInit = { 'Content-Type': 'application/json' };
  if (token) headers['Authorization'] = `Bearer ${token}`;
  const res = await fetch(`${API_BASE_URL}/api/v1/review-queue/prs/${prNumber}/brief`, { headers });
  if (res.status === 404) return null;
  if (!res.ok) throw new Error(`brief request failed: ${res.status}`);
  const data = (await res.json()) as { brief: ReviewQueueBrief };
  return data.brief;
}

export type SettlementAction = 'approve' | 'request-changes' | 'defer';

export interface SettlementOptions {
  note?: string;
  reason?: string;
  hours?: number;
  decisionSeconds?: number;
}

export async function settlePR(
  prNumber: number,
  action: SettlementAction,
  options: SettlementOptions = {},
): Promise<{ status: string; [key: string]: unknown }> {
  const token = getAccessToken();
  const headers: HeadersInit = { 'Content-Type': 'application/json' };
  if (token) headers['Authorization'] = `Bearer ${token}`;

  const body: Record<string, unknown> = {};
  if (options.note !== undefined) body.note = options.note;
  if (options.reason !== undefined) body.reason = options.reason;
  if (options.hours !== undefined) body.hours = options.hours;
  if (options.decisionSeconds !== undefined) body.decision_seconds = options.decisionSeconds;

  const res = await fetch(`${API_BASE_URL}/api/v1/review-queue/prs/${prNumber}/${action}`, {
    method: 'POST',
    headers,
    body: JSON.stringify(body),
  });
  if (!res.ok) {
    let detail: string;
    try {
      const errData = (await res.json()) as { error?: string };
      detail = errData.error || `${res.status}`;
    } catch {
      detail = `${res.status}`;
    }
    const err = new Error(detail) as Error & { status: number };
    err.status = res.status;
    throw err;
  }
  return res.json() as Promise<{ status: string }>;
}

/**
 * Convenience callback factory — combines settlement + cache invalidation.
 */
export function useSettlePR(onSettled?: () => void) {
  return useCallback(
    async (prNumber: number, action: SettlementAction, options: SettlementOptions = {}) => {
      const result = await settlePR(prNumber, action, options);
      onSettled?.();
      return result;
    },
    [onSettled],
  );
}

// ---------------------------------------------------------------------------
// Mode 3 on-demand brief generation
//
// Contracts mirror
//   POST   /api/v1/review-queue/prs/{n}/brief/generate
//   GET    /api/v1/review-queue/prs/{n}/brief/state
//   DELETE /api/v1/review-queue/prs/{n}/brief/generate
// implemented in aragora/server/handlers/review_queue_brief.py.
//
// The backend is gated by the ARAGORA_PDB_BRIEF_GENERATION_ENABLED flag.
// When the flag is off, every endpoint returns 503. The helpers below
// treat 503 as "feature disabled" and cache that observation in a
// module-local variable so callers can avoid showing generation UI.
// ---------------------------------------------------------------------------

/** Canonical lifecycle states from aragora/pdb/brief_state.py. */
export type BriefLifecycleState = 'absent' | 'queued' | 'running' | 'ready' | 'failed' | 'stale';

export interface BriefStateSnapshot {
  state: BriefLifecycleState;
  phase?: string;
  rolesComplete?: number;
  rolesTotal?: number;
  elapsedSeconds?: number;
  costUsdSoFar?: number;
  reason?: string;
  headSha?: string;
  panelModels?: string[];
}

export interface GenerateBriefResponse {
  state: BriefLifecycleState;
  pr_number?: number;
  head_sha?: string;
  estimated_completion_seconds?: number;
  panel_models?: string[];
  queued_at?: string;
}

/** Module-local feature-flag cache. `null` = not yet probed. */
let _briefGenerationEnabled: boolean | null = null;

function rememberFlag(enabled: boolean): void {
  _briefGenerationEnabled = enabled;
}

/** Returns the cached feature-flag state. Not a hook. */
export function getBriefGenerationFlag(): boolean | null {
  return _briefGenerationEnabled;
}

/**
 * For tests only — reset the cached flag so each test starts clean.
 *
 * The production UI reads the flag from 503 responses, so the cache
 * is stable for the page lifetime. Tests flip it around per-case.
 */
export function __resetBriefGenerationFlagForTests(): void {
  _briefGenerationEnabled = null;
}

async function parseErrorDetail(res: Response, fallback: string): Promise<string> {
  try {
    const data = (await res.json()) as { error?: string; message?: string };
    return data.error || data.message || fallback;
  } catch {
    return fallback;
  }
}

/**
 * Trigger a Mode 3 brief generation.
 *
 * Returns the decoded response (`{state: "queued", ...}`) on success
 * or when the backend reports a 409 because a prior request is still
 * in flight. Maps 503 to a `featureDisabled` error the caller can
 * detect via `err.status === 503` — that signal both updates the
 * module-local flag cache and lets the caller fall back to the legacy
 * UX without triggering a generic error toast.
 */
export async function generateBrief(
  prNumber: number,
  options: { force?: boolean; repo?: string } = {},
): Promise<GenerateBriefResponse> {
  const token = getAccessToken();
  const headers: HeadersInit = { 'Content-Type': 'application/json' };
  if (token) headers['Authorization'] = `Bearer ${token}`;

  const body: Record<string, unknown> = {};
  if (options.force) body.force = true;
  if (options.repo !== undefined) body.repo = options.repo;

  const res = await fetch(`${API_BASE_URL}/api/v1/review-queue/prs/${prNumber}/brief/generate`, {
    method: 'POST',
    headers,
    body: JSON.stringify(body),
  });

  if (res.status === 503) {
    rememberFlag(false);
    const err = new Error('brief generation feature is disabled') as Error & { status: number };
    err.status = 503;
    throw err;
  }

  rememberFlag(true);

  if (res.status === 409) {
    // Conflict: another job is queued/running/ready for this PR. Surface
    // the payload so callers can decide how to display the state.
    const data = (await res.json().catch(() => ({}))) as GenerateBriefResponse;
    return data;
  }

  if (!res.ok) {
    const detail = await parseErrorDetail(res, `generate failed: ${res.status}`);
    const err = new Error(detail) as Error & { status: number };
    err.status = res.status;
    throw err;
  }

  return (await res.json()) as GenerateBriefResponse;
}

interface RawBriefStateResponse {
  state: BriefLifecycleState;
  head_sha?: string;
  current_phase?: string;
  cost_usd_so_far?: number;
  started_at?: string;
  requested_at?: string;
  error_message?: string;
  failed_phase?: string;
  panel_models?: string[];
  roles_complete?: number;
  roles_total?: number;
}

function snapshotFromRaw(raw: RawBriefStateResponse): BriefStateSnapshot {
  let elapsed: number | undefined;
  const anchor = raw.started_at ?? raw.requested_at;
  if (anchor) {
    const ts = Date.parse(anchor);
    if (!Number.isNaN(ts)) {
      elapsed = Math.max(0, Math.round((Date.now() - ts) / 1000));
    }
  }
  return {
    state: raw.state,
    phase: raw.current_phase,
    costUsdSoFar: raw.cost_usd_so_far,
    elapsedSeconds: elapsed,
    reason: raw.error_message,
    headSha: raw.head_sha,
    panelModels: raw.panel_models,
    rolesComplete: raw.roles_complete,
    rolesTotal: raw.roles_total,
  };
}

/**
 * One-shot brief state read. Returns a normalized
 * :data:`BriefStateSnapshot`. On 503 returns an `{state: 'absent'}`
 * snapshot and caches the feature-flag state as off — the caller can
 * check :func:`getBriefGenerationFlag` afterwards to decide which UX
 * to render.
 */
export async function getBriefState(prNumber: number): Promise<BriefStateSnapshot> {
  const token = getAccessToken();
  const headers: HeadersInit = { 'Content-Type': 'application/json' };
  if (token) headers['Authorization'] = `Bearer ${token}`;

  const res = await fetch(`${API_BASE_URL}/api/v1/review-queue/prs/${prNumber}/brief/state`, {
    headers,
  });

  if (res.status === 503) {
    rememberFlag(false);
    return { state: 'absent' };
  }

  rememberFlag(true);

  if (res.status === 404) {
    return { state: 'absent' };
  }

  if (!res.ok) {
    const detail = await parseErrorDetail(res, `state request failed: ${res.status}`);
    const err = new Error(detail) as Error & { status: number };
    err.status = res.status;
    throw err;
  }

  const data = (await res.json()) as RawBriefStateResponse;
  return snapshotFromRaw(data);
}

/**
 * Cancel an in-flight generation. Safe to call when no job exists —
 * the backend returns 200 with `cancelled: false` in that case.
 */
export async function cancelBriefGeneration(prNumber: number): Promise<void> {
  const token = getAccessToken();
  const headers: HeadersInit = { 'Content-Type': 'application/json' };
  if (token) headers['Authorization'] = `Bearer ${token}`;

  const res = await fetch(`${API_BASE_URL}/api/v1/review-queue/prs/${prNumber}/brief/generate`, {
    method: 'DELETE',
    headers,
  });

  if (res.status === 503) {
    rememberFlag(false);
    return;
  }
  rememberFlag(true);

  if (!res.ok) {
    const detail = await parseErrorDetail(res, `cancel failed: ${res.status}`);
    const err = new Error(detail) as Error & { status: number };
    err.status = res.status;
    throw err;
  }
}

export interface UseBriefStateOptions {
  /**
   * When false, the hook will not issue any network requests. Defaults
   * to `true`. Useful for cards that haven't been expanded yet.
   */
  enabled?: boolean;
  /** Poll cadence while state is queued or running, in ms. */
  pollIntervalMs?: number;
}

export interface UseBriefStateResult {
  snapshot: BriefStateSnapshot | null;
  isLoading: boolean;
  error: Error | null;
  featureDisabled: boolean;
  refresh: () => Promise<BriefStateSnapshot | null>;
  setSnapshot: (next: BriefStateSnapshot | null) => void;
}

/**
 * React hook that polls `/brief/state` every 3s while the lifecycle is
 * `queued` or `running`, then stops once the state stabilizes.
 *
 * The hook dedupes inflight requests (only one outstanding fetch at a
 * time) and cancels outstanding timers on unmount or when `prNumber`
 * changes.
 */
export function useBriefState(
  prNumber: number | null,
  options: UseBriefStateOptions = {},
): UseBriefStateResult {
  const { enabled = true, pollIntervalMs = 3000 } = options;

  const [snapshot, setSnapshot] = useState<BriefStateSnapshot | null>(null);
  const [error, setError] = useState<Error | null>(null);
  const [isLoading, setIsLoading] = useState(false);
  const [featureDisabled, setFeatureDisabled] = useState(false);

  const mountedRef = useRef(true);
  const inflightRef = useRef(false);
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const clearTimer = useCallback(() => {
    if (timerRef.current !== null) {
      clearTimeout(timerRef.current);
      timerRef.current = null;
    }
  }, []);

  const refresh = useCallback(async (): Promise<BriefStateSnapshot | null> => {
    if (prNumber === null || !enabled) return null;
    if (inflightRef.current) return null;
    inflightRef.current = true;
    setIsLoading(true);
    try {
      const next = await getBriefState(prNumber);
      if (!mountedRef.current) return next;
      if (getBriefGenerationFlag() === false) {
        setFeatureDisabled(true);
      } else {
        setFeatureDisabled(false);
      }
      setSnapshot(next);
      setError(null);
      return next;
    } catch (err) {
      if (mountedRef.current) {
        setError(err as Error);
      }
      return null;
    } finally {
      inflightRef.current = false;
      if (mountedRef.current) setIsLoading(false);
    }
  }, [prNumber, enabled]);

  // Kick off an initial fetch when prNumber / enabled changes.
  useEffect(() => {
    mountedRef.current = true;
    if (prNumber === null || !enabled) {
      setSnapshot(null);
      setError(null);
      return () => {
        mountedRef.current = false;
        clearTimer();
      };
    }
    void refresh();
    return () => {
      mountedRef.current = false;
      clearTimer();
    };
  }, [prNumber, enabled, refresh, clearTimer]);

  // While state is queued or running, schedule a polling tick.
  useEffect(() => {
    if (!enabled || prNumber === null) return;
    const active = snapshot?.state === 'queued' || snapshot?.state === 'running';
    if (!active) {
      clearTimer();
      return;
    }
    clearTimer();
    timerRef.current = setTimeout(() => {
      void refresh();
    }, pollIntervalMs);
    return clearTimer;
  }, [snapshot, enabled, prNumber, pollIntervalMs, refresh, clearTimer]);

  return { snapshot, isLoading, error, featureDisabled, refresh, setSnapshot };
}
