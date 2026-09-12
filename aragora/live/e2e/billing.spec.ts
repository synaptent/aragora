import { test, expect, mockApiResponse } from './fixtures';

/**
 * E2E tests for Billing functionality.
 *
 * Tests the billing dashboard including:
 * - Usage display and limits
 * - Subscription status
 * - Invoice history
 * - Plan upgrade flow
 * - Billing portal access
 * - Authentication requirements
 */

// Mock subscription data
const mockSubscription = {
  subscription: {
    tier: 'pro',
    status: 'active',
    current_period_start: '2026-01-01T00:00:00Z',
    current_period_end: '2026-02-01T00:00:00Z',
    cancel_at_period_end: false,
    payment_method: { type: 'card', last4: '4242', brand: 'visa' },
  },
};

const mockFreeSubscription = {
  subscription: { tier: 'free', status: 'active', debates_limit: 10, debates_used: 5 },
};

// Mock usage data
const mockUsage = {
  usage: {
    debates_used: 45,
    debates_limit: 100,
    tokens_used: 125000,
    tokens_limit: 500000,
    period_start: '2026-01-01T00:00:00Z',
    period_end: '2026-02-01T00:00:00Z',
    agents_used: 4,
    storage_used_mb: 128,
  },
};

const mockUsageNearLimit = {
  usage: {
    debates_used: 95,
    debates_limit: 100,
    tokens_used: 480000,
    tokens_limit: 500000,
    period_start: '2026-01-01T00:00:00Z',
    period_end: '2026-02-01T00:00:00Z',
    agents_used: 8,
    storage_used_mb: 512,
  },
};

// Mock invoices
const mockInvoices = {
  invoices: [
    {
      id: 'inv_001',
      amount: 4900,
      currency: 'usd',
      status: 'paid',
      created_at: '2026-01-01T00:00:00Z',
      pdf_url: 'https://stripe.com/invoice/inv_001.pdf',
    },
    {
      id: 'inv_002',
      amount: 4900,
      currency: 'usd',
      status: 'paid',
      created_at: '2025-12-01T00:00:00Z',
      pdf_url: 'https://stripe.com/invoice/inv_002.pdf',
    },
  ],
};

const mockNoInvoices = { invoices: [] };

// Mock forecast
const mockForecast = {
  forecast: {
    projected_debates: 60,
    projected_tokens: 175000,
    trend: 'increasing',
    days_until_limit: 15,
  },
};

// Mock plans
const mockPlans = {
  plans: [
    {
      id: 'free',
      name: 'Free',
      price: 0,
      debates_limit: 10,
      features: ['10 debates/month', 'Basic agents'],
    },
    {
      id: 'pro',
      name: 'Pro',
      price: 4900,
      debates_limit: 100,
      features: ['100 debates/month', 'All agents', 'Priority support'],
    },
    {
      id: 'enterprise',
      name: 'Enterprise',
      price: null,
      debates_limit: -1,
      features: ['Unlimited debates', 'Custom agents', 'SLA', 'Dedicated support'],
    },
  ],
};

test.describe('Billing Page', () => {
  test.describe('Page Load and Navigation', () => {
    test('should redirect to login when not authenticated', async ({ page }) => {
      // Don't mock auth - page should redirect
      await page.goto('/billing');

      // Should redirect to login
      await expect(page).toHaveURL(/\/auth\/login|\/login/);
    });

    test('should load billing page when authenticated', async ({ page, aragoraPage }) => {
      // Mock all billing endpoints
      await mockApiResponse(page, '**/api/billing/usage', mockUsage);
      await mockApiResponse(page, '**/api/billing/subscription', mockSubscription);
      await mockApiResponse(page, '**/api/billing/invoices*', mockInvoices);
      await mockApiResponse(page, '**/api/billing/usage/forecast', mockForecast);
      await mockApiResponse(page, '**/api/billing/plans', mockPlans);

      // Mock authentication
      await page.addInitScript(() => {
        localStorage.setItem(
          'auth_tokens',
          JSON.stringify({
            access_token: 'mock-token',
            refresh_token: 'mock-refresh',
            expires_at: Date.now() + 3600000,
          }),
        );
        localStorage.setItem(
          'auth_user',
          JSON.stringify({ id: 'user-123', email: 'test@example.com' }),
        );
      });

      await page.goto('/billing');
      await aragoraPage.dismissAllOverlays();

      // Page should load successfully
      await expect(page).toHaveURL(/\/billing/);
      await expect(page.locator('body')).toBeVisible();
    });
  });

  test.describe('Usage Display', () => {
    test('should display usage metrics', async ({ page, aragoraPage }) => {
      await mockApiResponse(page, '**/api/billing/usage', mockUsage);
      await mockApiResponse(page, '**/api/billing/subscription', mockSubscription);
      await mockApiResponse(page, '**/api/billing/invoices*', mockInvoices);
      await mockApiResponse(page, '**/api/billing/usage/forecast', mockForecast);
      await mockApiResponse(page, '**/api/billing/plans', mockPlans);

      await page.addInitScript(() => {
        localStorage.setItem(
          'auth_tokens',
          JSON.stringify({
            access_token: 'mock-token',
            refresh_token: 'mock-refresh',
            expires_at: Date.now() + 3600000,
          }),
        );
        localStorage.setItem(
          'auth_user',
          JSON.stringify({ id: 'user-123', email: 'test@example.com' }),
        );
      });

      await page.goto('/billing');
      await aragoraPage.dismissAllOverlays();
      await page.waitForLoadState('domcontentloaded');

      // Should show usage numbers (45/100 debates)
      await expect(page.locator('text=/45.*100|45 of 100/')).toBeVisible({ timeout: 10000 });
    });

    test('should show warning when near usage limit', async ({ page, aragoraPage }) => {
      await mockApiResponse(page, '**/api/billing/usage', mockUsageNearLimit);
      await mockApiResponse(page, '**/api/billing/subscription', mockSubscription);
      await mockApiResponse(page, '**/api/billing/invoices*', mockInvoices);
      await mockApiResponse(page, '**/api/billing/usage/forecast', mockForecast);
      await mockApiResponse(page, '**/api/billing/plans', mockPlans);

      await page.addInitScript(() => {
        localStorage.setItem(
          'auth_tokens',
          JSON.stringify({
            access_token: 'mock-token',
            refresh_token: 'mock-refresh',
            expires_at: Date.now() + 3600000,
          }),
        );
        localStorage.setItem(
          'auth_user',
          JSON.stringify({ id: 'user-123', email: 'test@example.com' }),
        );
      });

      await page.goto('/billing');
      await aragoraPage.dismissAllOverlays();
      await page.waitForLoadState('domcontentloaded');

      // Should show 95% usage
      await expect(page.locator('text=/95.*100|95 of 100|95%/')).toBeVisible({ timeout: 10000 });
    });
  });

  test.describe('Subscription Status', () => {
    test('should display current subscription tier', async ({ page, aragoraPage }) => {
      await mockApiResponse(page, '**/api/billing/usage', mockUsage);
      await mockApiResponse(page, '**/api/billing/subscription', mockSubscription);
      await mockApiResponse(page, '**/api/billing/invoices*', mockInvoices);
      await mockApiResponse(page, '**/api/billing/usage/forecast', mockForecast);
      await mockApiResponse(page, '**/api/billing/plans', mockPlans);

      await page.addInitScript(() => {
        localStorage.setItem(
          'auth_tokens',
          JSON.stringify({
            access_token: 'mock-token',
            refresh_token: 'mock-refresh',
            expires_at: Date.now() + 3600000,
          }),
        );
        localStorage.setItem(
          'auth_user',
          JSON.stringify({ id: 'user-123', email: 'test@example.com' }),
        );
      });

      await page.goto('/billing');
      await aragoraPage.dismissAllOverlays();

      // Should show Pro tier
      await expect(page.locator('text=/pro|Pro/i')).toBeVisible({ timeout: 10000 });
    });

    test('should show free tier for free users', async ({ page, aragoraPage }) => {
      await mockApiResponse(page, '**/api/billing/usage', mockUsage);
      await mockApiResponse(page, '**/api/billing/subscription', mockFreeSubscription);
      await mockApiResponse(page, '**/api/billing/invoices*', mockNoInvoices);
      await mockApiResponse(page, '**/api/billing/usage/forecast', mockForecast);
      await mockApiResponse(page, '**/api/billing/plans', mockPlans);

      await page.addInitScript(() => {
        localStorage.setItem(
          'auth_tokens',
          JSON.stringify({
            access_token: 'mock-token',
            refresh_token: 'mock-refresh',
            expires_at: Date.now() + 3600000,
          }),
        );
        localStorage.setItem(
          'auth_user',
          JSON.stringify({ id: 'user-123', email: 'test@example.com' }),
        );
      });

      await page.goto('/billing');
      await aragoraPage.dismissAllOverlays();

      // Should show Free tier
      await expect(page.locator('text=/free|Free/i').first()).toBeVisible({ timeout: 10000 });
    });
  });

  test.describe('Plans Tab', () => {
    test('should display available plans', async ({ page, aragoraPage }) => {
      await mockApiResponse(page, '**/api/billing/usage', mockUsage);
      await mockApiResponse(page, '**/api/billing/subscription', mockSubscription);
      await mockApiResponse(page, '**/api/billing/invoices*', mockInvoices);
      await mockApiResponse(page, '**/api/billing/usage/forecast', mockForecast);
      await mockApiResponse(page, '**/api/billing/plans', mockPlans);

      await page.addInitScript(() => {
        localStorage.setItem(
          'auth_tokens',
          JSON.stringify({
            access_token: 'mock-token',
            refresh_token: 'mock-refresh',
            expires_at: Date.now() + 3600000,
          }),
        );
        localStorage.setItem(
          'auth_user',
          JSON.stringify({ id: 'user-123', email: 'test@example.com' }),
        );
      });

      await page.goto('/billing');
      await aragoraPage.dismissAllOverlays();

      // Click on Plans tab if available
      const plansTab = page.locator('text=Plans').first();
      if (await plansTab.isVisible()) {
        await plansTab.click();
      }

      // Should show plan options
      await expect(page.locator('text=/Enterprise|Pro|Business/i').first()).toBeVisible({
        timeout: 10000,
      });
    });
  });

  test.describe('Invoices Tab', () => {
    test('should display invoice history', async ({ page, aragoraPage }) => {
      await mockApiResponse(page, '**/api/billing/usage', mockUsage);
      await mockApiResponse(page, '**/api/billing/subscription', mockSubscription);
      await mockApiResponse(page, '**/api/billing/invoices*', mockInvoices);
      await mockApiResponse(page, '**/api/billing/usage/forecast', mockForecast);
      await mockApiResponse(page, '**/api/billing/plans', mockPlans);

      await page.addInitScript(() => {
        localStorage.setItem(
          'auth_tokens',
          JSON.stringify({
            access_token: 'mock-token',
            refresh_token: 'mock-refresh',
            expires_at: Date.now() + 3600000,
          }),
        );
        localStorage.setItem(
          'auth_user',
          JSON.stringify({ id: 'user-123', email: 'test@example.com' }),
        );
      });

      await page.goto('/billing');
      await aragoraPage.dismissAllOverlays();

      // Click on Invoices tab if available
      const invoicesTab = page.locator('text=Invoices').first();
      if (await invoicesTab.isVisible()) {
        await invoicesTab.click();

        // Should show invoice entries or "paid" status
        await expect(page.locator('text=/paid|\\$49/i').first()).toBeVisible({ timeout: 10000 });
      }
    });

    test('should show empty state when no invoices', async ({ page, aragoraPage }) => {
      await mockApiResponse(page, '**/api/billing/usage', mockUsage);
      await mockApiResponse(page, '**/api/billing/subscription', mockFreeSubscription);
      await mockApiResponse(page, '**/api/billing/invoices*', mockNoInvoices);
      await mockApiResponse(page, '**/api/billing/usage/forecast', mockForecast);
      await mockApiResponse(page, '**/api/billing/plans', mockPlans);

      await page.addInitScript(() => {
        localStorage.setItem(
          'auth_tokens',
          JSON.stringify({
            access_token: 'mock-token',
            refresh_token: 'mock-refresh',
            expires_at: Date.now() + 3600000,
          }),
        );
        localStorage.setItem(
          'auth_user',
          JSON.stringify({ id: 'user-123', email: 'test@example.com' }),
        );
      });

      await page.goto('/billing');
      await aragoraPage.dismissAllOverlays();

      // Click on Invoices tab if available
      const invoicesTab = page.locator('text=Invoices').first();
      if (await invoicesTab.isVisible()) {
        await invoicesTab.click();

        // Should show empty message or free tier indicator
        const hasNoInvoices = await page
          .locator('text=/no invoices|no billing history/i')
          .isVisible()
          .catch(() => false);
        const hasFreeIndicator = await page
          .locator('text=/free/i')
          .isVisible()
          .catch(() => false);
        expect(hasNoInvoices || hasFreeIndicator).toBe(true);
      }
    });
  });

  test.describe('Billing Actions', () => {
    test('should have manage billing button for paid users', async ({ page, aragoraPage }) => {
      await mockApiResponse(page, '**/api/billing/usage', mockUsage);
      await mockApiResponse(page, '**/api/billing/subscription', mockSubscription);
      await mockApiResponse(page, '**/api/billing/invoices*', mockInvoices);
      await mockApiResponse(page, '**/api/billing/usage/forecast', mockForecast);
      await mockApiResponse(page, '**/api/billing/plans', mockPlans);

      await page.addInitScript(() => {
        localStorage.setItem(
          'auth_tokens',
          JSON.stringify({
            access_token: 'mock-token',
            refresh_token: 'mock-refresh',
            expires_at: Date.now() + 3600000,
          }),
        );
        localStorage.setItem(
          'auth_user',
          JSON.stringify({ id: 'user-123', email: 'test@example.com' }),
        );
      });

      await page.goto('/billing');
      await aragoraPage.dismissAllOverlays();

      // Should have a manage/portal button
      const manageButton = page.locator('button:has-text(/manage|portal|billing settings/i)');
      await expect(manageButton).toBeVisible({ timeout: 10000 });
    });

    test('should call portal API when clicking manage billing', async ({ page, aragoraPage }) => {
      await mockApiResponse(page, '**/api/billing/usage', mockUsage);
      await mockApiResponse(page, '**/api/billing/subscription', mockSubscription);
      await mockApiResponse(page, '**/api/billing/invoices*', mockInvoices);
      await mockApiResponse(page, '**/api/billing/usage/forecast', mockForecast);
      await mockApiResponse(page, '**/api/billing/plans', mockPlans);

      // Mock the portal endpoint
      let portalCalled = false;
      await page.route('**/api/billing/portal', async (route) => {
        portalCalled = true;
        await route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify({ portal: { url: 'https://billing.stripe.com/session/test' } }),
        });
      });

      await page.addInitScript(() => {
        localStorage.setItem(
          'auth_tokens',
          JSON.stringify({
            access_token: 'mock-token',
            refresh_token: 'mock-refresh',
            expires_at: Date.now() + 3600000,
          }),
        );
        localStorage.setItem(
          'auth_user',
          JSON.stringify({ id: 'user-123', email: 'test@example.com' }),
        );
      });

      await page.goto('/billing');
      await aragoraPage.dismissAllOverlays();

      // Click manage billing button
      const manageButton = page.locator('button:has-text(/manage|portal/i)');
      if (await manageButton.isVisible()) {
        await manageButton.click();
        await page.waitForTimeout(500);
        expect(portalCalled).toBe(true);
      }
    });
  });
});

test.describe('Billing Success Page', () => {
  test('should display success message', async ({ page, aragoraPage }) => {
    await page.goto('/billing/success');
    await aragoraPage.dismissAllOverlays();

    // Should show success indication
    await expect(page.locator('text=/success|thank you|confirmed|complete/i').first()).toBeVisible({
      timeout: 10000,
    });
  });

  test('should have link back to billing', async ({ page, aragoraPage }) => {
    await page.goto('/billing/success');
    await aragoraPage.dismissAllOverlays();

    // Should have a link back to billing or dashboard
    const backLink = page.locator('a:has-text(/billing|dashboard|continue/i)').first();
    await expect(backLink).toBeVisible({ timeout: 10000 });
  });
});
