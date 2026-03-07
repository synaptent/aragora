/**
 * Mobile Experience Audit - Playwright E2E Test
 *
 * Audits key Aragora public pages for mobile usability across two viewports:
 *   - iPhone 14 (390x844)
 *   - Galaxy S21 (360x800)
 *
 * Checks per page:
 *   1. No horizontal scroll overflow
 *   2. Body text font-size >= 12px
 *   3. Touch targets (buttons, links) >= 44x44px
 *   4. Key elements visible and not clipped
 *   5. Navigation accessible
 *
 * Run against production:
 *   PLAYWRIGHT_BASE_URL=https://aragora.ai npx playwright test e2e/mobile/mobile-audit.spec.ts
 *
 * Or against local dev server:
 *   npx playwright test e2e/mobile/mobile-audit.spec.ts
 */

import { test, expect, Page } from '@playwright/test';

// ---------------------------------------------------------------------------
// Viewport definitions
// ---------------------------------------------------------------------------

interface MobileViewport {
  name: string;
  width: number;
  height: number;
}

const VIEWPORTS: MobileViewport[] = [
  { name: 'iPhone 14', width: 390, height: 844 },
  { name: 'Galaxy S21', width: 360, height: 800 },
];

// ---------------------------------------------------------------------------
// Pages to audit
// ---------------------------------------------------------------------------

interface AuditPage {
  /** URL path (relative to baseURL) */
  path: string;
  /** Human-readable label */
  label: string;
  /** Locators for elements that MUST be visible */
  requiredSelectors: string[];
}

const PAGES: AuditPage[] = [
  {
    path: '/landing/',
    label: 'Landing',
    requiredSelectors: [
      'h1, h2, [role="heading"]',          // hero heading
      'a, button',                          // CTA / nav
      'footer, [role="contentinfo"]',       // footer
    ],
  },
  {
    path: '/playground/',
    label: 'Playground',
    requiredSelectors: [
      'textarea, input[type="text"], [contenteditable="true"]', // input form
      'button, [role="button"]',                                // submit / action
    ],
  },
  {
    path: '/try/',
    label: 'Try (Debate)',
    requiredSelectors: [
      'main, [role="main"], #__next',        // content area
      'button, a, [role="button"]',          // interactive element
    ],
  },
  {
    path: '/about/',
    label: 'About',
    requiredSelectors: [
      'h1, h2, [role="heading"]',            // heading
      'p, [class*="text"], [class*="prose"]', // body content
    ],
  },
  {
    path: '/pricing/',
    label: 'Pricing',
    requiredSelectors: [
      'h1, h2, [role="heading"]',            // heading
      'button, a',                           // CTA buttons
    ],
  },
  {
    path: '/signup/',
    label: 'Sign Up',
    requiredSelectors: [
      'input, textarea, [role="textbox"]',   // form field
      'button, [role="button"]',             // submit
    ],
  },
];

// ---------------------------------------------------------------------------
// Minimum thresholds
// ---------------------------------------------------------------------------

/** Minimum readable font size in px (WCAG / Apple HIG recommendation) */
const MIN_FONT_SIZE_PX = 12;

/** Minimum touch target size in px (WCAG 2.5.8 / Apple 44pt guideline) */
const MIN_TOUCH_TARGET_PX = 44;

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

/**
 * Dismiss boot animation & onboarding overlays that may block the page.
 */
async function dismissOverlays(page: Page): Promise<void> {
  // Boot sequence overlay
  const bootOverlay = page.locator('[aria-label*="Boot sequence"]');
  if (await bootOverlay.isVisible({ timeout: 2000 }).catch(() => false)) {
    await bootOverlay.click();
    await bootOverlay
      .waitFor({ state: 'hidden', timeout: 5000 })
      .catch(() => {});
  }

  // Onboarding wizard skip button
  const skipBtn = page.locator('button:has-text("[SKIP]")');
  if (await skipBtn.isVisible({ timeout: 1000 }).catch(() => false)) {
    await skipBtn.click();
    await page
      .locator('.fixed.z-\\[100\\]')
      .waitFor({ state: 'hidden', timeout: 3000 })
      .catch(() => {});
  }
}

/**
 * Check that document does not overflow horizontally.
 * Returns { pass, scrollWidth, viewportWidth }.
 */
async function checkNoHorizontalOverflow(
  page: Page,
  viewportWidth: number,
): Promise<{ pass: boolean; scrollWidth: number }> {
  const scrollWidth = await page.evaluate(() => document.documentElement.scrollWidth);
  return { pass: scrollWidth <= viewportWidth, scrollWidth };
}

/**
 * Gather computed font sizes of body-text elements and return the smallest.
 * We sample <p>, <span>, <li>, <td>, <label>, and <a> elements.
 */
async function getSmallestBodyFontSize(page: Page): Promise<number> {
  const minSize: number = await page.evaluate(() => {
    const selectors = 'p, span, li, td, label, a';
    const els = document.querySelectorAll(selectors);
    let smallest = Infinity;
    for (const el of els) {
      // Skip hidden or empty elements
      if (!(el as HTMLElement).offsetParent && (el as HTMLElement).style.display !== 'fixed') continue;
      if (!el.textContent?.trim()) continue;
      const size = parseFloat(getComputedStyle(el).fontSize);
      if (size > 0 && size < smallest) smallest = size;
    }
    return smallest === Infinity ? 16 : smallest;
  });
  return minSize;
}

/**
 * Find interactive elements (buttons and links) that are smaller than the
 * minimum touch target size. Returns a list of offending elements.
 */
async function findSmallTouchTargets(
  page: Page,
  minSize: number,
): Promise<{ tag: string; text: string; width: number; height: number }[]> {
  return page.evaluate((min) => {
    const selectors = 'a, button, [role="button"], [role="link"], input[type="submit"], input[type="button"]';
    const els = document.querySelectorAll(selectors);
    const violations: { tag: string; text: string; width: number; height: number }[] = [];
    for (const el of els) {
      const rect = el.getBoundingClientRect();
      // Skip invisible / zero-size elements
      if (rect.width === 0 || rect.height === 0) continue;
      // Skip offscreen elements
      if (rect.bottom < 0 || rect.top > window.innerHeight * 3) continue;
      if (rect.width < min || rect.height < min) {
        violations.push({
          tag: el.tagName.toLowerCase(),
          text: (el.textContent || '').trim().slice(0, 60),
          width: Math.round(rect.width),
          height: Math.round(rect.height),
        });
      }
    }
    return violations;
  }, minSize);
}

/**
 * Check whether navigation is accessible on the page: either a visible
 * <nav> / hamburger menu button or at least one visible internal link.
 */
async function checkNavigationAccessible(page: Page): Promise<boolean> {
  return page.evaluate(() => {
    // Visible <nav>
    const nav = document.querySelector('nav');
    if (nav && nav.offsetParent !== null) return true;

    // Hamburger / menu toggle button
    const menuBtn = document.querySelector(
      'button[aria-label*="menu" i], button[aria-label*="Menu" i], ' +
      'button[aria-label*="navigation" i], button[aria-expanded], ' +
      '[data-testid*="menu"], [data-testid*="hamburger"]',
    );
    if (menuBtn && (menuBtn as HTMLElement).offsetParent !== null) return true;

    // Fallback: at least one visible internal link
    const links = document.querySelectorAll('a[href^="/"]');
    for (const link of links) {
      if ((link as HTMLElement).offsetParent !== null) return true;
    }

    return false;
  });
}

/**
 * Check that required selectors have at least one visible element (considering
 * vertical scroll — we scroll to each and check visibility).
 */
async function checkRequiredVisible(
  page: Page,
  selectors: string[],
): Promise<{ selector: string; visible: boolean }[]> {
  const results: { selector: string; visible: boolean }[] = [];
  for (const sel of selectors) {
    const locator = page.locator(sel).first();
    let visible = false;
    try {
      // Scroll into view if needed then check
      await locator.scrollIntoViewIfNeeded({ timeout: 3000 });
      visible = await locator.isVisible({ timeout: 2000 });
    } catch {
      visible = false;
    }
    results.push({ selector: sel, visible });
  }
  // Scroll back to top for consistent state
  await page.evaluate(() => window.scrollTo(0, 0));
  return results;
}

// ---------------------------------------------------------------------------
// Audit result collector (for summary report)
// ---------------------------------------------------------------------------

interface PageAuditResult {
  page: string;
  viewport: string;
  horizontalOverflow: { pass: boolean; scrollWidth: number; viewportWidth: number };
  fontSizeCheck: { pass: boolean; smallestPx: number };
  touchTargetCheck: { pass: boolean; violationCount: number; violations: { tag: string; text: string; width: number; height: number }[] };
  requiredElements: { pass: boolean; results: { selector: string; visible: boolean }[] };
  navigationAccessible: boolean;
  overallPass: boolean;
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

for (const viewport of VIEWPORTS) {
  test.describe(`Mobile Audit - ${viewport.name} (${viewport.width}x${viewport.height})`, () => {
    test.use({
      viewport: { width: viewport.width, height: viewport.height },
      // Emulate mobile user agent for more realistic rendering
      userAgent:
        viewport.name === 'iPhone 14'
          ? 'Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.0 Mobile/15E148 Safari/604.1'
          : 'Mozilla/5.0 (Linux; Android 12; SM-G991B) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/101.0.4951.41 Mobile Safari/537.36',
      isMobile: true,
      hasTouch: true,
    });

    for (const auditPage of PAGES) {
      test.describe(`${auditPage.label} (${auditPage.path})`, () => {
        let page: Page;

        test.beforeEach(async ({ page: p }) => {
          page = p;
          await page.goto(auditPage.path, {
            waitUntil: 'domcontentloaded',
            timeout: 30000,
          });
          await dismissOverlays(page);
          // Give dynamic content time to render
          await page.waitForTimeout(1000);
        });

        test('no horizontal scroll overflow', async () => {
          const result = await checkNoHorizontalOverflow(page, viewport.width);
          if (!result.pass) {
            console.log(
              `[FAIL] ${auditPage.label} on ${viewport.name}: ` +
              `scrollWidth=${result.scrollWidth} > viewportWidth=${viewport.width}`,
            );
          }
          // Record for summary
          recordPartial(auditPage.label, viewport.name, 'horizontalOverflow', {
            pass: result.pass,
            scrollWidth: result.scrollWidth,
            viewportWidth: viewport.width,
          });
          expect(
            result.pass,
            `Horizontal overflow detected: scrollWidth ${result.scrollWidth}px > viewport ${viewport.width}px`,
          ).toBe(true);
        });

        test('body text font-size >= 12px', async () => {
          const smallest = await getSmallestBodyFontSize(page);
          const pass = smallest >= MIN_FONT_SIZE_PX;
          if (!pass) {
            console.log(
              `[FAIL] ${auditPage.label} on ${viewport.name}: ` +
              `smallest font-size=${smallest}px < ${MIN_FONT_SIZE_PX}px`,
            );
          }
          recordPartial(auditPage.label, viewport.name, 'fontSizeCheck', {
            pass,
            smallestPx: smallest,
          });
          expect(
            pass,
            `Smallest body text font-size is ${smallest}px, below minimum ${MIN_FONT_SIZE_PX}px`,
          ).toBe(true);
        });

        test('touch targets >= 44x44px', async () => {
          const violations = await findSmallTouchTargets(page, MIN_TOUCH_TARGET_PX);
          const pass = violations.length === 0;
          if (!pass) {
            console.log(
              `[WARN] ${auditPage.label} on ${viewport.name}: ` +
              `${violations.length} touch target(s) below ${MIN_TOUCH_TARGET_PX}px`,
            );
            for (const v of violations.slice(0, 5)) {
              console.log(`  <${v.tag}> "${v.text}" ${v.width}x${v.height}`);
            }
          }
          recordPartial(auditPage.label, viewport.name, 'touchTargetCheck', {
            pass,
            violationCount: violations.length,
            violations: violations.slice(0, 10),
          });
          // Use soft assertion — small targets are a warning, not always blocking
          expect.soft(
            pass,
            `${violations.length} touch target(s) smaller than ${MIN_TOUCH_TARGET_PX}px minimum`,
          ).toBe(true);
        });

        test('key elements visible and not clipped', async () => {
          const results = await checkRequiredVisible(page, auditPage.requiredSelectors);
          const allVisible = results.every((r) => r.visible);
          if (!allVisible) {
            const missing = results.filter((r) => !r.visible);
            console.log(
              `[FAIL] ${auditPage.label} on ${viewport.name}: ` +
              `${missing.length} required element(s) not visible`,
            );
            for (const m of missing) {
              console.log(`  Missing: ${m.selector}`);
            }
          }
          recordPartial(auditPage.label, viewport.name, 'requiredElements', {
            pass: allVisible,
            results,
          });
          expect(
            allVisible,
            `Required elements not visible: ${results
              .filter((r) => !r.visible)
              .map((r) => r.selector)
              .join(', ')}`,
          ).toBe(true);
        });

        test('navigation is accessible', async () => {
          const accessible = await checkNavigationAccessible(page);
          if (!accessible) {
            console.log(
              `[FAIL] ${auditPage.label} on ${viewport.name}: ` +
              `no accessible navigation found (nav, hamburger, or internal links)`,
            );
          }
          recordPartial(auditPage.label, viewport.name, 'navigationAccessible', accessible);
          expect(
            accessible,
            'No accessible navigation found: expected <nav>, hamburger menu, or visible internal links',
          ).toBe(true);
        });
      });
    }
  });
}

// ---------------------------------------------------------------------------
// Summary report (printed after all tests)
// ---------------------------------------------------------------------------

// We collect partial results and merge them for the final summary.
// This uses a simple map keyed by "page|viewport".

const partialResults = new Map<string, Partial<PageAuditResult>>();

function recordPartial(
  pageName: string,
  viewportName: string,
  field: keyof PageAuditResult,
  value: unknown,
): void {
  const key = `${pageName}|${viewportName}`;
  if (!partialResults.has(key)) {
    partialResults.set(key, { page: pageName, viewport: viewportName });
  }
  const entry = partialResults.get(key)!;
  (entry as Record<string, unknown>)[field] = value;
}

test.afterAll(async () => {
  console.log('\n========================================');
  console.log('   MOBILE EXPERIENCE AUDIT SUMMARY');
  console.log('========================================\n');

  for (const [, partial] of partialResults) {
    const p = partial as PageAuditResult;
    const checks = [
      p.horizontalOverflow?.pass,
      p.fontSizeCheck?.pass,
      p.touchTargetCheck?.pass,
      p.requiredElements?.pass,
      p.navigationAccessible,
    ];
    const passCount = checks.filter(Boolean).length;
    const totalChecks = checks.filter((c) => c !== undefined).length;
    const status = passCount === totalChecks ? 'PASS' : 'FAIL';

    console.log(`[${status}] ${p.page} @ ${p.viewport}  (${passCount}/${totalChecks} checks)`);

    if (p.horizontalOverflow && !p.horizontalOverflow.pass) {
      console.log(
        `  - Horizontal overflow: scrollWidth=${p.horizontalOverflow.scrollWidth}px > ${p.horizontalOverflow.viewportWidth}px`,
      );
    }
    if (p.fontSizeCheck && !p.fontSizeCheck.pass) {
      console.log(`  - Font too small: ${p.fontSizeCheck.smallestPx}px < ${MIN_FONT_SIZE_PX}px`);
    }
    if (p.touchTargetCheck && !p.touchTargetCheck.pass) {
      console.log(
        `  - ${p.touchTargetCheck.violationCount} touch target(s) below ${MIN_TOUCH_TARGET_PX}px`,
      );
    }
    if (p.requiredElements && !p.requiredElements.pass) {
      const missing = p.requiredElements.results
        .filter((r) => !r.visible)
        .map((r) => r.selector);
      console.log(`  - Missing elements: ${missing.join(', ')}`);
    }
    if (p.navigationAccessible === false) {
      console.log('  - Navigation not accessible');
    }
  }

  console.log('\n========================================\n');
});
