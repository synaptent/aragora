import { defineConfig, devices } from '@playwright/test';

/**
 * Playwright configuration for Aragora Production E2E tests.
 *
 * These tests run against live production sites:
 * - aragora.ai (landing page)
 * - live.aragora.ai (dashboard)
 * - api.aragora.ai (API health)
 * - status.aragora.ai (status page)
 *
 * IMPORTANT: These are READ-ONLY tests that do not mutate production data.
 *
 * Run with: npx playwright test --config=playwright.production.config.ts
 */
export default defineConfig({
  testDir: './e2e/production',

  // Run tests sequentially to be respectful of production
  fullyParallel: false,

  // No retries in production - we want to see actual failures
  retries: 0,

  // Single worker for rate limiting
  workers: 1,

  // Extended timeout for production network latency
  timeout: 60000,

  // Expect timeout
  expect: { timeout: 15000 },

  // Reporter configuration
  reporter: [
    ['list'],
    ['html', { outputFolder: 'playwright-report-production', open: 'never' }],
    ['json', { outputFile: 'playwright-report-production/results.json' }],
  ],

  // Shared settings
  use: {
    // No base URL - each test specifies full URLs
    baseURL: undefined,

    // Collect trace on failure for debugging
    trace: 'on-first-retry',

    // Screenshot on every failure
    screenshot: 'only-on-failure',

    // Video on failure
    video: 'retain-on-failure',

    // Extended timeouts for production
    actionTimeout: 30000,
    navigationTimeout: 45000,

    // Respect production - add delays
    launchOptions: {
      slowMo: 500, // 500ms delay between actions
    },

    // Use standard user agent to avoid CORS issues with external resources
    // userAgent: 'AragoraE2ETest/1.0'  // Disabled - causes CORS issues with fonts/analytics
  },

  // Only test in Chrome for production (faster, reliable)
  projects: [
    {
      name: 'production-chromium',
      use: { ...devices['Desktop Chrome'], viewport: { width: 1920, height: 1080 } },
    },
    { name: 'production-mobile', use: { ...devices['iPhone 12'] } },
  ],

  // No web server - we're testing live production
  webServer: undefined,

  // Global setup/teardown for production tests
  globalSetup: undefined,
  globalTeardown: undefined,
});
