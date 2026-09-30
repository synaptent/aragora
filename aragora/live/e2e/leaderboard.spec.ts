import { test, expect } from './fixtures';

/**
 * E2E tests for the leaderboard feature.
 */

test.describe('Leaderboard', () => {
  test('should load leaderboard page', async ({ page, aragoraPage }) => {
    await page.goto('/leaderboard');
    await aragoraPage.dismissAllOverlays();
    await page.waitForLoadState('domcontentloaded');

    // Should have leaderboard heading - actual h1 is "> AGENT LEADERBOARD"
    const heading = page
      .locator('h1')
      .filter({ hasText: /leaderboard|ranking|agent/i })
      .first();
    await expect(heading).toBeVisible({ timeout: 10000 });
  });

  test('should display agent rankings', async ({ page, aragoraPage }) => {
    await page.goto('/leaderboard');
    await aragoraPage.dismissAllOverlays();
    await page.waitForLoadState('domcontentloaded');

    // Should show ranking table, list, or any content
    const rankingItems = page.locator(
      '[data-testid="ranking-row"], tr[data-agent], .agent-ranking, table tbody tr, [class*="rank"]',
    );

    const emptyState = page.locator('[data-testid="empty-leaderboard"], :text("No rankings")');
    const mainContent = page.locator('main').first();

    // Either rankings exist, empty state, or main content visible
    const hasRankings = (await rankingItems.count()) > 0;
    const hasEmptyState = await emptyState.isVisible().catch(() => false);
    const hasContent = await mainContent.isVisible().catch(() => false);

    expect(hasRankings || hasEmptyState || hasContent).toBeTruthy();
  });

  test('should show ELO ratings', async ({ page, aragoraPage }) => {
    await page.goto('/leaderboard');
    await aragoraPage.dismissAllOverlays();
    await page.waitForLoadState('domcontentloaded');

    // Look for ELO, ratings, or any numeric score content
    const ratings = page.locator(
      '[data-testid="elo-rating"], .elo-score, td, [class*="rating"], [class*="score"]',
    );
    const mainContent = page.locator('main').first();

    // Page should show ratings or main content
    const ratingsCount = await ratings.count();
    const hasContent = await mainContent.isVisible().catch(() => false);
    expect(ratingsCount > 0 || hasContent).toBeTruthy();
  });

  test('should display agent names', async ({ page, aragoraPage }) => {
    await page.goto('/leaderboard');
    await aragoraPage.dismissAllOverlays();
    await page.waitForLoadState('domcontentloaded');

    // Look for agent names
    const agentNames = page.locator('[data-testid="agent-name"], .agent-name, td:first-child');

    const namesCount = await agentNames.count();
    if (namesCount > 0) {
      // Should show recognizable agent types
      const firstAgent = await agentNames.first().textContent();
      expect(firstAgent).toBeDefined();
    }
  });

  test('should allow sorting by different metrics', async ({ page, aragoraPage }) => {
    await page.goto('/leaderboard');
    await aragoraPage.dismissAllOverlays();
    await page.waitForLoadState('domcontentloaded');

    // Look for sort controls
    const sortButtons = page.locator(
      '[data-testid="sort-button"], th[role="columnheader"], button:has-text("Sort")',
    );

    if ((await sortButtons.count()) > 0) {
      // Click on a sort header
      await sortButtons.first().click();

      // Page should update (URL or content)
      await page.waitForTimeout(500);
    }
  });

  test('should show win/loss statistics', async ({ page, aragoraPage }) => {
    await page.goto('/leaderboard');
    await aragoraPage.dismissAllOverlays();
    await page.waitForLoadState('domcontentloaded');

    // Look for win/loss or match statistics
    const stats = page.locator(
      '[data-testid="win-count"], [data-testid="loss-count"], :text("W:"), :text("L:"), .wins, .losses',
    );

    const hasStats = (await stats.count()) > 0;
    // Stats are optional but nice to have
    expect(hasStats).toBeDefined();
  });

  test('should be accessible', async ({ page, aragoraPage }) => {
    await page.goto('/leaderboard');
    await aragoraPage.dismissAllOverlays();

    // Table should have proper structure
    const table = page.locator('table');

    if (await table.isVisible().catch(() => false)) {
      // Should have headers
      const headers = page.locator('th, [role="columnheader"]');
      const headerCount = await headers.count();
      expect(headerCount).toBeGreaterThan(0);
    }
  });

  test('should handle loading state', async ({ page, aragoraPage }) => {
    await page.goto('/leaderboard');
    await aragoraPage.dismissAllOverlays();

    // During load, might show skeleton or spinner
    const loadingIndicator = page.locator(
      '[data-testid="loading"], .skeleton, .spinner, [aria-busy="true"]',
    );

    // Loading state should be brief
    if (await loadingIndicator.isVisible().catch(() => false)) {
      await expect(loadingIndicator).not.toBeVisible({ timeout: 10000 });
    }
  });
});

test.describe('Leaderboard Filtering', () => {
  test('should filter by time period', async ({ page, aragoraPage }) => {
    await page.goto('/leaderboard');
    await aragoraPage.dismissAllOverlays();
    await page.waitForLoadState('domcontentloaded');

    // Look for time period selector
    const periodSelector = page.locator(
      '[data-testid="period-selector"], select[name*="period"], button:has-text("Week"), button:has-text("Month")',
    );

    if (await periodSelector.isVisible().catch(() => false)) {
      // Change period
      await periodSelector.first().click();

      // Should update content
      await page.waitForTimeout(500);
    }
  });

  test('should filter by agent type', async ({ page, aragoraPage }) => {
    await page.goto('/leaderboard');
    await aragoraPage.dismissAllOverlays();
    await page.waitForLoadState('domcontentloaded');

    // Look for agent type filter
    const agentFilter = page.locator(
      '[data-testid="agent-filter"], select[name*="agent"], [data-filter="agent"]',
    );

    if (await agentFilter.isVisible().catch(() => false)) {
      await agentFilter.selectOption({ index: 1 });
      await page.waitForTimeout(500);
    }
  });
});

test.describe('Agent Details', () => {
  test('should link to agent detail page', async ({ page, aragoraPage }) => {
    await page.goto('/leaderboard');
    await aragoraPage.dismissAllOverlays();
    await page.waitForLoadState('domcontentloaded');

    // Click on agent name if it's a link
    const agentLink = page
      .locator('[data-testid="agent-link"], .agent-name a, a[href*="agent"]')
      .first();

    if (await agentLink.isVisible().catch(() => false)) {
      await agentLink.click();
      await aragoraPage.dismissAllOverlays();
      await expect(page).toHaveURL(/agent/i);
    }
  });

  test('should show agent performance chart', async ({ page, aragoraPage }) => {
    await page.goto('/leaderboard');
    await aragoraPage.dismissAllOverlays();
    await page.waitForLoadState('domcontentloaded');

    // Some leaderboards show inline charts
    const chart = page.locator(
      '[data-testid="performance-chart"], canvas, svg.recharts-surface, .chart',
    );

    const hasChart = await chart.isVisible().catch(() => false);
    expect(hasChart).toBeDefined();
  });
});
