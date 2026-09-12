/**
 * Tests for the Mode 3 brief-generation hook surface added in PR 4:
 *
 *   - generateBrief()
 *   - getBriefState()
 *   - cancelBriefGeneration()
 *   - useBriefState() — the polling hook
 *
 * Legacy helpers (fetchBrief / settlePR) are covered by
 * useReviewQueueActions.test.ts; this file focuses on the new surface.
 */

jest.mock('../src/config', () => ({
  API_BASE_URL: 'http://localhost:8080',
  WS_URL: 'ws://localhost:8765/ws',
}));

import { act, renderHook, waitFor } from '@testing-library/react';

import {
  __resetBriefGenerationFlagForTests,
  cancelBriefGeneration,
  generateBrief,
  getBriefGenerationFlag,
  getBriefState,
  useBriefState,
} from '../src/hooks/useReviewQueue';

type FetchInit = RequestInit | undefined;
type FetchArgs = [string, FetchInit];

function mockFetch(responder: (url: string, init: FetchInit) => Partial<Response>) {
  (global.fetch as jest.Mock).mockImplementation(async (url: string, init: FetchInit) => {
    const shape = responder(url, init);
    const status = shape.status ?? 200;
    return {
      ok: shape.ok ?? (status >= 200 && status < 300),
      status,
      json: async () => (shape as { _body?: unknown })._body ?? {},
    } as unknown as Response;
  });
}

function fetchCalls(): FetchArgs[] {
  return (global.fetch as jest.Mock).mock.calls as FetchArgs[];
}

describe('generateBrief', () => {
  beforeEach(() => {
    (global.fetch as jest.Mock).mockReset();
    __resetBriefGenerationFlagForTests();
  });

  it('POSTs to /brief/generate and returns the queued payload', async () => {
    mockFetch(() => ({
      status: 202,
      _body: {
        state: 'queued',
        pr_number: 42,
        head_sha: 'sha123',
        estimated_completion_seconds: 180,
      },
    }));
    const resp = await generateBrief(42);
    expect(resp.state).toBe('queued');
    expect(resp.estimated_completion_seconds).toBe(180);
    const [url, init] = fetchCalls()[0];
    expect(url).toContain('/api/v1/review-queue/prs/42/brief/generate');
    expect((init as RequestInit).method).toBe('POST');
    expect(getBriefGenerationFlag()).toBe(true);
  });

  it('forwards options.force to the backend body', async () => {
    mockFetch(() => ({ status: 202, _body: { state: 'queued' } }));
    await generateBrief(7, { force: true });
    const [, init] = fetchCalls()[0];
    expect(JSON.parse((init as RequestInit).body as string)).toMatchObject({ force: true });
  });

  it('tags 503 with feature-flag metadata and caches the flag as off', async () => {
    mockFetch(() => ({ status: 503, _body: { error: 'disabled' } }));
    await expect(generateBrief(1)).rejects.toMatchObject({ status: 503 });
    expect(getBriefGenerationFlag()).toBe(false);
  });

  it('returns 409 payload without throwing (dedupe path)', async () => {
    mockFetch(() => ({ status: 409, _body: { state: 'running', message: 'already running' } }));
    const resp = await generateBrief(1);
    expect(resp.state).toBe('running');
  });

  it('throws with API error detail on other non-2xx responses', async () => {
    mockFetch(() => ({ status: 500, _body: { error: 'boom' } }));
    await expect(generateBrief(1)).rejects.toThrow('boom');
  });
});

describe('getBriefState', () => {
  beforeEach(() => {
    (global.fetch as jest.Mock).mockReset();
    __resetBriefGenerationFlagForTests();
  });

  it('GETs /brief/state and normalizes the payload to a snapshot', async () => {
    mockFetch(() => ({
      status: 200,
      _body: {
        state: 'running',
        head_sha: 'sha987',
        current_phase: 'findings',
        cost_usd_so_far: 0.07,
        started_at: new Date(Date.now() - 5000).toISOString(),
        panel_models: ['claude-opus-4-8', 'gpt-4.1'],
        roles_complete: 2,
        roles_total: 8,
      },
    }));
    const snap = await getBriefState(17);
    expect(snap.state).toBe('running');
    expect(snap.phase).toBe('findings');
    expect(snap.costUsdSoFar).toBeCloseTo(0.07);
    expect(snap.panelModels).toEqual(['claude-opus-4-8', 'gpt-4.1']);
    expect(snap.rolesComplete).toBe(2);
    expect(snap.rolesTotal).toBe(8);
    expect(snap.elapsedSeconds).toBeGreaterThanOrEqual(4);
  });

  it('maps 503 to an absent snapshot and caches the flag as off', async () => {
    mockFetch(() => ({ status: 503 }));
    const snap = await getBriefState(42);
    expect(snap.state).toBe('absent');
    expect(getBriefGenerationFlag()).toBe(false);
  });

  it('maps 404 to an absent snapshot', async () => {
    mockFetch(() => ({ status: 404 }));
    const snap = await getBriefState(42);
    expect(snap.state).toBe('absent');
  });

  it('throws on 500', async () => {
    mockFetch(() => ({ status: 500, _body: { error: 'broken' } }));
    await expect(getBriefState(42)).rejects.toThrow('broken');
  });
});

describe('cancelBriefGeneration', () => {
  beforeEach(() => {
    (global.fetch as jest.Mock).mockReset();
    __resetBriefGenerationFlagForTests();
  });

  it('DELETEs /brief/generate', async () => {
    mockFetch(() => ({ status: 200, _body: { cancelled: true } }));
    await cancelBriefGeneration(9);
    const [url, init] = fetchCalls()[0];
    expect(url).toContain('/api/v1/review-queue/prs/9/brief/generate');
    expect((init as RequestInit).method).toBe('DELETE');
  });

  it('swallows 503 silently', async () => {
    mockFetch(() => ({ status: 503 }));
    await expect(cancelBriefGeneration(1)).resolves.toBeUndefined();
    expect(getBriefGenerationFlag()).toBe(false);
  });

  it('throws on 500', async () => {
    mockFetch(() => ({ status: 500 }));
    await expect(cancelBriefGeneration(1)).rejects.toThrow();
  });
});

describe('useBriefState polling', () => {
  beforeEach(() => {
    (global.fetch as jest.Mock).mockReset();
    __resetBriefGenerationFlagForTests();
    jest.useFakeTimers({ doNotFake: [] });
  });

  afterEach(() => {
    jest.useRealTimers();
  });

  async function flushMicrotasks() {
    await Promise.resolve();
    await Promise.resolve();
  }

  it('does not fetch when enabled is false', async () => {
    const { result } = renderHook(() => useBriefState(42, { enabled: false, pollIntervalMs: 50 }));
    await flushMicrotasks();
    expect(fetchCalls()).toHaveLength(0);
    expect(result.current.snapshot).toBeNull();
  });

  it('fetches once then stops polling when state is ready', async () => {
    mockFetch(() => ({ status: 200, _body: { state: 'ready', head_sha: 'sha' } }));
    const { result } = renderHook(() => useBriefState(42, { pollIntervalMs: 50 }));
    await waitFor(() => expect(result.current.snapshot?.state).toBe('ready'));
    const initial = fetchCalls().length;
    // Advance time — should NOT trigger extra fetches.
    await act(async () => {
      jest.advanceTimersByTime(200);
      await flushMicrotasks();
    });
    expect(fetchCalls().length).toBe(initial);
  });

  it('polls while state is queued/running then stops on ready', async () => {
    const states = ['queued', 'running', 'ready'];
    let i = 0;
    mockFetch(() => ({ status: 200, _body: { state: states[Math.min(i++, states.length - 1)] } }));

    const { result } = renderHook(() => useBriefState(42, { pollIntervalMs: 50 }));
    // First fetch → queued
    await waitFor(() => expect(result.current.snapshot?.state).toBe('queued'));

    // Advance past the first poll tick → running
    await act(async () => {
      jest.advanceTimersByTime(60);
      await flushMicrotasks();
    });
    await waitFor(() => expect(result.current.snapshot?.state).toBe('running'));

    // Advance past the second poll tick → ready
    await act(async () => {
      jest.advanceTimersByTime(60);
      await flushMicrotasks();
    });
    await waitFor(() => expect(result.current.snapshot?.state).toBe('ready'));

    const callsAtReady = fetchCalls().length;

    // No further polling after ready.
    await act(async () => {
      jest.advanceTimersByTime(200);
      await flushMicrotasks();
    });
    expect(fetchCalls().length).toBe(callsAtReady);
  });

  it('surfaces feature-disabled when backend returns 503', async () => {
    mockFetch(() => ({ status: 503 }));
    const { result } = renderHook(() => useBriefState(42, { pollIntervalMs: 50 }));
    await waitFor(() => expect(result.current.snapshot?.state).toBe('absent'));
    expect(result.current.featureDisabled).toBe(true);
  });
});
