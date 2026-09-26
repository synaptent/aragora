import { test, expect } from '@playwright/test';

/**
 * Real OAuth Flow Test
 *
 * Tests what actually happens when OAuth callback receives tokens
 */

test.describe('Real OAuth Flow', () => {
  test('should test callback with real-like JWT structure', async ({ page }) => {
    const logs: string[] = [];
    const apiRequests: { url: string; status: number; method: string }[] = [];

    // Capture all console messages
    page.on('console', (msg) => {
      logs.push(`[${msg.type()}] ${msg.text()}`);
    });

    // Capture all network requests
    page.on('response', async (response) => {
      const url = response.url();
      // Log all API calls
      if (url.includes('/api/') || url.includes('api.aragora.ai')) {
        apiRequests.push({ url, status: response.status(), method: response.request().method() });
      }
    });

    // Create a realistic-looking JWT (it won't validate but will trigger the flow)
    // Format: header.payload.signature (base64 encoded)
    const header = btoa(JSON.stringify({ alg: 'HS256', typ: 'JWT' }));
    const payload = btoa(
      JSON.stringify({
        sub: 'test-user-id',
        email: 'test@example.com',
        org_id: null,
        role: 'member',
        iat: Math.floor(Date.now() / 1000),
        exp: Math.floor(Date.now() / 1000) + 86400,
        type: 'access',
        tv: 1,
      }),
    );
    const signature = 'fake-signature-for-testing';
    const fakeAccessToken = `${header}.${payload}.${signature}`;
    const fakeRefreshToken = `${header}.${btoa(JSON.stringify({ type: 'refresh' }))}.${signature}`;

    // Navigate to callback with tokens
    // SECURITY: Tokens should be in URL fragment (#) not query params (?)
    const callbackUrl = `https://aragora.ai/auth/callback/#access_token=${fakeAccessToken}&refresh_token=${fakeRefreshToken}&token_type=Bearer&expires_in=86400`;

    console.log('\n=== Navigating to callback URL ===');
    console.log(`URL: ${callbackUrl.substring(0, 100)}...`);

    await page.goto(callbackUrl, { waitUntil: 'domcontentloaded' });
    await page.waitForTimeout(5000);

    console.log('\n=== Final URL ===');
    console.log(page.url());

    console.log('\n=== All API Requests ===');
    for (const req of apiRequests) {
      console.log(`  [${req.status}] ${req.method} ${req.url}`);
    }

    console.log('\n=== Console Logs (auth related) ===');
    const authLogs = logs.filter(
      (l) =>
        l.toLowerCase().includes('auth') ||
        l.toLowerCase().includes('token') ||
        l.toLowerCase().includes('/me') ||
        l.toLowerCase().includes('oauth'),
    );
    for (const log of authLogs) {
      console.log(`  ${log.substring(0, 200)}`);
    }

    // Check if any request went to wrong URL
    const wrongUrls = apiRequests.filter(
      (r) => r.url.includes('aragora.ai/api') && !r.url.includes('api.aragora.ai'),
    );

    if (wrongUrls.length > 0) {
      console.log('\n=== ISSUE: Requests to wrong URL ===');
      for (const req of wrongUrls) {
        console.log(`  ${req.url} -> ${req.status}`);
      }
    }

    // Check the actual /me request
    const meRequest = apiRequests.find((r) => r.url.includes('/me'));
    if (meRequest) {
      console.log(`\n=== /me Request ===`);
      console.log(`URL: ${meRequest.url}`);
      console.log(`Status: ${meRequest.status}`);

      // The correct URL should be api.aragora.ai
      expect(meRequest.url).toContain('api.aragora.ai');
    } else {
      console.log('\n=== WARNING: No /me request found ===');
    }
  });
});
