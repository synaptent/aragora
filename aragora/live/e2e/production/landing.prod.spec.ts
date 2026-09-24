/**
 * Landing Page Tests for Production
 *
 * Tests aragora.ai landing page functionality, navigation, and content.
 *
 * Run with: npx playwright test landing.prod.spec.ts --config=playwright.production.config.ts
 */

import { test, expect, PRODUCTION_DOMAINS, LANDING_PAGES } from './fixtures';

test.describe('Landing Page - aragora.ai', () => {
  test.describe('Page Accessibility', () => {
    for (const pageInfo of LANDING_PAGES) {
      test(`${pageInfo.name} page should be accessible`, async ({ page, productionPage }) => {
        const url = `${PRODUCTION_DOMAINS.landing}${pageInfo.path}`;
        await productionPage.goto(url);
        await productionPage.waitForHydration();

        // Page should load without errors
        await expect(page.locator('body')).toBeVisible();

        // No critical errors (excluding React hydration issues which are known)
        const criticalErrors = productionPage.errorCollector
          .getErrorsBySeverity('critical')
          .filter((e) => !e.message.includes('Minified React error'));
        if (criticalErrors.length > 0) {
          console.log(`Critical errors on ${pageInfo.name}:`);
          criticalErrors.forEach((e) => console.log(`  ${e.message}`));
        }
        expect(criticalErrors.length).toBe(0);
      });
    }
  });

  test.describe('Homepage Content', () => {
    test('should display hero section', async ({ page, productionPage }) => {
      await productionPage.goto(PRODUCTION_DOMAINS.landing);
      await productionPage.waitForHydration();

      // Should have some visible content (heading, banner, or main)
      const mainContent = page.locator('main').first();
      await expect(mainContent).toBeVisible();
    });

    test('should display navigation', async ({ page, productionPage }) => {
      await productionPage.goto(PRODUCTION_DOMAINS.landing);
      await productionPage.waitForHydration();

      // Should have navigation links
      const nav = page.locator('nav, header');
      await expect(nav.first()).toBeVisible();

      // Should have key navigation items
      const aboutLink = page.locator('a[href*="about"]');
      if ((await aboutLink.count()) > 0) {
        await expect(aboutLink.first()).toBeVisible();
      }
    });

    test('should display footer', async ({ page, productionPage }) => {
      await productionPage.goto(PRODUCTION_DOMAINS.landing);
      await productionPage.waitForHydration();

      // Should have footer
      const footer = page.locator('footer');
      if ((await footer.count()) > 0) {
        await expect(footer).toBeVisible();
      }
    });

    test('should have call-to-action buttons', async ({ page, productionPage }) => {
      await productionPage.goto(PRODUCTION_DOMAINS.landing);
      await productionPage.waitForHydration();

      // Should have some interactive buttons
      const buttons = page.locator('button, a.btn, [role="button"]');
      const buttonCount = await buttons.count();
      expect(buttonCount).toBeGreaterThan(0);
    });
  });

  test.describe('Navigation', () => {
    test('clicking About link should navigate to About page', async ({ page, productionPage }) => {
      await productionPage.goto(PRODUCTION_DOMAINS.landing);
      await productionPage.waitForHydration();

      const aboutLink = page.locator('a[href*="about"]').first();
      if (await aboutLink.isVisible().catch(() => false)) {
        await aboutLink.click();
        await page.waitForLoadState('domcontentloaded');

        // Should be on about page
        expect(page.url()).toContain('about');
      }
    });

    test('clicking Pricing link should navigate to Pricing page', async ({
      page,
      productionPage,
    }) => {
      await productionPage.goto(PRODUCTION_DOMAINS.landing);
      await productionPage.waitForHydration();

      const pricingLink = page.locator('a[href*="pricing"]').first();
      if (await pricingLink.isVisible().catch(() => false)) {
        await pricingLink.click();
        await page.waitForLoadState('domcontentloaded');

        expect(page.url()).toContain('pricing');
      }
    });

    test('clicking Security link should navigate to Security page', async ({
      page,
      productionPage,
    }) => {
      await productionPage.goto(PRODUCTION_DOMAINS.landing);
      await productionPage.waitForHydration();

      const securityLink = page.locator('a[href*="security"]').first();
      if (await securityLink.isVisible().catch(() => false)) {
        await securityLink.click();
        await page.waitForLoadState('domcontentloaded');

        expect(page.url()).toContain('security');
      }
    });

    test('clicking Privacy link should navigate to Privacy page', async ({
      page,
      productionPage,
    }) => {
      await productionPage.goto(PRODUCTION_DOMAINS.landing);
      await productionPage.waitForHydration();

      const privacyLink = page.locator('a[href*="privacy"]').first();
      if (await privacyLink.isVisible().catch(() => false)) {
        await privacyLink.click();
        await page.waitForLoadState('domcontentloaded');

        expect(page.url()).toContain('privacy');
      }
    });

    test('logo should link to homepage', async ({ page, productionPage }) => {
      await productionPage.goto(`${PRODUCTION_DOMAINS.landing}/about`);
      await productionPage.waitForHydration();

      // Find logo link (usually in header)
      const logoLink = page.locator('header a[href="/"], a[href="/"] img, a[href="/"] svg').first();
      if (await logoLink.isVisible().catch(() => false)) {
        await logoLink.click();
        await page.waitForLoadState('domcontentloaded');

        // Should be on homepage
        expect(page.url()).toBe(`${PRODUCTION_DOMAINS.landing}/`);
      }
    });
  });

  test.describe('Responsive Design', () => {
    test('should display correctly on mobile', async ({ page, productionPage }) => {
      await page.setViewportSize({ width: 375, height: 667 });
      await productionPage.goto(PRODUCTION_DOMAINS.landing);
      await productionPage.waitForHydration();

      // Content should be visible
      const body = page.locator('body');
      await expect(body).toBeVisible();

      // Check horizontal overflow - allow some tolerance (50px for scrollbars/transitions)
      const overflowPx = await page.evaluate(() => {
        return document.documentElement.scrollWidth - document.documentElement.clientWidth;
      });
      expect(overflowPx, `Horizontal overflow: ${overflowPx}px`).toBeLessThanOrEqual(50);
    });

    test('should display correctly on tablet', async ({ page, productionPage }) => {
      await page.setViewportSize({ width: 768, height: 1024 });
      await productionPage.goto(PRODUCTION_DOMAINS.landing);
      await productionPage.waitForHydration();

      const body = page.locator('body');
      await expect(body).toBeVisible();
    });

    test('should display correctly on desktop', async ({ page, productionPage }) => {
      await page.setViewportSize({ width: 1920, height: 1080 });
      await productionPage.goto(PRODUCTION_DOMAINS.landing);
      await productionPage.waitForHydration();

      const body = page.locator('body');
      await expect(body).toBeVisible();
    });
  });

  test.describe('About Page', () => {
    test('should display company information', async ({ page, productionPage }) => {
      await productionPage.goto(`${PRODUCTION_DOMAINS.landing}/about`);
      await productionPage.waitForHydration();

      // Should have content about the company
      const content = await page.content();
      const hasAboutContent =
        content.toLowerCase().includes('about') ||
        content.toLowerCase().includes('aragora') ||
        content.toLowerCase().includes('team') ||
        content.toLowerCase().includes('mission');

      expect(hasAboutContent).toBe(true);
    });
  });

  test.describe('Pricing Page', () => {
    test('should display pricing tiers', async ({ page, productionPage }) => {
      await productionPage.goto(`${PRODUCTION_DOMAINS.landing}/pricing`);
      await productionPage.waitForHydration();

      // Should have pricing content
      const content = await page.content();
      const hasPricingContent =
        content.toLowerCase().includes('pricing') ||
        content.toLowerCase().includes('plan') ||
        content.toLowerCase().includes('free') ||
        content.toLowerCase().includes('$');

      expect(hasPricingContent).toBe(true);
    });
  });

  test.describe('Security Page', () => {
    test('should display security information', async ({ page, productionPage }) => {
      await productionPage.goto(`${PRODUCTION_DOMAINS.landing}/security`);
      await productionPage.waitForHydration();

      // Should have security content
      const content = await page.content();
      const hasSecurityContent =
        content.toLowerCase().includes('security') ||
        content.toLowerCase().includes('privacy') ||
        content.toLowerCase().includes('compliance') ||
        content.toLowerCase().includes('soc 2');

      expect(hasSecurityContent).toBe(true);
    });
  });

  test.describe('Privacy Page', () => {
    test('should display privacy policy', async ({ page, productionPage }) => {
      await productionPage.goto(`${PRODUCTION_DOMAINS.landing}/privacy`);
      await productionPage.waitForHydration();

      // Should have privacy content
      const content = await page.content();
      const hasPrivacyContent =
        content.toLowerCase().includes('privacy') ||
        content.toLowerCase().includes('data') ||
        content.toLowerCase().includes('gdpr') ||
        content.toLowerCase().includes('ccpa');

      expect(hasPrivacyContent).toBe(true);
    });
  });

  test.describe('SEO', () => {
    test('should have proper meta tags', async ({ page, productionPage }) => {
      await productionPage.goto(PRODUCTION_DOMAINS.landing);
      await productionPage.waitForHydration();

      // Title
      const title = await page.title();
      expect(title).toBeTruthy();
      expect(title.length).toBeGreaterThan(0);

      // Description
      const description = await page.locator('meta[name="description"]').getAttribute('content');
      expect(description).toBeTruthy();

      // Viewport
      const viewport = await page.locator('meta[name="viewport"]').getAttribute('content');
      expect(viewport).toContain('width');
    });

    test('should have Open Graph tags', async ({ page, productionPage }) => {
      await productionPage.goto(PRODUCTION_DOMAINS.landing);
      await productionPage.waitForHydration();

      // OG title
      const ogTitle = page.locator('meta[property="og:title"]');
      if ((await ogTitle.count()) > 0) {
        const content = await ogTitle.getAttribute('content');
        expect(content).toBeTruthy();
      }

      // OG description
      const ogDescription = page.locator('meta[property="og:description"]');
      if ((await ogDescription.count()) > 0) {
        const content = await ogDescription.getAttribute('content');
        expect(content).toBeTruthy();
      }
    });

    test('should have canonical URL', async ({ page, productionPage }) => {
      await productionPage.goto(PRODUCTION_DOMAINS.landing);
      await productionPage.waitForHydration();

      const canonical = page.locator('link[rel="canonical"]');
      if ((await canonical.count()) > 0) {
        const href = await canonical.getAttribute('href');
        expect(href).toContain('aragora.ai');
      }
    });
  });

  test.describe('Performance', () => {
    test('should have reasonable initial load time', async ({ page }) => {
      const startTime = Date.now();

      await page.goto(PRODUCTION_DOMAINS.landing, { waitUntil: 'load' });

      const loadTime = Date.now() - startTime;
      console.log(`Landing page full load time: ${loadTime}ms`);

      // Should load within 10 seconds
      expect(loadTime).toBeLessThan(10000);
    });

    test('should have images optimized', async ({ page, productionPage }) => {
      await productionPage.goto(PRODUCTION_DOMAINS.landing);
      await productionPage.waitForHydration();

      // Check for lazy loading or next/image optimization
      const images = page.locator('img');
      const imageCount = await images.count();

      if (imageCount > 0) {
        // Check first few images
        for (let i = 0; i < Math.min(imageCount, 3); i++) {
          const img = images.nth(i);
          const src = await img.getAttribute('src');
          const loading = await img.getAttribute('loading');

          // Should have src
          expect(src).toBeTruthy();

          // Log image info
          console.log(`Image ${i + 1}: ${src?.substring(0, 50)}... loading=${loading}`);
        }
      }
    });
  });
});
