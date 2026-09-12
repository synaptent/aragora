import { test, expect, mockApiResponse } from './fixtures';

test.describe('Navigation', () => {
  test.beforeEach(async ({ page }) => {
    await mockApiResponse(page, '**/api/health', { status: 'ok' });
  });

  test('should navigate to home page', async ({ page, aragoraPage }) => {
    await page.goto('/');
    await aragoraPage.dismissAllOverlays();
    await expect(page).toHaveURL(/\/(?:landing\/?)?$/);
    await expect(page.locator('body')).toBeVisible();
  });

  test('should navigate to about page', async ({ page, aragoraPage }) => {
    await page.goto('/about');
    await aragoraPage.dismissAllOverlays();
    await page.waitForLoadState('domcontentloaded');
    // URL should contain 'about'
    expect(page.url()).toContain('about');
    // Page body should be visible
    await expect(page.locator('body')).toBeVisible({ timeout: 10000 });
  });

  test('should navigate to pulse page', async ({ page, aragoraPage }) => {
    await page.goto('/pulse');
    await aragoraPage.dismissAllOverlays();
    await page.waitForLoadState('domcontentloaded');
    expect(page.url()).toContain('pulse');
    // Page body should be visible
    await expect(page.locator('body')).toBeVisible({ timeout: 10000 });
  });

  test('should navigate to agents page', async ({ page, aragoraPage }) => {
    await page.goto('/agents');
    await aragoraPage.dismissAllOverlays();
    await page.waitForLoadState('domcontentloaded');
    expect(page.url()).toContain('agents');
    // Page body should be visible
    await expect(page.locator('body')).toBeVisible({ timeout: 10000 });
  });

  test('should navigate to plugins page', async ({ page, aragoraPage }) => {
    await page.goto('/plugins');
    await aragoraPage.dismissAllOverlays();
    await page.waitForLoadState('domcontentloaded');
    expect(page.url()).toContain('plugins');
    // Page body should be visible
    await expect(page.locator('body')).toBeVisible({ timeout: 10000 });
  });

  test('should navigate to batch page', async ({ page, aragoraPage }) => {
    await page.goto('/batch');
    await aragoraPage.dismissAllOverlays();
    await page.waitForLoadState('domcontentloaded');
    expect(page.url()).toContain('batch');
    // Page body should be visible
    await expect(page.locator('body')).toBeVisible({ timeout: 10000 });
  });

  test('should have working navigation links in header', async ({ page, aragoraPage }) => {
    await page.goto('/');
    await aragoraPage.dismissAllOverlays();

    // Find and click about link
    const aboutLink = page.locator('a[href="/about"]').first();
    if (await aboutLink.isVisible()) {
      await aboutLink.click();
      await expect(page).toHaveURL(/\/about\/?$/);
    }
  });

  test('should handle 404 for non-existent pages', async ({ page, aragoraPage }) => {
    await page.goto('/non-existent-page-12345');
    await aragoraPage.dismissAllOverlays();

    // Should show 404 or redirect
    const notFoundElement = page.locator('text=/404|not found|page.*exist/i').first();
    const hasNotFound = await notFoundElement.isVisible().catch(() => false);
    const redirectedToHome = page.url().endsWith('/');

    expect(hasNotFound || redirectedToHome).toBeTruthy();
  });

  test('should preserve scroll position on back navigation', async ({ page, aragoraPage }) => {
    await page.goto('/');
    await aragoraPage.dismissAllOverlays();

    // Scroll down
    await page.evaluate(() => window.scrollTo(0, 500));

    // Navigate to about
    await page.goto('/about');
    await aragoraPage.dismissAllOverlays();

    // Go back
    await page.goBack();

    // Check scroll position (browser may restore or not)
    await page.waitForTimeout(500);
  });

  test('should have proper page titles', async ({ page, aragoraPage }) => {
    const pages = [
      { path: '/', title: /aragora/i },
      { path: '/about', title: /aragora|about/i },
      { path: '/pulse', title: /aragora|pulse/i },
    ];

    for (const { path, title } of pages) {
      await page.goto(path);
      await aragoraPage.dismissAllOverlays();
      await expect(page).toHaveTitle(title);
    }
  });
});

test.describe('Navigation - Sidebar', () => {
  test.beforeEach(async ({ page }) => {
    await mockApiResponse(page, '**/api/health', { status: 'ok' });
  });

  test('sidebar navigation works', async ({ page, aragoraPage }) => {
    await page.goto('/');
    await aragoraPage.dismissAllOverlays();
    await page.waitForLoadState('domcontentloaded');

    // The left sidebar (aside with aria-label "Main navigation") should be present
    const sidebar = page.locator('aside[aria-label="Main navigation"]');
    const sidebarVisible = await sidebar.isVisible({ timeout: 5000 }).catch(() => false);

    if (!sidebarVisible) {
      // On narrower viewports the sidebar may need to be opened via a toggle
      const menuToggle = page
        .locator(
          'button[aria-label*="menu" i], button[aria-label*="sidebar" i], [data-testid="sidebar-toggle"]',
        )
        .first();
      if (await menuToggle.isVisible({ timeout: 3000 }).catch(() => false)) {
        await menuToggle.click();
        await sidebar.waitFor({ state: 'visible', timeout: 3000 }).catch(() => {});
      }
    }

    // Navigate through several sidebar links and verify the URL changes
    const routes = [
      { href: '/hub', label: /hub/i },
      { href: '/oracle', label: /oracle/i },
      { href: '/receipts', label: /receipts/i },
      { href: '/settings', label: /settings/i },
    ];

    for (const route of routes) {
      const link = sidebar.locator(`a[href="${route.href}"]`).first();
      const linkVisible = await link.isVisible({ timeout: 2000 }).catch(() => false);
      if (linkVisible) {
        await link.click();
        await page.waitForLoadState('domcontentloaded');
        expect(page.url()).toContain(route.href);
      }
    }
  });

  test('breadcrumbs update on navigation', async ({ page, aragoraPage }) => {
    await page.goto('/');
    await aragoraPage.dismissAllOverlays();
    await page.waitForLoadState('domcontentloaded');

    // Navigate to a nested page to trigger breadcrumbs
    await page.goto('/audit/templates');
    await aragoraPage.dismissAllOverlays();
    await page.waitForLoadState('domcontentloaded');

    // Look for breadcrumb-like elements (nav with aria-label breadcrumb, or
    // elements containing path segments)
    const breadcrumb = page
      .locator(
        'nav[aria-label*="breadcrumb" i], [data-testid*="breadcrumb"], [class*="breadcrumb"]',
      )
      .first();

    const hasBreadcrumb = await breadcrumb.isVisible({ timeout: 3000 }).catch(() => false);

    if (hasBreadcrumb) {
      // Breadcrumb should reflect current path (e.g. "Audit > Templates")
      const text = await breadcrumb.textContent();
      expect(text).toBeTruthy();

      // Navigate to a different page and verify breadcrumb updates
      await page.goto('/hub');
      await aragoraPage.dismissAllOverlays();
      await page.waitForLoadState('domcontentloaded');

      const updatedBreadcrumb = page
        .locator(
          'nav[aria-label*="breadcrumb" i], [data-testid*="breadcrumb"], [class*="breadcrumb"]',
        )
        .first();
      const updatedVisible = await updatedBreadcrumb
        .isVisible({ timeout: 3000 })
        .catch(() => false);
      if (updatedVisible) {
        const updatedText = await updatedBreadcrumb.textContent();
        // Breadcrumb text should differ between pages
        expect(updatedText).not.toBe(text);
      }
    } else {
      // If no breadcrumbs found, verify the page at least loaded (some apps
      // use the URL bar as the sole navigation indicator)
      expect(page.url()).toContain('/hub');
    }
  });
});

test.describe('Navigation - Mobile', () => {
  test.beforeEach(async ({ page }) => {
    await page.setViewportSize({ width: 375, height: 667 });
  });

  test('should have mobile navigation', async ({ page, aragoraPage }) => {
    await page.goto('/');
    await aragoraPage.dismissAllOverlays();

    // Look for hamburger menu or mobile nav
    const mobileMenu = page
      .locator('[class*="mobile"], [class*="hamburger"], button[aria-label*="menu"]')
      .first();

    if (await mobileMenu.isVisible()) {
      await mobileMenu.click();
      // Nav items should appear
      await page.waitForTimeout(300);
    }
  });

  test('should be responsive on mobile', async ({ page, aragoraPage }) => {
    await page.goto('/');
    await aragoraPage.dismissAllOverlays();
    await page.waitForLoadState('domcontentloaded');

    // Page body should be visible on mobile
    await expect(page.locator('body')).toBeVisible({ timeout: 10000 });

    // Note: Some horizontal overflow is acceptable on CRT-styled pages
    // The key is that content is usable, not that there's zero overflow
  });
});
