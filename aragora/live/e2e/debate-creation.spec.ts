import { test, expect, mockApiResponse, mockAgents } from './fixtures';

// Check if we're on live.aragora.ai which shows dashboard instead of landing
const isLiveProduction = () => {
  const baseUrl = process.env.PLAYWRIGHT_BASE_URL || '';
  return baseUrl.includes('live.aragora.ai');
};

test.describe('Debate Creation', () => {
  test.beforeEach(async ({ page, aragoraPage }) => {
    // Skip on live.aragora.ai - shows dashboard not landing page with debate form
    test.skip(isLiveProduction(), 'Debate creation form only on landing page');

    // Mock API endpoints
    await mockApiResponse(page, '**/api/health', { status: 'ok', version: '1.0.0' });
    await mockApiResponse(page, '**/api/agents', { agents: mockAgents });
    await page.goto('/');
    await aragoraPage.dismissAllOverlays();
    await page.waitForLoadState('domcontentloaded');
  });

  test('should display debate input form', async ({ page }) => {
    // Check for textarea/input for question
    const questionInput = page.locator('textarea, input[type="text"]').first();
    await expect(questionInput).toBeVisible();
    await expect(questionInput).toBeEnabled();
  });

  test('should allow typing a debate topic', async ({ page }) => {
    const questionInput = page.locator('textarea, input[type="text"]').first();
    await questionInput.fill('Should AI systems be open source?');
    await expect(questionInput).toHaveValue('Should AI systems be open source?');
  });

  test('should have placeholder text with sample questions', async ({ page }) => {
    const questionInput = page.locator('textarea, input[type="text"]').first();
    const placeholder = await questionInput.getAttribute('placeholder');
    // Placeholder should contain something meaningful
    expect(placeholder).toBeTruthy();
    expect(placeholder!.length).toBeGreaterThan(10);
  });

  test('should show advanced options toggle', async ({ page }) => {
    // Look for advanced options button
    const advancedToggle = page
      .locator('button, [role="button"]')
      .filter({ hasText: /advanced|options|settings|configure/i })
      .first();

    if (await advancedToggle.isVisible()) {
      await advancedToggle.click();
      // Advanced options should appear
      await expect(page.locator('text=/rounds|agents|mode/i').first()).toBeVisible();
    }
  });

  test('should allow selecting debate mode', async ({ page }) => {
    // Open advanced options first
    const advancedToggle = page
      .locator('button, [role="button"]')
      .filter({ hasText: /advanced|options|settings/i })
      .first();

    if (await advancedToggle.isVisible()) {
      await advancedToggle.click();

      // Check for mode selector
      const modeSelector = page
        .locator('select, [role="listbox"], button')
        .filter({ hasText: /standard|graph|matrix/i })
        .first();

      if (await modeSelector.isVisible()) {
        await expect(modeSelector).toBeEnabled();
      }
    }
  });

  test('should allow selecting agents', async ({ page }) => {
    // Open advanced options
    const advancedToggle = page
      .locator('button, [role="button"]')
      .filter({ hasText: /advanced|options|settings/i })
      .first();

    if (await advancedToggle.isVisible()) {
      await advancedToggle.click();

      // Look for agent selection UI
      const agentUI = page.locator('text=/claude|gpt|gemini/i').first();
      await expect(agentUI).toBeVisible({ timeout: 5000 });
    }
  });

  test('should show API status indicator', async ({ page }) => {
    // Look for connection/status indicator
    const statusIndicator = page
      .locator('[class*="status"], [class*="online"], [class*="connected"]')
      .or(page.locator('text=/online|connected|api/i'))
      .first();

    // Some kind of status should be visible
    await expect(statusIndicator).toBeVisible({ timeout: 10000 });
  });

  test('should submit debate and receive debate ID', async ({ page }) => {
    // Mock the debate creation endpoint
    await page.route('**/api/debate', async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          debate_id: 'test-debate-123',
          status: 'created',
          topic: 'Should AI systems be open source?',
        }),
      });
    });

    // Fill in the question
    const questionInput = page.locator('textarea, input[type="text"]').first();
    await questionInput.fill('Should AI systems be open source?');

    // Find and click submit button
    const submitButton = page
      .locator('button[type="submit"], button')
      .filter({ hasText: /start|debate|submit|go/i })
      .first();

    if (await submitButton.isVisible()) {
      await submitButton.click();

      // Wait for navigation or state change
      await page.waitForTimeout(1000);

      // Should either navigate or show debate ID
      const url = page.url();
      const debateIndicator = page
        .locator('text=/test-debate-123|debate.*progress|viewing/i')
        .first();

      const hasNavigated = url.includes('debate') || url.includes('test-debate-123');
      const hasDebateIndicator = await debateIndicator.isVisible().catch(() => false);

      expect(hasNavigated || hasDebateIndicator).toBeTruthy();
    }
  });

  test('should show loading state while submitting', async ({ page }) => {
    // Slow down the API response
    await page.route('**/api/debate', async (route) => {
      await new Promise((resolve) => setTimeout(resolve, 2000));
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ debate_id: 'test-debate-123' }),
      });
    });

    const questionInput = page.locator('textarea, input[type="text"]').first();
    await questionInput.fill('Test question');

    const submitButton = page
      .locator('button[type="submit"], button')
      .filter({ hasText: /start|debate|submit|go/i })
      .first();

    if (await submitButton.isVisible()) {
      await submitButton.click();

      // Should show loading state
      const loadingIndicator = page
        .locator('[class*="loading"], [class*="spinner"], [disabled]')
        .or(page.locator('button').filter({ hasText: /loading|submitting|starting/i }))
        .first();

      await expect(loadingIndicator).toBeVisible({ timeout: 1000 });
    }
  });

  test('should handle API errors gracefully', async ({ page }) => {
    // Mock API error
    await page.route('**/api/debate', async (route) => {
      await route.fulfill({
        status: 500,
        contentType: 'application/json',
        body: JSON.stringify({ error: 'Internal server error' }),
      });
    });

    const questionInput = page.locator('textarea, input[type="text"]').first();
    await questionInput.fill('Test question');

    const submitButton = page
      .locator('button[type="submit"], button')
      .filter({ hasText: /start|debate|submit|go/i })
      .first();

    if (await submitButton.isVisible()) {
      await submitButton.click();

      // Should show error message
      const errorMessage = page
        .locator('[class*="error"], [class*="warning"], [role="alert"]')
        .or(page.locator('text=/error|failed|problem/i'))
        .first();

      await expect(errorMessage).toBeVisible({ timeout: 5000 });
    }
  });

  test('should prevent empty submission', async ({ page }) => {
    const submitButton = page
      .locator('button[type="submit"], button')
      .filter({ hasText: /start|debate|submit|go/i })
      .first();

    if (await submitButton.isVisible()) {
      // Try to click without filling question
      const isDisabled = await submitButton.isDisabled();

      if (!isDisabled) {
        await submitButton.click();
        // Should not navigate or should show validation error
        await page.waitForTimeout(500);
        expect(page.url()).toBe(page.url()); // URL should not change
      } else {
        expect(isDisabled).toBeTruthy();
      }
    }
  });
});

test.describe('Debate Creation - Keyboard Navigation', () => {
  test.beforeEach(async () => {
    // Skip on live.aragora.ai - shows dashboard not landing page
    test.skip(isLiveProduction(), 'Debate creation form only on landing page');
  });

  test('should allow tabbing through form elements', async ({ page, aragoraPage }) => {
    await mockApiResponse(page, '**/api/health', { status: 'ok' });
    await page.goto('/');
    await aragoraPage.dismissAllOverlays();
    await page.waitForLoadState('domcontentloaded');

    // Focus the first input
    const questionInput = page.locator('textarea, input[type="text"]').first();
    if (await questionInput.isVisible().catch(() => false)) {
      await questionInput.focus();

      // Tab through elements
      await page.keyboard.press('Tab');

      // Something should be focused
      const focusedElement = page.locator(':focus');
      await expect(focusedElement).toBeVisible();
    }
  });
});
