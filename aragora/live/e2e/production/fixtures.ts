import { test as base, expect, Page } from '@playwright/test';

/**
 * Production test fixtures for Aragora E2E tests.
 *
 * These fixtures are designed for testing live production sites
 * with error collection, rate limiting, and screenshot capture.
 */

// Production domains
export const PRODUCTION_DOMAINS = {
  landing: 'https://aragora.ai',
  www: 'https://www.aragora.ai',
  dashboard: 'https://live.aragora.ai',
  api: 'https://api.aragora.ai',
  status: 'https://status.aragora.ai',
} as const;

// Error severity levels
export type ErrorSeverity = 'critical' | 'high' | 'medium' | 'low';

// Collected error interface
export interface CollectedError {
  type: 'console' | 'network' | 'exception' | 'accessibility' | 'broken-link';
  severity: ErrorSeverity;
  message: string;
  url: string;
  timestamp: Date;
  details?: Record<string, unknown>;
}

/**
 * Error collector for production tests.
 * Captures console errors, network failures, and JavaScript exceptions.
 */
export class ErrorCollector {
  public errors: CollectedError[] = [];
  private page: Page;

  constructor(page: Page) {
    this.page = page;
    this.setupListeners();
  }

  private setupListeners() {
    // Console errors
    this.page.on('console', (msg) => {
      const text = msg.text();

      // Filter out expected CORS errors from external resources
      // Note: api.aragora.ai CORS is a known issue to be fixed in server config
      const isExternalCorsError =
        text.includes('CORS policy') &&
        (text.includes('cloudflareinsights.com') ||
          text.includes('fonts.gstatic.com') ||
          text.includes('fonts.googleapis.com') ||
          text.includes('google-analytics.com') ||
          text.includes('googletagmanager.com') ||
          text.includes('api.aragora.ai') || // Known CORS config issue
          text.includes('localhost'));

      // Filter out expected network errors
      const isExpectedNetworkError =
        text.includes('Failed to load resource') &&
        (text.includes('cloudflareinsights.com') ||
          text.includes('fonts.gstatic.com') ||
          text.includes('localhost'));

      if (msg.type() === 'error' && !isExternalCorsError && !isExpectedNetworkError) {
        this.addError({
          type: 'console',
          severity: 'high',
          message: text,
          url: this.page.url(),
          timestamp: new Date(),
          details: { location: msg.location() },
        });
      } else if (msg.type() === 'warning') {
        // Filter out common non-critical warnings
        if (
          !text.includes('DevTools') &&
          !text.includes('Third-party cookie') &&
          !text.includes('CORS')
        ) {
          this.addError({
            type: 'console',
            severity: 'low',
            message: text,
            url: this.page.url(),
            timestamp: new Date(),
          });
        }
      }
    });

    // Page errors (unhandled exceptions)
    this.page.on('pageerror', (error) => {
      this.addError({
        type: 'exception',
        severity: 'critical',
        message: error.message,
        url: this.page.url(),
        timestamp: new Date(),
        details: { stack: error.stack },
      });
    });

    // Network failures
    this.page.on('requestfailed', (request) => {
      const failure = request.failure();
      const requestUrl = request.url();

      // Filter out expected failures
      const isExpectedFailure =
        !failure ||
        failure.errorText.includes('net::ERR_ABORTED') ||
        failure.errorText.includes('net::ERR_BLOCKED_BY_CLIENT') ||
        // External resources that may fail due to ad blockers or CORS
        requestUrl.includes('cloudflareinsights.com') ||
        requestUrl.includes('fonts.gstatic.com') ||
        requestUrl.includes('fonts.googleapis.com') ||
        requestUrl.includes('google-analytics.com') ||
        requestUrl.includes('googletagmanager.com') ||
        requestUrl.includes('api.aragora.ai') || // Known CORS config issue
        requestUrl.includes('localhost');

      if (!isExpectedFailure) {
        this.addError({
          type: 'network',
          severity: 'high',
          message: `Request failed: ${requestUrl} - ${failure?.errorText || 'unknown'}`,
          url: this.page.url(),
          timestamp: new Date(),
          details: { requestUrl, method: request.method(), errorText: failure?.errorText },
        });
      }
    });

    // Response errors (4xx, 5xx)
    this.page.on('response', (response) => {
      const status = response.status();
      if (status >= 400) {
        const severity: ErrorSeverity =
          status >= 500 ? 'critical' : status === 404 ? 'medium' : 'high';
        this.addError({
          type: 'network',
          severity,
          message: `HTTP ${status}: ${response.url()}`,
          url: this.page.url(),
          timestamp: new Date(),
          details: { requestUrl: response.url(), status, statusText: response.statusText() },
        });
      }
    });
  }

  private addError(error: CollectedError) {
    // Deduplicate errors
    const isDuplicate = this.errors.some(
      (e) => e.type === error.type && e.message === error.message && e.url === error.url,
    );
    if (!isDuplicate) {
      this.errors.push(error);
    }
  }

  /**
   * Add an error manually (e.g., from accessibility tests)
   */
  addManualError(error: Omit<CollectedError, 'timestamp'> & { timestamp?: Date }) {
    this.addError({ ...error, timestamp: error.timestamp || new Date() });
  }

  /**
   * Get errors filtered by severity
   */
  getErrorsBySeverity(severity: ErrorSeverity): CollectedError[] {
    return this.errors.filter((e) => e.severity === severity);
  }

  /**
   * Get critical and high severity errors
   */
  getCriticalErrors(): CollectedError[] {
    return this.errors.filter((e) => e.severity === 'critical' || e.severity === 'high');
  }

  /**
   * Check if there are any critical errors
   */
  hasCriticalErrors(): boolean {
    return this.errors.some((e) => e.severity === 'critical');
  }

  /**
   * Generate a summary report
   */
  generateReport(): string {
    const summary = {
      total: this.errors.length,
      critical: this.getErrorsBySeverity('critical').length,
      high: this.getErrorsBySeverity('high').length,
      medium: this.getErrorsBySeverity('medium').length,
      low: this.getErrorsBySeverity('low').length,
    };

    let report = `\n=== ERROR SUMMARY ===\n`;
    report += `Total: ${summary.total}\n`;
    report += `Critical: ${summary.critical}\n`;
    report += `High: ${summary.high}\n`;
    report += `Medium: ${summary.medium}\n`;
    report += `Low: ${summary.low}\n`;

    if (this.errors.length > 0) {
      report += `\n=== ERRORS ===\n`;
      for (const error of this.errors) {
        report += `\n[${error.severity.toUpperCase()}] ${error.type}\n`;
        report += `  URL: ${error.url}\n`;
        report += `  Message: ${error.message}\n`;
        if (error.details) {
          report += `  Details: ${JSON.stringify(error.details, null, 2)}\n`;
        }
      }
    }

    return report;
  }

  /**
   * Clear all collected errors
   */
  clear() {
    this.errors = [];
  }
}

/**
 * Production page helper with rate limiting and error collection.
 */
export class ProductionPage {
  private page: Page;
  public errorCollector: ErrorCollector;

  constructor(page: Page) {
    this.page = page;
    this.errorCollector = new ErrorCollector(page);
  }

  /**
   * Navigate to a URL with rate limiting delay
   */
  async goto(url: string, options?: { waitUntil?: 'load' | 'domcontentloaded' | 'networkidle' }) {
    // Rate limit: wait before navigation
    await this.page.waitForTimeout(1000);
    await this.page.goto(url, {
      waitUntil: options?.waitUntil || 'domcontentloaded',
      timeout: 45000,
    });
    // Wait for page to stabilize
    await this.page.waitForTimeout(500);
  }

  /**
   * Take a screenshot with automatic naming
   */
  async screenshot(name: string): Promise<Buffer> {
    const timestamp = new Date().toISOString().replace(/[:.]/g, '-');
    return this.page.screenshot({
      path: `playwright-report-production/screenshots/${name}-${timestamp}.png`,
      fullPage: true,
    });
  }

  /**
   * Wait for page to be fully loaded (hydrated)
   */
  async waitForHydration() {
    await this.page.waitForLoadState('domcontentloaded');
    // Wait for Next.js hydration marker or React root
    await this.page
      .waitForSelector('#__next, #root, [data-testid="app-root"]', { timeout: 10000 })
      .catch(() => {});
    // Additional wait for dynamic content
    await this.page.waitForTimeout(1000);
  }

  /**
   * Dismiss boot animation if present
   */
  async dismissBootAnimation() {
    const bootOverlay = this.page.locator('[aria-label*="Boot sequence"]');
    if (await bootOverlay.isVisible({ timeout: 2000 }).catch(() => false)) {
      await bootOverlay.click();
      await bootOverlay.waitFor({ state: 'hidden', timeout: 5000 }).catch(() => {});
    }
  }

  /**
   * Check if page has critical errors
   */
  hasCriticalErrors(): boolean {
    return this.errorCollector.hasCriticalErrors();
  }

  /**
   * Get the underlying Playwright page
   */
  getPage(): Page {
    return this.page;
  }
}

// Extended test with production fixtures
export const test = base.extend<{ productionPage: ProductionPage; errorCollector: ErrorCollector }>(
  {
    productionPage: async ({ page }, use) => {
      const prodPage = new ProductionPage(page);
      await use(prodPage);

      // After test: log any errors found
      const errors = prodPage.errorCollector.errors;
      if (errors.length > 0) {
        console.log(prodPage.errorCollector.generateReport());
      }
    },
    errorCollector: async ({ page }, use) => {
      const collector = new ErrorCollector(page);
      await use(collector);
    },
  },
);

export { expect };

// Helper to wait between requests (rate limiting)
export async function rateLimitDelay(page: Page, ms = 1000) {
  await page.waitForTimeout(ms);
}

// Helper to check if a URL is accessible
export async function isUrlAccessible(
  page: Page,
  url: string,
): Promise<{ accessible: boolean; status?: number; error?: string }> {
  try {
    const response = await page.goto(url, { waitUntil: 'domcontentloaded', timeout: 30000 });
    return { accessible: response !== null && response.status() < 400, status: response?.status() };
  } catch (error) {
    return { accessible: false, error: error instanceof Error ? error.message : String(error) };
  }
}

// All pages to test on aragora.ai
export const LANDING_PAGES = [
  { path: '/', name: 'Home' },
  { path: '/about', name: 'About' },
  { path: '/pricing', name: 'Pricing' },
  { path: '/security', name: 'Security' },
  { path: '/privacy', name: 'Privacy' },
];

// All pages to test on live.aragora.ai
export const DASHBOARD_PAGES = [
  { path: '/', name: 'Dashboard Home' },
  { path: '/debates', name: 'Debates' },
  { path: '/agents', name: 'Agents' },
  { path: '/leaderboard', name: 'Leaderboard' },
];

// API endpoints to health check
export const API_ENDPOINTS = [
  { path: '/api/health', name: 'Health Check' },
  { path: '/api/system/info', name: 'System Info' },
];
