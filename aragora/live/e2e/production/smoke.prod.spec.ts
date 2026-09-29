/**
 * Smoke Tests for Production
 *
 * Basic health checks for all Aragora production domains.
 * These tests verify that sites are up and responding correctly.
 *
 * Run with: npx playwright test smoke.prod.spec.ts --config=playwright.production.config.ts
 */

import { test, expect, PRODUCTION_DOMAINS } from './fixtures';

test.describe('Production Smoke Tests', () => {
  test.describe('Domain Availability', () => {
    test('aragora.ai should be accessible', async ({ page, productionPage }) => {
      await productionPage.goto(PRODUCTION_DOMAINS.landing);
      await productionPage.waitForHydration();

      // Page should load
      await expect(page).toHaveTitle(/Aragora/i);

      // Check for basic page structure
      const body = page.locator('body');
      await expect(body).toBeVisible();

      // No critical errors
      expect(productionPage.hasCriticalErrors()).toBe(false);
    });

    test.skip('www.aragora.ai should redirect to aragora.ai', async ({ page, productionPage }) => {
      // SKIPPED: www.aragora.ai DNS record does not exist (known infrastructure issue)
      // TODO: Add www CNAME record to Cloudflare DNS
      await productionPage.goto(PRODUCTION_DOMAINS.www);
      await productionPage.waitForHydration();

      // Should redirect to main domain or render same content
      const url = page.url();
      expect(url).toMatch(/aragora\.ai/);

      // Page should have content
      await expect(page.locator('body')).toBeVisible();
    });

    test('live.aragora.ai should be accessible', async ({ page, productionPage }) => {
      await productionPage.goto(PRODUCTION_DOMAINS.dashboard);
      await productionPage.waitForHydration();
      await productionPage.dismissBootAnimation();

      // Page should load
      const body = page.locator('body');
      await expect(body).toBeVisible();

      // Should have dashboard content
      await expect(page).toHaveTitle(/Aragora/i);

      // No critical errors
      expect(productionPage.hasCriticalErrors()).toBe(false);
    });

    test('api.aragora.ai health endpoint should respond', async ({ page }) => {
      const response = await page.goto(`${PRODUCTION_DOMAINS.api}/api/health`, {
        waitUntil: 'domcontentloaded',
      });

      expect(response).not.toBeNull();
      expect(response!.status()).toBe(200);

      // Should return JSON with healthy status
      const body = await page.locator('body').textContent();
      expect(body).toBeTruthy();

      // Try to parse as JSON
      try {
        const json = JSON.parse(body || '{}');
        expect(json.status || json.healthy).toBeTruthy();
      } catch {
        // If not JSON, just check it's not an error page
        expect(body).not.toContain('error');
      }
    });

    test('status.aragora.ai should be accessible', async ({ page, productionPage }) => {
      await productionPage.goto(PRODUCTION_DOMAINS.status);

      // Status page should load (Uptime Kuma)
      const body = page.locator('body');
      await expect(body).toBeVisible();

      // Should have status content
      const content = await page.content();
      // Uptime Kuma or status page indicators
      const hasStatusContent =
        content.includes('status') ||
        content.includes('Uptime') ||
        content.includes('monitor') ||
        content.includes('Operational');
      expect(hasStatusContent).toBe(true);
    });
  });

  test.describe('Response Times', () => {
    test('aragora.ai should load within 5 seconds', async ({ page }) => {
      const startTime = Date.now();
      await page.goto(PRODUCTION_DOMAINS.landing, { waitUntil: 'domcontentloaded' });
      const loadTime = Date.now() - startTime;

      console.log(`aragora.ai load time: ${loadTime}ms`);
      expect(loadTime).toBeLessThan(5000);
    });

    test('live.aragora.ai should load within 5 seconds', async ({ page }) => {
      const startTime = Date.now();
      await page.goto(PRODUCTION_DOMAINS.dashboard, { waitUntil: 'domcontentloaded' });
      const loadTime = Date.now() - startTime;

      console.log(`live.aragora.ai load time: ${loadTime}ms`);
      expect(loadTime).toBeLessThan(5000);
    });

    test('API health check should respond within 2 seconds', async ({ page }) => {
      const startTime = Date.now();
      await page.goto(`${PRODUCTION_DOMAINS.api}/api/health`, { waitUntil: 'domcontentloaded' });
      const loadTime = Date.now() - startTime;

      console.log(`API health check response time: ${loadTime}ms`);
      expect(loadTime).toBeLessThan(2000);
    });
  });

  test.describe('Console Errors', () => {
    test('aragora.ai should have no console errors on load', async ({ productionPage }) => {
      await productionPage.goto(PRODUCTION_DOMAINS.landing);
      await productionPage.waitForHydration();

      const errors = productionPage.errorCollector.getErrorsBySeverity('critical');
      const highErrors = productionPage.errorCollector.getErrorsBySeverity('high');

      // Log errors for debugging
      if (errors.length > 0 || highErrors.length > 0) {
        console.log('Critical/High errors on aragora.ai:');
        [...errors, ...highErrors].forEach((e) => {
          console.log(`  [${e.severity}] ${e.type}: ${e.message}`);
        });
      }

      expect(errors.length).toBe(0);
    });

    test('live.aragora.ai should have no console errors on load', async ({ productionPage }) => {
      await productionPage.goto(PRODUCTION_DOMAINS.dashboard);
      await productionPage.waitForHydration();
      await productionPage.dismissBootAnimation();

      const errors = productionPage.errorCollector.getErrorsBySeverity('critical');

      // Log errors for debugging
      if (errors.length > 0) {
        console.log('Critical errors on live.aragora.ai:');
        errors.forEach((e) => {
          console.log(`  [${e.severity}] ${e.type}: ${e.message}`);
        });
      }

      expect(errors.length).toBe(0);
    });
  });

  test.describe('SSL/TLS', () => {
    test('all domains should use HTTPS', async () => {
      const domains = [
        PRODUCTION_DOMAINS.landing,
        PRODUCTION_DOMAINS.dashboard,
        PRODUCTION_DOMAINS.api,
        PRODUCTION_DOMAINS.status,
      ];

      for (const domain of domains) {
        expect(domain).toMatch(/^https:\/\//);
      }
    });

    test('HTTP should redirect to HTTPS', async ({ page }) => {
      // Try HTTP version of main domain
      const _response = await page.goto('http://aragora.ai', { waitUntil: 'domcontentloaded' });

      // Should have redirected to HTTPS
      const finalUrl = page.url();
      expect(finalUrl).toMatch(/^https:\/\//);
    });
  });

  test.describe('Basic Content', () => {
    test('aragora.ai should have expected meta tags', async ({ page, productionPage }) => {
      await productionPage.goto(PRODUCTION_DOMAINS.landing);
      await productionPage.waitForHydration();

      // Check title
      await expect(page).toHaveTitle(/Aragora/i);

      // Check meta description
      const description = page.locator('meta[name="description"]');
      await expect(description).toHaveAttribute('content', /.+/);

      // Check viewport
      const viewport = page.locator('meta[name="viewport"]');
      await expect(viewport).toHaveAttribute('content', /width/);
    });

    test('live.aragora.ai should render main content', async ({ page, productionPage }) => {
      await productionPage.goto(PRODUCTION_DOMAINS.dashboard);
      await productionPage.waitForHydration();
      await productionPage.dismissBootAnimation();

      // Should have main content area
      const mainContent = page.locator('main, #__next, [data-testid="app-content"]');
      await expect(mainContent.first()).toBeVisible();
    });

    test('status.aragora.ai should show monitor status', async ({ page, productionPage }) => {
      await productionPage.goto(PRODUCTION_DOMAINS.status);

      // Wait for content to load
      await page.waitForTimeout(2000);

      // Should show some status indicators
      const content = await page.content();
      const hasMonitors =
        content.includes('UP') ||
        content.includes('Operational') ||
        content.includes('monitor') ||
        content.includes('API');

      expect(hasMonitors).toBe(true);
    });
  });
});

test.describe('Cross-Domain Consistency', () => {
  test('branding should be consistent across domains', async ({ page, productionPage }) => {
    // Check aragora.ai
    await productionPage.goto(PRODUCTION_DOMAINS.landing);
    await productionPage.waitForHydration();
    const landingTitle = await page.title();

    // Check live.aragora.ai
    await productionPage.goto(PRODUCTION_DOMAINS.dashboard);
    await productionPage.waitForHydration();
    await productionPage.dismissBootAnimation();
    const dashboardTitle = await page.title();

    // Both should mention Aragora
    expect(landingTitle.toLowerCase()).toContain('aragora');
    expect(dashboardTitle.toLowerCase()).toContain('aragora');
  });
});
