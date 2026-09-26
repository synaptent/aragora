/**
 * Critical Path Smoke Tests
 *
 * Minimal page-load tests that verify core pages render without crashing
 * and contain expected key elements. These are NOT full integration tests --
 * they verify the happy path of "page loads and shows something meaningful".
 *
 * Assumes a running dev server at localhost:3000 (or PLAYWRIGHT_BASE_URL).
 */

import { test, expect, mockApiResponse } from './fixtures';

test.describe('Critical Path - Page Load Smoke Tests', () => {
  test.beforeEach(async ({ page }) => {
    // Mock health endpoint so pages don't stall waiting for a real backend
    await mockApiResponse(page, '**/api/health', { status: 'ok', version: '1.0.0' });
  });

  test('landing page loads', async ({ page, aragoraPage }) => {
    await page.goto('/');
    await aragoraPage.dismissAllOverlays();
    await page.waitForLoadState('domcontentloaded');

    // Page title should contain "Aragora"
    await expect(page).toHaveTitle(/aragora/i);

    // Body is visible and main content area renders
    await expect(page.locator('body')).toBeVisible();

    // Should have some form of navigation (header, nav, or sidebar)
    const nav = page.locator('header, nav, [role="navigation"], aside').first();
    await expect(nav).toBeVisible({ timeout: 10_000 });
  });

  test('hub page accessible', async ({ page, aragoraPage }) => {
    await page.goto('/hub');
    await aragoraPage.dismissAllOverlays();
    await page.waitForLoadState('domcontentloaded');

    // URL should reflect /hub
    expect(page.url()).toContain('/hub');

    // Hub page has a hero heading asking "What do you want to do?"
    const heading = page.locator('h1');
    await expect(heading).toBeVisible({ timeout: 10_000 });
    await expect(heading).toContainText(/what do you want/i);

    // Quick debate input should be present
    const debateInput = page
      .locator('input[placeholder*="topic" i], input[placeholder*="debate" i]')
      .first();
    await expect(debateInput).toBeVisible();
  });

  test('debate page loads', async ({ page, aragoraPage }) => {
    // Oracle is the main debate interface
    await page.goto('/oracle');
    await aragoraPage.dismissAllOverlays();
    await page.waitForLoadState('domcontentloaded');

    expect(page.url()).toContain('/oracle');

    // Page body renders without crash
    await expect(page.locator('body')).toBeVisible();

    // Oracle page should have some interactive element (input, button, or form)
    const interactiveEl = page.locator('input, textarea, button, [role="textbox"], form').first();
    await expect(interactiveEl).toBeVisible({ timeout: 10_000 });
  });

  test('receipts page loads', async ({ page, aragoraPage }) => {
    // Mock receipts API so the page renders without a real backend
    await mockApiResponse(page, '**/api/v2/receipts**', { receipts: [], total: 0 });
    await mockApiResponse(page, '**/api/gauntlet/results**', { results: [], total: 0 });

    await page.goto('/receipts');
    await aragoraPage.dismissAllOverlays();
    await page.waitForLoadState('domcontentloaded');

    expect(page.url()).toContain('/receipts');

    // Receipts page has a heading with "Decision Receipts"
    const heading = page
      .locator('h1, h2')
      .filter({ hasText: /decision receipts/i })
      .first();
    await expect(heading).toBeVisible({ timeout: 10_000 });
  });

  test('settings page loads', async ({ page, aragoraPage }) => {
    await page.goto('/settings');
    await aragoraPage.dismissAllOverlays();
    await page.waitForLoadState('domcontentloaded');

    expect(page.url()).toContain('/settings');

    // Settings page should have a heading
    const heading = page.getByRole('heading', { name: /settings/i });
    await expect(heading).toBeVisible({ timeout: 10_000 });

    // At least one tab should be visible (Features, Debate, Appearance, etc.)
    const anyTab = page.getByRole('tab').first();
    await expect(anyTab).toBeVisible();
  });
});
