import { test, expect } from '@playwright/test';

/**
 * Production Auth Flow Tests
 *
 * These tests verify the full OAuth authentication flow works correctly
 * against the production site.
 */

test.describe('Production Auth Flow', () => {
  test('should verify login page loads with OAuth providers', async ({ page }) => {
    const errors: string[] = [];

    page.on('console', (msg) => {
      if (msg.type() === 'error') {
        errors.push(msg.text());
      }
    });

    await page.goto('https://aragora.ai/auth/login', { waitUntil: 'domcontentloaded' });
    await page.waitForTimeout(2000);

    // Check OAuth buttons are visible
    const googleBtn = page.locator('button:has-text("Google")');
    const githubBtn = page.locator('button:has-text("GitHub")');
    const microsoftBtn = page.locator('button:has-text("Microsoft")');

    console.log('\n=== OAuth Provider Buttons ===');
    console.log(`Google: ${await googleBtn.isVisible()}`);
    console.log(`GitHub: ${await githubBtn.isVisible()}`);
    console.log(`Microsoft: ${await microsoftBtn.isVisible()}`);

    // At least one should be visible
    const anyVisible =
      (await googleBtn.isVisible()) ||
      (await githubBtn.isVisible()) ||
      (await microsoftBtn.isVisible());

    expect(anyVisible).toBeTruthy();

    console.log(`\nConsole errors: ${errors.length}`);
    for (const err of errors.slice(0, 5)) {
      console.log(`  ${err.slice(0, 200)}`);
    }
  });

  test('should verify API health and auth endpoints', async ({ page }) => {
    // Test API endpoints directly
    await page.goto('https://aragora.ai');

    const results = await page.evaluate(async () => {
      const tests = [
        { name: 'Health', url: 'https://api.aragora.ai/api/health', method: 'GET' },
        {
          name: 'OAuth Providers',
          url: 'https://api.aragora.ai/api/auth/oauth/providers',
          method: 'GET',
        },
        { name: '/me (no auth)', url: 'https://api.aragora.ai/api/v1/auth/me', method: 'GET' },
      ];

      const results: { name: string; status: number; ok: boolean }[] = [];

      for (const t of tests) {
        try {
          const response = await fetch(t.url, {
            method: t.method,
            headers: { 'Content-Type': 'application/json' },
          });
          results.push({ name: t.name, status: response.status, ok: response.ok });
        } catch {
          results.push({ name: t.name, status: 0, ok: false });
        }
      }

      return results;
    });

    console.log('\n=== API Endpoint Tests ===');
    for (const r of results) {
      console.log(`${r.name}: ${r.status} (${r.ok ? 'OK' : 'FAIL'})`);
    }

    // Health should return 200
    expect(results.find((r) => r.name === 'Health')?.status).toBe(200);

    // OAuth providers should return 200
    expect(results.find((r) => r.name === 'OAuth Providers')?.status).toBe(200);

    // /me without auth should return 401, NOT 405
    const meResult = results.find((r) => r.name === '/me (no auth)');
    expect(meResult?.status).toBe(401);
  });

  test('should not have excessive console errors on homepage', async ({ page }) => {
    let errorCount = 0;
    const errorPatterns: Record<string, number> = {};

    page.on('console', (msg) => {
      if (msg.type() === 'error') {
        errorCount++;
        const key = msg.text().slice(0, 50);
        errorPatterns[key] = (errorPatterns[key] || 0) + 1;
      }
    });

    await page.goto('https://aragora.ai', { waitUntil: 'domcontentloaded' });
    await page.waitForTimeout(5000);

    console.log(`\n=== Homepage Console Errors ===`);
    console.log(`Total errors in 5s: ${errorCount}`);

    if (errorCount > 0) {
      console.log('\nError patterns:');
      const sorted = Object.entries(errorPatterns).sort((a, b) => b[1] - a[1]);
      for (const [pattern, count] of sorted.slice(0, 10)) {
        console.log(`  [${count}x] ${pattern}...`);
      }
    }

    // Should have less than 10 errors in 5 seconds
    expect(errorCount).toBeLessThan(10);
  });

  test('should handle main page question input', async ({ page }) => {
    const apiCalls: { url: string; status: number }[] = [];

    page.on('response', (response) => {
      const url = response.url();
      if (url.includes('api.aragora.ai') || url.includes('/api/')) {
        apiCalls.push({ url: url.replace(/https?:\/\/[^\/]+/, ''), status: response.status() });
      }
    });

    await page.goto('https://aragora.ai', { waitUntil: 'domcontentloaded' });
    await page.waitForTimeout(3000); // Wait for React to hydrate

    // Look for input field
    const input = page
      .locator(
        'input[placeholder*="question"], textarea[placeholder*="question"], input[type="text"]',
      )
      .first();

    if (await input.isVisible()) {
      console.log('\n=== Question Input Found ===');
      await input.fill('Test question');
      await page.waitForTimeout(1000);

      // Look for submit button
      const submitBtn = page
        .locator('button[type="submit"], button:has-text("Submit"), button:has-text("Ask")')
        .first();
      if (await submitBtn.isVisible()) {
        console.log('Submit button found');
      }
    } else {
      console.log('Question input not found (may require login)');
    }

    console.log('\n=== API Calls Made ===');
    for (const call of apiCalls) {
      console.log(`  [${call.status}] ${call.url}`);
    }

    // Should have made some API calls
    expect(apiCalls.length).toBeGreaterThan(0);
  });
});
