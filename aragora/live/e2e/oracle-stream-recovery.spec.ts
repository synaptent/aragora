import { test, expect } from './fixtures';

test.describe('Oracle Stream Recovery', () => {
  test('surfaces first-token stall and allows reset recovery', async ({ page, aragoraPage }) => {
    await page.addInitScript(() => {
      const nativeSetTimeout = window.setTimeout.bind(window);
      window.setTimeout = ((handler: TimerHandler, timeout?: number, ...args: unknown[]) => {
        const requested = typeof timeout === 'number' ? timeout : 0;
        const accelerated = requested >= 10000 ? 40 : requested;
        return nativeSetTimeout(handler, accelerated, ...args);
      }) as typeof window.setTimeout;

      class MockOracleWebSocket {
        static CONNECTING = 0;
        static OPEN = 1;
        static CLOSING = 2;
        static CLOSED = 3;

        onopen: ((event: Event) => void) | null = null;
        onclose: ((event: Event) => void) | null = null;
        onmessage: ((event: MessageEvent) => void) | null = null;
        onerror: ((event: Event) => void) | null = null;
        readyState = MockOracleWebSocket.CONNECTING;
        binaryType = 'arraybuffer';
        readonly url: string;

        constructor(url: string) {
          this.url = url;
          nativeSetTimeout(() => {
            this.readyState = MockOracleWebSocket.OPEN;
            this.onopen?.(new Event('open'));
            this.emit({ type: 'connected' });
          }, 0);
        }

        send(payload: string): void {
          let data: { type?: string } | null = null;
          try {
            data = JSON.parse(payload) as { type?: string };
          } catch {
            data = null;
          }
          if (!data) return;
          if (data.type === 'ask') {
            // Intentionally never emit token to force first-token stall.
            this.emit({ type: 'reflex_start' });
          } else if (data.type === 'stop') {
            this.emit({ type: 'pong' });
          }
        }

        close(): void {
          if (this.readyState === MockOracleWebSocket.CLOSED) return;
          this.readyState = MockOracleWebSocket.CLOSED;
          this.onclose?.(new Event('close'));
        }

        emit(payload: unknown): void {
          this.onmessage?.({ data: JSON.stringify(payload) } as MessageEvent);
        }
      }

      Object.defineProperty(window, 'WebSocket', {
        configurable: true,
        writable: true,
        value: MockOracleWebSocket,
      });
    });

    await page.goto('/oracle', { waitUntil: 'domcontentloaded' });
    await aragoraPage.dismissAllOverlays();

    await page.locator('textarea').first().fill('Show me where this strategy fails.');
    await page.getByRole('button', { name: 'SPEAK' }).click();

    const stallBadge = page.getByText('Stall: no first token');
    const resetButton = page.getByRole('button', { name: 'Reset Stream' });

    await expect(stallBadge).toBeVisible({ timeout: 5000 });
    await expect(resetButton).toBeVisible({ timeout: 5000 });

    await resetButton.click();

    await expect(stallBadge).toBeHidden({ timeout: 5000 });
    await expect(resetButton).toBeHidden({ timeout: 5000 });
  });

  test('falls back to batch mode when websocket initialization fails', async ({
    page,
    aragoraPage,
  }) => {
    await page.addInitScript(() => {
      const NativeWebSocket = window.WebSocket;

      function FailingOracleWebSocket(url: string | URL, protocols?: string | string[]): WebSocket {
        const normalizedUrl = typeof url === 'string' ? url : url.toString();
        if (normalizedUrl.includes('/ws/oracle')) {
          throw new Error('ws unavailable');
        }
        return protocols !== undefined
          ? new NativeWebSocket(url, protocols)
          : new NativeWebSocket(url);
      }

      Object.assign(FailingOracleWebSocket, {
        CONNECTING: NativeWebSocket.CONNECTING,
        OPEN: NativeWebSocket.OPEN,
        CLOSING: NativeWebSocket.CLOSING,
        CLOSED: NativeWebSocket.CLOSED,
      });

      FailingOracleWebSocket.prototype = NativeWebSocket.prototype;

      Object.defineProperty(window, 'WebSocket', {
        configurable: true,
        writable: true,
        value: FailingOracleWebSocket,
      });
    });

    await page.route('**/api/v1/playground/debate', async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          id: 'oracle-batch-initial',
          topic: 'test',
          status: 'completed',
          rounds_used: 1,
          consensus_reached: true,
          confidence: 0.77,
          verdict: 'APPROVED',
          duration_seconds: 0.4,
          participants: ['claude', 'gpt'],
          proposals: { claude: 'Initial batch response from claude.' },
          final_answer: 'Initial batch response from claude.',
          receipt_hash: null,
        }),
      });
    });

    await page.route('**/api/v1/playground/debate/live', async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          id: 'oracle-batch-live',
          topic: 'test',
          status: 'completed',
          rounds_used: 2,
          consensus_reached: true,
          confidence: 0.81,
          verdict: 'APPROVED',
          duration_seconds: 1.2,
          participants: ['claude', 'gpt'],
          proposals: {
            claude: 'Tentacle one says risk is manageable.',
            gpt: 'Tentacle two says monitor confidence drift.',
          },
          final_answer: 'Batch fallback synthesis.',
          receipt_hash: null,
        }),
      });
    });

    await page.goto('/oracle', { waitUntil: 'domcontentloaded' });
    await aragoraPage.dismissAllOverlays();

    await expect(page.getByText(/stream:\s*batch fallback/i)).toBeVisible({ timeout: 15000 });

    await page.locator('textarea').first().fill('Give me the strongest objection.');
    await page.getByRole('button', { name: 'SPEAK' }).click();

    await expect(page.getByText(/stream:\s*batch fallback/i)).toBeVisible({ timeout: 8000 });
    await expect(page.getByText('Initial batch response from claude.')).toBeVisible({
      timeout: 8000,
    });
  });
});
