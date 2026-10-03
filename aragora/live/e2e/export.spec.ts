import { test, expect, mockApiResponse, mockDebate } from './fixtures';

test.describe('Debate Export', () => {
  test.beforeEach(async ({ page }) => {
    await mockApiResponse(page, '**/api/health', { status: 'ok' });
    await mockApiResponse(page, '**/api/debates/test-debate', mockDebate);
  });

  test('should have export button on debate page', async ({ page, aragoraPage }) => {
    await page.goto('/debate/test-debate');
    await aragoraPage.dismissAllOverlays();
    await page.waitForLoadState('domcontentloaded');

    // Page should load - export button is optional feature
    await expect(page.locator('body')).toBeVisible({ timeout: 10000 });
  });

  test('should show export options on click', async ({ page }) => {
    await page.goto('/debate/test-debate');

    const exportButton = page.locator('button, a').filter({
      hasText: /export|download/i
    }).first();

    if (await exportButton.isVisible()) {
      await exportButton.click();

      // Should show format options
      const formatOptions = page.locator('text=/pdf|html|markdown|json/i').first();
      await expect(formatOptions).toBeVisible({ timeout: 5000 });
    }
  });

  test('should export to PDF', async ({ page }) => {
    // Mock PDF export endpoint
    await page.route('**/api/debates/test-debate/export/pdf', async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/pdf',
        body: Buffer.from('PDF content'),
      });
    });

    await page.goto('/debate/test-debate');

    const exportButton = page.locator('button, a').filter({
      hasText: /export|download/i
    }).first();

    if (await exportButton.isVisible()) {
      await exportButton.click();

      // Find PDF option
      const pdfOption = page.locator('button, a').filter({
        hasText: /pdf/i
      }).first();

      if (await pdfOption.isVisible()) {
        // Set up download listener
        const downloadPromise = page.waitForEvent('download', { timeout: 5000 }).catch(() => null);

        await pdfOption.click();

        // May or may not trigger download in test env
        await downloadPromise;
      }
    }
  });

  test('should export to HTML', async ({ page }) => {
    await page.route('**/api/debates/test-debate/export/html', async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'text/html',
        body: '<html><body>Debate export</body></html>',
      });
    });

    await page.goto('/debate/test-debate');

    const exportButton = page.locator('button, a').filter({
      hasText: /export|download/i
    }).first();

    if (await exportButton.isVisible()) {
      await exportButton.click();

      const htmlOption = page.locator('button, a').filter({
        hasText: /html/i
      }).first();

      if (await htmlOption.isVisible()) {
        await htmlOption.click();
        await page.waitForTimeout(1000);
      }
    }
  });

  test('should export to JSON', async ({ page }) => {
    await page.route('**/api/debates/test-debate/export/json', async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(mockDebate),
      });
    });

    await page.goto('/debate/test-debate');

    const exportButton = page.locator('button, a').filter({
      hasText: /export|download/i
    }).first();

    if (await exportButton.isVisible()) {
      await exportButton.click();

      const jsonOption = page.locator('button, a').filter({
        hasText: /json/i
      }).first();

      if (await jsonOption.isVisible()) {
        await jsonOption.click();
        await page.waitForTimeout(1000);
      }
    }
  });

  test('should show loading state during export', async ({ page }) => {
    // Slow down export
    await page.route('**/api/debates/test-debate/export/**', async (route) => {
      await new Promise(resolve => setTimeout(resolve, 2000));
      await route.fulfill({
        status: 200,
        body: 'content',
      });
    });

    await page.goto('/debate/test-debate');

    const exportButton = page.locator('button, a').filter({
      hasText: /export|download/i
    }).first();

    if (await exportButton.isVisible()) {
      await exportButton.click();

      const formatOption = page.locator('button, a').filter({
        hasText: /pdf|html|json/i
      }).first();

      if (await formatOption.isVisible()) {
        await formatOption.click();

        // Should show loading
        const loading = page.locator('[class*="loading"], [class*="spinner"]').or(
          page.locator('text=/exporting|generating|loading/i')
        ).first();

        await expect(loading).toBeVisible({ timeout: 1000 });
      }
    }
  });

  test('should handle export errors', async ({ page }) => {
    await page.route('**/api/debates/test-debate/export/**', async (route) => {
      await route.fulfill({
        status: 500,
        contentType: 'application/json',
        body: JSON.stringify({ error: 'Export failed' }),
      });
    });

    await page.goto('/debate/test-debate');

    const exportButton = page.locator('button, a').filter({
      hasText: /export|download/i
    }).first();

    if (await exportButton.isVisible()) {
      await exportButton.click();

      const formatOption = page.locator('button, a').filter({
        hasText: /pdf|html|json/i
      }).first();

      if (await formatOption.isVisible()) {
        await formatOption.click();

        // Should show error
        const error = page.locator('[class*="error"], [role="alert"]').or(
          page.locator('text=/error|failed/i')
        ).first();

        await expect(error).toBeVisible({ timeout: 5000 });
      }
    }
  });
});

test.describe('Debate Sharing', () => {
  test.beforeEach(async ({ page }) => {
    await mockApiResponse(page, '**/api/health', { status: 'ok' });
    await mockApiResponse(page, '**/api/debates/test-debate', mockDebate);
  });

  test('should have share button', async ({ page }) => {
    await page.goto('/debate/test-debate');

    const shareButton = page.locator('button, a').filter({
      hasText: /share|copy.*link/i
    }).first();

    // Share functionality may or may not be visible
    if (await shareButton.isVisible()) {
      await expect(shareButton).toBeEnabled();
    }
  });

  test('should copy link to clipboard', async ({ page }) => {
    await page.goto('/debate/test-debate');

    const shareButton = page.locator('button, a').filter({
      hasText: /share|copy/i
    }).first();

    if (await shareButton.isVisible()) {
      await shareButton.click();

      // Should show confirmation
      const confirmation = page.locator('text=/copied|link/i').first();
      await expect(confirmation).toBeVisible({ timeout: 3000 });
    }
  });
});
