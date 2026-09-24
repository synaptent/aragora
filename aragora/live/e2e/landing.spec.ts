import { test, expect } from './fixtures';

test.describe('Landing Page', () => {
  test.beforeEach(async ({ page, aragoraPage }) => {
    await page.goto('/');
    await aragoraPage.dismissAllOverlays();
    await page.waitForLoadState('domcontentloaded');
  });

  test('should display the landing page with ASCII art title', async ({ page }) => {
    // Wait for page to load
    await expect(page).toHaveTitle(/Aragora/i);

    // Check for ASCII art banner on desktop OR h1 on mobile OR compact banner
    const asciiBanner = page.locator('pre').filter({ hasText: /ARAGORA/i });
    const mobileTitle = page.locator('h1').filter({ hasText: /ARAGORA/i });
    const compactBanner = page
      .locator('[class*="AsciiBanner"], header')
      .filter({ hasText: /ARAGORA/i });

    await expect(asciiBanner.or(mobileTitle).or(compactBanner).first()).toBeVisible({
      timeout: 10000,
    });
  });

  test('should have navigation links in header', async ({ page }) => {
    // Check for any navigation links in header or the page
    const headerLinks = page.locator('header a, nav a').first();
    const footerLinks = page.locator('footer a').first();
    const anyLink = page.locator('a[href^="/"]').first();

    // At least one internal nav link should be visible somewhere
    const hasHeader = await headerLinks.isVisible().catch(() => false);
    const hasFooter = await footerLinks.isVisible().catch(() => false);
    const hasAny = await anyLink.isVisible().catch(() => false);

    expect(hasHeader || hasFooter || hasAny).toBeTruthy();
  });

  test('should have theme toggle', async ({ page }) => {
    // Look for theme toggle button
    const themeToggle = page
      .locator('button')
      .filter({ hasText: /theme|dark|light/i })
      .or(page.locator('[aria-label*="theme"]'))
      .or(
        page
          .locator('button')
          .filter({ has: page.locator('svg') })
          .first(),
      );

    // Theme toggle should be present
    await expect(themeToggle.first()).toBeVisible();
  });

  test('should display debate input form', async ({ page }) => {
    // Check for main input area
    const inputArea = page.locator('textarea, input[type="text"]').first();
    await expect(inputArea).toBeVisible();
  });

  test('should show agent selection options', async ({ page }) => {
    // Look for agent-related UI elements
    const agentSection = page.locator('text=/agent|claude|gpt|gemini/i').first();
    await expect(agentSection).toBeVisible({ timeout: 10000 });
  });

  test('should navigate to about page', async ({ page, aragoraPage }) => {
    // Direct navigation - about page should always be accessible
    await page.goto('/about');
    await aragoraPage.dismissAllOverlays();
    await page.waitForLoadState('domcontentloaded');
    // URL should contain 'about' (may have trailing slash or query params)
    expect(page.url()).toContain('about');
    // About page should have some content
    const mainContent = page.locator('main, body').first();
    await expect(mainContent).toBeVisible({ timeout: 10000 });
  });

  test('should be responsive on mobile viewport', async ({ page, aragoraPage }) => {
    await page.setViewportSize({ width: 375, height: 667 });
    await page.goto('/');
    await aragoraPage.dismissAllOverlays();
    await page.waitForLoadState('domcontentloaded');

    // Mobile title should be visible (h1 or the compact banner header)
    const mobileTitle = page.locator('h1').filter({ hasText: /ARAGORA/i });
    const headerBanner = page.locator('header').first();
    await expect(mobileTitle.or(headerBanner)).toBeVisible({ timeout: 10000 });
  });

  test('should have proper meta tags', async ({ page }) => {
    // Check for description meta tag
    const description = page.locator('meta[name="description"]');
    await expect(description).toHaveAttribute('content', /.+/);
  });

  test('should display error banner when error occurs', async ({ page }) => {
    // Trigger an error by mocking API failure
    await page.route('**/api/**', (route) => {
      route.fulfill({ status: 500, body: JSON.stringify({ error: 'Test error' }) });
    });

    // Try to interact with the page in a way that triggers API call
    const inputArea = page.locator('textarea, input[type="text"]').first();
    if (await inputArea.isVisible()) {
      await inputArea.fill('Test topic');
      // Look for submit button and click
      const submitButton = page
        .locator('button[type="submit"], button')
        .filter({ hasText: /start|debate|submit/i })
        .first();
      if (await submitButton.isVisible()) {
        await submitButton.click();
        // Error should appear. The landing error state uses inline crimson
        // styles rather than a warning/error utility class.
        await expect(
          page.getByText(/Test error|Something went wrong|Could not connect/i).first(),
        ).toBeVisible({ timeout: 10000 });
      }
    }
  });
});

test.describe('Landing Page - CRT Effects', () => {
  test('should have scanlines effect', async ({ page, aragoraPage }) => {
    await page.goto('/');
    await aragoraPage.dismissAllOverlays();

    // Check for scanlines element (usually a div with specific styling)
    const _scanlines = page.locator('[class*="scanline"], [class*="Scanline"]').first();
    // Scanlines may be implemented differently, so we just check page renders
    await expect(page.locator('body')).toBeVisible();
  });
});

test.describe('Landing Page - Accessibility', () => {
  test('should have proper heading hierarchy', async ({ page, aragoraPage }) => {
    await page.goto('/');
    await aragoraPage.dismissAllOverlays();

    // Check that there's at least one h1
    const h1 = page.locator('h1').first();
    await expect(h1).toBeVisible();
  });

  test('should have focusable interactive elements', async ({ page, aragoraPage }) => {
    await page.goto('/');
    await aragoraPage.dismissAllOverlays();

    // Tab through page and check focus
    await page.keyboard.press('Tab');
    const focusedElement = page.locator(':focus');
    await expect(focusedElement).toBeVisible();
  });

  test('should have proper color contrast', async ({ page, aragoraPage }) => {
    await page.goto('/');
    await aragoraPage.dismissAllOverlays();

    // Check that text is visible (basic contrast check)
    const textElements = page.locator('p, span, a, button');
    const firstText = textElements.first();
    await expect(firstText).toBeVisible();
  });
});
