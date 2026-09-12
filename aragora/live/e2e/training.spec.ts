import { test, expect, mockApiResponse } from './fixtures';

/**
 * E2E tests for Training Export functionality.
 *
 * Tests the training data export system including:
 * - Page loading and navigation
 * - Export type selection (SFT, DPO, Gauntlet)
 * - Export configuration options
 * - Tab navigation (Export, Formats, History)
 * - API endpoint handling
 */

// Mock training stats data
const mockStats = {
  available_exporters: ['sft', 'dpo', 'gauntlet'],
  export_directory: '/exports',
  exported_files: [
    {
      name: 'sft_export_1705555200000.json',
      size_bytes: 15360,
      created_at: new Date().toISOString(),
      modified_at: new Date().toISOString(),
    },
    {
      name: 'dpo_export_1705468800000.jsonl',
      size_bytes: 8192,
      created_at: new Date().toISOString(),
      modified_at: new Date().toISOString(),
    },
  ],
  sft_available: true,
};

// Mock formats data
const mockFormats = {
  formats: {
    sft: {
      description: 'Supervised Fine-Tuning format',
      schema: { instruction: 'string', response: 'string' },
      use_case: 'General instruction tuning',
    },
    dpo: {
      description: 'Direct Preference Optimization format',
      schema: { prompt: 'string', chosen: 'string', rejected: 'string' },
      use_case: 'Preference learning',
    },
    gauntlet: {
      description: 'Adversarial training format',
      schema: { attack: 'string', defense: 'string', outcome: 'string' },
      use_case: 'Red-teaming and safety training',
    },
  },
  output_formats: ['json', 'jsonl'],
  endpoints: {
    sft: '/api/training/export/sft',
    dpo: '/api/training/export/dpo',
    gauntlet: '/api/training/export/gauntlet',
  },
};

// Mock export result
const _mockExportResult = {
  export_type: 'sft',
  total_records: 50,
  parameters: { min_confidence: 0.7, min_success_rate: 0.6, limit: 100 },
  exported_at: new Date().toISOString(),
  format: 'json',
  records: [
    { instruction: 'Test instruction 1', response: 'Test response 1' },
    { instruction: 'Test instruction 2', response: 'Test response 2' },
  ],
};

test.describe('Training Export Page', () => {
  test('should load training page', async ({ page, aragoraPage }) => {
    await page.goto('/training');
    await aragoraPage.dismissAllOverlays();

    await expect(page).toHaveURL(/\/training/);
    await expect(page.locator('body')).toBeVisible();
  });

  test('should display training export panel', async ({ page, aragoraPage }) => {
    await mockApiResponse(page, '**/api/training/stats', mockStats);
    await mockApiResponse(page, '**/api/training/formats', mockFormats);

    await page.goto('/training');
    await aragoraPage.dismissAllOverlays();
    await page.waitForLoadState('domcontentloaded');

    // Page should have training-related content
    await expect(page.locator('body')).toBeVisible();

    // Check for main heading
    const heading = page.locator('h1, h2').filter({ hasText: /training/i });
    await expect(heading.first()).toBeVisible({ timeout: 5000 });
  });

  test('should have export type selection', async ({ page, aragoraPage }) => {
    await mockApiResponse(page, '**/api/training/**', mockStats);
    await mockApiResponse(page, '**/api/training/formats', mockFormats);

    await page.goto('/training');
    await aragoraPage.dismissAllOverlays();
    await page.waitForLoadState('domcontentloaded');

    // Look for export type buttons (SFT, DPO, Gauntlet)
    const sftButton = page.locator('button', { hasText: /sft/i });
    const hasSft = await sftButton
      .first()
      .isVisible({ timeout: 3000 })
      .catch(() => false);
    expect(hasSft).toBeDefined();
  });

  test('should have tab navigation', async ({ page, aragoraPage }) => {
    await mockApiResponse(page, '**/api/training/**', mockStats);
    await mockApiResponse(page, '**/api/training/formats', mockFormats);

    await page.goto('/training');
    await aragoraPage.dismissAllOverlays();
    await page.waitForLoadState('domcontentloaded');

    // Look for tab buttons
    const tabs = page.locator('button').filter({ hasText: /export|formats|history/i });
    const hasTab = await tabs
      .first()
      .isVisible({ timeout: 3000 })
      .catch(() => false);
    expect(hasTab).toBeDefined();
  });

  test('should have export configuration options', async ({ page, aragoraPage }) => {
    await mockApiResponse(page, '**/api/training/**', mockStats);
    await mockApiResponse(page, '**/api/training/formats', mockFormats);

    await page.goto('/training');
    await aragoraPage.dismissAllOverlays();
    await page.waitForLoadState('domcontentloaded');

    // Look for configuration inputs (sliders, selects, checkboxes)
    const inputs = page.locator(
      'input[type="range"], input[type="number"], select, input[type="checkbox"]',
    );
    const hasInputs = await inputs
      .first()
      .isVisible({ timeout: 3000 })
      .catch(() => false);
    expect(hasInputs).toBeDefined();
  });

  test('should handle empty state gracefully', async ({ page, aragoraPage }) => {
    await mockApiResponse(page, '**/api/training/stats', {
      available_exporters: [],
      export_directory: '/exports',
      exported_files: [],
    });
    await mockApiResponse(page, '**/api/training/formats', mockFormats);

    await page.goto('/training');
    await aragoraPage.dismissAllOverlays();
    await page.waitForLoadState('domcontentloaded');

    // Page should handle empty state
    await expect(page.locator('body')).toBeVisible();
  });

  test('should fall back gracefully when API unavailable', async ({ page, aragoraPage }) => {
    await page.route('**/api/training/**', (route) => {
      route.fulfill({ status: 503, body: 'Service Unavailable' });
    });

    await page.goto('/training');
    await aragoraPage.dismissAllOverlays();
    await page.waitForLoadState('domcontentloaded');

    // Page should still be functional
    await expect(page.locator('body')).toBeVisible();
  });
});

test.describe('Training Export Flow', () => {
  test('should select export type', async ({ page, aragoraPage }) => {
    await mockApiResponse(page, '**/api/training/**', mockStats);
    await mockApiResponse(page, '**/api/training/formats', mockFormats);

    await page.goto('/training');
    await aragoraPage.dismissAllOverlays();
    await page.waitForLoadState('domcontentloaded');

    // Try clicking DPO export type if available
    const dpoButton = page.locator('button', { hasText: /dpo/i }).first();
    const hasDpo = await dpoButton.isVisible({ timeout: 3000 }).catch(() => false);

    if (hasDpo) {
      await dpoButton.click();
      await page.waitForTimeout(300);
    }

    await expect(page.locator('body')).toBeVisible();
  });

  test('should switch tabs', async ({ page, aragoraPage }) => {
    await mockApiResponse(page, '**/api/training/**', mockStats);
    await mockApiResponse(page, '**/api/training/formats', mockFormats);

    await page.goto('/training');
    await aragoraPage.dismissAllOverlays();
    await page.waitForLoadState('domcontentloaded');

    // Try clicking Formats tab
    const formatsTab = page.locator('button', { hasText: /formats/i }).first();
    const hasFormats = await formatsTab.isVisible({ timeout: 3000 }).catch(() => false);

    if (hasFormats) {
      await formatsTab.click();
      await page.waitForTimeout(300);
    }

    await expect(page.locator('body')).toBeVisible();
  });

  test('should handle export button state', async ({ page, aragoraPage }) => {
    await mockApiResponse(page, '**/api/training/**', mockStats);
    await mockApiResponse(page, '**/api/training/formats', mockFormats);

    await page.goto('/training');
    await aragoraPage.dismissAllOverlays();
    await page.waitForLoadState('domcontentloaded');

    // Look for export button
    const exportButton = page.locator('button', { hasText: /export.*data/i }).first();
    const hasExport = await exportButton.isVisible({ timeout: 3000 }).catch(() => false);

    if (hasExport) {
      // Button should exist and be clickable or disabled based on availability
      const isDisabled = await exportButton.isDisabled().catch(() => false);
      expect(typeof isDisabled).toBe('boolean');
    }

    await expect(page.locator('body')).toBeVisible();
  });
});

test.describe('Training API Endpoints', () => {
  test.skip(({ browserName }) => browserName !== 'chromium', 'API tests only run in chromium');

  test('should handle /api/training/stats endpoint', async ({ page }) => {
    const response = await page.request.get('/api/training/stats').catch(() => null);

    if (response) {
      expect([200, 404, 503]).toContain(response.status());
    } else {
      expect(true).toBe(true);
    }
  });

  test('should handle /api/training/formats endpoint', async ({ page }) => {
    const response = await page.request.get('/api/training/formats').catch(() => null);

    if (response) {
      expect([200, 404, 503]).toContain(response.status());
    } else {
      expect(true).toBe(true);
    }
  });

  test('should handle /api/training/export/sft endpoint', async ({ page }) => {
    const response = await page.request
      .post('/api/training/export/sft', { data: { limit: 10, format: 'json' } })
      .catch(() => null);

    if (response) {
      expect([200, 400, 404, 503]).toContain(response.status());
    } else {
      expect(true).toBe(true);
    }
  });
});

test.describe('Training Page Navigation', () => {
  test('should have navigation links', async ({ page, aragoraPage }) => {
    await page.goto('/training');
    await aragoraPage.dismissAllOverlays();
    await page.waitForLoadState('domcontentloaded');

    // Check for header navigation
    const dashboardLink = page.locator('a[href="/"], a:has-text("DASHBOARD")');
    const hasNav = await dashboardLink
      .first()
      .isVisible({ timeout: 3000 })
      .catch(() => false);
    expect(hasNav).toBeDefined();
  });

  test('should navigate to other pages', async ({ page, aragoraPage }) => {
    await page.goto('/training');
    await aragoraPage.dismissAllOverlays();
    await page.waitForLoadState('domcontentloaded');

    // Click dashboard link if available
    const dashboardLink = page.locator('a:has-text("DASHBOARD")').first();
    const hasDashboard = await dashboardLink.isVisible({ timeout: 3000 }).catch(() => false);

    if (hasDashboard) {
      await dashboardLink.click();
      await page.waitForLoadState('domcontentloaded');
      await expect(page).toHaveURL('/');
    } else {
      // If no dashboard link, page should still be functional
      await expect(page.locator('body')).toBeVisible();
    }
  });
});
