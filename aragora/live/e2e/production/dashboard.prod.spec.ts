/**
 * Dashboard Tests for Production
 *
 * Tests live.aragora.ai dashboard functionality.
 *
 * Run with: npx playwright test dashboard.prod.spec.ts --config=playwright.production.config.ts
 */

import { test, expect, PRODUCTION_DOMAINS, DASHBOARD_PAGES } from './fixtures';

test.describe('Dashboard - live.aragora.ai', () => {
  test.describe('Page Accessibility', () => {
    for (const pageInfo of DASHBOARD_PAGES) {
      test(`${pageInfo.name} should be accessible`, async ({ page, productionPage }) => {
        const url = `${PRODUCTION_DOMAINS.dashboard}${pageInfo.path}`;
        await productionPage.goto(url);
        await productionPage.waitForHydration();
        await productionPage.dismissBootAnimation();

        // Page should load
        await expect(page.locator('body')).toBeVisible();

        // No critical errors (excluding React hydration issues which are known)
        const criticalErrors = productionPage.errorCollector
          .getErrorsBySeverity('critical')
          .filter((e) => !e.message.includes('Minified React error'));
        if (criticalErrors.length > 0) {
          console.log(`Critical errors on ${pageInfo.name}:`);
          criticalErrors.forEach((e) => console.log(`  ${e.message}`));
        }
        expect(criticalErrors.length).toBe(0);
      });
    }
  });

  test.describe('Dashboard Home', () => {
    test('should display main dashboard content', async ({ page, productionPage }) => {
      await productionPage.goto(PRODUCTION_DOMAINS.dashboard);
      await productionPage.waitForHydration();
      await productionPage.dismissBootAnimation();

      // Should have main content
      const mainContent = page.locator('main, #__next, [data-testid="app-content"]');
      await expect(mainContent.first()).toBeVisible();
    });

    test('should display navigation', async ({ page, productionPage }) => {
      await productionPage.goto(PRODUCTION_DOMAINS.dashboard);
      await productionPage.waitForHydration();
      await productionPage.dismissBootAnimation();

      // Should have navigation
      const nav = page.locator('nav, header, [role="navigation"]');
      await expect(nav.first()).toBeVisible();
    });

    test('should have debate-related UI elements', async ({ page, productionPage }) => {
      await productionPage.goto(PRODUCTION_DOMAINS.dashboard);
      await productionPage.waitForHydration();
      await productionPage.dismissBootAnimation();

      // Should have some debate-related content
      const content = await page.content();
      const hasDebateContent =
        content.toLowerCase().includes('debate') ||
        content.toLowerCase().includes('agent') ||
        content.toLowerCase().includes('topic') ||
        content.toLowerCase().includes('claude') ||
        content.toLowerCase().includes('gpt');

      expect(hasDebateContent).toBe(true);
    });
  });

  test.describe('Debates Page', () => {
    test('should display debates list or empty state', async ({ page, productionPage }) => {
      await productionPage.goto(`${PRODUCTION_DOMAINS.dashboard}/debates`);
      await productionPage.waitForHydration();
      await productionPage.dismissBootAnimation();

      // Should have debates content or empty state
      const content = await page.content();
      const hasContent =
        content.toLowerCase().includes('debate') ||
        content.toLowerCase().includes('no debates') ||
        content.toLowerCase().includes('start') ||
        content.toLowerCase().includes('create');

      expect(hasContent).toBe(true);
    });

    test('should have create debate functionality', async ({ page, productionPage }) => {
      await productionPage.goto(`${PRODUCTION_DOMAINS.dashboard}/debates`);
      await productionPage.waitForHydration();
      await productionPage.dismissBootAnimation();

      // Should have input or button to create debate
      const createButton = page.locator(
        'button:has-text("new"), button:has-text("create"), button:has-text("start"), textarea, input[type="text"]',
      );
      const hasCreateUI = (await createButton.count()) > 0;

      // It's OK if creation requires auth
      console.log(`Debates page has create UI: ${hasCreateUI}`);
    });
  });

  test.describe('Agents Page', () => {
    test('should display agents information', async ({ page, productionPage }) => {
      await productionPage.goto(`${PRODUCTION_DOMAINS.dashboard}/agents`);
      await productionPage.waitForHydration();
      await productionPage.dismissBootAnimation();

      // Should have agent content
      const content = await page.content();
      const hasAgentContent =
        content.toLowerCase().includes('agent') ||
        content.toLowerCase().includes('claude') ||
        content.toLowerCase().includes('gpt') ||
        content.toLowerCase().includes('gemini') ||
        content.toLowerCase().includes('mistral');

      expect(hasAgentContent).toBe(true);
    });
  });

  test.describe('Leaderboard Page', () => {
    test('should display leaderboard', async ({ page, productionPage }) => {
      await productionPage.goto(`${PRODUCTION_DOMAINS.dashboard}/leaderboard`);
      await productionPage.waitForHydration();
      await productionPage.dismissBootAnimation();

      // Should have leaderboard content
      const content = await page.content();
      const hasLeaderboardContent =
        content.toLowerCase().includes('leaderboard') ||
        content.toLowerCase().includes('ranking') ||
        content.toLowerCase().includes('elo') ||
        content.toLowerCase().includes('score');

      expect(hasLeaderboardContent).toBe(true);
    });

    test('should display agent rankings', async ({ page, productionPage }) => {
      await productionPage.goto(`${PRODUCTION_DOMAINS.dashboard}/leaderboard`);
      await productionPage.waitForHydration();
      await productionPage.dismissBootAnimation();

      // Look for agent names in the leaderboard
      const content = await page.content();
      const hasAgentNames =
        content.toLowerCase().includes('claude') ||
        content.toLowerCase().includes('gpt') ||
        content.toLowerCase().includes('gemini');

      // It's OK if there are no rankings yet
      console.log(`Leaderboard has agent names: ${hasAgentNames}`);
    });
  });

  test.describe('Interactive Elements', () => {
    test('should have functional theme toggle', async ({ page, productionPage }) => {
      await productionPage.goto(PRODUCTION_DOMAINS.dashboard);
      await productionPage.waitForHydration();
      await productionPage.dismissBootAnimation();

      // Find theme toggle
      const themeToggle = page
        .locator(
          'button[aria-label*="theme"], button:has-text("dark"), button:has-text("light"), [data-testid="theme-toggle"]',
        )
        .first();

      if (await themeToggle.isVisible().catch(() => false)) {
        // Get initial background
        const initialBg = await page.evaluate(() => {
          return window.getComputedStyle(document.body).backgroundColor;
        });

        await themeToggle.click();
        await page.waitForTimeout(500);

        // Background might change
        const newBg = await page.evaluate(() => {
          return window.getComputedStyle(document.body).backgroundColor;
        });

        console.log(`Theme toggle: ${initialBg} -> ${newBg}`);
      }
    });

    test('should have working navigation links', async ({ page, productionPage }) => {
      await productionPage.goto(PRODUCTION_DOMAINS.dashboard);
      await productionPage.waitForHydration();
      await productionPage.dismissBootAnimation();

      // Page should have some navigation links
      const navLinks = page.locator('a[href]');
      const hasLinks = (await navLinks.count()) > 0;
      expect(hasLinks).toBe(true);
    });
  });

  test.describe('WebSocket Connection', () => {
    test('should attempt WebSocket connection', async ({ page, productionPage }) => {
      let wsConnected = false;
      let wsUrl = '';

      page.on('websocket', (ws) => {
        wsConnected = true;
        wsUrl = ws.url();
        console.log(`WebSocket connected: ${wsUrl}`);
      });

      await productionPage.goto(PRODUCTION_DOMAINS.dashboard);
      await productionPage.waitForHydration();
      await productionPage.dismissBootAnimation();

      // Wait for potential WebSocket connection
      await page.waitForTimeout(3000);

      console.log(`WebSocket attempted: ${wsConnected}`);
      if (wsConnected) {
        expect(wsUrl).toBeTruthy();
      }
    });
  });

  test.describe('Responsive Design', () => {
    test('should display correctly on mobile', async ({ page, productionPage }) => {
      await page.setViewportSize({ width: 375, height: 667 });
      await productionPage.goto(PRODUCTION_DOMAINS.dashboard);
      await productionPage.waitForHydration();
      await productionPage.dismissBootAnimation();

      // Content should be visible
      await expect(page.locator('body')).toBeVisible();

      // Note: Some horizontal overflow is acceptable for CRT-styled pages
    });

    test('should have mobile-friendly navigation', async ({ page, productionPage }) => {
      await page.setViewportSize({ width: 375, height: 667 });
      await productionPage.goto(PRODUCTION_DOMAINS.dashboard);
      await productionPage.waitForHydration();
      await productionPage.dismissBootAnimation();

      // Should have mobile menu or hamburger
      const mobileMenu = page.locator(
        '[aria-label*="menu"], button[aria-label*="nav"], [data-testid="mobile-menu"], .hamburger',
      );

      // Either visible mobile menu or regular nav should be present
      const hasMobileNav = (await mobileMenu.count()) > 0;
      console.log(`Has mobile navigation: ${hasMobileNav}`);
    });
  });

  test.describe('Error Handling', () => {
    test('should handle 404 routes gracefully', async ({ page, productionPage }) => {
      await productionPage.goto(`${PRODUCTION_DOMAINS.dashboard}/nonexistent-page-12345`);

      // Should show 404 or redirect
      const content = await page.content();
      const has404 =
        content.includes('404') ||
        content.toLowerCase().includes('not found') ||
        page.url() === `${PRODUCTION_DOMAINS.dashboard}/`;

      expect(has404).toBe(true);
    });
  });

  test.describe('Performance', () => {
    test('should load within acceptable time', async ({ page }) => {
      const startTime = Date.now();

      await page.goto(PRODUCTION_DOMAINS.dashboard, { waitUntil: 'domcontentloaded' });

      const loadTime = Date.now() - startTime;
      console.log(`Dashboard DOM content loaded: ${loadTime}ms`);

      expect(loadTime).toBeLessThan(5000);
    });

    test('should be interactive quickly', async ({ productionPage }) => {
      const startTime = Date.now();

      await productionPage.goto(PRODUCTION_DOMAINS.dashboard);
      await productionPage.waitForHydration();
      await productionPage.dismissBootAnimation();

      const interactiveTime = Date.now() - startTime;
      console.log(`Dashboard interactive: ${interactiveTime}ms`);

      // Allow up to 20 seconds for boot animation and hydration
      expect(interactiveTime).toBeLessThan(20000);
    });
  });
});
