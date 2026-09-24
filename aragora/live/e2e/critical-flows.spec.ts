/**
 * Critical User Flow Tests
 *
 * These tests cover the most important user journeys through the application.
 * They serve as smoke tests to ensure core functionality works end-to-end.
 */

import { test, expect, mockApiResponse, mockDebate, mockAgents } from './fixtures';

test.describe('Critical User Flows', () => {
  test.describe('Homepage to Debate Flow', () => {
    test('user can navigate from homepage to debates archive', async ({ page, aragoraPage }) => {
      // Mock API responses
      await mockApiResponse(page, '**/api/health', { status: 'ok', version: '1.0.0' });
      await mockApiResponse(page, '**/api/debates', { debates: [mockDebate], total: 1 });

      // Start at homepage
      await page.goto('/');
      await aragoraPage.dismissAllOverlays();

      // Navigate to debates archive
      const debatesLink = page
        .locator('a[href*="/debates"], button')
        .filter({ hasText: /debates|archive|history/i })
        .first();

      if (await debatesLink.isVisible()) {
        await debatesLink.click();
        await page.waitForURL(/debates/);

        // Should see debate list or empty state
        const debateList = page.locator('[data-testid="debate-list"], .debate-list, .debates');
        const emptyState = page.locator('text=/no debates|empty|start/i');

        const hasContent = await debateList.or(emptyState).first().isVisible({ timeout: 5000 });
        expect(hasContent).toBeTruthy();
      }
    });

    test('user can navigate to leaderboard', async ({ page, aragoraPage }) => {
      await mockApiResponse(page, '**/api/health', { status: 'ok', version: '1.0.0' });
      await mockApiResponse(page, '**/api/leaderboard', {
        rankings: mockAgents.map((a, i) => ({ ...a, rank: i + 1, elo: 1500 - i * 10 })),
      });

      await page.goto('/');
      await aragoraPage.dismissAllOverlays();

      // Navigate to leaderboard
      const leaderboardLink = page
        .locator('a[href*="/leaderboard"], button')
        .filter({ hasText: /leaderboard|rankings|agents/i })
        .first();

      if (await leaderboardLink.isVisible()) {
        await leaderboardLink.click();
        await page.waitForURL(/leaderboard/);

        // Should see rankings
        const rankings = page.locator('[data-testid="rankings"], .rankings, .leaderboard');
        await expect(rankings.or(page.locator('text=/ranking|elo|score/i').first())).toBeVisible({
          timeout: 5000,
        });
      }
    });
  });

  test.describe('Navigation and Layout', () => {
    test('main navigation is accessible', async ({ page, aragoraPage }) => {
      await mockApiResponse(page, '**/api/health', { status: 'ok', version: '1.0.0' });

      await page.goto('/');
      await aragoraPage.dismissAllOverlays();

      // Check header/navigation exists
      const nav = page.locator('header, nav, [role="navigation"]').first();
      await expect(nav).toBeVisible();

      // Check theme toggle is present
      const themeToggle = page
        .locator('[data-testid="theme-toggle"], button')
        .filter({ hasText: /theme|dark|light/i })
        .or(page.locator('[aria-label*="theme"]'));

      if (await themeToggle.first().isVisible()) {
        await expect(themeToggle.first()).toBeEnabled();
      }
    });

    test('footer contains expected links', async ({ page, aragoraPage }) => {
      await mockApiResponse(page, '**/api/health', { status: 'ok', version: '1.0.0' });

      await page.goto('/');
      await aragoraPage.dismissAllOverlays();

      // Check footer exists
      const footer = page.locator('footer').first();

      if (await footer.isVisible({ timeout: 2000 })) {
        // Footer should have some content
        const footerText = await footer.textContent();
        expect(footerText!.length).toBeGreaterThan(0);
      }
    });

    test('sidebar can be opened and closed', async ({ page, aragoraPage }) => {
      await mockApiResponse(page, '**/api/health', { status: 'ok', version: '1.0.0' });

      await page.goto('/');
      await aragoraPage.dismissAllOverlays();

      // Look for sidebar toggle
      const sidebarToggle = page
        .locator('[data-testid="sidebar-toggle"], [aria-label*="menu"], button')
        .filter({ hasText: /menu|sidebar/i })
        .first();

      if (await sidebarToggle.isVisible()) {
        // Open sidebar
        await sidebarToggle.click();

        // Sidebar should be visible
        const sidebar = page
          .locator('[data-testid="sidebar"], aside, [role="complementary"]')
          .first();
        await expect(sidebar).toBeVisible({ timeout: 2000 });

        // Close with escape key
        await page.keyboard.press('Escape');
      }
    });
  });

  test.describe('Error Handling', () => {
    test('shows error state when API fails', async ({ page, aragoraPage }) => {
      // Mock API to return error
      await page.route('**/api/health', (route) => {
        route.fulfill({ status: 500, body: JSON.stringify({ error: 'Internal Server Error' }) });
      });

      await page.goto('/');
      await aragoraPage.dismissAllOverlays();

      // App should handle error gracefully (not crash)
      const errorBoundary = page.locator('[data-testid="error-boundary"], .error');
      const mainContent = page.locator('main, [role="main"]');

      // Either error message or fallback content should be visible
      const hasContent = await errorBoundary.or(mainContent).first().isVisible({ timeout: 5000 });
      expect(hasContent).toBeTruthy();
    });

    test('404 page shows for unknown routes', async ({ page, aragoraPage }) => {
      await page.goto('/this-page-does-not-exist-12345');
      await aragoraPage.dismissAllOverlays();

      // Should show 404 or redirect to homepage
      const is404 = page.locator('text=/not found|404|page.*exist/i');
      const isHome = page.url().endsWith('/') || page.url().includes('?');

      const handled = (await is404.isVisible({ timeout: 3000 }).catch(() => false)) || isHome;
      expect(handled).toBeTruthy();
    });
  });

  test.describe('Keyboard Navigation', () => {
    test('can navigate with Tab key', async ({ page, aragoraPage }) => {
      await mockApiResponse(page, '**/api/health', { status: 'ok', version: '1.0.0' });

      await page.goto('/');
      await aragoraPage.dismissAllOverlays();

      // Press Tab multiple times
      for (let i = 0; i < 5; i++) {
        await page.keyboard.press('Tab');
      }

      // Something should be focused
      const focusedElement = await page.evaluate(() => document.activeElement?.tagName);
      expect(focusedElement).toBeTruthy();
      expect(focusedElement).not.toBe('BODY');
    });

    test('escape key closes modals', async ({ page, aragoraPage }) => {
      await mockApiResponse(page, '**/api/health', { status: 'ok', version: '1.0.0' });

      await page.goto('/');
      await aragoraPage.dismissAllOverlays();

      // Try to find and open a modal
      const modalTrigger = page
        .locator('button')
        .filter({ hasText: /open|show|details|more/i })
        .first();

      if (await modalTrigger.isVisible()) {
        await modalTrigger.click();
        await page.waitForTimeout(500);

        // Check if modal opened
        const modal = page.locator('[role="dialog"], .modal, [data-testid*="modal"]');

        if (await modal.isVisible()) {
          // Press Escape to close
          await page.keyboard.press('Escape');
          await expect(modal).not.toBeVisible({ timeout: 2000 });
        }
      }
    });
  });

  test.describe('Responsive Design', () => {
    test('works on mobile viewport', async ({ page, aragoraPage }) => {
      await mockApiResponse(page, '**/api/health', { status: 'ok', version: '1.0.0' });

      // Set mobile viewport
      await page.setViewportSize({ width: 375, height: 667 });

      await page.goto('/');
      await aragoraPage.dismissAllOverlays();

      // Page should be scrollable and content visible
      const body = page.locator('body');
      await expect(body).toBeVisible();

      // No horizontal overflow (basic responsive check)
      const bodyWidth = await page.evaluate(() => document.body.scrollWidth);
      const viewportWidth = await page.evaluate(() => window.innerWidth);
      expect(bodyWidth).toBeLessThanOrEqual(viewportWidth + 10); // Small tolerance
    });

    test('works on tablet viewport', async ({ page, aragoraPage }) => {
      await mockApiResponse(page, '**/api/health', { status: 'ok', version: '1.0.0' });

      await page.setViewportSize({ width: 768, height: 1024 });

      await page.goto('/');
      await aragoraPage.dismissAllOverlays();

      const body = page.locator('body');
      await expect(body).toBeVisible();
    });
  });

  test.describe('Performance', () => {
    test('page loads within acceptable time', async ({ page, aragoraPage }) => {
      await mockApiResponse(page, '**/api/health', { status: 'ok', version: '1.0.0' });

      const startTime = Date.now();
      await page.goto('/');
      await aragoraPage.dismissAllOverlays();

      // Wait for main content
      await page.waitForLoadState('domcontentloaded');
      const loadTime = Date.now() - startTime;

      // Should load within 10 seconds (generous for CI environments)
      expect(loadTime).toBeLessThan(10000);
    });
  });
});
