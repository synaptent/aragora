import { test, expect } from '@playwright/test';

/**
 * Auth Flow Debug Tests
 *
 * Detailed tests to identify why auth is failing after OAuth callback
 */

test.describe('Auth Flow Debug', () => {
  test('should complete full OAuth flow and verify session', async ({ page }) => {
    const logs: string[] = [];
    const apiCalls: { url: string; status: number; method: string; body?: string }[] = [];

    // Capture all console messages
    page.on('console', (msg) => {
      const text = msg.text();
      logs.push(`[${msg.type()}] ${text}`);
    });

    // Capture all API responses
    page.on('response', async (response) => {
      const url = response.url();
      if (url.includes('api.aragora.ai') || url.includes('/api/')) {
        let body = '';
        try {
          body = await response.text();
          if (body.length > 200) body = body.slice(0, 200) + '...';
        } catch {}
        apiCalls.push({
          url: url.replace(/https?:\/\/[^\/]+/, ''),
          status: response.status(),
          method: response.request().method(),
          body,
        });
      }
    });

    // Go to login
    await page.goto('https://aragora.ai/auth/login', { waitUntil: 'networkidle' });
    await page.waitForTimeout(2000);

    console.log('\n=== After Login Page Load ===');
    console.log('API calls:', apiCalls.length);
    for (const call of apiCalls) {
      console.log(`  [${call.status}] ${call.method} ${call.url}`);
      if (call.status >= 400) {
        console.log(`    Body: ${call.body}`);
      }
    }

    // Check for OAuth provider buttons
    const googleBtn = page.locator('button:has-text("Google")');
    const githubBtn = page.locator('button:has-text("GitHub")');

    console.log('\nOAuth buttons visible:');
    console.log(`  Google: ${await googleBtn.isVisible()}`);
    console.log(`  GitHub: ${await githubBtn.isVisible()}`);

    // Check localStorage
    const tokens = await page.evaluate(() => {
      return {
        tokens: localStorage.getItem('aragora_tokens'),
        user: localStorage.getItem('aragora_user'),
      };
    });
    console.log('\nLocalStorage state:');
    console.log(`  tokens: ${tokens.tokens ? 'present' : 'empty'}`);
    console.log(`  user: ${tokens.user ? 'present' : 'empty'}`);

    // Check for any error messages on page
    const errorText = await page.locator('[class*="error"], [role="alert"]').allTextContents();
    if (errorText.length > 0) {
      console.log('\nError messages on page:');
      for (const err of errorText) {
        console.log(`  ${err}`);
      }
    }

    // Count console errors
    const errors = logs.filter((l) => l.startsWith('[error]'));
    console.log(`\nConsole errors: ${errors.length}`);
    for (const err of errors.slice(0, 10)) {
      console.log(`  ${err.slice(0, 200)}`);
    }
  });

  test('should simulate OAuth callback with real-like tokens', async ({ page }) => {
    const logs: string[] = [];
    const apiCalls: { url: string; status: number; method: string }[] = [];

    page.on('console', (msg) => {
      logs.push(`[${msg.type()}] ${msg.text()}`);
    });

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

    // Go directly to callback with fake tokens (will fail but shows the flow)
    // SECURITY: Tokens should be in URL fragment (#) not query params (?)
    const fakeToken =
      'eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiJ0ZXN0LXVzZXItaWQiLCJlbWFpbCI6InRlc3RAZXhhbXBsZS5jb20ifQ.fake';
    await page.goto(
      `https://aragora.ai/auth/callback/#access_token=${fakeToken}&refresh_token=refresh-token&token_type=Bearer&expires_in=86400`,
      { waitUntil: 'networkidle' },
    );

    await page.waitForTimeout(5000);

    console.log('\n=== OAuth Callback Test ===');
    console.log('Final URL:', page.url());

    console.log('\nAPI calls during callback:');
    for (const call of apiCalls) {
      console.log(`  [${call.status}] ${call.method} ${call.url}`);
    }

    // Check for /me endpoint calls
    const meCalls = apiCalls.filter((c) => c.url.includes('/me'));
    console.log(`\n/me endpoint calls: ${meCalls.length}`);
    for (const call of meCalls) {
      console.log(`  [${call.status}] ${call.method} ${call.url}`);
    }

    // Log auth-related console messages
    const authLogs = logs.filter(
      (l) =>
        l.toLowerCase().includes('auth') ||
        l.toLowerCase().includes('token') ||
        l.toLowerCase().includes('/me'),
    );
    console.log('\nAuth-related console messages:');
    for (const log of authLogs.slice(0, 20)) {
      console.log(`  ${log.slice(0, 200)}`);
    }

    // Count errors
    const errors = logs.filter((l) => l.startsWith('[error]'));
    console.log(`\nTotal console errors: ${errors.length}`);
  });

  test('should test if apiFetch retry causes console spam', async ({ page }) => {
    let messageCount = 0;
    const errorPatterns: Record<string, number> = {};

    page.on('console', (msg) => {
      messageCount++;
      const key = msg.text().slice(0, 50);
      errorPatterns[key] = (errorPatterns[key] || 0) + 1;
    });

    // Set up localStorage as if logged in with expired token
    await page.goto('https://aragora.ai');
    await page.evaluate(() => {
      localStorage.setItem(
        'aragora_tokens',
        JSON.stringify({
          access_token: 'expired-token',
          refresh_token: 'expired-refresh',
          expires_at: new Date(Date.now() - 1000).toISOString(), // Expired
        }),
      );
      localStorage.setItem(
        'aragora_user',
        JSON.stringify({ id: 'test-user', email: 'test@example.com', name: 'Test User' }),
      );
    });

    // Reload and wait - should trigger token refresh attempts
    const startTime = Date.now();
    await page.reload({ waitUntil: 'networkidle' });

    // Wait 30 seconds to see if there's console spam
    await page.waitForTimeout(30000);

    const elapsedMs = Date.now() - startTime;
    const messagesPerSecond = messageCount / (elapsedMs / 1000);

    console.log('\n=== Console Spam Analysis ===');
    console.log(`Total messages in ${elapsedMs}ms: ${messageCount}`);
    console.log(`Messages per second: ${messagesPerSecond.toFixed(2)}`);

    console.log('\nMost frequent patterns:');
    const sorted = Object.entries(errorPatterns)
      .sort((a, b) => b[1] - a[1])
      .slice(0, 10);
    for (const [pattern, count] of sorted) {
      console.log(`  [${count}x] ${pattern}`);
    }

    // Flag if there's potential spam (>10 messages/second)
    if (messagesPerSecond > 10) {
      console.log('\n⚠️  WARNING: Potential console spam detected!');
    }

    // Test should flag if there's excessive logging
    expect(messagesPerSecond).toBeLessThan(100);
  });

  test('should verify /api/v1/auth/me returns correct response', async ({ page }) => {
    // Test the API endpoint directly via page.evaluate
    await page.goto('https://aragora.ai');

    const result = await page.evaluate(async () => {
      const response = await fetch('https://api.aragora.ai/api/v1/auth/me', {
        headers: { Authorization: 'Bearer test-token', 'Content-Type': 'application/json' },
      });
      return {
        status: response.status,
        statusText: response.statusText,
        headers: Object.fromEntries(response.headers.entries()),
        body: await response.text(),
      };
    });

    console.log('\n=== /api/v1/auth/me Response ===');
    console.log(`Status: ${result.status} ${result.statusText}`);
    console.log(`Body: ${result.body.slice(0, 500)}`);

    // Should return 401 for invalid token, NOT 405
    expect(result.status).not.toBe(405);
    expect([401, 200]).toContain(result.status);
  });
});
