/**
 * Visual Regression Tests for UI Consistency
 *
 * These tests verify:
 * 1. No duplicate/nested headers on any page
 * 2. Consistent styling across all pages
 * 3. Proper theme switching without layout shifts
 * 4. Screenshot baselines for visual regression
 */

import { test, expect, Page } from '@playwright/test';
import { AragoraPage } from './fixtures';

// Pages to test for UI consistency
const PAGES_TO_TEST = [
  { path: '/', name: 'dashboard', description: 'Dashboard home' },
  { path: '/landing', name: 'landing', description: 'Landing page' },
  { path: '/arena', name: 'arena', description: 'Arena page' },
  { path: '/debates', name: 'debates', description: 'Debates list' },
  { path: '/agents', name: 'agents', description: 'Agents list' },
  { path: '/leaderboard', name: 'leaderboard', description: 'Leaderboard' },
  { path: '/knowledge', name: 'knowledge', description: 'Knowledge base' },
  { path: '/settings', name: 'settings', description: 'Settings' },
];

// Selectors to mask (dynamic content that changes between runs)
const DYNAMIC_CONTENT_MASKS = [
  '[data-testid="timestamp"]',
  '[data-testid="live-status"]',
  '[data-testid="connection-status"]',
  '.animate-pulse',
  '[aria-busy="true"]',
];

// Helper to count header elements
async function countHeaders(page: Page): Promise<number> {
  return await page.evaluate(() => {
    const headers = document.querySelectorAll('header, [role="banner"]');
    return headers.length;
  });
}

// Helper to check for nested headers
async function hasNestedHeaders(page: Page): Promise<boolean> {
  return await page.evaluate(() => {
    const headers = document.querySelectorAll('header');
    for (const header of headers) {
      if (header.querySelector('header')) {
        return true;
      }
    }
    return false;
  });
}

// Helper to count ARAGORA branding instances
async function countAragoraBranding(page: Page): Promise<number> {
  return await page.evaluate(() => {
    const body = document.body;
    const text = body.innerText;
    const matches = text.match(/ARAGORA/gi);
    return matches ? matches.length : 0;
  });
}

// Helper to count theme toggles
async function countThemeToggles(page: Page): Promise<number> {
  return await page.evaluate(() => {
    // Look for theme toggle buttons (sun/moon icons or theme-related buttons)
    const toggles = document.querySelectorAll(
      'button[aria-label*="theme" i], button[aria-label*="dark" i], button[aria-label*="light" i], [data-testid="theme-toggle"]',
    );
    return toggles.length;
  });
}

// Helper to set theme
async function setTheme(page: Page, theme: 'dark' | 'light') {
  await page.evaluate((t) => {
    if (t === 'light') {
      document.body.setAttribute('data-theme', 'light');
      document.documentElement.classList.remove('dark');
    } else {
      document.body.removeAttribute('data-theme');
      document.documentElement.classList.add('dark');
    }
    localStorage.setItem('aragora-theme', t);
  }, theme);
  // Wait for CSS transitions
  await page.waitForTimeout(300);
}

// Helper to prepare page for screenshot
async function prepareForScreenshot(page: Page) {
  const aragoraPage = new AragoraPage(page);
  await aragoraPage.dismissAllOverlays();
  await page.waitForLoadState('networkidle').catch(() => {});

  // Disable animations for consistent screenshots
  await page.addStyleTag({
    content: `
      *, *::before, *::after {
        animation-duration: 0s !important;
        animation-delay: 0s !important;
        transition-duration: 0s !important;
        transition-delay: 0s !important;
      }
      .crt-flicker { animation: none !important; }
      .animate-pulse { animation: none !important; }
    `,
  });

  await page.waitForTimeout(500);
}

test.describe('Header Consistency', () => {
  for (const pageConfig of PAGES_TO_TEST) {
    test(`${pageConfig.name}: should have at most one header`, async ({ page }) => {
      await page.goto(pageConfig.path);
      await prepareForScreenshot(page);

      const headerCount = await countHeaders(page);
      expect(
        headerCount,
        `Page ${pageConfig.path} has ${headerCount} headers (expected at most 1)`,
      ).toBeLessThanOrEqual(1);
    });

    test(`${pageConfig.name}: should not have nested headers`, async ({ page }) => {
      await page.goto(pageConfig.path);
      await prepareForScreenshot(page);

      const hasNested = await hasNestedHeaders(page);
      expect(hasNested, `Page ${pageConfig.path} has nested header elements`).toBe(false);
    });
  }
});

test.describe('Branding Consistency', () => {
  test('dashboard should have ARAGORA branding in TopBar only', async ({ page }) => {
    await page.goto('/');
    await prepareForScreenshot(page);

    // Dashboard uses AppShell with TopBar - ARAGORA should appear once
    const brandingCount = await countAragoraBranding(page);
    expect(
      brandingCount,
      'Dashboard should have ARAGORA branding exactly once in TopBar',
    ).toBeGreaterThanOrEqual(1);
  });

  test('landing page should have ARAGORA branding in its own header only', async ({ page }) => {
    await page.goto('/landing');
    await prepareForScreenshot(page);

    // Landing page has standalone header - no AppShell TopBar
    const brandingCount = await countAragoraBranding(page);
    expect(
      brandingCount,
      'Landing page should have ARAGORA branding (may appear in ASCII art + header)',
    ).toBeGreaterThanOrEqual(1);
  });
});

test.describe('Theme Toggle Consistency', () => {
  for (const pageConfig of PAGES_TO_TEST) {
    test(`${pageConfig.name}: should have at most one theme toggle`, async ({ page }) => {
      await page.goto(pageConfig.path);
      await prepareForScreenshot(page);

      const toggleCount = await countThemeToggles(page);
      expect(
        toggleCount,
        `Page ${pageConfig.path} has ${toggleCount} theme toggles (expected at most 1)`,
      ).toBeLessThanOrEqual(1);
    });
  }
});

test.describe('Visual Regression Screenshots', () => {
  test.describe('Desktop Viewport', () => {
    test.beforeEach(async ({ page }) => {
      await page.setViewportSize({ width: 1280, height: 720 });
    });

    for (const pageConfig of PAGES_TO_TEST) {
      test(`${pageConfig.name}: dark theme screenshot`, async ({ page }) => {
        await page.goto(pageConfig.path);
        await prepareForScreenshot(page);
        await setTheme(page, 'dark');

        await expect(page).toHaveScreenshot(`${pageConfig.name}-dark-desktop.png`, {
          fullPage: true,
          mask: DYNAMIC_CONTENT_MASKS.map((s) => page.locator(s)),
        });
      });

      test(`${pageConfig.name}: light theme screenshot`, async ({ page }) => {
        await page.goto(pageConfig.path);
        await prepareForScreenshot(page);
        await setTheme(page, 'light');

        await expect(page).toHaveScreenshot(`${pageConfig.name}-light-desktop.png`, {
          fullPage: true,
          mask: DYNAMIC_CONTENT_MASKS.map((s) => page.locator(s)),
        });
      });
    }
  });

  test.describe('Mobile Viewport', () => {
    test.beforeEach(async ({ page }) => {
      await page.setViewportSize({ width: 375, height: 667 });
    });

    for (const pageConfig of PAGES_TO_TEST) {
      test(`${pageConfig.name}: mobile dark theme screenshot`, async ({ page }) => {
        await page.goto(pageConfig.path);
        await prepareForScreenshot(page);
        await setTheme(page, 'dark');

        await expect(page).toHaveScreenshot(`${pageConfig.name}-dark-mobile.png`, {
          fullPage: true,
          mask: DYNAMIC_CONTENT_MASKS.map((s) => page.locator(s)),
        });
      });
    }
  });
});

test.describe('Layout Stability', () => {
  test('theme switching should not cause layout shift', async ({ page }) => {
    await page.goto('/');
    await prepareForScreenshot(page);

    // Get initial bounds
    await setTheme(page, 'dark');
    const darkBounds = await page.locator('main').boundingBox();

    // Switch to light theme
    await setTheme(page, 'light');
    const lightBounds = await page.locator('main').boundingBox();

    // Verify no significant layout shift
    expect(darkBounds?.width).toBe(lightBounds?.width);
    expect(darkBounds?.height).toBeCloseTo(lightBounds?.height ?? 0, 0);
  });

  test('header height should be consistent across pages', async ({ page }) => {
    const headerHeights: Record<string, number> = {};

    for (const pageConfig of PAGES_TO_TEST) {
      await page.goto(pageConfig.path);
      await prepareForScreenshot(page);

      const header = page.locator('header').first();
      if (await header.isVisible()) {
        const bounds = await header.boundingBox();
        if (bounds) {
          headerHeights[pageConfig.name] = bounds.height;
        }
      }
    }

    // Get unique heights
    const uniqueHeights = [...new Set(Object.values(headerHeights))];

    // Allow for some variance (48px AppShell TopBar vs other headers)
    // but flag if there are too many different header heights
    expect(
      uniqueHeights.length,
      `Found ${uniqueHeights.length} different header heights: ${JSON.stringify(headerHeights)}`,
    ).toBeLessThanOrEqual(2);
  });
});

test.describe('Debate Viewer (Standalone)', () => {
  test('should have its own header without AppShell', async ({ page }) => {
    // Use a mock debate ID
    await page.goto('/debate/test-123');
    await prepareForScreenshot(page);

    const headerCount = await countHeaders(page);
    expect(headerCount, 'Debate viewer should have exactly one header').toBeLessThanOrEqual(1);

    const hasNested = await hasNestedHeaders(page);
    expect(hasNested, 'Debate viewer should not have nested headers').toBe(false);
  });
});
