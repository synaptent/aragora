import { defineConfig, devices } from '@playwright/test';

export const SPECIALTY_PROJECT_TEST_IGNORE = [
  '**/production/**',
  '**/accessibility.spec.ts',
  '**/visual-regression.spec.ts',
  '**/mobile/mobile-audit.spec.ts',
] as const;

export const CI_SMOKE_TEST_MATCH = [
  '**/config-validation.spec.ts',
  '**/homepage.spec.ts',
  '**/landing.spec.ts',
  '**/navigation.spec.ts',
] as const;

/**
 * Playwright configuration for Aragora Live Dashboard E2E tests.
 * @see https://playwright.dev/docs/test-configuration
 */
export default defineConfig({
  // Test directory
  testDir: './e2e',

  // Exclude production tests from regular CI runs (they test live site)
  testIgnore: process.env.PLAYWRIGHT_INCLUDE_PROD ? undefined : '**/production/**',

  // Global test timeout (30s per test)
  timeout: 30_000,

  // Run tests in files in parallel
  fullyParallel: true,

  // Fail the build on CI if you accidentally left test.only in the source code
  forbidOnly: !!process.env.CI,

  // Retry on CI only
  retries: process.env.CI ? 2 : 0,

  // Opt out of parallel tests on CI
  workers: process.env.CI ? 1 : undefined,

  // Reporter to use
  reporter: [
    ['list'],
    ['html', { outputFolder: 'playwright-report' }],
    // Add JSON reporter for CI parsing
    ...(process.env.CI ? [['json', { outputFile: 'playwright-results.json' }] as const] : []),
  ],

  // Shared settings for all the projects below
  use: {
    // Base URL to use in actions like `await page.goto('/')`
    baseURL: process.env.PLAYWRIGHT_BASE_URL || 'http://localhost:3000',

    // Collect trace when retrying the failed test
    trace: 'on-first-retry',

    // Screenshot on failure
    screenshot: 'only-on-failure',

    // Video on failure
    video: 'on-first-retry',
  },

  // Visual regression settings for toHaveScreenshot
  expect: {
    toHaveScreenshot: {
      // Maximum allowed pixel difference
      maxDiffPixels: 100,
      // Maximum allowed ratio of different pixels (0.2%)
      maxDiffPixelRatio: 0.002,
      // Disable animations for consistent screenshots
      animations: 'disabled',
      // Threshold for per-pixel color comparison (0-1)
      threshold: 0.2,
    },
  },

  // Configure projects for major browsers
  projects: [
    {
      name: 'chromium',
      use: { ...devices['Desktop Chrome'] },
      testIgnore: SPECIALTY_PROJECT_TEST_IGNORE,
    },

    // Bounded PR lane: stable local smoke specs only. The broad Chromium suite
    // remains available through the chromium project for nightly/manual runs.
    {
      name: 'ci-smoke',
      use: { ...devices['Desktop Chrome'] },
      testMatch: CI_SMOKE_TEST_MATCH,
      testIgnore: SPECIALTY_PROJECT_TEST_IGNORE,
    },

    {
      name: 'firefox',
      use: { ...devices['Desktop Firefox'] },
      testIgnore: SPECIALTY_PROJECT_TEST_IGNORE,
    },

    {
      name: 'webkit',
      use: { ...devices['Desktop Safari'] },
      testIgnore: SPECIALTY_PROJECT_TEST_IGNORE,
    },

    // Test against mobile viewports (for responsiveness)
    {
      name: 'Mobile Chrome',
      use: { ...devices['Pixel 5'] },
      testIgnore: SPECIALTY_PROJECT_TEST_IGNORE,
    },
    {
      name: 'Mobile Safari',
      use: { ...devices['iPhone 12'] },
      testIgnore: SPECIALTY_PROJECT_TEST_IGNORE,
    },

    // Accessibility tests - run with: npx playwright test --project=accessibility
    {
      name: 'accessibility',
      use: { ...devices['Desktop Chrome'] },
      testMatch: /accessibility\.spec\.ts/,
    },

    // Visual regression tests - run with: npx playwright test --project=visual-regression
    {
      name: 'visual-regression',
      use: { ...devices['Desktop Chrome'] },
      testMatch: /visual-regression\.spec\.ts/,
    },

    // Mobile audit tests - run with: npx playwright test --project=mobile-audit
    // Against production: PLAYWRIGHT_BASE_URL=https://aragora.ai npx playwright test --project=mobile-audit
    {
      name: 'mobile-audit',
      use: { ...devices['Desktop Chrome'] }, // viewport overridden per-test
      testDir: './e2e/mobile',
      testMatch: /mobile-audit\.spec\.ts/,
    },

    // Production monitoring tests - run with: PLAYWRIGHT_INCLUDE_PROD=1 npx playwright test --project=production
    {
      name: 'production',
      use: { ...devices['Desktop Chrome'], baseURL: 'https://aragora.ai' },
      testDir: './e2e/production',
      testMatch: /\.prod\.spec\.ts/,
    },
  ],

  // Run your local dev server before starting the tests
  webServer: {
    command: 'npm run dev',
    url: 'http://localhost:3000',
    reuseExistingServer: true,
    timeout: 120 * 1000,
  },
});
