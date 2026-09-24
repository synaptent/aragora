import { test, expect } from '@playwright/test';

/**
 * Console Error Analysis Tests
 *
 * These tests capture and analyze console errors in production
 * to identify sources of console spam.
 */

test.describe('Console Error Analysis', () => {
  test('should capture console errors on production site', async ({ page }) => {
    const consoleMessages: { type: string; text: string; count: number }[] = [];
    const errorCounts: Record<string, number> = {};

    // Capture all console messages
    page.on('console', (msg) => {
      const text = msg.text();
      const type = msg.type();

      // Count unique error patterns
      const key = `${type}:${text.slice(0, 100)}`;
      errorCounts[key] = (errorCounts[key] || 0) + 1;

      // Only store first occurrence
      if (!consoleMessages.find((m) => m.text.startsWith(text.slice(0, 100)))) {
        consoleMessages.push({ type, text, count: 1 });
      }
    });

    // Also capture network failures
    const networkErrors: string[] = [];
    page.on('requestfailed', (request) => {
      networkErrors.push(`${request.failure()?.errorText}: ${request.url()}`);
    });

    // Navigate to production
    await page.goto('https://aragora.ai', { waitUntil: 'networkidle' });

    // Wait 10 seconds to capture any repeated errors
    await page.waitForTimeout(10000);

    // Log summary
    console.log('\n=== Console Error Summary ===');
    console.log(`Total unique message patterns: ${Object.keys(errorCounts).length}`);

    const sortedErrors = Object.entries(errorCounts)
      .sort((a, b) => b[1] - a[1])
      .slice(0, 20);

    console.log('\nTop 20 most frequent messages:');
    for (const [key, count] of sortedErrors) {
      console.log(`  [${count}x] ${key}`);
    }

    console.log('\n=== Network Errors ===');
    for (const err of networkErrors.slice(0, 10)) {
      console.log(`  ${err}`);
    }

    // Find error-type messages
    const errors = Object.entries(errorCounts).filter(([key]) => key.startsWith('error:'));
    console.log(`\n=== Error-type messages: ${errors.length} ===`);

    // Test passes if less than 100 unique error patterns in 10 seconds
    expect(errors.length).toBeLessThan(100);
  });

  test('should capture errors during OAuth callback flow', async ({ page }) => {
    const consoleMessages: { type: string; text: string; url: string }[] = [];

    page.on('console', (msg) => {
      consoleMessages.push({ type: msg.type(), text: msg.text(), url: page.url() });
    });

    page.on('pageerror', (error) => {
      consoleMessages.push({ type: 'pageerror', text: error.message, url: page.url() });
    });

    // Go to login page
    await page.goto('https://aragora.ai/auth/login', { waitUntil: 'networkidle' });
    await page.waitForTimeout(2000);

    console.log('\n=== Login Page Console Messages ===');
    const loginErrors = consoleMessages.filter((m) => m.type === 'error');
    for (const err of loginErrors) {
      console.log(`  [error] ${err.text.slice(0, 200)}`);
    }

    // Check for OAuth buttons
    const oauthButtons = await page
      .locator('button:has-text("Google"), button:has-text("GitHub"), button:has-text("Microsoft")')
      .count();
    console.log(`\nOAuth buttons found: ${oauthButtons}`);

    // The test passes if login page loads
    expect(loginErrors.length).toBeLessThan(50);
  });

  test('should identify WebSocket connection issues', async ({ page }) => {
    const wsErrors: string[] = [];
    const wsConnections: string[] = [];

    page.on('console', (msg) => {
      const text = msg.text();
      if (
        text.toLowerCase().includes('websocket') ||
        text.toLowerCase().includes('ws://') ||
        text.toLowerCase().includes('wss://')
      ) {
        wsErrors.push(`[${msg.type()}] ${text}`);
      }
    });

    // Monitor WebSocket connections
    page.on('websocket', (ws) => {
      wsConnections.push(`WS opened: ${ws.url()}`);
      ws.on('close', () => {
        wsConnections.push(`WS closed: ${ws.url()}`);
      });
      ws.on('framereceived', () => {});
      ws.on('framesent', () => {});
    });

    await page.goto('https://aragora.ai', { waitUntil: 'networkidle' });
    await page.waitForTimeout(5000);

    console.log('\n=== WebSocket Activity ===');
    for (const conn of wsConnections) {
      console.log(`  ${conn}`);
    }

    console.log('\n=== WebSocket-related Console Messages ===');
    for (const err of wsErrors.slice(0, 20)) {
      console.log(`  ${err}`);
    }
  });

  test('should test authenticated state persistence', async ({ page }) => {
    const apiCalls: { url: string; status: number; method: string }[] = [];

    page.on('response', (response) => {
      const url = response.url();
      if (url.includes('api.aragora.ai') || url.includes('/api/')) {
        apiCalls.push({
          url: url.replace(/https?:\/\/[^\/]+/, ''),
          status: response.status(),
          method: response.request().method(),
        });
      }
    });

    // Simulate logged-in state
    await page.goto('https://aragora.ai', { waitUntil: 'networkidle' });

    // Add fake tokens to localStorage to trigger auth flow
    await page.evaluate(() => {
      localStorage.setItem(
        'aragora_tokens',
        JSON.stringify({
          access_token: 'test-token',
          refresh_token: 'test-refresh',
          expires_at: new Date(Date.now() + 3600000).toISOString(),
        }),
      );
    });

    // Reload to trigger auth check
    await page.reload({ waitUntil: 'networkidle' });
    await page.waitForTimeout(3000);

    console.log('\n=== API Calls Made ===');
    for (const call of apiCalls) {
      console.log(`  [${call.status}] ${call.method} ${call.url}`);
    }

    // Count auth-related failures
    const authFailures = apiCalls.filter(
      (c) =>
        (c.url.includes('/auth/') || c.url.includes('/me')) &&
        (c.status === 401 || c.status === 405 || c.status === 404),
    );

    console.log(`\nAuth-related failures: ${authFailures.length}`);

    // Should not have repeated auth failures
    expect(authFailures.length).toBeLessThan(5);
  });
});
