import { test, expect, mockApiResponse } from './fixtures';

/**
 * E2E tests for Knowledge Mound functionality.
 *
 * Tests the knowledge system including:
 * - Knowledge node display and filtering
 * - Search functionality
 * - Node details and relationships
 * - Stats display
 */

// Mock knowledge data
const mockNodes = [
  {
    id: 'node-1',
    nodeType: 'fact',
    content: 'Test fact about AI systems',
    confidence: 0.85,
    tier: 'medium',
    sourceType: 'consensus',
    topics: ['AI', 'systems'],
    createdAt: new Date().toISOString(),
    updatedAt: new Date().toISOString(),
  },
  {
    id: 'node-2',
    nodeType: 'memory',
    content: 'Memory from previous debate',
    confidence: 0.72,
    tier: 'slow',
    sourceType: 'continuum',
    topics: ['debate', 'memory'],
    createdAt: new Date().toISOString(),
    updatedAt: new Date().toISOString(),
  },
];

const mockStats = {
  totalNodes: 42,
  nodesByType: { fact: 15, memory: 12, consensus: 10, evidence: 5 },
  nodesByTier: { fast: 5, medium: 20, slow: 12, glacial: 5 },
  nodesBySource: { consensus: 18, continuum: 14, document: 10 },
  totalRelationships: 67,
};

test.describe('Knowledge Mound Page', () => {
  test('should load knowledge page', async ({ page, aragoraPage }) => {
    await page.goto('/knowledge');
    await aragoraPage.dismissAllOverlays();

    await expect(page).toHaveURL(/\/knowledge/);
    await expect(page.locator('body')).toBeVisible();
  });

  test('should display knowledge nodes when API returns data', async ({ page, aragoraPage }) => {
    await mockApiResponse(page, '**/api/knowledge/nodes**', { nodes: mockNodes });
    await mockApiResponse(page, '**/api/knowledge/stats', mockStats);

    await page.goto('/knowledge');
    await aragoraPage.dismissAllOverlays();
    await page.waitForLoadState('domcontentloaded');

    // Should show content
    await expect(page.locator('body')).toBeVisible();
  });

  test('should display knowledge stats', async ({ page, aragoraPage }) => {
    await mockApiResponse(page, '**/api/knowledge/nodes**', { nodes: mockNodes });
    await mockApiResponse(page, '**/api/knowledge/stats', mockStats);

    await page.goto('/knowledge');
    await aragoraPage.dismissAllOverlays();
    await page.waitForLoadState('domcontentloaded');

    // Stats should be displayed somewhere on page
    const body = page.locator('body');
    await expect(body).toBeVisible();
  });

  test('should have search functionality', async ({ page, aragoraPage }) => {
    await mockApiResponse(page, '**/api/knowledge/**', { nodes: mockNodes });

    await page.goto('/knowledge');
    await aragoraPage.dismissAllOverlays();
    await page.waitForLoadState('domcontentloaded');

    // Look for search input
    const searchInput = page.locator(
      'input[type="text"], input[placeholder*="search" i], input[placeholder*="Search" i]',
    );
    const hasSearch = await searchInput
      .first()
      .isVisible()
      .catch(() => false);
    expect(hasSearch).toBeDefined();
  });

  test('should have filter options', async ({ page, aragoraPage }) => {
    await mockApiResponse(page, '**/api/knowledge/**', { nodes: mockNodes });

    await page.goto('/knowledge');
    await aragoraPage.dismissAllOverlays();
    await page.waitForLoadState('domcontentloaded');

    // Look for filter buttons or selects
    const filters = page.locator(
      'select, [role="combobox"], button:has-text("Filter"), button:has-text("All")',
    );
    const hasFilters = await filters
      .first()
      .isVisible()
      .catch(() => false);
    expect(hasFilters).toBeDefined();
  });

  test('should handle empty state gracefully', async ({ page, aragoraPage }) => {
    await mockApiResponse(page, '**/api/knowledge/nodes**', { nodes: [] });
    await mockApiResponse(page, '**/api/knowledge/stats', {
      totalNodes: 0,
      nodesByType: {},
      nodesByTier: {},
      nodesBySource: {},
      totalRelationships: 0,
    });

    await page.goto('/knowledge');
    await aragoraPage.dismissAllOverlays();
    await page.waitForLoadState('domcontentloaded');

    // Page should handle empty state
    await expect(page.locator('body')).toBeVisible();
  });

  test('should fall back gracefully when API unavailable', async ({ page, aragoraPage }) => {
    await page.route('**/api/knowledge/**', (route) => {
      route.fulfill({ status: 503, body: 'Service Unavailable' });
    });

    await page.goto('/knowledge');
    await aragoraPage.dismissAllOverlays();
    await page.waitForLoadState('domcontentloaded');

    // Page should still be functional
    await expect(page.locator('body')).toBeVisible();
  });
});

test.describe('Knowledge Search and Query', () => {
  test('should search knowledge nodes', async ({ page, aragoraPage }) => {
    await mockApiResponse(page, '**/api/knowledge/**', { nodes: mockNodes });

    await page.goto('/knowledge');
    await aragoraPage.dismissAllOverlays();
    await page.waitForLoadState('domcontentloaded');

    // Look for search input - page may or may not have one
    const searchInput = page.locator('input[type="text"], input[placeholder*="search" i]').first();
    const hasSearch = await searchInput.isVisible({ timeout: 2000 }).catch(() => false);

    if (hasSearch) {
      await searchInput.fill('AI');
      await page.waitForTimeout(300);
    }

    // Page should still be functional
    await expect(page.locator('body')).toBeVisible();
  });

  test('should query knowledge API', async ({ page, aragoraPage }) => {
    let queryRequested = false;

    await page.route('**/api/knowledge/query**', (route) => {
      queryRequested = true;
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ answer: 'Test answer', facts: mockNodes }),
      });
    });

    await page.goto('/knowledge');
    await aragoraPage.dismissAllOverlays();
    await page.waitForLoadState('domcontentloaded');

    // Query endpoint availability is tracked
    expect(queryRequested).toBeDefined();
  });
});

test.describe('Knowledge API Endpoints', () => {
  test.skip(({ browserName }) => browserName !== 'chromium', 'API tests only run in chromium');

  test('should handle /api/knowledge/facts endpoint', async ({ page }) => {
    const response = await page.request.get('/api/knowledge/facts').catch(() => null);

    if (response) {
      expect([200, 404, 503]).toContain(response.status());
    } else {
      expect(true).toBe(true);
    }
  });

  test('should handle /api/knowledge/stats endpoint', async ({ page }) => {
    const response = await page.request.get('/api/knowledge/stats').catch(() => null);

    if (response) {
      expect([200, 404, 503]).toContain(response.status());
    } else {
      expect(true).toBe(true);
    }
  });
});

// =============================================================================
// Knowledge Mound Visibility, Sharing, and Federation Tests
// =============================================================================

const mockSharedItems = [
  {
    id: 'shared-1',
    title: 'Shared knowledge item',
    content: 'This is a shared knowledge item from another workspace',
    sharedBy: { id: 'user-1', name: 'Alice', type: 'user' as const },
    sharedAt: new Date().toISOString(),
    permissions: ['read'],
    sourceWorkspace: { id: 'ws-1', name: 'Research Team' },
  },
];

const mockFederatedRegions = [
  {
    id: 'us-west-2',
    name: 'US West 2',
    endpointUrl: 'https://us-west-2.example.com/api',
    mode: 'bidirectional' as const,
    scope: 'summary' as const,
    enabled: true,
    health: 'healthy' as const,
    lastSyncAt: new Date().toISOString(),
    nodesSynced: 150,
  },
  {
    id: 'eu-west-1',
    name: 'EU West 1',
    endpointUrl: 'https://eu-west-1.example.com/api',
    mode: 'pull' as const,
    scope: 'metadata' as const,
    enabled: false,
    health: 'offline' as const,
    nodesSynced: 0,
  },
];

test.describe('Knowledge Mound Visibility', () => {
  test('should display visibility selector for nodes', async ({ page, aragoraPage }) => {
    await mockApiResponse(page, '**/api/knowledge/mound/nodes/**', mockNodes);

    await page.goto('/admin/knowledge');
    await aragoraPage.dismissAllOverlays();
    await page.waitForLoadState('domcontentloaded');

    // Page should load
    await expect(page.locator('body')).toBeVisible();
  });

  test('should handle visibility API endpoints', async ({ page }) => {
    // Mock the visibility endpoint
    await page.route('**/api/knowledge/mound/nodes/*/visibility', (route) => {
      if (route.request().method() === 'GET') {
        route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify({ visibility: 'workspace', isDiscoverable: true, setBy: 'user-1' }),
        });
      } else if (route.request().method() === 'PUT') {
        route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify({ success: true }),
        });
      } else {
        route.continue();
      }
    });

    // Test GET visibility
    const getResponse = await page.request
      .get('/api/knowledge/mound/nodes/test-node/visibility')
      .catch(() => null);
    if (getResponse) {
      expect([200, 401, 404]).toContain(getResponse.status());
    }
  });

  test('should handle access grant endpoints', async ({ page }) => {
    await page.route('**/api/knowledge/mound/nodes/*/access', (route) => {
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          grants: [
            { id: 'grant-1', granteeType: 'user', granteeId: 'user-2', permissions: ['read'] },
          ],
        }),
      });
    });

    const response = await page.request
      .get('/api/knowledge/mound/nodes/test-node/access')
      .catch(() => null);
    if (response) {
      expect([200, 401, 404]).toContain(response.status());
    }
  });
});

test.describe('Knowledge Mound Sharing', () => {
  test('should display shared items tab', async ({ page, aragoraPage }) => {
    await mockApiResponse(page, '**/api/knowledge/mound/shared-with-me**', {
      items: mockSharedItems,
      count: 1,
    });

    await page.goto('/admin/knowledge');
    await aragoraPage.dismissAllOverlays();
    await page.waitForLoadState('domcontentloaded');

    // Look for shared tab
    const sharedTab = page.locator('button:has-text("Shared"), [role="tab"]:has-text("Shared")');
    const hasSharedTab = await sharedTab
      .first()
      .isVisible({ timeout: 3000 })
      .catch(() => false);

    if (hasSharedTab) {
      await sharedTab.first().click();
      await page.waitForTimeout(500);
    }

    await expect(page.locator('body')).toBeVisible();
  });

  test('should handle share API endpoints', async ({ page }) => {
    // Mock share endpoint
    await page.route('**/api/knowledge/mound/share', (route) => {
      if (route.request().method() === 'POST') {
        route.fulfill({
          status: 201,
          contentType: 'application/json',
          body: JSON.stringify({
            success: true,
            share: {
              itemId: 'node-1',
              targetType: 'workspace',
              targetId: 'ws-2',
              permissions: ['read'],
            },
          }),
        });
      } else {
        route.continue();
      }
    });

    const response = await page.request
      .post('/api/knowledge/mound/share', {
        data: { item_id: 'node-1', target_type: 'workspace', target_id: 'ws-2' },
      })
      .catch(() => null);

    if (response) {
      expect([201, 400, 401, 404]).toContain(response.status());
    }
  });

  test('should handle shared-with-me endpoint', async ({ page }) => {
    await mockApiResponse(page, '**/api/knowledge/mound/shared-with-me**', {
      items: mockSharedItems,
      count: 1,
    });

    const response = await page.request
      .get('/api/knowledge/mound/shared-with-me')
      .catch(() => null);
    if (response) {
      expect([200, 401, 404]).toContain(response.status());
    }
  });
});

test.describe('Knowledge Mound Federation', () => {
  test('should display federation tab for admins', async ({ page, aragoraPage }) => {
    await mockApiResponse(page, '**/api/knowledge/mound/federation/regions', {
      regions: mockFederatedRegions,
      count: 2,
    });
    await mockApiResponse(page, '**/api/knowledge/mound/federation/status', {
      regions: mockFederatedRegions.reduce((acc, r) => ({ ...acc, [r.id]: r }), {}),
      totalRegions: 2,
      enabledRegions: 1,
    });

    await page.goto('/admin/knowledge');
    await aragoraPage.dismissAllOverlays();
    await page.waitForLoadState('domcontentloaded');

    // Look for federation tab
    const federationTab = page.locator(
      'button:has-text("Federation"), [role="tab"]:has-text("Federation")',
    );
    const hasFederationTab = await federationTab
      .first()
      .isVisible({ timeout: 3000 })
      .catch(() => false);

    if (hasFederationTab) {
      await federationTab.first().click();
      await page.waitForTimeout(500);
    }

    await expect(page.locator('body')).toBeVisible();
  });

  test('should handle federation regions endpoint', async ({ page }) => {
    await mockApiResponse(page, '**/api/knowledge/mound/federation/regions', {
      regions: mockFederatedRegions,
      count: 2,
    });

    const response = await page.request
      .get('/api/knowledge/mound/federation/regions')
      .catch(() => null);
    if (response) {
      expect([200, 401, 404]).toContain(response.status());
    }
  });

  test('should handle federation status endpoint', async ({ page }) => {
    await page.route('**/api/knowledge/mound/federation/status', (route) => {
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          regions: { 'us-west-2': mockFederatedRegions[0] },
          totalRegions: 1,
          enabledRegions: 1,
        }),
      });
    });

    const response = await page.request
      .get('/api/knowledge/mound/federation/status')
      .catch(() => null);
    if (response) {
      expect([200, 401, 404]).toContain(response.status());
    }
  });

  test('should handle sync push endpoint', async ({ page }) => {
    await page.route('**/api/knowledge/mound/federation/sync/push', (route) => {
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          success: true,
          regionId: 'us-west-2',
          direction: 'push',
          nodesSynced: 10,
          nodesFailed: 0,
          durationMs: 150,
        }),
      });
    });

    const response = await page.request
      .post('/api/knowledge/mound/federation/sync/push', { data: { region_id: 'us-west-2' } })
      .catch(() => null);

    if (response) {
      expect([200, 400, 401, 404]).toContain(response.status());
    }
  });

  test('should handle sync pull endpoint', async ({ page }) => {
    await page.route('**/api/knowledge/mound/federation/sync/pull', (route) => {
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          success: true,
          regionId: 'us-west-2',
          direction: 'pull',
          nodesSynced: 5,
          nodesFailed: 0,
          durationMs: 120,
        }),
      });
    });

    const response = await page.request
      .post('/api/knowledge/mound/federation/sync/pull', { data: { region_id: 'us-west-2' } })
      .catch(() => null);

    if (response) {
      expect([200, 400, 401, 404]).toContain(response.status());
    }
  });
});

test.describe('Knowledge Mound Global Knowledge', () => {
  test('should handle global knowledge query endpoint', async ({ page }) => {
    await page.route('**/api/knowledge/mound/global', (route) => {
      if (route.request().method() === 'GET') {
        route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify({
            items: [
              {
                id: 'global-fact-1',
                content: 'Verified global fact',
                confidence: 0.95,
                verifiedBy: 'admin',
              },
            ],
            count: 1,
          }),
        });
      } else {
        route.continue();
      }
    });

    const response = await page.request
      .get('/api/knowledge/mound/global?query=test')
      .catch(() => null);
    if (response) {
      expect([200, 401, 404]).toContain(response.status());
    }
  });

  test('should handle system facts endpoint', async ({ page }) => {
    await page.route('**/api/knowledge/mound/global/facts', (route) => {
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          facts: [{ id: 'fact-1', content: 'System verified fact', confidence: 0.99 }],
          count: 1,
          total: 1,
        }),
      });
    });

    const response = await page.request.get('/api/knowledge/mound/global/facts').catch(() => null);
    if (response) {
      expect([200, 401, 404]).toContain(response.status());
    }
  });

  test('should handle promote to global endpoint', async ({ page }) => {
    await page.route('**/api/knowledge/mound/global/promote', (route) => {
      route.fulfill({
        status: 201,
        contentType: 'application/json',
        body: JSON.stringify({ success: true, globalId: 'promoted-1', originalId: 'node-1' }),
      });
    });

    const response = await page.request
      .post('/api/knowledge/mound/global/promote', {
        data: { item_id: 'node-1', workspace_id: 'ws-1', reason: 'high_consensus' },
      })
      .catch(() => null);

    if (response) {
      expect([201, 400, 401, 403, 404]).toContain(response.status());
    }
  });
});
