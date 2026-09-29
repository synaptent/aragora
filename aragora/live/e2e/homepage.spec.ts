import type { Locator, Page } from '@playwright/test';
import { test, expect } from './fixtures';

/**
 * E2E tests for the Aragora homepage and navigation.
 */

async function openResponsiveHeaderNav(page: Page): Promise<Locator> {
  const desktopNav = page.locator('header nav').first();
  if (await desktopNav.isVisible().catch(() => false)) {
    return desktopNav;
  }

  const mobileMenuButton = page.getByRole('button', { name: /open menu|close menu/i }).first();
  await expect(mobileMenuButton).toBeVisible();
  if ((await mobileMenuButton.getAttribute('aria-expanded')) !== 'true') {
    await mobileMenuButton.click();
  }

  const mobileNav = page
    .locator('nav')
    .filter({ has: page.getByRole('link', { name: 'Sign up free' }) });
  await expect(mobileNav).toBeVisible();
  return mobileNav;
}

test.describe('Homepage', () => {
  test('should load successfully', async ({ page, aragoraPage }) => {
    await page.goto('/');
    await aragoraPage.dismissAllOverlays();

    // Should have a title
    await expect(page).toHaveTitle(/Aragora/i);

    // Should show main heading or logo
    const heading = page.locator('h1, [data-testid="logo"]').first();
    await expect(heading).toBeVisible();
  });

  test('should display navigation', async ({ page, aragoraPage }) => {
    await page.goto('/');
    await aragoraPage.dismissAllOverlays();

    const nav = await openResponsiveHeaderNav(page);
    await expect(nav.getByRole('link', { name: 'Quickstart' })).toBeVisible();
    await expect(nav.getByRole('link', { name: 'Docs' }).first()).toBeVisible();
    await expect(nav.getByRole('link', { name: 'Pricing' }).first()).toBeVisible();
  });

  test('should be responsive on mobile', async ({ page, aragoraPage }) => {
    // Set mobile viewport
    await page.setViewportSize({ width: 375, height: 667 });
    await page.goto('/');
    await aragoraPage.dismissAllOverlays();

    // Page should still be functional
    await expect(page).toHaveTitle(/Aragora/i);

    // Content should not overflow horizontally
    const body = page.locator('body');
    const bodyBox = await body.boundingBox();
    expect(bodyBox?.width).toBeLessThanOrEqual(375);
  });

  test('should have no console errors on load', async ({ page, aragoraPage }) => {
    const consoleErrors: string[] = [];
    page.on('console', (msg) => {
      if (msg.type() === 'error') {
        consoleErrors.push(msg.text());
      }
    });

    await page.goto('/');
    await aragoraPage.dismissAllOverlays();
    await page.waitForLoadState('domcontentloaded');

    // Filter out expected errors:
    // - WebSocket: connection may fail in test environment
    // - favicon: missing favicon is not critical
    // - CORS: expected when testing cross-origin (e.g., localhost -> live.aragora.ai)
    // - ERR_FAILED: usually accompanies CORS errors
    // - 404: some resources may not exist in production
    const unexpectedErrors = consoleErrors.filter(
      (err) =>
        !err.includes('WebSocket') &&
        !err.includes('favicon') &&
        !err.includes('CORS') &&
        !err.includes('ERR_FAILED') &&
        !err.includes('404') &&
        !err.includes('429') &&
        !err.includes('Too Many Requests'),
    );

    expect(unexpectedErrors).toHaveLength(0);
  });

  test('should have accessible page structure', async ({ page, aragoraPage }) => {
    await page.goto('/');
    await aragoraPage.dismissAllOverlays();

    await expect(page.locator('header, [role="banner"]').first()).toBeVisible();
    await expect(page.locator('footer, [role="contentinfo"]').first()).toBeVisible();

    const headings = page.locator('h1, h2, h3');
    const headingCount = await headings.count();
    expect(headingCount).toBeGreaterThan(0);
  });
});

test.describe('Navigation', () => {
  test('should navigate to quickstart page', async ({ page, aragoraPage }) => {
    await page.goto('/');
    await aragoraPage.dismissAllOverlays();

    const nav = await openResponsiveHeaderNav(page);
    await nav.getByRole('link', { name: 'Quickstart' }).first().click();
    await expect(page).toHaveURL(/quickstart/i);
  });

  test('should navigate to pricing', async ({ page, aragoraPage }) => {
    await page.goto('/');
    await aragoraPage.dismissAllOverlays();

    const nav = await openResponsiveHeaderNav(page);
    await nav.getByRole('link', { name: 'Pricing' }).first().click();
    await expect(page).toHaveURL(/pricing/i);
  });

  test('should navigate back to homepage from any page', async ({ page, aragoraPage }) => {
    await page.goto('/debates');
    await aragoraPage.dismissAllOverlays();

    // Click on logo or home link
    const homeLink = page.locator('a[href="/"], [data-testid="logo"]').first();
    await homeLink.click();
    await expect(page).toHaveURL(/.*\/$/);
  });
});
