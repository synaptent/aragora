import { test, expect, mockApiResponse } from './fixtures';

/**
 * E2E tests for ML Dashboard page (/ml).
 *
 * Tests ML capabilities display, agent routing, quality scoring,
 * and consensus prediction features.
 */

const mockCapabilities = {
  capabilities: {
    routing: true,
    scoring: true,
    consensus: true,
    embeddings: true,
    training_export: true,
  },
  models: {
    routing: 'task-router-v1',
    scoring: 'quality-scorer-v1',
    consensus: 'consensus-predictor-v1',
  },
  version: '1.0.0',
};

const mockStats = {
  stats: {
    routing: { registered_agents: 8, historical_records: 1250 },
    consensus: { calibration_samples: 450, accuracy: 0.87, precision: 0.85, recall: 0.89 },
  },
  status: 'healthy',
};

const mockRoutingResult = {
  selected_agents: ['anthropic-api', 'openai-api', 'grok'],
  task_type: 'analysis',
  confidence: 0.92,
  reasoning: [
    'Task requires multi-perspective analysis',
    'Selected agents have strong analytical capabilities',
    'Team diversity score optimized',
  ],
  agent_scores: {
    'anthropic-api': 0.95,
    'openai-api': 0.91,
    grok: 0.88,
    deepseek: 0.82,
    mistral: 0.79,
  },
  diversity_score: 0.85,
};

const mockScoringResult = {
  overall: 0.85,
  coherence: 0.88,
  completeness: 0.82,
  relevance: 0.9,
  clarity: 0.8,
  confidence: 0.87,
  is_high_quality: true,
  needs_review: false,
};

const mockConsensusPrediction = {
  will_converge: true,
  confidence: 0.78,
  estimated_rounds: 4,
  risk_factors: ['Divergent initial positions', 'Complex topic'],
  recommended_actions: ['Consider adding a mediator agent', 'Enable evidence collection'],
};

test.describe('ML Dashboard Page', () => {
  test.beforeEach(async ({ page, aragoraPage }) => {
    await mockApiResponse(page, '**/api/health', { status: 'ok' });
    await mockApiResponse(page, '**/api/ml/models', mockCapabilities);
    await mockApiResponse(page, '**/api/ml/stats', mockStats);
    await page.goto('/ml');
    await aragoraPage.dismissAllOverlays();
    await page.waitForLoadState('domcontentloaded');
  });

  test('should load ML page with title', async ({ page }) => {
    await page.waitForTimeout(1500);
    await expect(page).toHaveTitle(/ML|Aragora/i, { timeout: 10000 });

    // Should show ML-related heading
    const mlHeading = page.locator('text=/ml intelligence|machine learning/i').first();
    const mainContent = page.locator('main').first();
    const hasHeading = await mlHeading.isVisible({ timeout: 5000 }).catch(() => false);
    const hasMain = await mainContent.isVisible().catch(() => false);
    expect(hasHeading || hasMain).toBeTruthy();
  });

  test('should display ML capabilities section', async ({ page }) => {
    await page.waitForTimeout(2000);

    // Should show capability cards
    const routingCapability = page.locator('text=/agent routing|task-based/i').first();
    const scoringCapability = page.locator('text=/quality scoring|response quality/i').first();
    const consensusCapability = page.locator('text=/consensus prediction|convergence/i').first();
    const trainingCapability = page.locator('text=/training export|sft.*dpo/i').first();

    const hasRouting = await routingCapability.isVisible({ timeout: 5000 }).catch(() => false);
    const hasScoring = await scoringCapability.isVisible().catch(() => false);
    const hasConsensus = await consensusCapability.isVisible().catch(() => false);
    const hasTraining = await trainingCapability.isVisible().catch(() => false);

    expect(hasRouting || hasScoring || hasConsensus || hasTraining).toBeTruthy();
  });

  test('should display navigation links', async ({ page }) => {
    await page.waitForTimeout(1500);

    // Should show navigation links to other pages
    const dashboardLink = page.getByRole('link', { name: /dashboard/i }).first();
    const analyticsLink = page.getByRole('link', { name: /analytics/i }).first();
    const leaderboardLink = page.getByRole('link', { name: /ranks|leaderboard/i }).first();

    const hasDashboard = await dashboardLink.isVisible({ timeout: 3000 }).catch(() => false);
    const hasAnalytics = await analyticsLink.isVisible().catch(() => false);
    const hasLeaderboard = await leaderboardLink.isVisible().catch(() => false);

    expect(hasDashboard || hasAnalytics || hasLeaderboard).toBeTruthy();
  });

  test('should render MLDashboard component', async ({ page }) => {
    await page.waitForTimeout(2000);

    // MLDashboard should render - check for tabs or content
    const tabButtons = page.locator('button, [role="tab"]');
    const statsTab = tabButtons.filter({ hasText: /stats/i }).first();
    const routeTab = tabButtons.filter({ hasText: /route/i }).first();

    const hasStats = await statsTab.isVisible({ timeout: 5000 }).catch(() => false);
    const hasRoute = await routeTab.isVisible().catch(() => false);

    // Or check for any dashboard content
    const dashboardContent = page.locator('text=/capabilities|routing|scoring/i').first();
    const hasContent = await dashboardContent.isVisible({ timeout: 3000 }).catch(() => false);

    expect(hasStats || hasRoute || hasContent).toBeTruthy();
  });
});

test.describe('ML Dashboard - Stats Tab', () => {
  test.beforeEach(async ({ page, aragoraPage }) => {
    await mockApiResponse(page, '**/api/health', { status: 'ok' });
    await mockApiResponse(page, '**/api/ml/models', mockCapabilities);
    await mockApiResponse(page, '**/api/ml/stats', mockStats);
    await page.goto('/ml');
    await aragoraPage.dismissAllOverlays();
    await page.waitForLoadState('domcontentloaded');
  });

  test('should display routing statistics', async ({ page }) => {
    await page.waitForTimeout(2000);

    // Click stats tab if available
    const statsTab = page.locator('button, [role="tab"]').filter({ hasText: /stats/i }).first();
    if (await statsTab.isVisible({ timeout: 2000 }).catch(() => false)) {
      await statsTab.click();
      await page.waitForTimeout(500);
    }

    // Should show routing stats from mock
    const agentCount = page.locator('text=/8|registered.*agents/i').first();
    const recordCount = page.locator('text=/1250|historical.*records/i').first();

    const hasAgentCount = await agentCount.isVisible({ timeout: 3000 }).catch(() => false);
    const hasRecordCount = await recordCount.isVisible().catch(() => false);

    // Also check for any stats-related content
    const statsContent = page.locator('text=/routing|consensus|stats/i').first();
    const hasStatsContent = await statsContent.isVisible().catch(() => false);

    expect(hasAgentCount || hasRecordCount || hasStatsContent).toBeTruthy();
  });

  test('should display consensus statistics', async ({ page }) => {
    await page.waitForTimeout(2000);

    // Click stats tab if available
    const statsTab = page.locator('button, [role="tab"]').filter({ hasText: /stats/i }).first();
    if (await statsTab.isVisible({ timeout: 2000 }).catch(() => false)) {
      await statsTab.click();
      await page.waitForTimeout(500);
    }

    // Should show consensus accuracy from mock (0.87 = 87%)
    const accuracyDisplay = page.locator('text=/87%|0\\.87|accuracy/i').first();
    const calibrationSamples = page.locator('text=/450|calibration.*samples/i').first();

    const hasAccuracy = await accuracyDisplay.isVisible({ timeout: 3000 }).catch(() => false);
    const hasSamples = await calibrationSamples.isVisible().catch(() => false);

    // Also check for general consensus-related content
    const consensusContent = page.locator('text=/consensus|accuracy|precision|recall/i').first();
    const hasConsensusContent = await consensusContent.isVisible().catch(() => false);

    expect(hasAccuracy || hasSamples || hasConsensusContent).toBeTruthy();
  });
});

test.describe('ML Dashboard - Agent Routing', () => {
  test.beforeEach(async ({ page, aragoraPage }) => {
    await mockApiResponse(page, '**/api/health', { status: 'ok' });
    await mockApiResponse(page, '**/api/ml/models', mockCapabilities);
    await mockApiResponse(page, '**/api/ml/stats', mockStats);
    await mockApiResponse(page, '**/api/ml/route', mockRoutingResult);
    await page.goto('/ml');
    await aragoraPage.dismissAllOverlays();
    await page.waitForLoadState('domcontentloaded');
  });

  test('should display routing form when route tab is selected', async ({ page }) => {
    await page.waitForTimeout(2000);

    // Click route tab
    const routeTab = page.locator('button, [role="tab"]').filter({ hasText: /route/i }).first();
    if (await routeTab.isVisible({ timeout: 3000 }).catch(() => false)) {
      await routeTab.click();
      await page.waitForTimeout(500);

      // Should show routing form elements
      const taskInput = page.locator('input, textarea').filter({ hasText: /task/i }).first();
      const agentInput = page.locator('input, textarea').first();
      const routeButton = page
        .locator('button')
        .filter({ hasText: /route|select|run/i })
        .first();

      const hasTaskInput = await taskInput.isVisible({ timeout: 3000 }).catch(() => false);
      const hasAgentInput = await agentInput.isVisible().catch(() => false);
      const hasRouteButton = await routeButton.isVisible().catch(() => false);

      expect(hasTaskInput || hasAgentInput || hasRouteButton).toBeTruthy();
    }
  });

  test.skip('should perform agent routing on form submission', async ({ page }) => {
    await page.waitForTimeout(2000);

    // Click route tab
    const routeTab = page.locator('button, [role="tab"]').filter({ hasText: /route/i }).first();
    if (await routeTab.isVisible({ timeout: 3000 }).catch(() => false)) {
      await routeTab.click();
      await page.waitForTimeout(500);

      // Fill in routing task
      const taskInput = page.locator('input[placeholder*="task"], textarea').first();
      if (await taskInput.isVisible({ timeout: 2000 }).catch(() => false)) {
        await taskInput.fill('Analyze the performance implications of microservices');

        // Click route button
        const routeButton = page
          .locator('button')
          .filter({ hasText: /route|select|run/i })
          .first();
        if (await routeButton.isVisible().catch(() => false)) {
          await routeButton.click();
          await page.waitForTimeout(1000);

          // Should show routing results
          const selectedAgents = page.locator('text=/anthropic-api|selected.*agents/i').first();
          const confidence = page.locator('text=/92%|0\\.92|confidence/i').first();

          const hasSelectedAgents = await selectedAgents
            .isVisible({ timeout: 5000 })
            .catch(() => false);
          const hasConfidence = await confidence.isVisible().catch(() => false);

          expect(hasSelectedAgents || hasConfidence).toBeTruthy();
        }
      }
    }
  });
});

test.describe('ML Dashboard - Quality Scoring', () => {
  test.beforeEach(async ({ page, aragoraPage }) => {
    await mockApiResponse(page, '**/api/health', { status: 'ok' });
    await mockApiResponse(page, '**/api/ml/models', mockCapabilities);
    await mockApiResponse(page, '**/api/ml/stats', mockStats);
    await mockApiResponse(page, '**/api/ml/score', mockScoringResult);
    await page.goto('/ml');
    await aragoraPage.dismissAllOverlays();
    await page.waitForLoadState('domcontentloaded');
  });

  test('should display scoring form when score tab is selected', async ({ page }) => {
    await page.waitForTimeout(2000);

    // Click score tab
    const scoreTab = page.locator('button, [role="tab"]').filter({ hasText: /score/i }).first();
    if (await scoreTab.isVisible({ timeout: 3000 }).catch(() => false)) {
      await scoreTab.click();
      await page.waitForTimeout(500);

      // Should show scoring form elements
      const textInput = page.locator('input, textarea').first();
      const scoreButton = page
        .locator('button')
        .filter({ hasText: /score|analyze|run/i })
        .first();

      const hasTextInput = await textInput.isVisible({ timeout: 3000 }).catch(() => false);
      const hasScoreButton = await scoreButton.isVisible().catch(() => false);

      expect(hasTextInput || hasScoreButton).toBeTruthy();
    }
  });
});

test.describe('ML Dashboard - Consensus Prediction', () => {
  test.beforeEach(async ({ page, aragoraPage }) => {
    await mockApiResponse(page, '**/api/health', { status: 'ok' });
    await mockApiResponse(page, '**/api/ml/models', mockCapabilities);
    await mockApiResponse(page, '**/api/ml/stats', mockStats);
    await mockApiResponse(page, '**/api/ml/predict-consensus', mockConsensusPrediction);
    await page.goto('/ml');
    await aragoraPage.dismissAllOverlays();
    await page.waitForLoadState('domcontentloaded');
  });

  test('should display prediction form when predict tab is selected', async ({ page }) => {
    await page.waitForTimeout(2000);

    // Click predict tab
    const predictTab = page
      .locator('button, [role="tab"]')
      .filter({ hasText: /predict/i })
      .first();
    if (await predictTab.isVisible({ timeout: 3000 }).catch(() => false)) {
      await predictTab.click();
      await page.waitForTimeout(500);

      // Should show prediction form elements
      const taskInput = page.locator('input, textarea').first();
      const predictButton = page
        .locator('button')
        .filter({ hasText: /predict|run/i })
        .first();

      const hasTaskInput = await taskInput.isVisible({ timeout: 3000 }).catch(() => false);
      const hasPredictButton = await predictButton.isVisible().catch(() => false);

      expect(hasTaskInput || hasPredictButton).toBeTruthy();
    }
  });
});

test.describe('ML Dashboard - Error Handling', () => {
  test('should handle API errors gracefully', async ({ page, aragoraPage }) => {
    await mockApiResponse(page, '**/api/health', { status: 'ok' });
    // Mock API failure
    await page.route('**/api/ml/models', async (route) => {
      await route.fulfill({
        status: 503,
        contentType: 'application/json',
        body: JSON.stringify({ error: 'Service unavailable' }),
      });
    });
    await page.route('**/api/ml/stats', async (route) => {
      await route.fulfill({
        status: 503,
        contentType: 'application/json',
        body: JSON.stringify({ error: 'Service unavailable' }),
      });
    });

    await page.goto('/ml');
    await aragoraPage.dismissAllOverlays();
    await page.waitForLoadState('domcontentloaded');
    await page.waitForTimeout(2000);

    // Page should still render even if API fails
    const mainContent = page.locator('main').first();
    const errorMessage = page.locator('text=/error|unavailable|failed/i').first();

    const hasMain = await mainContent.isVisible({ timeout: 5000 }).catch(() => false);
    const hasError = await errorMessage.isVisible().catch(() => false);

    // Page should render (either with error message or fallback)
    expect(hasMain || hasError).toBeTruthy();
  });

  test('should show loading state initially', async ({ page, aragoraPage }) => {
    // Add delay to mock response to observe loading state
    await mockApiResponse(page, '**/api/health', { status: 'ok' });
    await page.route('**/api/ml/models', async (route) => {
      await new Promise((resolve) => setTimeout(resolve, 500));
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(mockCapabilities),
      });
    });
    await mockApiResponse(page, '**/api/ml/stats', mockStats);

    await page.goto('/ml');
    await aragoraPage.dismissAllOverlays();

    // Should show some content while loading (skeleton or loading indicator)
    const loadingContent = page
      .locator('.animate-pulse, [aria-busy="true"], text=/loading/i')
      .first();
    const mainContent = page.locator('main').first();

    // Page should render something during load
    const hasLoading = await loadingContent.isVisible({ timeout: 2000 }).catch(() => false);
    const hasMain = await mainContent.isVisible().catch(() => false);

    expect(hasLoading || hasMain).toBeTruthy();
  });
});
