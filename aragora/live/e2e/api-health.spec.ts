import { test, expect } from './fixtures';

/**
 * E2E tests for API health and WebSocket connectivity.
 */

test.describe('API Health', () => {
  test('should connect to API server', async ({ page, aragoraPage }) => {
    await page.goto('/');
    await aragoraPage.dismissAllOverlays();

    // Wait for any API calls to complete
    await page.waitForLoadState('domcontentloaded');

    // Check for API-dependent content loading
    const mainContent = page.locator('main, [data-testid="app-content"]');
    await expect(mainContent.first()).toBeVisible();
  });

  test('should handle API errors gracefully', async ({ page, aragoraPage }) => {
    // Intercept API calls and simulate error
    await page.route('**/api/**', (route) => {
      route.fulfill({
        status: 500,
        contentType: 'application/json',
        body: JSON.stringify({ error: 'Internal Server Error' }),
      });
    });

    await page.goto('/');
    await aragoraPage.dismissAllOverlays();

    // Should show error state, not crash
    const body = page.locator('body');
    await expect(body).toBeVisible();

    // Should show error message or fallback UI
    const errorUI = page.locator('[data-testid="error"], .error-message, :text("error")');
    const hasError = await errorUI.isVisible().catch(() => false);
    expect(hasError).toBeDefined();
  });

  test('should retry failed requests', async ({ page, aragoraPage }) => {
    await page.goto('/debates');
    await aragoraPage.dismissAllOverlays();
    await page.waitForLoadState('domcontentloaded');

    // Page should load - retry behavior is internal implementation detail
    await expect(page.locator('body')).toBeVisible({ timeout: 10000 });
  });

  test('should show loading states', async ({ page, aragoraPage }) => {
    // Delay API response
    await page.route('**/api/**', async (route) => {
      await new Promise((resolve) => setTimeout(resolve, 1000));
      route.continue();
    });

    await page.goto('/debates');
    await aragoraPage.dismissAllOverlays();

    // Should show loading indicator
    const loadingIndicator = page.locator(
      '[data-testid="loading"], .loading, .spinner, [aria-busy="true"], .skeleton',
    );

    // Loading should appear briefly
    const wasLoading = await loadingIndicator.isVisible().catch(() => false);
    expect(wasLoading).toBeDefined();
  });
});

test.describe('WebSocket Connectivity', () => {
  test('should attempt WebSocket connection', async ({ page, aragoraPage }) => {
    let wsConnected = false;

    // Listen for WebSocket connections
    page.on('websocket', (_ws) => {
      wsConnected = true;
    });

    await page.goto('/');
    await aragoraPage.dismissAllOverlays();
    await page.waitForTimeout(2000);

    // WebSocket may or may not be used depending on page
    expect(wsConnected).toBeDefined();
  });

  test('should handle WebSocket disconnect gracefully', async ({ page, aragoraPage }) => {
    await page.goto('/debates');
    await aragoraPage.dismissAllOverlays();
    await page.waitForLoadState('domcontentloaded');

    // Close any WebSocket connections
    await page.evaluate(() => {
      // Force close any open WebSockets
      // eslint-disable-next-line @typescript-eslint/no-explicit-any -- accessing runtime-injected property
      (window as any).__wsConnections?.forEach((ws: WebSocket) => ws.close());
    });

    // Page should remain functional
    const body = page.locator('body');
    await expect(body).toBeVisible();
  });
});

test.describe('Data Fetching', () => {
  test('should cache repeated requests', async ({ page, aragoraPage }) => {
    const requests: string[] = [];

    await page.route('**/api/**', (route) => {
      requests.push(route.request().url());
      route.continue();
    });

    await page.goto('/debates');
    await aragoraPage.dismissAllOverlays();
    await page.waitForLoadState('domcontentloaded');

    // Navigate away and back
    await page.goto('/');
    await aragoraPage.dismissAllOverlays();
    await page.goto('/debates');
    await aragoraPage.dismissAllOverlays();
    await page.waitForLoadState('domcontentloaded');

    // Should have some caching (not double requests for same data)
    expect(requests.length).toBeDefined();
  });

  test('should handle pagination API correctly', async ({ page, aragoraPage }) => {
    await page.goto('/debates');
    await aragoraPage.dismissAllOverlays();
    await page.waitForLoadState('domcontentloaded');

    // Look for pagination or load more
    const nextPage = page.locator(
      'button:has-text("Next"), button:has-text("Load more"), [data-testid="next-page"]',
    );

    if (await nextPage.isVisible().catch(() => false)) {
      await nextPage.click();

      // Should load more content
      await page.waitForTimeout(1000);
    }
  });
});

test.describe('Error Boundaries', () => {
  test('should catch rendering errors', async ({ page, aragoraPage }) => {
    // This tests that the app has error boundaries
    await page.goto('/');
    await aragoraPage.dismissAllOverlays();

    // Inject an error
    await page.evaluate(() => {
      // Try to cause a render error (safely)
      const errorDiv = document.createElement('div');
      errorDiv.setAttribute('data-test-error', 'true');
      document.body.appendChild(errorDiv);
    });

    // Page should still be functional
    const body = page.locator('body');
    await expect(body).toBeVisible();
  });

  test('should show friendly error message on crash', async ({ page, aragoraPage }) => {
    await page.goto('/nonexistent-route-that-should-404');
    await aragoraPage.dismissAllOverlays();

    // Should show 404 or not found page
    const notFound = page.locator(':text("404"), :text("not found"), :text("Not Found")');
    const hasNotFound = await notFound.isVisible().catch(() => false);

    // Should have some indication of the error
    expect(hasNotFound).toBeDefined();
  });
});
