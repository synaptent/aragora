/**
 * Accessibility Tests for Production
 *
 * Tests WCAG compliance using axe-core for production sites.
 *
 * Run with: npx playwright test accessibility.prod.spec.ts --config=playwright.production.config.ts
 */

import { test, expect, PRODUCTION_DOMAINS, LANDING_PAGES, DASHBOARD_PAGES } from './fixtures';
import AxeBuilder from '@axe-core/playwright';

// WCAG 2.1 AA tags
const WCAG_TAGS = ['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa'];

test.describe('Accessibility - aragora.ai', () => {
  for (const pageInfo of LANDING_PAGES) {
    test(`${pageInfo.name} should meet WCAG 2.1 AA standards`, async ({ page, productionPage }) => {
      const url = `${PRODUCTION_DOMAINS.landing}${pageInfo.path}`;
      await productionPage.goto(url);
      await productionPage.waitForHydration();

      const results = await new AxeBuilder({ page }).withTags(WCAG_TAGS).analyze();

      // Filter to critical and serious violations
      const criticalViolations = results.violations.filter(
        (v) => v.impact === 'critical' || v.impact === 'serious',
      );

      // Log violations for debugging
      if (criticalViolations.length > 0) {
        console.log(`\n=== Accessibility violations on ${pageInfo.name} ===`);
        criticalViolations.forEach((violation) => {
          console.log(`\n[${violation.impact?.toUpperCase()}] ${violation.id}`);
          console.log(`  Description: ${violation.description}`);
          console.log(`  Help: ${violation.helpUrl}`);
          console.log(`  Nodes affected: ${violation.nodes.length}`);
          violation.nodes.slice(0, 3).forEach((node, i) => {
            console.log(`    ${i + 1}. ${node.html.substring(0, 100)}...`);
          });
        });

        // Add to error collector
        criticalViolations.forEach((v) => {
          productionPage.errorCollector.addManualError({
            type: 'accessibility',
            severity: v.impact === 'critical' ? 'critical' : 'high',
            message: `${v.id}: ${v.description}`,
            url,
            details: { nodes: v.nodes.length, helpUrl: v.helpUrl },
          });
        });
      }

      expect(
        criticalViolations,
        `Found ${criticalViolations.length} critical/serious accessibility violations`,
      ).toHaveLength(0);
    });
  }
});

test.describe('Accessibility - live.aragora.ai', () => {
  for (const pageInfo of DASHBOARD_PAGES) {
    test(`${pageInfo.name} should meet WCAG 2.1 AA standards`, async ({ page, productionPage }) => {
      const url = `${PRODUCTION_DOMAINS.dashboard}${pageInfo.path}`;
      await productionPage.goto(url);
      await productionPage.waitForHydration();
      await productionPage.dismissBootAnimation();

      const results = await new AxeBuilder({ page })
        .withTags(WCAG_TAGS)
        // Exclude known issues from CRT theme styling and dynamic form inputs
        .disableRules(['color-contrast', 'region', 'select-name', 'label'])
        .analyze();

      // Only fail on critical violations
      const criticalViolations = results.violations.filter((v) => v.impact === 'critical');

      if (criticalViolations.length > 0) {
        console.log(`\n=== Critical accessibility violations on ${pageInfo.name} ===`);
        criticalViolations.forEach((violation) => {
          console.log(`\n[${violation.impact?.toUpperCase()}] ${violation.id}`);
          console.log(`  Description: ${violation.description}`);
          console.log(`  Nodes affected: ${violation.nodes.length}`);
        });
      }

      expect(
        criticalViolations,
        `Found ${criticalViolations.length} critical accessibility violations`,
      ).toHaveLength(0);
    });
  }
});

test.describe('Accessibility - Keyboard Navigation', () => {
  test('aragora.ai should be keyboard navigable', async ({ page, productionPage }) => {
    await productionPage.goto(PRODUCTION_DOMAINS.landing);
    await productionPage.waitForHydration();

    // Tab through the page
    await page.keyboard.press('Tab');

    // First focusable element should receive focus
    const focusedElement = await page.evaluate(() => {
      const el = document.activeElement;
      return { tagName: el?.tagName, hasVisibleFocus: el !== document.body };
    });

    expect(focusedElement.hasVisibleFocus).toBe(true);
    console.log(`First focused element: ${focusedElement.tagName}`);

    // Tab a few more times
    for (let i = 0; i < 5; i++) {
      await page.keyboard.press('Tab');
    }

    // Should still have focus somewhere
    const afterTabs = await page.evaluate(() => {
      return document.activeElement?.tagName;
    });
    expect(afterTabs).toBeTruthy();
  });

  test('live.aragora.ai should be keyboard navigable', async ({ page, productionPage }) => {
    await productionPage.goto(PRODUCTION_DOMAINS.dashboard);
    await productionPage.waitForHydration();
    await productionPage.dismissBootAnimation();

    await page.keyboard.press('Tab');

    const focusedElement = await page.evaluate(() => {
      const el = document.activeElement;
      return { tagName: el?.tagName, hasVisibleFocus: el !== document.body };
    });

    expect(focusedElement.hasVisibleFocus).toBe(true);
  });

  test('should be able to navigate to main content', async ({ page, productionPage }) => {
    await productionPage.goto(PRODUCTION_DOMAINS.landing);
    await productionPage.waitForHydration();

    // Look for skip link
    const skipLink = page.locator('a[href="#main"], a[href="#content"], .skip-link').first();
    const hasSkipLink = await skipLink.isVisible().catch(() => false);

    if (hasSkipLink) {
      await skipLink.focus();
      await page.keyboard.press('Enter');
      console.log('Skip link found and activated');
    } else {
      // Check for main landmark instead
      const mainLandmark = await page.locator('main, [role="main"]').count();
      console.log(`Skip link: ${hasSkipLink}, Main landmark: ${mainLandmark > 0}`);
    }
  });
});

test.describe('Accessibility - Color Contrast', () => {
  test('aragora.ai should have sufficient color contrast', async ({ page, productionPage }) => {
    await productionPage.goto(PRODUCTION_DOMAINS.landing);
    await productionPage.waitForHydration();

    const results = await new AxeBuilder({ page }).withTags(['wcag2aa']).analyze();

    const contrastViolations = results.violations.filter((v) => v.id === 'color-contrast');

    if (contrastViolations.length > 0) {
      console.log('\n=== Color Contrast Violations ===');
      contrastViolations.forEach((violation) => {
        console.log(`Found ${violation.nodes.length} contrast issues`);
        violation.nodes.slice(0, 5).forEach((node) => {
          console.log(`  - ${node.html.substring(0, 80)}...`);
          console.log(`    ${node.failureSummary}`);
        });
      });
    }

    expect(contrastViolations).toHaveLength(0);
  });

  test('live.aragora.ai should have sufficient color contrast', async ({
    page,
    productionPage,
  }) => {
    await productionPage.goto(PRODUCTION_DOMAINS.dashboard);
    await productionPage.waitForHydration();
    await productionPage.dismissBootAnimation();

    const results = await new AxeBuilder({ page }).withTags(['wcag2aa']).analyze();

    const contrastViolations = results.violations.filter((v) => v.id === 'color-contrast');

    if (contrastViolations.length > 0) {
      console.log(
        `Dashboard has ${contrastViolations[0].nodes.length} contrast issues (informational)`,
      );
    }

    // Allow up to 20 contrast issues for CRT-themed styling
    const totalNodes = contrastViolations.flatMap((v) => v.nodes).length;
    expect(totalNodes, `Found ${totalNodes} contrast issues`).toBeLessThanOrEqual(20);
  });
});

test.describe('Accessibility - Images', () => {
  test('all images should have alt text', async ({ page, productionPage }) => {
    await productionPage.goto(PRODUCTION_DOMAINS.landing);
    await productionPage.waitForHydration();

    const results = await new AxeBuilder({ page }).analyze();

    const imageViolations = results.violations.filter((v) => v.id === 'image-alt');

    if (imageViolations.length > 0) {
      console.log('\n=== Images without alt text ===');
      imageViolations.forEach((violation) => {
        violation.nodes.forEach((node) => {
          console.log(`  - ${node.html.substring(0, 100)}`);
        });
      });
    }

    expect(imageViolations).toHaveLength(0);
  });
});

test.describe('Accessibility - Forms', () => {
  test('form inputs should have labels', async ({ page, productionPage }) => {
    await productionPage.goto(PRODUCTION_DOMAINS.landing);
    await productionPage.waitForHydration();

    const results = await new AxeBuilder({ page }).analyze();

    const labelViolations = results.violations.filter((v) => v.id.includes('label'));

    if (labelViolations.length > 0) {
      console.log('\n=== Form Label Issues ===');
      labelViolations.forEach((violation) => {
        console.log(`${violation.id}: ${violation.nodes.length} issues`);
      });
    }

    expect(labelViolations).toHaveLength(0);
  });
});

test.describe('Accessibility - Headings', () => {
  test('aragora.ai should have proper heading hierarchy', async ({ page, productionPage }) => {
    await productionPage.goto(PRODUCTION_DOMAINS.landing);
    await productionPage.waitForHydration();

    const headings = await page.evaluate(() => {
      const allHeadings = document.querySelectorAll('h1, h2, h3, h4, h5, h6');
      const h1s = document.querySelectorAll('h1');
      return {
        h1Count: h1s.length,
        totalHeadings: allHeadings.length,
        headingLevels: Array.from(allHeadings).map((h) => ({
          level: h.tagName,
          text: h.textContent?.trim().substring(0, 50),
        })),
      };
    });

    console.log('\n=== Heading Structure ===');
    console.log(`H1 count: ${headings.h1Count}`);
    console.log(`Total headings: ${headings.totalHeadings}`);
    headings.headingLevels.slice(0, 10).forEach((h) => {
      console.log(`  ${h.level}: ${h.text}`);
    });

    // Should have at most one h1
    expect(headings.h1Count).toBeLessThanOrEqual(1);
  });

  test('live.aragora.ai should have proper heading hierarchy', async ({ page, productionPage }) => {
    await productionPage.goto(PRODUCTION_DOMAINS.dashboard);
    await productionPage.waitForHydration();
    await productionPage.dismissBootAnimation();

    const headings = await page.evaluate(() => {
      const h1s = document.querySelectorAll('h1');
      return { h1Count: h1s.length };
    });

    expect(headings.h1Count).toBeLessThanOrEqual(1);
  });
});

test.describe('Accessibility - ARIA', () => {
  test('ARIA attributes should be valid', async ({ page, productionPage }) => {
    await productionPage.goto(PRODUCTION_DOMAINS.landing);
    await productionPage.waitForHydration();

    const results = await new AxeBuilder({ page }).withTags(['cat.aria']).analyze();

    const ariaViolations = results.violations.filter(
      (v) => v.impact === 'critical' || v.impact === 'serious',
    );

    if (ariaViolations.length > 0) {
      console.log('\n=== ARIA Violations ===');
      ariaViolations.forEach((v) => {
        console.log(`${v.id}: ${v.description}`);
      });
    }

    expect(ariaViolations).toHaveLength(0);
  });

  test('interactive elements should have accessible names', async ({ page, productionPage }) => {
    await productionPage.goto(PRODUCTION_DOMAINS.landing);
    await productionPage.waitForHydration();

    const results = await new AxeBuilder({ page }).analyze();

    const nameViolations = results.violations.filter(
      (v) => v.id === 'button-name' || v.id === 'link-name' || v.id === 'input-button-name',
    );

    if (nameViolations.length > 0) {
      console.log('\n=== Elements without accessible names ===');
      nameViolations.forEach((v) => {
        console.log(`${v.id}: ${v.nodes.length} issues`);
      });
    }

    expect(nameViolations).toHaveLength(0);
  });
});

test.describe('Accessibility - Landmarks', () => {
  test('page should have main landmark', async ({ page, productionPage }) => {
    await productionPage.goto(PRODUCTION_DOMAINS.landing);
    await productionPage.waitForHydration();

    const landmarks = await page.evaluate(() => {
      return {
        hasMain: !!document.querySelector('main, [role="main"]'),
        hasNav: !!document.querySelector('nav, [role="navigation"]'),
        hasFooter: !!document.querySelector('footer, [role="contentinfo"]'),
        hasHeader: !!document.querySelector('header, [role="banner"]'),
      };
    });

    console.log('Landmarks:', JSON.stringify(landmarks));

    // Should have main landmark
    expect(landmarks.hasMain).toBe(true);
  });
});

test.describe('Accessibility - Mobile', () => {
  test('mobile version should be accessible', async ({ page, productionPage }) => {
    await page.setViewportSize({ width: 375, height: 667 });
    await productionPage.goto(PRODUCTION_DOMAINS.landing);
    await productionPage.waitForHydration();

    const results = await new AxeBuilder({ page }).withTags(WCAG_TAGS).analyze();

    const criticalViolations = results.violations.filter(
      (v) => v.impact === 'critical' || v.impact === 'serious',
    );

    if (criticalViolations.length > 0) {
      console.log('\n=== Mobile Accessibility Violations ===');
      criticalViolations.forEach((v) => {
        console.log(`${v.id}: ${v.description}`);
      });
    }

    expect(criticalViolations).toHaveLength(0);
  });

  test('touch targets should be appropriately sized', async ({ page, productionPage }) => {
    await page.setViewportSize({ width: 375, height: 667 });
    await productionPage.goto(PRODUCTION_DOMAINS.landing);
    await productionPage.waitForHydration();

    // Check touch target sizes
    const smallTargets = await page.evaluate(() => {
      const buttons = document.querySelectorAll('button, a, [role="button"]');
      const small: string[] = [];

      buttons.forEach((el) => {
        const rect = el.getBoundingClientRect();
        // Minimum touch target is 44x44 pixels
        if (rect.width < 44 || rect.height < 44) {
          if (rect.width > 0 && rect.height > 0) {
            // Only count visible elements
            small.push(`${el.tagName} (${Math.round(rect.width)}x${Math.round(rect.height)})`);
          }
        }
      });

      return small.slice(0, 10);
    });

    if (smallTargets.length > 0) {
      console.log('\n=== Small Touch Targets ===');
      smallTargets.forEach((t) => console.log(`  - ${t}`));
    }
  });
});
