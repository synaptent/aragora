/**
 * Script to capture JavaScript console errors from live.aragora.ai
 *
 * Usage: npx ts-node scripts/capture-console-errors.ts
 * Or: npx playwright test scripts/capture-console-errors.ts --project=chromium
 */

import { chromium } from 'playwright';
import type { ConsoleMessage } from 'playwright';

interface ErrorEntry {
  page: string;
  type: string;
  message: string;
  location?: string;
}

const PAGES_TO_CHECK = [
  '/',
  '/about',
  '/debates',
  '/agents',
  '/tournaments',
  '/insights',
  '/evidence',
  '/memory',
  '/network',
  '/rankings',
  '/dashboard',
];

const MAX_ERRORS_PER_PAGE = 10;
const MAX_TOTAL_ERRORS = 50;

async function captureConsoleErrors() {
  const browser = await chromium.launch({ headless: true });
  const context = await browser.newContext();
  const page = await context.newPage();

  const allErrors: ErrorEntry[] = [];
  const errorCounts: Record<string, number> = {};

  // Capture console messages
  page.on('console', (msg: ConsoleMessage) => {
    if (msg.type() === 'error' || msg.type() === 'warning') {
      const currentUrl = page.url();
      const pagePath = new URL(currentUrl).pathname;

      if (!errorCounts[pagePath]) {
        errorCounts[pagePath] = 0;
      }

      if (errorCounts[pagePath] < MAX_ERRORS_PER_PAGE && allErrors.length < MAX_TOTAL_ERRORS) {
        allErrors.push({
          page: pagePath,
          type: msg.type(),
          message: msg.text().slice(0, 500), // Truncate long messages
          location: msg.location()?.url,
        });
        errorCounts[pagePath]++;
      }
    }
  });

  // Capture page errors (uncaught exceptions)
  page.on('pageerror', (error) => {
    const currentUrl = page.url();
    const pagePath = new URL(currentUrl).pathname;

    if (allErrors.length < MAX_TOTAL_ERRORS) {
      allErrors.push({ page: pagePath, type: 'pageerror', message: error.message.slice(0, 500) });
    }
  });

  console.log('='.repeat(60));
  console.log('Console Error Capture for live.aragora.ai');
  console.log('='.repeat(60));
  console.log(`Checking ${PAGES_TO_CHECK.length} pages...`);
  console.log(`Max ${MAX_ERRORS_PER_PAGE} errors per page, ${MAX_TOTAL_ERRORS} total`);
  console.log('='.repeat(60));

  for (const pagePath of PAGES_TO_CHECK) {
    const url = `https://live.aragora.ai${pagePath}`;
    console.log(`\nVisiting: ${url}`);

    try {
      await page.goto(url, { waitUntil: 'networkidle', timeout: 30000 });

      // Wait a bit for any async errors
      await page.waitForTimeout(2000);

      const pageErrors = allErrors.filter((e) => e.page === pagePath);
      console.log(`  → Found ${pageErrors.length} errors/warnings`);
    } catch (error) {
      console.log(`  → Failed to load: ${(error as Error).message.slice(0, 100)}`);
    }

    if (allErrors.length >= MAX_TOTAL_ERRORS) {
      console.log('\nMax errors reached, stopping...');
      break;
    }
  }

  await browser.close();

  // Output results
  console.log('\n' + '='.repeat(60));
  console.log('RESULTS SUMMARY');
  console.log('='.repeat(60));
  console.log(`Total errors/warnings captured: ${allErrors.length}`);

  // Group by page
  const byPage: Record<string, ErrorEntry[]> = {};
  for (const error of allErrors) {
    if (!byPage[error.page]) {
      byPage[error.page] = [];
    }
    byPage[error.page].push(error);
  }

  // Group similar errors
  const uniqueMessages = new Map<string, { count: number; pages: string[]; type: string }>();
  for (const error of allErrors) {
    const key = error.message.slice(0, 100);
    if (uniqueMessages.has(key)) {
      const existing = uniqueMessages.get(key)!;
      existing.count++;
      if (!existing.pages.includes(error.page)) {
        existing.pages.push(error.page);
      }
    } else {
      uniqueMessages.set(key, { count: 1, pages: [error.page], type: error.type });
    }
  }

  console.log('\n' + '-'.repeat(60));
  console.log('UNIQUE ERRORS (deduplicated)');
  console.log('-'.repeat(60));

  let i = 0;
  for (const [message, info] of uniqueMessages) {
    i++;
    console.log(`\n[${i}] (${info.type}) x${info.count} on: ${info.pages.join(', ')}`);
    console.log(`    ${message}`);
  }

  console.log('\n' + '='.repeat(60));
  console.log('END OF REPORT');
  console.log('='.repeat(60));

  return { allErrors, uniqueMessages: Object.fromEntries(uniqueMessages) };
}

// Run if executed directly
captureConsoleErrors().catch(console.error);
