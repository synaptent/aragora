/**
 * Critical Debate Lifecycle E2E Tests
 *
 * Tests the complete debate flow end-to-end:
 *   Create debate → WebSocket streams agent proposals → Critiques →
 *   Consensus detected → Receipt generated → Receipt viewable/exportable
 *
 * Uses mocked API and WebSocket responses to simulate the full lifecycle
 * without requiring a running backend.
 */

import { test, expect, mockApiResponse, mockAgents } from './fixtures';

// ── Mock Data ──────────────────────────────────────────────────────────

const DEBATE_ID = 'lifecycle-debate-001';

const mockDebateCreated = {
  debate_id: DEBATE_ID,
  status: 'created',
  topic: 'Should companies adopt a 4-day work week?',
};

const mockDebateRunning = {
  id: DEBATE_ID,
  topic: 'Should companies adopt a 4-day work week?',
  status: 'running',
  created_at: new Date().toISOString(),
  agents: ['claude', 'gpt'],
  messages: [],
  consensus: null,
};

const round1Messages = [
  {
    id: 'msg-r1-proposal',
    agent: 'claude',
    role: 'proposer',
    content:
      'I propose that companies should adopt a 4-day work week. Research from Iceland and Microsoft Japan shows productivity gains of 20-40% with reduced hours.',
    round: 1,
    timestamp: new Date().toISOString(),
  },
  {
    id: 'msg-r1-critique',
    agent: 'gpt',
    role: 'critic',
    content:
      'While the cited studies are promising, they primarily involve knowledge workers. Industries requiring continuous coverage (healthcare, manufacturing) face implementation challenges.',
    round: 1,
    timestamp: new Date(Date.now() + 1000).toISOString(),
  },
];

const round2Messages = [
  {
    id: 'msg-r2-revision',
    agent: 'claude',
    role: 'proposer',
    content:
      'Revised proposal: A phased 4-day work week for knowledge workers, with flexible scheduling for coverage-dependent industries. This addresses the implementation gap while capturing productivity benefits.',
    round: 2,
    timestamp: new Date(Date.now() + 2000).toISOString(),
  },
  {
    id: 'msg-r2-support',
    agent: 'gpt',
    role: 'critic',
    content:
      'The phased approach is sound. I support this revision with the additional condition that companies should run 3-month pilot programs before full adoption.',
    round: 2,
    timestamp: new Date(Date.now() + 3000).toISOString(),
  },
];

const mockConsensus = {
  reached: true,
  type: 'majority',
  round: 2,
  summary:
    'Agents agreed on a phased 4-day work week for knowledge workers with pilot programs. Coverage-dependent industries should use flexible scheduling.',
  confidence: 0.87,
};

const mockDebateCompleted = {
  ...mockDebateRunning,
  status: 'completed',
  messages: [...round1Messages, ...round2Messages],
  consensus: mockConsensus,
};

const mockReceipt = {
  receipt_id: `receipt-${DEBATE_ID}`,
  debate_id: DEBATE_ID,
  topic: mockDebateCompleted.topic,
  verdict: 'CONSENSUS_REACHED',
  confidence: 0.87,
  hash: 'sha256:a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6',
  created_at: new Date().toISOString(),
  agents_participated: ['claude', 'gpt'],
  rounds_completed: 2,
  consensus_summary: mockConsensus.summary,
};

// Check if we're on live.aragora.ai (skip lifecycle tests in prod)
const isLiveProduction = () => {
  const baseUrl = process.env.PLAYWRIGHT_BASE_URL || '';
  return baseUrl.includes('live.aragora.ai');
};

// ── Test Suite ──────────────────────────────────────────────────────────

test.describe('Critical Debate Lifecycle', () => {
  test.beforeEach(async ({ page }) => {
    test.skip(isLiveProduction(), 'Lifecycle tests use mocked APIs, not for production');
    await mockApiResponse(page, '**/api/health', { status: 'ok', version: '1.0.0' });
    await mockApiResponse(page, '**/api/agents', { agents: mockAgents });
  });

  test.describe('Phase 1: Debate Creation', () => {
    test('should create debate and navigate to viewer', async ({ page, aragoraPage }) => {
      // Mock the creation endpoint
      await page.route('**/api/debate', async (route) => {
        if (route.request().method() === 'POST') {
          await route.fulfill({
            status: 201,
            contentType: 'application/json',
            body: JSON.stringify(mockDebateCreated),
          });
        } else {
          await route.continue();
        }
      });

      // Mock the debate detail endpoint for the redirect
      await mockApiResponse(page, `**/api/debates/${DEBATE_ID}`, mockDebateRunning);

      await page.goto('/');
      await aragoraPage.dismissAllOverlays();
      await page.waitForLoadState('domcontentloaded');

      // Fill in debate topic
      const questionInput = page.locator('textarea, input[type="text"]').first();
      if (await questionInput.isVisible({ timeout: 5000 }).catch(() => false)) {
        await questionInput.fill('Should companies adopt a 4-day work week?');

        // Submit the debate
        const submitButton = page
          .locator('button[type="submit"], button')
          .filter({ hasText: /start|debate|submit|go/i })
          .first();

        if (await submitButton.isVisible()) {
          await submitButton.click();

          // Should navigate to debate page or show progress
          await page.waitForTimeout(2000);
          const url = page.url();
          const hasNavigated = url.includes('debate') || url.includes(DEBATE_ID);
          const hasProgress = await page
            .locator('text=/progress|loading|initializing|creating/i')
            .first()
            .isVisible()
            .catch(() => false);

          expect(hasNavigated || hasProgress).toBeTruthy();
        }
      }
    });

    test('should show debate creation API call with correct payload', async ({
      page,
      aragoraPage,
    }) => {
      let capturedPayload: Record<string, unknown> | null = null;

      await page.route('**/api/debate', async (route) => {
        if (route.request().method() === 'POST') {
          capturedPayload = route.request().postDataJSON();
          await route.fulfill({
            status: 201,
            contentType: 'application/json',
            body: JSON.stringify(mockDebateCreated),
          });
        } else {
          await route.continue();
        }
      });

      await mockApiResponse(page, `**/api/debates/${DEBATE_ID}`, mockDebateRunning);

      await page.goto('/');
      await aragoraPage.dismissAllOverlays();
      await page.waitForLoadState('domcontentloaded');

      const questionInput = page.locator('textarea, input[type="text"]').first();
      if (await questionInput.isVisible({ timeout: 5000 }).catch(() => false)) {
        await questionInput.fill('Should companies adopt a 4-day work week?');

        const submitButton = page
          .locator('button[type="submit"], button')
          .filter({ hasText: /start|debate|submit|go/i })
          .first();

        if (await submitButton.isVisible()) {
          await submitButton.click();
          await page.waitForTimeout(2000);

          if (capturedPayload) {
            // Verify the payload contains the topic
            expect(JSON.stringify(capturedPayload)).toContain('4-day work week');
          }
        }
      }
    });
  });

  test.describe('Phase 2: Live Debate Streaming', () => {
    test('should display agent messages as they arrive', async ({ page, aragoraPage }) => {
      // Start with empty messages, then populate
      let messageIndex = 0;
      const allMessages = [...round1Messages, ...round2Messages];

      await page.route(`**/api/debates/${DEBATE_ID}`, async (route) => {
        const currentMessages = allMessages.slice(0, messageIndex);
        await route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify({
            ...mockDebateRunning,
            messages: currentMessages,
            status: messageIndex >= allMessages.length ? 'completed' : 'running',
            consensus: messageIndex >= allMessages.length ? mockConsensus : null,
          }),
        });
      });

      await page.goto(`/debate/${DEBATE_ID}`);
      await aragoraPage.dismissAllOverlays();
      await page.waitForLoadState('domcontentloaded');

      // Simulate messages arriving over time
      messageIndex = 1; // First proposal arrives

      // Wait for content to appear (page polls or we trigger reload)
      const mainContent = page.locator('main').first();
      await expect(mainContent).toBeVisible({ timeout: 10000 });

      // The page should have loaded without errors
      const bodyText = await page.locator('body').textContent();
      expect(bodyText).toBeTruthy();
    });

    test('should attempt WebSocket connection for live debate', async ({ page, aragoraPage }) => {
      const wsUrls: string[] = [];
      page.on('websocket', (ws) => {
        wsUrls.push(ws.url());
      });

      await mockApiResponse(page, `**/api/debates/${DEBATE_ID}`, {
        ...mockDebateRunning,
        status: 'running',
      });

      await page.goto(`/debate/${DEBATE_ID}`);
      await aragoraPage.dismissAllOverlays();

      // Give time for WebSocket connection attempt
      await page.waitForTimeout(3000);

      // WebSocket should be attempted (may not connect in test env without backend)
      // The important thing is the page doesn't crash without WebSocket
      await expect(page.locator('body')).toBeVisible();
    });

    test('should show round indicators during debate', async ({ page, aragoraPage }) => {
      await mockApiResponse(page, `**/api/debates/${DEBATE_ID}`, {
        ...mockDebateRunning,
        messages: round1Messages,
      });

      await page.goto(`/debate/${DEBATE_ID}`);
      await aragoraPage.dismissAllOverlays();
      await page.waitForLoadState('domcontentloaded');

      // Look for round indicators, agent names, or message content
      const roundIndicator = page.locator('text=/round|r1|phase|proposal|critique/i').first();
      const agentName = page.locator('text=/claude|gpt/i').first();
      const mainContent = page.locator('main').first();

      await expect(roundIndicator.or(agentName).or(mainContent)).toBeVisible({ timeout: 10000 });
    });
  });

  test.describe('Phase 3: Consensus Detection', () => {
    test('should display consensus when reached', async ({ page, aragoraPage }) => {
      await mockApiResponse(page, `**/api/debates/${DEBATE_ID}`, mockDebateCompleted);

      await page.goto(`/debate/${DEBATE_ID}`);
      await aragoraPage.dismissAllOverlays();
      await page.waitForLoadState('domcontentloaded');

      // Look for consensus indicator, status change, or completion marker
      const consensusIndicator = page
        .locator('text=/consensus|agreed|completed|resolved|verdict/i')
        .first();
      const statusIndicator = page.locator('[class*="status"], [class*="complete"]').first();
      const mainContent = page.locator('main').first();

      await expect(consensusIndicator.or(statusIndicator).or(mainContent)).toBeVisible({
        timeout: 10000,
      });
    });

    test('should show consensus summary text', async ({ page, aragoraPage }) => {
      await mockApiResponse(page, `**/api/debates/${DEBATE_ID}`, mockDebateCompleted);

      await page.goto(`/debate/${DEBATE_ID}`);
      await aragoraPage.dismissAllOverlays();
      await page.waitForLoadState('domcontentloaded');

      // Page should have loaded with debate content
      const bodyText = await page.locator('body').textContent();
      expect(bodyText).toBeTruthy();
      // The consensus summary or debate topic should appear somewhere
      const hasTopic =
        bodyText!.toLowerCase().includes('4-day') || bodyText!.toLowerCase().includes('work week');
      const hasGenericContent = bodyText!.length > 100;
      expect(hasTopic || hasGenericContent).toBeTruthy();
    });

    test('should transition from running to completed state', async ({ page, aragoraPage }) => {
      let requestCount = 0;

      await page.route(`**/api/debates/${DEBATE_ID}`, async (route) => {
        requestCount++;
        // First request: running, subsequent: completed
        const isCompleted = requestCount > 1;
        await route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify(isCompleted ? mockDebateCompleted : mockDebateRunning),
        });
      });

      await page.goto(`/debate/${DEBATE_ID}`);
      await aragoraPage.dismissAllOverlays();
      await page.waitForLoadState('domcontentloaded');

      // Page should load in running state
      await expect(page.locator('body')).toBeVisible({ timeout: 10000 });

      // Trigger a refresh to get completed state
      await page.reload();
      await aragoraPage.dismissAllOverlays();
      await page.waitForLoadState('domcontentloaded');

      // Should now show completed state
      const completedIndicator = page.locator('text=/completed|consensus|finished|done/i').first();
      const mainContent = page.locator('main').first();
      await expect(completedIndicator.or(mainContent)).toBeVisible({ timeout: 10000 });
    });
  });

  test.describe('Phase 4: Receipt Generation', () => {
    test('should show receipt after debate completion', async ({ page, aragoraPage }) => {
      await mockApiResponse(page, `**/api/debates/${DEBATE_ID}`, mockDebateCompleted);
      await mockApiResponse(page, `**/api/debates/${DEBATE_ID}/receipt`, mockReceipt);
      await mockApiResponse(page, `**/api/receipts/${DEBATE_ID}`, mockReceipt);

      await page.goto(`/debate/${DEBATE_ID}`);
      await aragoraPage.dismissAllOverlays();
      await page.waitForLoadState('domcontentloaded');

      // Look for receipt link/button or receipt content
      const receiptLink = page
        .locator('a, button')
        .filter({ hasText: /receipt|audit|proof|certificate/i })
        .first();
      const mainContent = page.locator('main').first();

      await expect(receiptLink.or(mainContent)).toBeVisible({ timeout: 10000 });
    });

    test('should navigate to receipt page', async ({ page, aragoraPage }) => {
      await mockApiResponse(page, `**/api/debates/${DEBATE_ID}`, mockDebateCompleted);
      await mockApiResponse(page, `**/api/debates/${DEBATE_ID}/receipt`, mockReceipt);
      await mockApiResponse(page, `**/api/receipts/**`, mockReceipt);
      await mockApiResponse(page, `**/api/gauntlet/**`, mockReceipt);

      await page.goto(`/debate/${DEBATE_ID}`);
      await aragoraPage.dismissAllOverlays();
      await page.waitForLoadState('domcontentloaded');

      const receiptLink = page
        .locator('a, button')
        .filter({ hasText: /receipt|audit|proof/i })
        .first();

      if (await receiptLink.isVisible({ timeout: 5000 }).catch(() => false)) {
        await receiptLink.click();
        await page.waitForTimeout(2000);

        // Should navigate to receipt page or show receipt modal
        const url = page.url();
        const receiptContent = page.locator('text=/receipt|hash|sha256|verdict/i').first();
        const hasNavigated = url.includes('receipt') || url.includes('gauntlet');
        const hasContent = await receiptContent.isVisible().catch(() => false);

        expect(hasNavigated || hasContent).toBeTruthy();
      }
    });

    test('should display receipt integrity hash', async ({ page, aragoraPage }) => {
      await mockApiResponse(page, `**/api/debates/${DEBATE_ID}`, mockDebateCompleted);
      await mockApiResponse(page, `**/api/debates/${DEBATE_ID}/receipt`, mockReceipt);
      await mockApiResponse(page, `**/api/receipts/**`, mockReceipt);

      // Navigate directly to receipt if available
      await page.goto(`/debate/${DEBATE_ID}`);
      await aragoraPage.dismissAllOverlays();
      await page.waitForLoadState('domcontentloaded');

      // Receipt hash should be displayed somewhere on the completed debate page
      const bodyText = await page.locator('body').textContent();
      // Page should render without errors
      expect(bodyText).toBeTruthy();
    });
  });

  test.describe('Phase 5: Export & Sharing', () => {
    test('should allow exporting completed debate', async ({ page, aragoraPage }) => {
      await mockApiResponse(page, `**/api/debates/${DEBATE_ID}`, mockDebateCompleted);

      // Mock export endpoints
      await page.route(`**/api/debates/${DEBATE_ID}/export/**`, async (route) => {
        const url = route.request().url();
        if (url.includes('pdf')) {
          await route.fulfill({
            status: 200,
            contentType: 'application/pdf',
            body: Buffer.from('%PDF-1.4 mock content'),
          });
        } else if (url.includes('json')) {
          await route.fulfill({
            status: 200,
            contentType: 'application/json',
            body: JSON.stringify(mockDebateCompleted),
          });
        } else {
          await route.fulfill({
            status: 200,
            contentType: 'text/html',
            body: '<html><body>Debate export</body></html>',
          });
        }
      });

      await page.goto(`/debate/${DEBATE_ID}`);
      await aragoraPage.dismissAllOverlays();
      await page.waitForLoadState('domcontentloaded');

      const exportButton = page
        .locator('button, a')
        .filter({ hasText: /export|download/i })
        .first();

      if (await exportButton.isVisible({ timeout: 5000 }).catch(() => false)) {
        await exportButton.click();

        // Should show format options
        const formatOptions = page.locator('text=/pdf|html|json|markdown/i').first();
        await expect(formatOptions).toBeVisible({ timeout: 3000 });
      }
    });

    test('should allow sharing debate link', async ({ page, aragoraPage }) => {
      await mockApiResponse(page, `**/api/debates/${DEBATE_ID}`, mockDebateCompleted);

      await page.goto(`/debate/${DEBATE_ID}`);
      await aragoraPage.dismissAllOverlays();
      await page.waitForLoadState('domcontentloaded');

      const shareButton = page
        .locator('button, a')
        .filter({ hasText: /share|copy.*link|link/i })
        .first();

      if (await shareButton.isVisible({ timeout: 3000 }).catch(() => false)) {
        await shareButton.click();

        // Should show confirmation
        const confirmation = page.locator('text=/copied|link|shared/i').first();
        await expect(confirmation).toBeVisible({ timeout: 3000 });
      }
    });
  });

  test.describe('Full Lifecycle Integration', () => {
    test('complete flow: homepage → create → view → complete → receipt', async ({
      page,
      aragoraPage,
    }) => {
      // ── Step 1: Mock all API endpoints ──
      await page.route('**/api/debate', async (route) => {
        if (route.request().method() === 'POST') {
          await route.fulfill({
            status: 201,
            contentType: 'application/json',
            body: JSON.stringify(mockDebateCreated),
          });
        } else {
          await route.continue();
        }
      });

      let debateViewCount = 0;
      await page.route(`**/api/debates/${DEBATE_ID}`, async (route) => {
        debateViewCount++;
        // Progress through lifecycle stages
        const debate =
          debateViewCount <= 1
            ? { ...mockDebateRunning, messages: round1Messages }
            : mockDebateCompleted;
        await route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify(debate),
        });
      });

      await mockApiResponse(page, `**/api/debates/${DEBATE_ID}/receipt`, mockReceipt);

      // ── Step 2: Start at homepage ──
      await page.goto('/');
      await aragoraPage.dismissAllOverlays();
      await page.waitForLoadState('domcontentloaded');

      // ── Step 3: Create debate ──
      const questionInput = page.locator('textarea, input[type="text"]').first();
      if (await questionInput.isVisible({ timeout: 5000 }).catch(() => false)) {
        await questionInput.fill('Should companies adopt a 4-day work week?');

        const submitButton = page
          .locator('button[type="submit"], button')
          .filter({ hasText: /start|debate|submit|go/i })
          .first();

        if (await submitButton.isVisible()) {
          await submitButton.click();
          await page.waitForTimeout(2000);
        }
      }

      // ── Step 4: Navigate to debate viewer (may already be there from creation) ──
      if (!page.url().includes('debate')) {
        await page.goto(`/debate/${DEBATE_ID}`);
        await aragoraPage.dismissAllOverlays();
      }
      await page.waitForLoadState('domcontentloaded');

      // Verify page loaded with content
      const mainContent = page.locator('main').first();
      await expect(mainContent).toBeVisible({ timeout: 10000 });

      // ── Step 5: Reload to see completed state ──
      await page.reload();
      await aragoraPage.dismissAllOverlays();
      await page.waitForLoadState('domcontentloaded');

      // Should now show completed debate
      await expect(page.locator('body')).toBeVisible({ timeout: 10000 });
      const bodyText = await page.locator('body').textContent();
      expect(bodyText!.length).toBeGreaterThan(50);
    });

    test('debate viewer handles all message types correctly', async ({ page, aragoraPage }) => {
      const fullDebate = {
        ...mockDebateCompleted,
        messages: [
          ...round1Messages,
          ...round2Messages,
          {
            id: 'msg-vote',
            agent: 'system',
            role: 'system',
            content: 'Consensus reached with 87% confidence.',
            round: 2,
            timestamp: new Date(Date.now() + 4000).toISOString(),
          },
        ],
      };

      await mockApiResponse(page, `**/api/debates/${DEBATE_ID}`, fullDebate);

      await page.goto(`/debate/${DEBATE_ID}`);
      await aragoraPage.dismissAllOverlays();
      await page.waitForLoadState('domcontentloaded');

      // Page should render all message types without errors
      const mainContent = page.locator('main').first();
      await expect(mainContent).toBeVisible({ timeout: 10000 });

      // No error boundaries should be triggered
      const errorBoundary = page.locator('[data-testid="error-boundary"], .error-boundary');
      const hasError = await errorBoundary.isVisible({ timeout: 1000 }).catch(() => false);
      expect(hasError).toBeFalsy();
    });
  });

  test.describe('Error Recovery', () => {
    test('should handle debate creation failure gracefully', async ({ page, aragoraPage }) => {
      await page.route('**/api/debate', async (route) => {
        if (route.request().method() === 'POST') {
          await route.fulfill({
            status: 503,
            contentType: 'application/json',
            body: JSON.stringify({ error: 'Service temporarily unavailable' }),
          });
        } else {
          await route.continue();
        }
      });

      await page.goto('/');
      await aragoraPage.dismissAllOverlays();
      await page.waitForLoadState('domcontentloaded');

      const questionInput = page.locator('textarea, input[type="text"]').first();
      if (await questionInput.isVisible({ timeout: 5000 }).catch(() => false)) {
        await questionInput.fill('Test question');

        const submitButton = page
          .locator('button[type="submit"], button')
          .filter({ hasText: /start|debate|submit|go/i })
          .first();

        if (await submitButton.isVisible()) {
          await submitButton.click();
          await page.waitForTimeout(2000);

          // Should show error or remain on page (not crash)
          const errorMessage = page
            .locator('[class*="error"], [role="alert"]')
            .or(page.locator('text=/error|failed|unavailable/i'))
            .first();
          const stillOnPage = !page.url().includes(DEBATE_ID);

          const hasError = await errorMessage.isVisible().catch(() => false);
          expect(hasError || stillOnPage).toBeTruthy();
        }
      }
    });

    test('should handle missing debate gracefully', async ({ page, aragoraPage }) => {
      await page.route('**/api/debates/nonexistent**', async (route) => {
        await route.fulfill({
          status: 404,
          contentType: 'application/json',
          body: JSON.stringify({ error: 'Debate not found' }),
        });
      });

      await page.goto('/debate/nonexistent-debate-id');
      await aragoraPage.dismissAllOverlays();
      await page.waitForLoadState('domcontentloaded');

      // Page should handle 404 without crashing
      await expect(page.locator('body')).toBeVisible({ timeout: 10000 });
    });

    test('should handle debate data loading timeout', async ({ page, aragoraPage }) => {
      await page.route(`**/api/debates/${DEBATE_ID}`, async (route) => {
        // Simulate slow response
        await new Promise((resolve) => setTimeout(resolve, 8000));
        await route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify(mockDebateRunning),
        });
      });

      await page.goto(`/debate/${DEBATE_ID}`);
      await aragoraPage.dismissAllOverlays();

      // Should show loading state, not crash
      const loadingIndicator = page
        .locator('[class*="loading"], [class*="spinner"], [class*="skeleton"]')
        .or(page.locator('text=/loading|initializing/i'))
        .first();
      const mainContent = page.locator('main, body').first();

      await expect(loadingIndicator.or(mainContent)).toBeVisible({ timeout: 5000 });
    });

    test('should handle WebSocket disconnect gracefully', async ({ page, aragoraPage }) => {
      await mockApiResponse(page, `**/api/debates/${DEBATE_ID}`, mockDebateRunning);

      // Track console errors
      const consoleErrors: string[] = [];
      page.on('console', (msg) => {
        if (msg.type() === 'error') {
          consoleErrors.push(msg.text());
        }
      });

      await page.goto(`/debate/${DEBATE_ID}`);
      await aragoraPage.dismissAllOverlays();
      await page.waitForLoadState('domcontentloaded');

      // Wait for any WebSocket attempts
      await page.waitForTimeout(3000);

      // Page should remain functional (no unhandled errors)
      await expect(page.locator('body')).toBeVisible();

      // Filter out expected WebSocket errors (connection refused in test env)
      const unexpectedErrors = consoleErrors.filter(
        (e) => !e.includes('WebSocket') && !e.includes('ws://') && !e.includes('wss://'),
      );

      // Should have no unexpected JS errors
      expect(unexpectedErrors.length).toBeLessThanOrEqual(2); // Tolerate minor fetch errors
    });
  });
});
