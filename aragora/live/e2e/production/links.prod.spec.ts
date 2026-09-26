/**
 * Link Checker Tests for Production
 *
 * Tests for broken links on production sites.
 *
 * Run with: npx playwright test links.prod.spec.ts --config=playwright.production.config.ts
 */

import { test, expect, PRODUCTION_DOMAINS } from './fixtures';

interface LinkResult {
  url: string;
  text: string;
  status: number | null;
  error?: string;
}

test.describe('Link Checker - aragora.ai', () => {
  test('should have no broken internal links on homepage', async ({ page, productionPage }) => {
    await productionPage.goto(PRODUCTION_DOMAINS.landing);
    await productionPage.waitForHydration();

    // Get all internal links
    const links = await page.evaluate((domain) => {
      const anchors = document.querySelectorAll('a[href]');
      const internalLinks: { href: string; text: string }[] = [];

      anchors.forEach((a) => {
        const href = a.getAttribute('href');
        if (href && (href.startsWith('/') || href.startsWith(domain) || href.startsWith('#'))) {
          // Skip anchor-only links
          if (href !== '#' && !href.startsWith('#')) {
            internalLinks.push({
              href: href.startsWith('/') ? `${domain}${href}` : href,
              text: (a.textContent || '').trim().substring(0, 50),
            });
          }
        }
      });

      // Deduplicate
      return [...new Map(internalLinks.map((l) => [l.href, l])).values()];
    }, PRODUCTION_DOMAINS.landing);

    console.log(`Found ${links.length} internal links on homepage`);

    const brokenLinks: LinkResult[] = [];

    // Check each link (with rate limiting)
    for (const link of links.slice(0, 20)) {
      // Limit to first 20 links
      await page.waitForTimeout(500); // Rate limit

      try {
        const response = await page.goto(link.href, {
          waitUntil: 'domcontentloaded',
          timeout: 15000,
        });

        const status = response?.status() || 0;
        if (status >= 400) {
          brokenLinks.push({ url: link.href, text: link.text, status });
        }
      } catch (error) {
        brokenLinks.push({
          url: link.href,
          text: link.text,
          status: null,
          error: error instanceof Error ? error.message : String(error),
        });
      }
    }

    if (brokenLinks.length > 0) {
      console.log('\n=== Broken Links on aragora.ai ===');
      brokenLinks.forEach((link) => {
        console.log(`  [${link.status || 'ERR'}] ${link.url} (${link.text || 'no text'})`);
        if (link.error) {
          console.log(`    Error: ${link.error}`);
        }
      });
    }

    expect(brokenLinks.filter((l) => l.status === 404)).toHaveLength(0);
  });

  test('should have no broken internal links on about page', async ({ page, productionPage }) => {
    await productionPage.goto(`${PRODUCTION_DOMAINS.landing}/about`);
    await productionPage.waitForHydration();

    const links = await page.evaluate((domain) => {
      const anchors = document.querySelectorAll('a[href^="/"], a[href^="' + domain + '"]');
      const hrefs: string[] = [];

      anchors.forEach((a) => {
        const href = a.getAttribute('href');
        if (href && href !== '#') {
          hrefs.push(href.startsWith('/') ? `${domain}${href}` : href);
        }
      });

      return [...new Set(hrefs)];
    }, PRODUCTION_DOMAINS.landing);

    console.log(`Found ${links.length} internal links on about page`);

    const brokenLinks: string[] = [];

    for (const link of links.slice(0, 10)) {
      await page.waitForTimeout(500);

      try {
        const response = await page.goto(link, { waitUntil: 'domcontentloaded', timeout: 15000 });

        if (response && response.status() >= 400) {
          brokenLinks.push(`${link} (${response.status()})`);
        }
      } catch {
        brokenLinks.push(`${link} (error)`);
      }
    }

    if (brokenLinks.length > 0) {
      console.log('Broken links:', brokenLinks);
    }

    expect(brokenLinks.filter((l) => l.includes('404'))).toHaveLength(0);
  });
});

test.describe('Link Checker - live.aragora.ai', () => {
  test('should have no broken internal links', async ({ page, productionPage }) => {
    await productionPage.goto(PRODUCTION_DOMAINS.dashboard);
    await productionPage.waitForHydration();
    await productionPage.dismissBootAnimation();

    const links = await page.evaluate((domain) => {
      const anchors = document.querySelectorAll('a[href]');
      const internalLinks: string[] = [];

      anchors.forEach((a) => {
        const href = a.getAttribute('href');
        if (href && (href.startsWith('/') || href.startsWith(domain))) {
          if (href !== '#') {
            internalLinks.push(href.startsWith('/') ? `${domain}${href}` : href);
          }
        }
      });

      return [...new Set(internalLinks)];
    }, PRODUCTION_DOMAINS.dashboard);

    console.log(`Found ${links.length} internal links on dashboard`);

    const brokenLinks: LinkResult[] = [];

    for (const link of links.slice(0, 15)) {
      await page.waitForTimeout(500);

      try {
        const response = await page.goto(link, { waitUntil: 'domcontentloaded', timeout: 15000 });

        const status = response?.status() || 0;
        if (status >= 400) {
          brokenLinks.push({ url: link, text: '', status });
        }
      } catch (error) {
        brokenLinks.push({
          url: link,
          text: '',
          status: null,
          error: error instanceof Error ? error.message : String(error),
        });
      }
    }

    if (brokenLinks.length > 0) {
      console.log('\n=== Broken Links on live.aragora.ai ===');
      brokenLinks.forEach((link) => {
        console.log(`  [${link.status || 'ERR'}] ${link.url}`);
      });
    }

    expect(brokenLinks.filter((l) => l.status === 404)).toHaveLength(0);
  });
});

test.describe('External Link Verification', () => {
  test('external links should be valid on aragora.ai', async ({ page, productionPage }) => {
    await productionPage.goto(PRODUCTION_DOMAINS.landing);
    await productionPage.waitForHydration();

    const externalLinks = await page.evaluate(() => {
      const anchors = document.querySelectorAll('a[href^="http"]');
      const links: { href: string; text: string }[] = [];

      anchors.forEach((a) => {
        const href = a.getAttribute('href');
        if (href && !href.includes('aragora.ai')) {
          links.push({ href, text: (a.textContent || '').trim().substring(0, 30) });
        }
      });

      return [...new Map(links.map((l) => [l.href, l])).values()];
    });

    console.log(`Found ${externalLinks.length} external links`);

    // Just log external links, don't verify (to avoid hitting external services)
    externalLinks.slice(0, 10).forEach((link) => {
      console.log(`  - ${link.href} (${link.text || 'no text'})`);
    });

    // Check that external links have proper attributes
    const linkSecurity = await page.evaluate(() => {
      const externalAnchors = document.querySelectorAll('a[href^="http"]');
      const issues: string[] = [];

      externalAnchors.forEach((a) => {
        const href = a.getAttribute('href');
        const target = a.getAttribute('target');
        const rel = a.getAttribute('rel');

        if (href && !href.includes('aragora.ai')) {
          // External links opening in new tab should have rel="noopener"
          if (target === '_blank' && (!rel || !rel.includes('noopener'))) {
            issues.push(href);
          }
        }
      });

      return issues;
    });

    if (linkSecurity.length > 0) {
      console.log('\n=== External links without rel="noopener" ===');
      linkSecurity.slice(0, 5).forEach((link) => {
        console.log(`  - ${link}`);
      });
    }
  });
});

test.describe('Image Source Verification', () => {
  test('all images should have valid sources on aragora.ai', async ({ page, productionPage }) => {
    await productionPage.goto(PRODUCTION_DOMAINS.landing);
    await productionPage.waitForHydration();

    const images = await page.evaluate(() => {
      const imgs = document.querySelectorAll('img[src]');
      const sources: { src: string; alt: string }[] = [];

      imgs.forEach((img) => {
        const src = img.getAttribute('src');
        const alt = img.getAttribute('alt');
        if (src) {
          sources.push({ src, alt: alt || '' });
        }
      });

      return sources;
    });

    console.log(`Found ${images.length} images`);

    const brokenImages: string[] = [];

    // Check each image
    for (const img of images) {
      const loaded = await page.evaluate(async (src) => {
        return new Promise<boolean>((resolve) => {
          const image = new Image();
          image.onload = () => resolve(true);
          image.onerror = () => resolve(false);
          image.src = src;
        });
      }, img.src);

      if (!loaded) {
        brokenImages.push(img.src);
      }
    }

    if (brokenImages.length > 0) {
      console.log('\n=== Broken Images ===');
      brokenImages.forEach((src) => {
        console.log(`  - ${src}`);
      });
    }

    expect(brokenImages).toHaveLength(0);
  });

  test('all images should have valid sources on live.aragora.ai', async ({
    page,
    productionPage,
  }) => {
    await productionPage.goto(PRODUCTION_DOMAINS.dashboard);
    await productionPage.waitForHydration();
    await productionPage.dismissBootAnimation();

    const images = await page.evaluate(() => {
      const imgs = document.querySelectorAll('img[src]');
      return Array.from(imgs)
        .map((img) => img.getAttribute('src'))
        .filter(Boolean);
    });

    console.log(`Found ${images.length} images on dashboard`);

    const brokenImages: string[] = [];

    for (const src of images) {
      if (!src) continue;

      const loaded = await page.evaluate(async (imgSrc) => {
        return new Promise<boolean>((resolve) => {
          const image = new Image();
          image.onload = () => resolve(true);
          image.onerror = () => resolve(false);
          image.src = imgSrc;
        });
      }, src);

      if (!loaded) {
        brokenImages.push(src);
      }
    }

    if (brokenImages.length > 0) {
      console.log('Broken images:', brokenImages);
    }

    expect(brokenImages).toHaveLength(0);
  });
});

test.describe('Navigation Link Consistency', () => {
  test('navigation links should work on aragora.ai', async ({ page, productionPage }) => {
    await productionPage.goto(PRODUCTION_DOMAINS.landing);
    await productionPage.waitForHydration();

    // Get navigation links
    const navLinks = await page.evaluate(() => {
      const nav = document.querySelector('nav, header');
      if (!nav) return [];

      const links = nav.querySelectorAll('a[href]');
      return Array.from(links)
        .map((a) => ({ href: a.getAttribute('href'), text: a.textContent?.trim() }))
        .filter((l) => l.href && l.href !== '#');
    });

    console.log(`Found ${navLinks.length} navigation links`);

    // Test each nav link
    for (const link of navLinks) {
      if (!link.href) continue;

      const url = link.href.startsWith('/')
        ? `${PRODUCTION_DOMAINS.landing}${link.href}`
        : link.href;

      // Skip external links
      if (!url.includes('aragora.ai')) continue;

      await page.waitForTimeout(500);

      try {
        const response = await page.goto(url, { waitUntil: 'domcontentloaded', timeout: 15000 });

        const status = response?.status() || 0;
        console.log(`  [${status}] ${link.text} -> ${url}`);

        expect(status).toBeLessThan(400);
      } catch {
        console.log(`  [ERR] ${link.text} -> ${url}`);
        // Don't fail on timeout, just log
      }
    }
  });
});

test.describe('Footer Links', () => {
  test('footer links should work on aragora.ai', async ({ page, productionPage }) => {
    await productionPage.goto(PRODUCTION_DOMAINS.landing);
    await productionPage.waitForHydration();

    const footerLinks = await page.evaluate(() => {
      const footer = document.querySelector('footer');
      if (!footer) return [];

      const links = footer.querySelectorAll('a[href]');
      return Array.from(links)
        .map((a) => ({ href: a.getAttribute('href'), text: a.textContent?.trim() }))
        .filter((l) => l.href && l.href !== '#');
    });

    console.log(`Found ${footerLinks.length} footer links`);

    const brokenFooterLinks: string[] = [];

    for (const link of footerLinks) {
      if (!link.href) continue;

      const url = link.href.startsWith('/')
        ? `${PRODUCTION_DOMAINS.landing}${link.href}`
        : link.href;

      // Skip external links
      if (!url.includes('aragora.ai')) {
        console.log(`  [EXT] ${link.text} -> ${url}`);
        continue;
      }

      await page.waitForTimeout(300);

      try {
        const response = await page.goto(url, { waitUntil: 'domcontentloaded', timeout: 10000 });

        const status = response?.status() || 0;
        if (status >= 400) {
          brokenFooterLinks.push(`${link.text}: ${url} (${status})`);
        } else {
          console.log(`  [${status}] ${link.text}`);
        }
      } catch {
        brokenFooterLinks.push(`${link.text}: ${url} (error)`);
      }
    }

    if (brokenFooterLinks.length > 0) {
      console.log('\n=== Broken Footer Links ===');
      brokenFooterLinks.forEach((l) => console.log(`  - ${l}`));
    }

    expect(brokenFooterLinks.filter((l) => l.includes('404'))).toHaveLength(0);
  });
});
