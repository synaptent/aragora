/**
 * Review Queue Namespace API
 *
 * Methods for the PDB (PR intelligence brief) review queue: listing open PRs
 * eligible for settlement, fetching briefs, submitting approve /
 * request-changes reviews (via the caller's authenticated identity — not
 * automation), and deferring PRs locally.
 */

import type { AragoraClient } from '../client';

/** Brief verdict enum. */
export type BriefVerdict =
  | 'approve_candidate'
  | 'needs_human_attention'
  | 'repair_first';

/** PR entry in the review queue list response. */
export interface ReviewQueuePR {
  number: number;
  title: string;
  author: string;
  head_sha: string;
  created_at: string;
  subsystems: string[];
  check_counts: Record<string, number>;
  has_brief: boolean;
  verdict?: BriefVerdict;
}

/** Session statistics for the header badge. */
export interface ReviewQueueStats {
  approved_today: number;
  median_decision_seconds?: number;
  streak: number;
}

/**
 * Review Queue namespace for browser-based PR settlement triage.
 *
 * @example
 * ```typescript
 * const { prs } = await client.reviewQueue.listPRs();
 * for (const pr of prs) {
 *   console.log(pr.number, pr.title);
 * }
 * ```
 */
export class ReviewQueueAPI {
  constructor(private client: AragoraClient) {}

  /** List open PRs currently in the review queue. */
  async listPRs(options?: {
    includeDeferred?: boolean;
  }): Promise<{ prs: ReviewQueuePR[]; total: number }> {
    const params: Record<string, unknown> = {};
    if (options?.includeDeferred) {
      params.include_deferred = '1';
    }
    return this.client.request<{ prs: ReviewQueuePR[]; total: number }>(
      'GET',
      '/api/v1/review-queue/prs',
      { params }
    );
  }

  /** Fetch the PDB brief for a specific PR (404 if no brief exists). */
  async getBrief(prNumber: number): Promise<{ brief: Record<string, unknown> }> {
    return this.client.request<{ brief: Record<string, unknown> }>(
      'GET',
      `/api/v1/review-queue/prs/${prNumber}/brief`
    );
  }

  /** Submit a GitHub APPROVE review for the PR using the caller's identity. */
  async approve(
    prNumber: number,
    options?: { note?: string }
  ): Promise<{ ok: boolean; review_id?: number }> {
    const body: Record<string, unknown> = {};
    if (options?.note !== undefined) {
      body.note = options.note;
    }
    return this.client.request<{ ok: boolean; review_id?: number }>(
      'POST',
      `/api/v1/review-queue/prs/${prNumber}/approve`,
      { body }
    );
  }

  /** Submit a REQUEST_CHANGES review with a required reason. */
  async requestChanges(
    prNumber: number,
    reason: string
  ): Promise<{ ok: boolean; review_id?: number }> {
    return this.client.request<{ ok: boolean; review_id?: number }>(
      'POST',
      `/api/v1/review-queue/prs/${prNumber}/request-changes`,
      { body: { reason } }
    );
  }

  /** Defer the PR locally (hides it from the queue for ~4 hours). */
  async defer(prNumber: number): Promise<{ ok: boolean; deferred_until: string }> {
    return this.client.request<{ ok: boolean; deferred_until: string }>(
      'POST',
      `/api/v1/review-queue/prs/${prNumber}/defer`
    );
  }

  /** Fetch session stats for the header badge. */
  async stats(): Promise<ReviewQueueStats> {
    return this.client.request<ReviewQueueStats>(
      'GET',
      '/api/v1/review-queue/stats'
    );
  }

  /** Fetch rolling-window triage metrics (7-day and 30-day windows). */
  async triageMetrics(): Promise<Record<string, unknown>> {
    return this.client.request<Record<string, unknown>>(
      'GET',
      '/api/v1/review-queue/triage-metrics'
    );
  }
}
