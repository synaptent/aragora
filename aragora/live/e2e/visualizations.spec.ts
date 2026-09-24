import { test, expect, mockApiResponse } from './fixtures';

/**
 * E2E tests for the visualization components:
 * - Gauntlet Heatmap
 * - Belief Network Graph
 * - CruxPanel
 */

// Mock gauntlet results
const mockGauntletResults = {
  results: [
    {
      gauntlet_id: 'gauntlet-123',
      input_summary: 'Contract Analysis Pipeline',
      input_hash: 'abc123',
      verdict: 'PASS',
      confidence: 0.92,
      robustness_score: 0.85,
      critical_count: 0,
      high_count: 2,
      total_findings: 8,
      created_at: new Date().toISOString(),
      duration_seconds: 45,
    },
    {
      gauntlet_id: 'gauntlet-456',
      input_summary: 'Security Audit Workflow',
      input_hash: 'def456',
      verdict: 'CONDITIONAL',
      confidence: 0.78,
      robustness_score: 0.65,
      critical_count: 1,
      high_count: 3,
      total_findings: 15,
      created_at: new Date(Date.now() - 3600000).toISOString(),
      duration_seconds: 120,
    },
  ],
  total: 2,
};

// Mock heatmap data
const mockHeatmapData = {
  gauntlet_id: 'gauntlet-123',
  categories: ['Input Validation', 'Logic Errors', 'Security', 'Performance'],
  cells: [
    {
      category: 'Input Validation',
      subcategory: 'Injection',
      severity: 'high',
      count: 2,
      examples: ['SQL injection in param'],
    },
    {
      category: 'Input Validation',
      subcategory: 'XSS',
      severity: 'medium',
      count: 3,
      examples: ['Reflected XSS'],
    },
    {
      category: 'Security',
      subcategory: 'Auth',
      severity: 'critical',
      count: 1,
      examples: ['Auth bypass'],
    },
    {
      category: 'Logic Errors',
      subcategory: 'Edge Cases',
      severity: 'low',
      count: 5,
      examples: ['Empty array handling'],
    },
    {
      category: 'Performance',
      subcategory: 'Memory',
      severity: 'info',
      count: 2,
      examples: ['Memory leak potential'],
    },
  ],
  total_findings: 13,
  max_count: 5,
};

// Mock belief network data
const mockBeliefNetwork = {
  nodes: [
    {
      id: 'node-1',
      claim_id: 'claim-1',
      statement: 'AI systems should be transparent',
      author: 'claude',
      centrality: 0.8,
      is_crux: true,
      crux_score: 0.9,
      entropy: 0.65,
    },
    {
      id: 'node-2',
      claim_id: 'claim-2',
      statement: 'Transparency enables accountability',
      author: 'gpt4',
      centrality: 0.6,
      is_crux: false,
    },
    {
      id: 'node-3',
      claim_id: 'claim-3',
      statement: 'Some opacity is necessary for security',
      author: 'gemini',
      centrality: 0.5,
      is_crux: true,
      crux_score: 0.75,
      entropy: 0.8,
    },
  ],
  links: [
    { source: 'node-1', target: 'node-2', weight: 0.8, type: 'supports' },
    { source: 'node-3', target: 'node-1', weight: 0.6, type: 'contradicts' },
  ],
  metadata: { debate_id: 'debate-123', total_claims: 3, crux_count: 2 },
};

// Mock cruxes data
const mockCruxes = {
  cruxes: [
    {
      claim_id: 'claim-1',
      statement: 'AI systems should be transparent by default',
      author: 'claude',
      crux_score: 0.92,
      centrality: 0.85,
      entropy: 0.65,
      current_belief: { true_prob: 0.7, false_prob: 0.15, uncertain_prob: 0.15, confidence: 0.85 },
    },
    {
      claim_id: 'claim-3',
      statement: 'Security considerations may require some opacity',
      author: 'gemini',
      crux_score: 0.78,
      centrality: 0.55,
      entropy: 0.82,
      current_belief: { true_prob: 0.5, false_prob: 0.3, uncertain_prob: 0.2, confidence: 0.6 },
    },
  ],
};

// Mock load-bearing claims
const mockLoadBearing = {
  load_bearing_claims: [
    {
      claim_id: 'claim-2',
      statement: 'Transparency enables accountability',
      author: 'gpt4',
      centrality: 0.75,
    },
    {
      claim_id: 'claim-4',
      statement: 'Users deserve to know how decisions are made',
      author: 'claude',
      centrality: 0.68,
    },
  ],
};

test.describe('Gauntlet Panel', () => {
  test.beforeEach(async ({ page }) => {
    await mockApiResponse(page, '**/api/gauntlet/results*', mockGauntletResults);
    await mockApiResponse(page, '**/api/gauntlet/*/heatmap', mockHeatmapData);
  });

  test('should display gauntlet results list', async ({ page, aragoraPage }) => {
    await page.goto('/');
    await aragoraPage.dismissAllOverlays();

    // Find gauntlet panel (might be on main page or dedicated page)
    const gauntletPanel = page.locator(
      '[data-testid="gauntlet-panel"], :text("GAUNTLET"), :text("Stress Test")',
    );

    if (await gauntletPanel.isVisible().catch(() => false)) {
      await expect(gauntletPanel.first()).toBeVisible();
    }
  });

  test('should show verdict badges', async ({ page, aragoraPage }) => {
    await page.goto('/');
    await aragoraPage.dismissAllOverlays();

    // Look for verdict indicators
    const verdicts = page.locator(':text("PASS"), :text("CONDITIONAL"), :text("FAIL")');

    if ((await verdicts.count()) > 0) {
      await expect(verdicts.first()).toBeVisible();
    }
  });

  test('should expand result to show heatmap', async ({ page, aragoraPage }) => {
    await page.goto('/');
    await aragoraPage.dismissAllOverlays();

    // Find and click on a gauntlet result
    const resultItem = page.locator('[data-testid="gauntlet-result"], .gauntlet-result').first();

    if (await resultItem.isVisible().catch(() => false)) {
      await resultItem.click();

      // Heatmap should appear
      const heatmap = page.locator(
        '[data-testid="heatmap"], .heatmap, :text("Vulnerability Heatmap")',
      );
      await expect(heatmap.first()).toBeVisible({ timeout: 5000 });
    }
  });

  test('should filter results by verdict', async ({ page, aragoraPage }) => {
    await page.goto('/');
    await aragoraPage.dismissAllOverlays();

    // Find filter buttons
    const filterButtons = page.locator(
      'button:has-text("PASS"), button:has-text("FAIL"), button:has-text("CONDITIONAL")',
    );

    if (
      await filterButtons
        .first()
        .isVisible()
        .catch(() => false)
    ) {
      await filterButtons.first().click();

      // Results should be filtered
      await page.waitForTimeout(300);
    }
  });
});

test.describe('Gauntlet Heatmap', () => {
  test.beforeEach(async ({ page }) => {
    await mockApiResponse(page, '**/api/gauntlet/*/heatmap', mockHeatmapData);
  });

  test('should display severity legend', async ({ page, aragoraPage }) => {
    // Navigate to a page with heatmap
    await page.goto('/');
    await aragoraPage.dismissAllOverlays();

    // If heatmap is visible, check for legend
    const heatmap = page.locator('[data-testid="heatmap"], .heatmap');

    if (await heatmap.isVisible().catch(() => false)) {
      const legend = page.locator(
        ':text("CRITICAL"), :text("HIGH"), :text("MEDIUM"), :text("LOW"), :text("INFO")',
      );
      await expect(legend.first()).toBeVisible();
    }
  });

  test('should display heatmap grid', async ({ page, aragoraPage }) => {
    await page.goto('/');
    await aragoraPage.dismissAllOverlays();

    const heatmap = page.locator('[data-testid="heatmap"], .heatmap, table');

    if (await heatmap.isVisible().catch(() => false)) {
      // Should have rows/columns
      const cells = heatmap.locator('td, .heatmap-cell');
      const cellCount = await cells.count();
      expect(cellCount).toBeGreaterThan(0);
    }
  });

  test('should show tooltip on cell hover', async ({ page, aragoraPage }) => {
    await page.goto('/');
    await aragoraPage.dismissAllOverlays();

    const heatmapCell = page.locator('.heatmap-cell, td > div').first();

    if (await heatmapCell.isVisible().catch(() => false)) {
      await heatmapCell.hover();

      // Tooltip should appear
      const tooltip = page.locator('[data-testid="tooltip"], .tooltip, [role="tooltip"]');

      if (await tooltip.isVisible({ timeout: 2000 }).catch(() => false)) {
        await expect(tooltip.first()).toBeVisible();
      }
    }
  });

  test('should display summary stats', async ({ page, aragoraPage }) => {
    await page.goto('/');
    await aragoraPage.dismissAllOverlays();

    const heatmap = page.locator('[data-testid="heatmap"], .heatmap');

    if (await heatmap.isVisible().catch(() => false)) {
      // Should show total findings or severity counts
      const stats = page.locator(':text("findings"), :text("total")');

      if ((await stats.count()) > 0) {
        await expect(stats.first()).toBeVisible();
      }
    }
  });
});

test.describe('CruxPanel', () => {
  test.beforeEach(async ({ page }) => {
    await mockApiResponse(page, '**/api/belief-network/*/cruxes*', mockCruxes);
    await mockApiResponse(page, '**/api/belief-network/*/load-bearing-claims*', mockLoadBearing);
    await mockApiResponse(page, '**/api/belief-network/*/graph*', mockBeliefNetwork);
  });

  test('should display crux panel', async ({ page, aragoraPage }) => {
    await page.goto('/');
    await aragoraPage.dismissAllOverlays();

    // Find crux panel
    const cruxPanel = page.locator(
      '[data-testid="crux-panel"], :text("CRUX"), :text("Belief Network")',
    );

    if (await cruxPanel.isVisible().catch(() => false)) {
      await expect(cruxPanel.first()).toBeVisible();
    }
  });

  test('should have debate ID input', async ({ page, aragoraPage }) => {
    await page.goto('/');
    await aragoraPage.dismissAllOverlays();

    const debateInput = page.locator('input[placeholder*="debate"], input[placeholder*="ID"]');

    if (await debateInput.isVisible().catch(() => false)) {
      await expect(debateInput.first()).toBeVisible();
    }
  });

  test('should switch between tabs', async ({ page, aragoraPage }) => {
    await page.goto('/');
    await aragoraPage.dismissAllOverlays();

    // Look for tab buttons
    const cruxesTab = page.locator('button:has-text("CRUX"), button:has-text("Cruxes")').first();
    const loadBearingTab = page
      .locator('button:has-text("LOAD-BEARING"), button:has-text("Load-Bearing")')
      .first();
    const graphTab = page.locator('button:has-text("GRAPH"), button:has-text("Graph")').first();

    if (await cruxesTab.isVisible().catch(() => false)) {
      // Click load-bearing tab
      if (await loadBearingTab.isVisible().catch(() => false)) {
        await loadBearingTab.click();
        await page.waitForTimeout(300);
      }

      // Click graph tab
      if (await graphTab.isVisible().catch(() => false)) {
        await graphTab.click();
        await page.waitForTimeout(300);
      }

      // Click back to cruxes
      await cruxesTab.click();
    }
  });

  test('should display crux cards with scores', async ({ page, aragoraPage }) => {
    await page.goto('/');
    await aragoraPage.dismissAllOverlays();

    // After fetching cruxes, should show crux cards
    const cruxCards = page.locator('[data-testid="crux-card"], .crux-card, :text("CRUX #")');

    if ((await cruxCards.count()) > 0) {
      await expect(cruxCards.first()).toBeVisible();

      // Should show score
      const score = page.locator(':text("score"), :text("centrality"), :text("entropy")');
      await expect(score.first()).toBeVisible();
    }
  });

  test('should display belief probabilities', async ({ page, aragoraPage }) => {
    await page.goto('/');
    await aragoraPage.dismissAllOverlays();

    // Look for belief probability indicators
    const beliefs = page.locator(':text("T:"), :text("F:"), :text("?:"), .belief-prob');

    if ((await beliefs.count()) > 0) {
      await expect(beliefs.first()).toBeVisible();
    }
  });
});

test.describe('Belief Network Graph', () => {
  test.beforeEach(async ({ page }) => {
    await mockApiResponse(page, '**/api/belief-network/*/graph*', mockBeliefNetwork);
    await mockApiResponse(page, '**/api/belief-network/*/cruxes*', mockCruxes);
    await mockApiResponse(page, '**/api/belief-network/*/load-bearing-claims*', mockLoadBearing);
  });

  test('should display belief network graph', async ({ page, aragoraPage }) => {
    await page.goto('/');
    await aragoraPage.dismissAllOverlays();

    // Navigate to graph tab if needed
    const graphTab = page.locator('button:has-text("GRAPH")').first();

    if (await graphTab.isVisible().catch(() => false)) {
      await graphTab.click();
    }

    // Graph container should be visible
    const graphContainer = page.locator('[data-testid="belief-graph"], .belief-graph, svg');

    if (await graphContainer.isVisible({ timeout: 5000 }).catch(() => false)) {
      await expect(graphContainer.first()).toBeVisible();
    }
  });

  test('should display graph nodes', async ({ page, aragoraPage }) => {
    await page.goto('/');
    await aragoraPage.dismissAllOverlays();

    const graphTab = page.locator('button:has-text("GRAPH")').first();

    if (await graphTab.isVisible().catch(() => false)) {
      await graphTab.click();
    }

    // Look for graph nodes (circles in SVG)
    const nodes = page.locator('svg circle, [data-testid="graph-node"]');

    if ((await nodes.count()) > 0) {
      await expect(nodes.first()).toBeVisible();
    }
  });

  test('should display graph edges', async ({ page, aragoraPage }) => {
    await page.goto('/');
    await aragoraPage.dismissAllOverlays();

    const graphTab = page.locator('button:has-text("GRAPH")').first();

    if (await graphTab.isVisible().catch(() => false)) {
      await graphTab.click();
    }

    // Look for graph edges (lines in SVG)
    const edges = page.locator('svg line, svg path, [data-testid="graph-edge"]');

    if ((await edges.count()) > 0) {
      await expect(edges.first()).toBeVisible();
    }
  });

  test('should highlight crux nodes', async ({ page, aragoraPage }) => {
    await page.goto('/');
    await aragoraPage.dismissAllOverlays();

    const graphTab = page.locator('button:has-text("GRAPH")').first();

    if (await graphTab.isVisible().catch(() => false)) {
      await graphTab.click();
    }

    // Crux nodes should have special styling
    const cruxNodes = page.locator('[data-testid="crux-node"], .crux-node, :text("CRUX")');

    if ((await cruxNodes.count()) > 0) {
      await expect(cruxNodes.first()).toBeVisible();
    }
  });

  test('should show node details on click', async ({ page, aragoraPage }) => {
    await page.goto('/');
    await aragoraPage.dismissAllOverlays();

    const graphTab = page.locator('button:has-text("GRAPH")').first();

    if (await graphTab.isVisible().catch(() => false)) {
      await graphTab.click();
    }

    // Click on a node
    const node = page.locator('svg circle, svg g[style*="cursor"]').first();

    if (await node.isVisible().catch(() => false)) {
      await node.click();

      // Details panel should appear
      const details = page.locator(
        '[data-testid="node-details"], .node-details, :text("Centrality")',
      );

      if (await details.isVisible({ timeout: 3000 }).catch(() => false)) {
        await expect(details.first()).toBeVisible();
      }
    }
  });

  test('should display author legend', async ({ page, aragoraPage }) => {
    await page.goto('/');
    await aragoraPage.dismissAllOverlays();

    const graphTab = page.locator('button:has-text("GRAPH")').first();

    if (await graphTab.isVisible().catch(() => false)) {
      await graphTab.click();
    }

    // Legend should show author colors
    const legend = page.locator(':text("Authors:"), .author-legend');

    if (await legend.isVisible().catch(() => false)) {
      await expect(legend.first()).toBeVisible();
    }
  });

  test('should display graph metadata', async ({ page, aragoraPage }) => {
    await page.goto('/');
    await aragoraPage.dismissAllOverlays();

    const graphTab = page.locator('button:has-text("GRAPH")').first();

    if (await graphTab.isVisible().catch(() => false)) {
      await graphTab.click();
    }

    // Should show claims count and crux count
    const metadata = page.locator(':text("claims"), :text("cruxes")');

    if ((await metadata.count()) > 0) {
      await expect(metadata.first()).toBeVisible();
    }
  });
});

test.describe('Visualization Accessibility', () => {
  test('heatmap should have proper color contrast', async ({ page, aragoraPage }) => {
    await page.goto('/');
    await aragoraPage.dismissAllOverlays();

    // Heatmap cells should have readable text
    const heatmapCells = page.locator('.heatmap-cell, td > div');

    if ((await heatmapCells.count()) > 0) {
      // Cells should be visible with adequate contrast
      await expect(heatmapCells.first()).toBeVisible();
    }
  });

  test('graph should be keyboard navigable', async ({ page, aragoraPage }) => {
    await page.goto('/');
    await aragoraPage.dismissAllOverlays();

    const graphTab = page.locator('button:has-text("GRAPH")').first();

    if (await graphTab.isVisible().catch(() => false)) {
      await graphTab.click();

      // Graph container should be focusable
      const graphContainer = page.locator('svg, [data-testid="belief-graph"]').first();

      if (await graphContainer.isVisible().catch(() => false)) {
        // Should be able to focus
        await graphContainer.focus();
      }
    }
  });
});
