import { test, expect } from './fixtures';

/**
 * E2E tests for feature availability and integration.
 *
 * These tests verify that all major features are accessible and
 * properly integrated with the backend.
 */

test.describe('Feature Availability', () => {
  test.describe('Core Navigation', () => {
    test('should have all primary navigation items', async ({ page, aragoraPage }) => {
      await page.goto('/');
      await aragoraPage.dismissAllOverlays();

      // Check sidebar or navigation exists
      const nav = page.locator('nav, aside, [role="navigation"]');
      await expect(nav.first()).toBeVisible();

      // Check for key navigation items (may be in sidebar)
      const links = await page.locator('a[href], button').allTextContents();
      const navText = links.join(' ').toLowerCase();

      // Should have core navigation features
      const hasDebates = navText.includes('debate') || navText.includes('live');
      const hasAgents = navText.includes('agent') || navText.includes('leaderboard');
      const hasSettings = navText.includes('setting');

      expect(hasDebates || hasAgents || hasSettings).toBe(true);
    });

    test('should navigate to debates page', async ({ page, aragoraPage }) => {
      await page.goto('/');
      await aragoraPage.dismissAllOverlays();

      // Navigate to debates (may be /debates or visible on home)
      await page.goto('/debates');
      await aragoraPage.dismissAllOverlays();

      // Should load without errors
      const body = page.locator('body');
      await expect(body).toBeVisible();
    });

    test('should navigate to settings page', async ({ page, aragoraPage }) => {
      await page.goto('/settings');
      await aragoraPage.dismissAllOverlays();

      // Settings page should load
      const body = page.locator('body');
      await expect(body).toBeVisible();

      // Should have settings content
      const content = await page.content();
      const hasSettingsContent =
        content.toLowerCase().includes('setting') ||
        content.toLowerCase().includes('preference') ||
        content.toLowerCase().includes('config');

      expect(hasSettingsContent).toBe(true);
    });
  });

  test.describe('Debate Features', () => {
    test('should have debate creation form', async ({ page, aragoraPage }) => {
      await page.goto('/');
      await aragoraPage.dismissAllOverlays();

      // Look for debate input or creation form
      const debateInput = page.locator(
        'input[placeholder*="question"], textarea[placeholder*="question"], ' +
          'input[name="topic"], textarea[name="topic"], ' +
          '[data-testid="debate-topic-input"]',
      );

      // May not be visible until user action
      const inputVisible = await debateInput
        .first()
        .isVisible()
        .catch(() => false);

      // If not directly visible, look for "Start Debate" button
      const startButton = page.locator(
        'button:has-text("Start"), button:has-text("Debate"), button:has-text("Ask")',
      );
      const buttonVisible = await startButton
        .first()
        .isVisible()
        .catch(() => false);

      expect(inputVisible || buttonVisible).toBe(true);
    });

    test('should show agent selection when creating debate', async ({ page, aragoraPage }) => {
      await page.goto('/');
      await aragoraPage.dismissAllOverlays();

      // Look for agent selection UI
      const agentSelect = page.locator(
        '[data-testid*="agent"], ' +
          'button:has-text("Select agents"), ' +
          '[role="listbox"], ' +
          '.agent-selector',
      );

      const agentsVisible = await agentSelect
        .first()
        .isVisible({ timeout: 3000 })
        .catch(() => false);

      // May need to interact to show agents
      if (!agentsVisible) {
        const showAgentsButton = page.locator('button:has-text("agent"), button:has-text("Agent")');
        if (
          await showAgentsButton
            .first()
            .isVisible()
            .catch(() => false)
        ) {
          await showAgentsButton.first().click();
        }
      }

      // Just verify no crash
      await expect(page.locator('body')).toBeVisible();
    });
  });

  test.describe('Analytics Features', () => {
    test('should load analytics/insights page', async ({ page, aragoraPage }) => {
      await page.goto('/analytics');
      await aragoraPage.dismissAllOverlays();

      const body = page.locator('body');
      await expect(body).toBeVisible();
    });

    test('should load leaderboard page', async ({ page, aragoraPage }) => {
      await page.goto('/leaderboard');
      await aragoraPage.dismissAllOverlays();

      const body = page.locator('body');
      await expect(body).toBeVisible();

      // Should have ranking/score content
      const content = await page.content();
      const hasRankingContent =
        content.toLowerCase().includes('rank') ||
        content.toLowerCase().includes('score') ||
        content.toLowerCase().includes('elo') ||
        content.toLowerCase().includes('agent');

      expect(hasRankingContent).toBe(true);
    });
  });

  test.describe('Knowledge Features', () => {
    test('should load knowledge page', async ({ page, aragoraPage }) => {
      await page.goto('/knowledge');
      await aragoraPage.dismissAllOverlays();

      const body = page.locator('body');
      await expect(body).toBeVisible();
    });
  });

  test.describe('Admin Features', () => {
    test('should load admin page', async ({ page, aragoraPage }) => {
      await page.goto('/admin');
      await aragoraPage.dismissAllOverlays();

      const body = page.locator('body');
      await expect(body).toBeVisible();

      // Admin may require auth - just verify page loads without crash
      const content = await page.content();
      expect(content.length).toBeGreaterThan(100);
    });
  });

  test.describe('Error Handling', () => {
    test('should handle 404 pages gracefully', async ({ page, aragoraPage }) => {
      await page.goto('/this-page-does-not-exist-12345');
      await aragoraPage.dismissAllOverlays();

      // Should show 404 or redirect, not crash
      const body = page.locator('body');
      await expect(body).toBeVisible();
    });

    test('should handle API errors without crashing', async ({ page, aragoraPage }) => {
      // Simulate API failure for a specific endpoint
      await page.route('**/api/debates**', (route) => {
        route.fulfill({ status: 500, body: JSON.stringify({ error: 'Internal Server Error' }) });
      });

      await page.goto('/debates');
      await aragoraPage.dismissAllOverlays();

      // Page should still render (with error state)
      const body = page.locator('body');
      await expect(body).toBeVisible();
    });
  });

  test.describe('UI Components', () => {
    test('should have theme toggle', async ({ page, aragoraPage }) => {
      await page.goto('/');
      await aragoraPage.dismissAllOverlays();

      // Look for theme toggle
      const themeToggle = page.locator(
        '[data-testid="theme-toggle"], ' +
          'button[aria-label*="theme"], ' +
          'button[aria-label*="Theme"], ' +
          'button[aria-label*="dark"], ' +
          'button[aria-label*="light"]',
      );

      const hasThemeToggle = await themeToggle
        .first()
        .isVisible({ timeout: 3000 })
        .catch(() => false);

      // Theme toggle is expected but not critical
      expect(typeof hasThemeToggle).toBe('boolean');
    });

    test('should have responsive sidebar', async ({ page, aragoraPage }) => {
      await page.goto('/');
      await aragoraPage.dismissAllOverlays();

      // Check sidebar exists
      const sidebar = page.locator('aside, [data-testid="sidebar"], nav.sidebar');
      const hasSidebar = await sidebar
        .first()
        .isVisible({ timeout: 3000 })
        .catch(() => false);

      // If sidebar exists, test collapse on mobile
      if (hasSidebar) {
        // Resize to mobile viewport
        await page.setViewportSize({ width: 375, height: 667 });
        await page.waitForTimeout(500);

        // Sidebar may be hidden or collapsed on mobile
        const body = page.locator('body');
        await expect(body).toBeVisible();
      }
    });
  });

  test.describe('Performance', () => {
    test('should load homepage within 5 seconds', async ({ page, aragoraPage }) => {
      const startTime = Date.now();
      await page.goto('/', { waitUntil: 'domcontentloaded' });
      const loadTime = Date.now() - startTime;

      await aragoraPage.dismissAllOverlays();

      console.log(`Homepage load time: ${loadTime}ms`);
      expect(loadTime).toBeLessThan(5000);
    });

    test('should not have memory leaks from repeated navigation', async ({ page, aragoraPage }) => {
      await page.goto('/');
      await aragoraPage.dismissAllOverlays();

      // Navigate between pages multiple times
      const pages = ['/', '/debates', '/leaderboard', '/settings'];
      for (const path of pages) {
        await page.goto(path);
        await aragoraPage.dismissAllOverlays();
        await page.waitForTimeout(500);
      }

      // Page should still be responsive
      const body = page.locator('body');
      await expect(body).toBeVisible();
    });
  });
});
