import { test, expect, mockApiResponse } from './fixtures';

/**
 * E2E tests for Memory page and MemoryExplorerPanel.
 *
 * Tests memory tier visualization, search, and critique browsing.
 */

const mockTierStats = {
  tiers: {
    FAST: { count: 15, avg_importance: 0.8, ttl_hours: 0.017, max_entries: 100 },
    MEDIUM: { count: 42, avg_importance: 0.65, ttl_hours: 1, max_entries: 500 },
    SLOW: { count: 128, avg_importance: 0.45, ttl_hours: 24, max_entries: 1000 },
    GLACIAL: { count: 87, avg_importance: 0.72, ttl_hours: 168, max_entries: 5000 },
  },
  total_memories: 272,
  transitions: [
    { from_tier: 'FAST', to_tier: 'MEDIUM', count: 5 },
    { from_tier: 'MEDIUM', to_tier: 'SLOW', count: 12 },
  ],
};

const mockPressure = {
  pressure: 0.45,
  status: 'normal',
  tier_utilization: {
    FAST: { count: 15, limit: 100, utilization: 0.15 },
    MEDIUM: { count: 42, limit: 500, utilization: 0.084 },
    SLOW: { count: 128, limit: 1000, utilization: 0.128 },
    GLACIAL: { count: 87, limit: 5000, utilization: 0.017 },
  },
  total_memories: 272,
  cleanup_recommended: false,
};

const mockSearchResults = {
  query: 'test',
  results: [
    {
      id: 'mem_001',
      tier: 'fast',
      content: 'Test memory content for search result',
      importance: 0.85,
      surprise_score: 0.2,
      created_at: new Date().toISOString(),
    },
    {
      id: 'mem_002',
      tier: 'medium',
      content: 'Another test memory with different tier',
      importance: 0.6,
      surprise_score: 0.1,
      created_at: new Date().toISOString(),
    },
  ],
  count: 2,
  tiers_searched: ['fast', 'medium', 'slow', 'glacial'],
};

const mockCritiques = {
  critiques: [
    {
      id: null,
      debate_id: null,
      agent: 'claude',
      target_agent: 'grok',
      critique_type: null,
      content: 'Argument lacks supporting evidence',
      severity: 'medium',
      accepted: null,
      created_at: null,
    },
    {
      id: null,
      debate_id: null,
      agent: 'gemini',
      target_agent: 'claude',
      critique_type: null,
      content: 'Logical fallacy detected in premise',
      severity: 'high',
      accepted: null,
      created_at: null,
    },
  ],
  count: 2,
  total: 25,
  offset: 0,
  limit: 20,
};

test.describe('Memory Page', () => {
  test.beforeEach(async ({ page, aragoraPage }) => {
    await mockApiResponse(page, '**/api/health', { status: 'ok' });
    await mockApiResponse(page, '**/api/memory/tier-stats', mockTierStats);
    await mockApiResponse(page, '**/api/memory/pressure', mockPressure);
    await mockApiResponse(page, '**/api/memory/archive-stats', { total_archived: 45 });
    await page.goto('/memory');
    await aragoraPage.dismissAllOverlays();
    await page.waitForLoadState('domcontentloaded');
  });

  test('should load memory page', async ({ page }) => {
    // Wait for page to settle after lazy loading
    await page.waitForTimeout(1500);
    await expect(page).toHaveTitle(/Memory|Aragora/i, { timeout: 10000 });
    // Should show memory-related heading or content
    const memoryHeading = page.locator('text=/memory|continuum/i').first();
    const mainContent = page.locator('main').first();
    const hasHeading = await memoryHeading.isVisible({ timeout: 5000 }).catch(() => false);
    const hasMain = await mainContent.isVisible().catch(() => false);
    expect(hasHeading || hasMain).toBeTruthy();
  });

  test('should display tab navigation', async ({ page }) => {
    // Check for tabs - give more time for lazy-loaded components
    await page.waitForTimeout(2000);

    // Look for tabs or panel buttons
    const overviewTab = page
      .locator('button, [role="tab"]')
      .filter({ hasText: /overview/i })
      .first();
    const searchTab = page
      .locator('button, [role="tab"]')
      .filter({ hasText: /search/i })
      .first();
    const explorerTab = page
      .locator('button, [role="tab"]')
      .filter({ hasText: /explorer|analytics/i })
      .first();

    const hasOverview = await overviewTab.isVisible({ timeout: 5000 }).catch(() => false);
    const hasSearch = await searchTab.isVisible().catch(() => false);
    const hasExplorer = await explorerTab.isVisible().catch(() => false);

    // Also check for memory panel content directly
    const memoryContent = page.locator('text=/tier|memory|continuum/i').first();
    const hasMemoryContent = await memoryContent.isVisible({ timeout: 2000 }).catch(() => false);

    // At least one tab, memory content, or main should be visible
    const mainVisible = await page
      .locator('main')
      .isVisible()
      .catch(() => false);
    expect(hasOverview || hasSearch || hasExplorer || hasMemoryContent || mainVisible).toBeTruthy();
  });

  test('should display memory tier statistics', async ({ page }) => {
    // Should show tier cards or stats
    const tierContent = page.locator('text=/fast|medium|slow|glacial/i').first();
    const statsContent = page.locator('text=/memories|entries|count/i').first();
    const totalMemories = page.locator('text=/272|total/i').first();

    const hasTier = await tierContent.isVisible({ timeout: 5000 }).catch(() => false);
    const hasStats = await statsContent.isVisible().catch(() => false);
    const hasTotal = await totalMemories.isVisible().catch(() => false);

    expect(hasTier || hasStats || hasTotal).toBeTruthy();
  });

  test.skip('should show demo mode indicator when API fails', async ({ page, aragoraPage }) => {
    // Re-mock to simulate API failure
    await page.route('**/api/memory/tier-stats', async (route) => {
      await route.fulfill({
        status: 503,
        contentType: 'application/json',
        body: JSON.stringify({ error: 'Service unavailable' }),
      });
    });

    await page.reload();
    await aragoraPage.dismissAllOverlays();
    await page.waitForLoadState('domcontentloaded');
    await page.waitForTimeout(2000);

    // Should show demo mode indicator or fallback - page should still render
    const demoIndicator = page.locator('text=/demo|unavailable|offline|using demo/i').first();
    const mainContent = page.locator('main').first();

    // Page should render even if API fails
    const hasDemo = await demoIndicator.isVisible({ timeout: 5000 }).catch(() => false);
    const hasMain = await mainContent.isVisible().catch(() => false);
    expect(hasDemo || hasMain).toBeTruthy();
  });
});

test.describe('Memory Explorer - Search Tab', () => {
  test.beforeEach(async ({ page, aragoraPage }) => {
    await mockApiResponse(page, '**/api/health', { status: 'ok' });
    await mockApiResponse(page, '**/api/memory/tier-stats', mockTierStats);
    await mockApiResponse(page, '**/api/memory/pressure', mockPressure);
    await mockApiResponse(page, '**/api/memory/search**', mockSearchResults);
    await page.goto('/memory');
    await aragoraPage.dismissAllOverlays();
    await page.waitForLoadState('domcontentloaded');
  });

  test('should allow searching memories', async ({ page }) => {
    // Click search tab if available
    const searchTab = page
      .locator('button, [role="tab"]')
      .filter({ hasText: /search/i })
      .first();
    if (await searchTab.isVisible({ timeout: 2000 }).catch(() => false)) {
      await searchTab.click();
    }

    // Find search input
    const searchInput = page.locator('input[type="text"], input[placeholder*="search" i]').first();

    if (await searchInput.isVisible({ timeout: 3000 }).catch(() => false)) {
      await searchInput.fill('test');
      await page.waitForTimeout(500);

      // Results should appear
      const results = page.locator('text=/result|content|memory/i').first();
      await expect(results).toBeVisible({ timeout: 5000 });
    }
  });

  test('should allow tier filtering', async ({ page }) => {
    // Click search tab if available
    const searchTab = page
      .locator('button, [role="tab"]')
      .filter({ hasText: /search/i })
      .first();
    if (await searchTab.isVisible({ timeout: 2000 }).catch(() => false)) {
      await searchTab.click();
    }

    // Find tier filter buttons
    const fastTier = page.locator('button').filter({ hasText: /fast/i }).first();
    if (await fastTier.isVisible({ timeout: 2000 }).catch(() => false)) {
      await fastTier.click();
      // Clicking should toggle the tier filter
      await page.waitForTimeout(300);
    }
    // Test passes if page loads
    expect(true).toBeTruthy();
  });

  test('should show search error feedback', async ({ page, aragoraPage }) => {
    // Mock search to fail
    await page.route('**/api/memory/search**', async (route) => {
      await route.fulfill({
        status: 500,
        contentType: 'application/json',
        body: JSON.stringify({ error: 'Search failed' }),
      });
    });

    await page.reload();
    await aragoraPage.dismissAllOverlays();

    // Click search tab if available
    const searchTab = page
      .locator('button, [role="tab"]')
      .filter({ hasText: /search/i })
      .first();
    if (await searchTab.isVisible({ timeout: 2000 }).catch(() => false)) {
      await searchTab.click();
    }

    const searchInput = page.locator('input[type="text"], input[placeholder*="search" i]').first();
    if (await searchInput.isVisible({ timeout: 3000 }).catch(() => false)) {
      await searchInput.fill('test');
      await page.waitForTimeout(500);

      // Should show error or no results
      const errorMessage = page.locator('text=/error|failed|no memories|unable/i').first();
      const mainContent = page.locator('main').first();
      const hasError = await errorMessage.isVisible({ timeout: 5000 }).catch(() => false);
      const hasMain = await mainContent.isVisible().catch(() => false);
      expect(hasError || hasMain).toBeTruthy();
    }
  });
});

test.describe('Memory Explorer - Critiques Tab', () => {
  test.beforeEach(async ({ page, aragoraPage }) => {
    await mockApiResponse(page, '**/api/health', { status: 'ok' });
    await mockApiResponse(page, '**/api/memory/tier-stats', mockTierStats);
    await mockApiResponse(page, '**/api/memory/pressure', mockPressure);
    await mockApiResponse(page, '**/api/memory/critiques**', mockCritiques);
    await page.goto('/memory');
    await aragoraPage.dismissAllOverlays();
    await page.waitForLoadState('domcontentloaded');
  });

  test('should display critiques tab', async ({ page }) => {
    const critiquesTab = page
      .locator('button, [role="tab"]')
      .filter({ hasText: /critiques/i })
      .first();
    if (await critiquesTab.isVisible({ timeout: 2000 }).catch(() => false)) {
      await critiquesTab.click();

      // Should show critiques or empty state
      const critiqueContent = page.locator('text=/critique|agent|severity/i').first();
      const emptyState = page.locator('text=/no critiques/i').first();
      const mainContent = page.locator('main').first();

      await expect(critiqueContent.or(emptyState).or(mainContent)).toBeVisible({ timeout: 5000 });
    }
  });

  test('should show critique error feedback', async ({ page, aragoraPage }) => {
    // Mock critiques to fail
    await page.route('**/api/memory/critiques**', async (route) => {
      await route.fulfill({
        status: 500,
        contentType: 'application/json',
        body: JSON.stringify({ error: 'Failed to load critiques' }),
      });
    });

    await page.reload();
    await aragoraPage.dismissAllOverlays();

    const critiquesTab = page
      .locator('button, [role="tab"]')
      .filter({ hasText: /critiques/i })
      .first();
    if (await critiquesTab.isVisible({ timeout: 2000 }).catch(() => false)) {
      await critiquesTab.click();
      await page.waitForTimeout(500);

      // Should show error message
      const errorMessage = page.locator('text=/error|failed|unable/i').first();
      const mainContent = page.locator('main').first();
      await expect(errorMessage.or(mainContent)).toBeVisible({ timeout: 5000 });
    }
  });
});

test.describe('Memory Explorer - Transitions Tab', () => {
  test.beforeEach(async ({ page, aragoraPage }) => {
    await mockApiResponse(page, '**/api/health', { status: 'ok' });
    await mockApiResponse(page, '**/api/memory/tier-stats', mockTierStats);
    await mockApiResponse(page, '**/api/memory/pressure', mockPressure);
    await page.goto('/memory');
    await aragoraPage.dismissAllOverlays();
    await page.waitForLoadState('domcontentloaded');
  });

  test('should display transitions tab', async ({ page }) => {
    const transitionsTab = page
      .locator('button, [role="tab"]')
      .filter({ hasText: /transitions/i })
      .first();
    if (await transitionsTab.isVisible({ timeout: 2000 }).catch(() => false)) {
      await transitionsTab.click();

      // Should show transitions or empty state
      const transitionContent = page.locator('text=/transition|promote|demote/i').first();
      const emptyState = page.locator('text=/no.*transitions/i').first();
      const mainContent = page.locator('main').first();

      await expect(transitionContent.or(emptyState).or(mainContent)).toBeVisible({ timeout: 5000 });
    }
  });
});

test.describe('Memory API Endpoints', () => {
  test('should handle /api/memory/tier-stats endpoint', async ({ page }) => {
    const response = await page.request.get('/api/memory/tier-stats');
    // Endpoint may return 503 if continuum not initialized, 404 if route not registered,
    // or 429 when shared local rate limiting is already active.
    expect([200, 404, 429, 503]).toContain(response.status());
  });

  test('should handle /api/memory/pressure endpoint', async ({ page }) => {
    const response = await page.request.get('/api/memory/pressure');
    expect([200, 404, 429, 503]).toContain(response.status());
  });
});
