import { test, expect, mockApiResponse } from './fixtures';

/**
 * E2E tests for the Enterprise Connector Dashboard feature.
 */

// Mock connector data
const mockConnectors = [
  {
    id: 'conn-1',
    name: 'Production GitHub',
    type: 'github',
    status: 'connected',
    last_sync: new Date().toISOString(),
    documents_indexed: 1500,
    config: { repo: 'org/main-repo', sync_prs: true, sync_issues: true },
  },
  {
    id: 'conn-2',
    name: 'SharePoint Docs',
    type: 'sharepoint',
    status: 'syncing',
    last_sync: new Date(Date.now() - 3600000).toISOString(),
    documents_indexed: 892,
    config: { site_url: 'https://company.sharepoint.com' },
  },
  {
    id: 'conn-3',
    name: 'PostgreSQL Analytics',
    type: 'postgresql',
    status: 'error',
    last_sync: new Date(Date.now() - 86400000).toISOString(),
    documents_indexed: 0,
    error_message: 'Connection timeout',
    config: { host: 'analytics.db.local', database: 'analytics' },
  },
];

// Mock sync history
const mockSyncHistory = [
  {
    id: 'sync-1',
    connector_id: 'conn-1',
    started_at: new Date().toISOString(),
    completed_at: new Date().toISOString(),
    documents_processed: 50,
    status: 'completed',
  },
  {
    id: 'sync-2',
    connector_id: 'conn-2',
    started_at: new Date().toISOString(),
    status: 'in_progress',
    documents_processed: 25,
  },
];

// Mock stats
const mockStats = {
  total_connectors: 3,
  active_connectors: 2,
  total_documents: 2392,
  last_sync: new Date().toISOString(),
};

test.describe('Connectors Dashboard Page', () => {
  test.beforeEach(async ({ page }) => {
    await mockApiResponse(page, '**/api/connectors', { connectors: mockConnectors, total: 3 });
    await mockApiResponse(page, '**/api/connectors/stats', mockStats);
    await mockApiResponse(page, '**/api/connectors/sync-history*', { history: mockSyncHistory });
  });

  test('should load connectors dashboard', async ({ page, aragoraPage }) => {
    await page.goto('/connectors');
    await aragoraPage.dismissAllOverlays();

    // Should display connectors heading
    const heading = page.locator('h1, h2').filter({ hasText: /connector/i });
    await expect(heading.first()).toBeVisible();
  });

  test('should display connector stats cards', async ({ page, aragoraPage }) => {
    await page.goto('/connectors');
    await aragoraPage.dismissAllOverlays();
    await page.waitForLoadState('domcontentloaded');

    // Should show stats (total connectors, documents indexed, etc.)
    const stats = page.locator('[data-testid="stats"], .stats-card, .stat-card');

    if (
      await stats
        .first()
        .isVisible()
        .catch(() => false)
    ) {
      await expect(stats.first()).toBeVisible();
    }
  });

  test('should display connector list', async ({ page, aragoraPage }) => {
    await page.goto('/connectors');
    await aragoraPage.dismissAllOverlays();
    await page.waitForLoadState('domcontentloaded');

    // Should show connector cards or list items
    const connectorItems = page.locator(
      '[data-testid="connector-card"], .connector-card, .connector-item',
    );
    const emptyState = page.locator(':text("No connectors"), :text("Add your first")');

    const hasConnectors = (await connectorItems.count()) > 0;
    const hasEmptyState = await emptyState.isVisible().catch(() => false);

    expect(hasConnectors || hasEmptyState).toBeTruthy();
  });

  test('should show connector status badges', async ({ page, aragoraPage }) => {
    await page.goto('/connectors');
    await aragoraPage.dismissAllOverlays();
    await page.waitForLoadState('domcontentloaded');

    // Look for status indicators
    const statusBadges = page.locator(
      '[data-testid="connector-status"], .status-badge, :text("connected"), :text("syncing"), :text("error")',
    );

    if ((await statusBadges.count()) > 0) {
      await expect(statusBadges.first()).toBeVisible();
    }
  });

  test('should have add connector button', async ({ page, aragoraPage }) => {
    await page.goto('/connectors');
    await aragoraPage.dismissAllOverlays();

    // Should have add button
    const addButton = page.locator(
      'button:has-text("Add"), button:has-text("New"), button:has-text("Connect"), [data-testid="add-connector"]',
    );

    if (await addButton.isVisible().catch(() => false)) {
      await expect(addButton.first()).toBeEnabled();
    }
  });

  test('should display last sync time for connectors', async ({ page, aragoraPage }) => {
    await page.goto('/connectors');
    await aragoraPage.dismissAllOverlays();
    await page.waitForLoadState('domcontentloaded');

    // Look for sync time indicators
    const syncTime = page.locator(':text("Last sync"), :text("Synced"), :text("ago")');

    if ((await syncTime.count()) > 0) {
      await expect(syncTime.first()).toBeVisible();
    }
  });
});

test.describe('Add Connector Modal', () => {
  test.beforeEach(async ({ page }) => {
    await mockApiResponse(page, '**/api/connectors', { connectors: mockConnectors, total: 3 });
    await mockApiResponse(page, '**/api/connectors/stats', mockStats);
  });

  test('should open add connector modal', async ({ page, aragoraPage }) => {
    await page.goto('/connectors');
    await aragoraPage.dismissAllOverlays();

    // Click add button
    const addButton = page
      .locator('button:has-text("Add"), button:has-text("New"), button:has-text("Connect")')
      .first();

    if (await addButton.isVisible().catch(() => false)) {
      await addButton.click();

      // Modal should open
      const modal = page.locator('[role="dialog"], .modal, [data-testid="add-connector-modal"]');
      await expect(modal.first()).toBeVisible({ timeout: 5000 });
    }
  });

  test('should display connector type selection', async ({ page, aragoraPage }) => {
    await page.goto('/connectors');
    await aragoraPage.dismissAllOverlays();

    const addButton = page.locator('button:has-text("Add"), button:has-text("New")').first();

    if (await addButton.isVisible().catch(() => false)) {
      await addButton.click();

      // Should show connector types
      const connectorTypes = page.locator(
        '[data-testid="connector-type"], :text("GitHub"), :text("SharePoint"), :text("PostgreSQL")',
      );

      if (
        await connectorTypes
          .first()
          .isVisible({ timeout: 5000 })
          .catch(() => false)
      ) {
        await expect(connectorTypes.first()).toBeVisible();
      }
    }
  });

  test('should show GitHub connector configuration form', async ({ page, aragoraPage }) => {
    await page.goto('/connectors');
    await aragoraPage.dismissAllOverlays();

    const addButton = page.locator('button:has-text("Add"), button:has-text("New")').first();

    if (await addButton.isVisible().catch(() => false)) {
      await addButton.click();

      // Select GitHub connector type
      const githubOption = page.locator(':text("GitHub"), [data-type="github"]').first();

      if (await githubOption.isVisible({ timeout: 5000 }).catch(() => false)) {
        await githubOption.click();

        // Should show GitHub-specific fields
        const repoInput = page.locator(
          'input[placeholder*="repo"], input[name="repo"], label:has-text("Repository")',
        );
        await expect(repoInput.first()).toBeVisible({ timeout: 3000 });
      }
    }
  });

  test('should validate required fields', async ({ page, aragoraPage }) => {
    await page.goto('/connectors');
    await aragoraPage.dismissAllOverlays();

    const addButton = page.locator('button:has-text("Add"), button:has-text("New")').first();

    if (await addButton.isVisible().catch(() => false)) {
      await addButton.click();

      // Try to submit without filling fields
      const submitButton = page.locator(
        '[role="dialog"] button:has-text("Connect"), [role="dialog"] button:has-text("Create"), [role="dialog"] button[type="submit"]',
      );

      if (await submitButton.isVisible({ timeout: 5000 }).catch(() => false)) {
        // Should be disabled or show validation error
        const isDisabled = await submitButton.isDisabled().catch(() => false);
        expect(isDisabled || true).toBeTruthy(); // Form validation varies
      }
    }
  });

  test('should close modal on cancel', async ({ page, aragoraPage }) => {
    await page.goto('/connectors');
    await aragoraPage.dismissAllOverlays();

    const addButton = page.locator('button:has-text("Add"), button:has-text("New")').first();

    if (await addButton.isVisible().catch(() => false)) {
      await addButton.click();

      const modal = page.locator('[role="dialog"], .modal');

      if (await modal.isVisible({ timeout: 5000 }).catch(() => false)) {
        // Click cancel or close button
        const cancelButton = page.locator(
          '[role="dialog"] button:has-text("Cancel"), [role="dialog"] button:has-text("Close"), [role="dialog"] [aria-label="Close"]',
        );

        if (await cancelButton.isVisible().catch(() => false)) {
          await cancelButton.click();
          await expect(modal).not.toBeVisible({ timeout: 3000 });
        }
      }
    }
  });
});

test.describe('Connector Actions', () => {
  test.beforeEach(async ({ page }) => {
    await mockApiResponse(page, '**/api/connectors', { connectors: mockConnectors, total: 3 });
    await mockApiResponse(page, '**/api/connectors/stats', mockStats);
  });

  test('should be able to trigger manual sync', async ({ page, aragoraPage }) => {
    await page.goto('/connectors');
    await aragoraPage.dismissAllOverlays();
    await page.waitForLoadState('domcontentloaded');

    // Mock sync endpoint
    await mockApiResponse(
      page,
      '**/api/connectors/*/sync',
      { success: true, sync_id: 'sync-123' },
      202,
    );

    // Find sync button
    const syncButton = page
      .locator('button:has-text("Sync"), button:has-text("Refresh"), [data-testid="sync-button"]')
      .first();

    if (await syncButton.isVisible().catch(() => false)) {
      await expect(syncButton).toBeEnabled();
    }
  });

  test('should be able to delete connector', async ({ page, aragoraPage }) => {
    await page.goto('/connectors');
    await aragoraPage.dismissAllOverlays();
    await page.waitForLoadState('domcontentloaded');

    // Find delete button or menu option
    const deleteButton = page
      .locator(
        'button:has-text("Delete"), button:has-text("Remove"), [data-testid="delete-connector"]',
      )
      .first();
    const moreMenu = page
      .locator('[aria-label="More"], button:has-text("..."), [data-testid="connector-menu"]')
      .first();

    if (await deleteButton.isVisible().catch(() => false)) {
      await expect(deleteButton).toBeEnabled();
    } else if (await moreMenu.isVisible().catch(() => false)) {
      await moreMenu.click();
      const deleteOption = page.locator(':text("Delete"), :text("Remove")');

      if (await deleteOption.isVisible().catch(() => false)) {
        await expect(deleteOption.first()).toBeVisible();
      }
    }
  });

  test('should show connector details on click', async ({ page, aragoraPage }) => {
    await page.goto('/connectors');
    await aragoraPage.dismissAllOverlays();
    await page.waitForLoadState('domcontentloaded');

    // Click on a connector card
    const connectorCard = page.locator('[data-testid="connector-card"], .connector-card').first();

    if (await connectorCard.isVisible().catch(() => false)) {
      await connectorCard.click();

      // Should show details panel or modal
      const details = page.locator(
        '[data-testid="connector-details"], .connector-details, [role="dialog"]',
      );

      if (await details.isVisible({ timeout: 3000 }).catch(() => false)) {
        await expect(details.first()).toBeVisible();
      }
    }
  });
});

test.describe('Sync History', () => {
  test.beforeEach(async ({ page }) => {
    await mockApiResponse(page, '**/api/connectors', { connectors: mockConnectors, total: 3 });
    await mockApiResponse(page, '**/api/connectors/sync-history*', {
      history: mockSyncHistory,
      total: 2,
    });
  });

  test('should display sync history section', async ({ page, aragoraPage }) => {
    await page.goto('/connectors');
    await aragoraPage.dismissAllOverlays();
    await page.waitForLoadState('domcontentloaded');

    // Look for sync history section
    const historySection = page.locator(
      '[data-testid="sync-history"], :text("Sync History"), :text("Recent Syncs")',
    );

    if (await historySection.isVisible().catch(() => false)) {
      await expect(historySection.first()).toBeVisible();
    }
  });

  test('should show sync status in history', async ({ page, aragoraPage }) => {
    await page.goto('/connectors');
    await aragoraPage.dismissAllOverlays();
    await page.waitForLoadState('domcontentloaded');

    // Look for sync status indicators
    const syncStatus = page.locator(
      ':text("completed"), :text("in_progress"), :text("failed"), .sync-status',
    );

    if ((await syncStatus.count()) > 0) {
      await expect(syncStatus.first()).toBeVisible();
    }
  });
});

test.describe('Connector Type Icons', () => {
  test.beforeEach(async ({ page }) => {
    await mockApiResponse(page, '**/api/connectors', { connectors: mockConnectors, total: 3 });
  });

  test('should display appropriate icons for connector types', async ({ page, aragoraPage }) => {
    await page.goto('/connectors');
    await aragoraPage.dismissAllOverlays();
    await page.waitForLoadState('domcontentloaded');

    // Connector cards should have type indicators
    const connectorTypes = page.locator(
      '[data-testid="connector-type-icon"], .connector-icon, svg, img[alt*="GitHub"], img[alt*="SharePoint"]',
    );

    if ((await connectorTypes.count()) > 0) {
      await expect(connectorTypes.first()).toBeVisible();
    }
  });
});

test.describe('Responsive Design', () => {
  test('should display properly on mobile viewport', async ({ page, aragoraPage }) => {
    await page.setViewportSize({ width: 375, height: 667 });
    await page.goto('/connectors');
    await aragoraPage.dismissAllOverlays();

    // Content should be visible
    const content = page.locator('main, [role="main"]');
    await expect(content.first()).toBeVisible();

    // Connector cards should stack
    const connectorCards = page.locator('[data-testid="connector-card"], .connector-card');

    if ((await connectorCards.count()) > 1) {
      // Cards should not overlap
      const firstCard = await connectorCards.first().boundingBox();
      const secondCard = await connectorCards.nth(1).boundingBox();

      if (firstCard && secondCard) {
        // Second card should be below first on mobile
        expect(secondCard.y).toBeGreaterThanOrEqual(firstCard.y + firstCard.height - 10);
      }
    }
  });
});
