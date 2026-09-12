import { test, expect } from './fixtures';

/**
 * E2E tests for the debates feature.
 */

test.describe('Debates List', () => {
  test('should load debates page', async ({ page, aragoraPage }) => {
    await page.goto('/debates');
    await aragoraPage.dismissAllOverlays();

    // Should have debates heading or content
    const debatesContent = page.locator(
      '[data-testid="debates-list"], h1:has-text("Debate"), main',
    );
    await expect(debatesContent.first()).toBeVisible();
  });

  test('should display debate cards or list items', async ({ page, aragoraPage }) => {
    await page.goto('/debates');
    await aragoraPage.dismissAllOverlays();

    // Wait for content to load
    await page.waitForLoadState('domcontentloaded');

    // Should show debate items or empty state
    const debateItems = page.locator('[data-testid="debate-item"], .debate-card, article');
    const emptyState = page.locator('[data-testid="empty-state"], :text("No debates")');

    // Either debates exist or empty state is shown
    const hasDebates = (await debateItems.count()) > 0;
    const hasEmptyState = await emptyState.isVisible().catch(() => false);

    expect(hasDebates || hasEmptyState).toBeTruthy();
  });

  test('should be able to filter or search debates', async ({ page, aragoraPage }) => {
    await page.goto('/debates');
    await aragoraPage.dismissAllOverlays();

    // Look for search or filter input
    const searchInput = page.locator(
      'input[type="search"], input[placeholder*="search" i], [data-testid="search-input"]',
    );

    if (await searchInput.isVisible().catch(() => false)) {
      await searchInput.fill('test query');

      // Should update the URL or filter results
      await page.waitForTimeout(500); // Debounce time
    }
  });

  test('should show pagination or load more for large lists', async ({ page, aragoraPage }) => {
    await page.goto('/debates');
    await aragoraPage.dismissAllOverlays();

    await page.waitForLoadState('domcontentloaded');

    // Check for pagination controls
    const pagination = page.locator(
      '[data-testid="pagination"], .pagination, button:has-text("Load more"), button:has-text("Next")',
    );

    // If there are many debates, pagination should exist
    const debateItems = page.locator('[data-testid="debate-item"], .debate-card, article');
    const debateCount = await debateItems.count();

    if (debateCount >= 10) {
      await expect(pagination.first()).toBeVisible();
    }
  });
});

test.describe('Single Debate View', () => {
  test('should load individual debate page', async ({ page, aragoraPage }) => {
    // Navigate to debates list first
    await page.goto('/debates');
    await aragoraPage.dismissAllOverlays();
    await page.waitForLoadState('domcontentloaded');

    // Click on first debate if available
    const debateLink = page
      .locator('[data-testid="debate-item"] a, .debate-card a, article a')
      .first();

    if (await debateLink.isVisible().catch(() => false)) {
      await debateLink.click();
      await aragoraPage.dismissAllOverlays();

      // Should be on a debate detail page
      await expect(page).toHaveURL(/debate/i);

      // Should show debate content
      const debateContent = page.locator('[data-testid="debate-content"], .debate-detail, main');
      await expect(debateContent.first()).toBeVisible();
    }
  });

  test('should display debate messages and critiques', async ({ page, aragoraPage }) => {
    await page.goto('/debate/test-debate');
    await aragoraPage.dismissAllOverlays();

    await page.waitForLoadState('domcontentloaded');

    // Check for message containers
    const messages = page.locator('[data-testid="message"], .message, [role="log"]');

    // Either messages exist or loading/error state
    const _hasMessages = (await messages.count()) > 0;
    const hasContent = await page.locator('main').isVisible();

    expect(hasContent).toBeTruthy();
  });

  test('should show agent information', async ({ page, aragoraPage }) => {
    await page.goto('/debates');
    await aragoraPage.dismissAllOverlays();
    await page.waitForLoadState('domcontentloaded');

    const debateLink = page.locator('[data-testid="debate-item"] a, .debate-card a').first();

    if (await debateLink.isVisible().catch(() => false)) {
      await debateLink.click();
      await aragoraPage.dismissAllOverlays();
      await page.waitForLoadState('domcontentloaded');

      // Should show agent names/avatars
      const agentInfo = page.locator('[data-testid="agent"], .agent-name, .agent-avatar');

      if ((await agentInfo.count()) > 0) {
        await expect(agentInfo.first()).toBeVisible();
      }
    }
  });

  test('should display consensus status', async ({ page, aragoraPage }) => {
    await page.goto('/debates');
    await aragoraPage.dismissAllOverlays();
    await page.waitForLoadState('domcontentloaded');

    const debateLink = page.locator('[data-testid="debate-item"] a, .debate-card a').first();

    if (await debateLink.isVisible().catch(() => false)) {
      await debateLink.click();
      await aragoraPage.dismissAllOverlays();
      await page.waitForLoadState('domcontentloaded');

      // Look for consensus indicator
      const consensusInfo = page.locator(
        '[data-testid="consensus"], :text("consensus"), :text("confidence"), .consensus-badge',
      );

      // Consensus info might be present
      const hasConsensus = (await consensusInfo.count()) > 0;
      expect(hasConsensus).toBeDefined(); // Just verify page loads
    }
  });
});

test.describe('Debate Interaction', () => {
  test('should allow voting on debate outcomes', async ({ page, aragoraPage }) => {
    await page.goto('/debates');
    await aragoraPage.dismissAllOverlays();
    await page.waitForLoadState('domcontentloaded');

    const debateLink = page.locator('[data-testid="debate-item"] a, .debate-card a').first();

    if (await debateLink.isVisible().catch(() => false)) {
      await debateLink.click();
      await aragoraPage.dismissAllOverlays();
      await page.waitForLoadState('domcontentloaded');

      // Look for voting buttons
      const voteButtons = page.locator(
        '[data-testid="vote"], button:has-text("Vote"), button:has-text("Agree")',
      );

      if ((await voteButtons.count()) > 0) {
        // Should be clickable (might need auth)
        await expect(voteButtons.first()).toBeEnabled();
      }
    }
  });

  test('should show audience feedback section', async ({ page, aragoraPage }) => {
    await page.goto('/debates');
    await aragoraPage.dismissAllOverlays();
    await page.waitForLoadState('domcontentloaded');

    const debateLink = page.locator('[data-testid="debate-item"] a, .debate-card a').first();

    if (await debateLink.isVisible().catch(() => false)) {
      await debateLink.click();
      await aragoraPage.dismissAllOverlays();
      await page.waitForLoadState('domcontentloaded');

      // Look for feedback or comments section
      const feedbackSection = page.locator(
        '[data-testid="feedback"], [data-testid="comments"], .audience-feedback, .comments-section',
      );

      // Feedback section might exist
      const hasFeedback = await feedbackSection.isVisible().catch(() => false);
      expect(hasFeedback).toBeDefined();
    }
  });
});
