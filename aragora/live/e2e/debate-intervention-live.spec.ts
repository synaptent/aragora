import { test, expect } from './fixtures';

test.describe('Live Debate Intervention', () => {
  test('opens intervention panel and issues pause/inject API calls', async ({
    page,
    aragoraPage,
  }) => {
    const debateId = 'adhoc_intervention_e2e';

    await page.addInitScript((id: string) => {
      const NativeWebSocket = window.WebSocket;

      class MockDebateWebSocket {
        static CONNECTING = 0;
        static OPEN = 1;
        static CLOSING = 2;
        static CLOSED = 3;

        onopen: ((event: Event) => void) | null = null;
        onclose: ((event: Event) => void) | null = null;
        onmessage: ((event: MessageEvent) => void) | null = null;
        onerror: ((event: Event) => void) | null = null;
        readyState = MockDebateWebSocket.CONNECTING;
        binaryType = 'blob';
        readonly url: string;

        constructor(url: string) {
          this.url = url;
          setTimeout(() => {
            this.readyState = MockDebateWebSocket.OPEN;
            this.onopen?.(new Event('open'));
          }, 0);
        }

        send(payload: string): void {
          let parsed: { type?: string } = {};
          try {
            parsed = JSON.parse(payload) as { type?: string };
          } catch {
            parsed = {};
          }
          if (parsed.type === 'subscribe') {
            this.emit({
              type: 'debate_start',
              loop_id: id,
              data: { debate_id: id, task: 'Intervention E2E debate', agents: ['claude', 'gpt-5'] },
            });
            this.emit({ type: 'round_start', loop_id: id, round: 1, data: { round: 1 } });
            this.emit({
              type: 'agent_message',
              loop_id: id,
              agent: 'claude',
              round: 1,
              data: {
                agent: 'claude',
                role: 'proposer',
                content: 'Initial live argument.',
                round: 1,
              },
            });
          }
        }

        close(): void {
          this.readyState = MockDebateWebSocket.CLOSED;
          this.onclose?.(new Event('close'));
        }

        emit(payload: unknown): void {
          this.onmessage?.({ data: JSON.stringify(payload) } as MessageEvent);
        }
      }

      function WrappedWebSocket(url: string | URL, protocols?: string | string[]): WebSocket {
        const normalizedUrl = typeof url === 'string' ? url : url.toString();
        // Debate stream uses the base WS endpoint (e.g. ws://host/ws).
        if (/\/ws\/?$/.test(normalizedUrl)) {
          return new MockDebateWebSocket(normalizedUrl) as unknown as WebSocket;
        }
        return protocols !== undefined
          ? new NativeWebSocket(url, protocols)
          : new NativeWebSocket(url);
      }

      Object.assign(WrappedWebSocket, {
        CONNECTING: NativeWebSocket.CONNECTING,
        OPEN: NativeWebSocket.OPEN,
        CLOSING: NativeWebSocket.CLOSING,
        CLOSED: NativeWebSocket.CLOSED,
      });
      WrappedWebSocket.prototype = NativeWebSocket.prototype;

      Object.defineProperty(window, 'WebSocket', {
        configurable: true,
        writable: true,
        value: WrappedWebSocket,
      });
    }, debateId);

    await page.route(`**/api/v1/debates/${debateId}`, async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ id: debateId, status: 'in_progress' }),
      });
    });
    await page.route(`**/api/v1/debates/${debateId}/inject-evidence`, async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ ok: true }),
      });
    });
    await page.route(`**/api/v1/debates/${debateId}/pause`, async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ ok: true }),
      });
    });

    await page.goto(`/debates/${debateId}`, { waitUntil: 'domcontentloaded' });
    await aragoraPage.dismissAllOverlays();

    const interveneToggle = page.getByRole('button', { name: '[INTERVENE]' });
    await expect(interveneToggle).toBeVisible({ timeout: 10000 });
    await interveneToggle.click();

    await expect(page.getByText('Intervention Controls')).toBeVisible({ timeout: 5000 });

    const injectReq = page.waitForRequest(
      (req) =>
        req.url().includes(`/api/v1/debates/${debateId}/inject-evidence`) &&
        req.method() === 'POST',
    );
    await page
      .getByPlaceholder('Add your argument to the debate...')
      .fill('Test intervention payload');
    await page.getByRole('button', { name: /INJECT ARGUMENT/ }).click();
    await injectReq;

    const pauseReq = page.waitForRequest(
      (req) => req.url().includes(`/api/v1/debates/${debateId}/pause`) && req.method() === 'POST',
    );
    await page.getByRole('button', { name: /PAUSE/ }).click();
    await pauseReq;

    // Toasts auto-dismiss quickly; assert stable intervention history/state instead.
    await expect(page.getByText('Test intervention payload')).toBeVisible({ timeout: 5000 });
    await expect(page.getByText('Paused debate')).toBeVisible({ timeout: 5000 });
    await expect(page.getByRole('button', { name: 'RESUME' })).toBeVisible({ timeout: 5000 });
  });
});
