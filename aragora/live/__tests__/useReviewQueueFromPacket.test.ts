/**
 * Tests for useReviewQueueFromPacket — settlement-packet receipt -> ReviewQueuePR adapter.
 */

import { webcrypto } from 'node:crypto';
import { TextDecoder as NodeTextDecoder, TextEncoder as NodeTextEncoder } from 'node:util';
import { renderHook } from '@testing-library/react';

// jsdom does not expose TextEncoder/TextDecoder nor `crypto.subtle`. Some
// jsdom builds also lock `globalThis.crypto` as a non-writable getter, so
// a plain assignment is silently ignored — use Object.defineProperty
// to force the override.
if (typeof globalThis.TextEncoder === 'undefined') {
  Object.defineProperty(globalThis, 'TextEncoder', {
    value: NodeTextEncoder,
    configurable: true,
    writable: true,
  });
}
if (typeof globalThis.TextDecoder === 'undefined') {
  Object.defineProperty(globalThis, 'TextDecoder', {
    value: NodeTextDecoder,
    configurable: true,
    writable: true,
  });
}
const existingCrypto = (globalThis as { crypto?: { subtle?: unknown } }).crypto;
if (!existingCrypto || !existingCrypto.subtle) {
  Object.defineProperty(globalThis, 'crypto', {
    value: webcrypto,
    configurable: true,
    writable: true,
  });
}

import {
  canonicalJson,
  mapReceiptToReviewQueueList,
  mapSettlementEntryToReviewQueuePR,
  useReviewQueueFromPacket,
  verifyReceiptSha256,
  type SettlementReceipt,
} from '../src/hooks/useReviewQueueFromPacket';

const FIXED_NOW = new Date('2026-05-17T12:00:00.000Z');

function sampleReceipt(overrides: Partial<SettlementReceipt> = {}): SettlementReceipt {
  return {
    schema_version: 'aragora-open-queue-settlement/1.0',
    generated_at_utc: '2026-05-17T14:28:11.000Z',
    repo: 'synaptent/aragora',
    pinned_state: [
      {
        number: 7240,
        head_sha: 'aaaaaaaaaaaaaaaa',
        draft: false,
        decision: 'REVIEW_REQUIRED',
        merge_state: 'BLOCKED',
        tier: '2',
        in_flight: 1,
        failures: 0,
        successes: 57,
        files_touched_count: 20,
        recommended_action: 'review and admin-merge if quorum holds',
      },
      {
        number: 7243,
        head_sha: 'bbbbbbbbbbbbbbbb',
        draft: true,
        decision: 'REVIEW_REQUIRED',
        merge_state: 'BLOCKED',
        tier: '0',
        in_flight: 0,
        failures: 0,
        successes: 3,
        files_touched_count: 1,
        recommended_action: 'docs-only — admin-squash any time',
      },
    ],
    sha256: 'pretend-canonical-hash',
    hmac_sha256: null,
    signed_at_utc: null,
    ...overrides,
  };
}

describe('mapSettlementEntryToReviewQueuePR', () => {
  it('maps the canonical fields into a ReviewQueuePR shape', () => {
    const entry = sampleReceipt().pinned_state[0];
    const pr = mapSettlementEntryToReviewQueuePR(entry, {
      repo: 'synaptent/aragora',
      now: FIXED_NOW,
    });
    expect(pr.number).toBe(7240);
    expect(pr.head_sha).toBe('aaaaaaaaaaaaaaaa');
    expect(pr.is_draft).toBe(false);
    expect(pr.tier).toBe('2');
    expect(pr.ci).toEqual({ success: 57, failure: 0, pending: 1, total: 58 });
    expect(pr.url).toBe('https://github.com/synaptent/aragora/pull/7240');
    expect(pr.changed_files).toBe(20);
  });

  it('uses placeholder defaults when receipt has no title/author/labels', () => {
    const entry = sampleReceipt().pinned_state[0];
    const pr = mapSettlementEntryToReviewQueuePR(entry, { now: FIXED_NOW });
    expect(pr.title).toBe('(no title in receipt)');
    expect(pr.author).toBe('(unknown)');
    expect(pr.labels).toEqual([]);
    expect(pr.brief_present).toBe(false);
    expect(pr.verdict).toBeNull();
    expect(pr.deferred).toBe(false);
  });

  it('honors supplement maps for title/author/labels', () => {
    const entry = sampleReceipt().pinned_state[0];
    const pr = mapSettlementEntryToReviewQueuePR(entry, {
      repo: 'synaptent/aragora',
      titles: { 7240: 'feat(codex): inspector' },
      authors: { 7240: 'an0mium' },
      labels: { 7240: ['governance'] },
      updatedAtIso: { 7240: '2026-05-17T11:00:00.000Z' },
      now: FIXED_NOW,
    });
    expect(pr.title).toBe('feat(codex): inspector');
    expect(pr.author).toBe('an0mium');
    expect(pr.labels).toEqual(['governance']);
    expect(pr.age_seconds).toBe(3600);
  });

  it('emits a synthetic url when repo is not provided', () => {
    const entry = sampleReceipt().pinned_state[0];
    const pr = mapSettlementEntryToReviewQueuePR(entry, { now: FIXED_NOW });
    expect(pr.url).toBe('#pr-7240');
  });

  it('preserves null tier from receipt', () => {
    const pr = mapSettlementEntryToReviewQueuePR(
      { number: 1, head_sha: 'x', tier: null },
      { now: FIXED_NOW },
    );
    expect(pr.tier).toBeNull();
  });

  it('stringifies numeric tier values', () => {
    const pr = mapSettlementEntryToReviewQueuePR(
      { number: 1, head_sha: 'x', tier: 4 },
      { now: FIXED_NOW },
    );
    expect(pr.tier).toBe('4');
  });

  it('clamps negative counts to zero', () => {
    const pr = mapSettlementEntryToReviewQueuePR(
      { number: 1, head_sha: 'x', failures: -3, in_flight: -1, successes: 2 },
      { now: FIXED_NOW },
    );
    expect(pr.ci.failure).toBe(0);
    expect(pr.ci.pending).toBe(0);
    expect(pr.ci.success).toBe(2);
    expect(pr.ci.total).toBe(2);
  });
});

describe('mapReceiptToReviewQueueList', () => {
  it('flattens pinned_state[] into a ReviewQueueListResponse', () => {
    const receipt = sampleReceipt();
    const list = mapReceiptToReviewQueueList(receipt);
    expect(list.prs.length).toBe(2);
    expect(list.total).toBe(2);
    expect(list.visible).toBe(2);
    expect(list.deferred_count).toBe(0);
    expect(list.degraded).toBe(false);
    expect(list.prs[0].number).toBe(7240);
    expect(list.prs[1].number).toBe(7243);
    expect(list.prs[1].is_draft).toBe(true);
  });

  it('returns empty list when pinned_state is missing', () => {
    const list = mapReceiptToReviewQueueList({ pinned_state: [] } as SettlementReceipt);
    expect(list.prs).toEqual([]);
    expect(list.total).toBe(0);
  });
});

describe('canonicalJson', () => {
  it('matches Python json.dumps(sort_keys=True, separators=(",", ":"))', () => {
    expect(canonicalJson({ b: 1, a: 2 })).toBe('{"a":2,"b":1}');
    expect(canonicalJson([3, 2, 1])).toBe('[3,2,1]');
    expect(canonicalJson(null)).toBe('null');
    expect(canonicalJson(true)).toBe('true');
    expect(canonicalJson('he"llo')).toBe('"he\\"llo"');
  });

  it('handles nested structures deterministically', () => {
    const a = canonicalJson({ outer: { z: 1, a: 2 }, list: [{ b: 1, a: 2 }] });
    const b = canonicalJson({ list: [{ a: 2, b: 1 }], outer: { a: 2, z: 1 } });
    expect(a).toBe(b);
  });
});

describe('verifyReceiptSha256', () => {
  it('matches when the receipt was generated honestly', async () => {
    // Build a receipt, compute its expected sha256, then re-verify.
    const payload: SettlementReceipt = {
      schema_version: 'aragora-open-queue-settlement/1.0',
      generated_at_utc: '2026-05-17T00:00:00.000Z',
      pinned_state: [
        { number: 1, head_sha: 'a', tier: '0' },
        { number: 2, head_sha: 'b', tier: '1' },
      ],
    };
    const canonical = canonicalJson({ ...payload });
    const bytes = new TextEncoder().encode(canonical);
    const hash = await crypto.subtle.digest('SHA-256', bytes);
    const sha = Array.from(new Uint8Array(hash))
      .map((x) => x.toString(16).padStart(2, '0'))
      .join('');
    const signed: SettlementReceipt = { ...payload, sha256: sha };
    const result = await verifyReceiptSha256(signed);
    expect(result.matches).toBe(true);
    expect(result.claimed).toBe(sha);
    expect(result.recomputed).toBe(sha);
    expect(result.hmacPresent).toBe(false);
    expect(result.hmacVerified).toBe(false);
  });

  it('does not claim browser-side hmac verification for signed receipts', async () => {
    const payload: SettlementReceipt = {
      schema_version: 'aragora-open-queue-settlement/1.0',
      generated_at_utc: '2026-05-17T00:00:00.000Z',
      pinned_state: [{ number: 1, head_sha: 'a', tier: '0' }],
    };
    const canonical = canonicalJson({ ...payload });
    const bytes = new TextEncoder().encode(canonical);
    const hash = await crypto.subtle.digest('SHA-256', bytes);
    const sha = Array.from(new Uint8Array(hash))
      .map((x) => x.toString(16).padStart(2, '0'))
      .join('');
    const signed: SettlementReceipt = {
      ...payload,
      sha256: sha,
      hmac_sha256: 'f'.repeat(64),
      signed_at_utc: '2026-05-17T00:01:00.000Z',
    };
    const result = await verifyReceiptSha256(signed);
    expect(result.matches).toBe(true);
    expect(result.hmacClaimed).toBe('f'.repeat(64));
    expect(result.hmacPresent).toBe(true);
    expect(result.hmacVerified).toBe(false);
  });

  it('flags mismatch when the payload is tampered after signing', async () => {
    const payload: SettlementReceipt = { pinned_state: [{ number: 1, head_sha: 'a' }] };
    const canonical = canonicalJson(payload);
    const hash = await crypto.subtle.digest('SHA-256', new TextEncoder().encode(canonical));
    const sha = Array.from(new Uint8Array(hash))
      .map((x) => x.toString(16).padStart(2, '0'))
      .join('');
    const tampered: SettlementReceipt = {
      ...payload,
      sha256: sha,
      pinned_state: [{ number: 1, head_sha: 'TAMPERED' }],
    };
    const result = await verifyReceiptSha256(tampered);
    expect(result.matches).toBe(false);
    expect(result.claimed).toBe(sha);
    expect(result.recomputed).not.toBe(sha);
  });
});

describe('useReviewQueueFromPacket', () => {
  it('returns empty state when receipt is null', () => {
    const { result } = renderHook(() => useReviewQueueFromPacket(null));
    expect(result.current.prs).toEqual([]);
    expect(result.current.total).toBe(0);
    expect(result.current.isLoading).toBe(false);
    expect(result.current.error).toBeNull();
    expect(result.current.receipt).toBeNull();
  });

  it('maps a receipt into the same shape useReviewQueue returns', () => {
    const receipt = sampleReceipt();
    const { result } = renderHook(() => useReviewQueueFromPacket(receipt));
    expect(result.current.prs.length).toBe(2);
    expect(result.current.total).toBe(2);
    expect(result.current.visible).toBe(2);
    expect(result.current.deferredCount).toBe(0);
    expect(result.current.degraded).toBe(false);
    expect(result.current.receipt).toBe(receipt);
    // Tier field flows through so PR-A's badge renders correctly when this hook drives the UI.
    expect(result.current.prs[0].tier).toBe('2');
    expect(result.current.prs[1].tier).toBe('0');
  });

  it('passes supplements through to the mapped PRs', () => {
    const receipt = sampleReceipt();
    const { result } = renderHook(() =>
      useReviewQueueFromPacket(receipt, { titles: { 7240: 'inspector', 7243: 'docs refresh' } }),
    );
    expect(result.current.prs[0].title).toBe('inspector');
    expect(result.current.prs[1].title).toBe('docs refresh');
  });

  it('always reports isLoading=false and error=null (synchronous adapter)', () => {
    const receipt = sampleReceipt();
    const { result } = renderHook(() => useReviewQueueFromPacket(receipt));
    expect(result.current.isLoading).toBe(false);
    expect(result.current.isValidating).toBe(false);
    expect(result.current.error).toBeNull();
  });
});
