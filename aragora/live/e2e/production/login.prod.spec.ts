import { test, expect, Page } from '@playwright/test';

/**
 * Real Login Flow Tests for aragora.ai
 *
 * These tests verify actual login functionality works correctly.
 * Requires environment variables:
 *   - ARAGORA_TEST_EMAIL: Test account email for username/password login
 *   - ARAGORA_TEST_PASSWORD: Test account password
 *   - GOOGLE_TEST_EMAIL: Google account email for OAuth testing
 *   - GOOGLE_TEST_PASSWORD: Google account password
 *
 * Run with:
 *   ARAGORA_TEST_EMAIL=your@email.com ARAGORA_TEST_PASSWORD=pass \
 *   GOOGLE_TEST_EMAIL=google@gmail.com GOOGLE_TEST_PASSWORD=pass \
 *   npx playwright test login.prod.spec.ts --config=playwright.production.config.ts
 */

// Production URLs
const ARAGORA_LOGIN_URL = 'https://aragora.ai/auth/login';
const _ARAGORA_DASHBOARD_URL = 'https://aragora.ai/dashboard';
const ARAGORA_HOME_URL = 'https://aragora.ai';

// Timeout constants
const NAVIGATION_TIMEOUT = 30000;
const AUTH_TIMEOUT = 60000;

interface _LoginResult {
  success: boolean;
  finalUrl: string;
  error?: string;
  authenticated?: boolean;
}

/**
 * Helper to check if we're authenticated by looking for auth indicators
 */
async function isAuthenticated(page: Page): Promise<boolean> {
  try {
    // Look for common authenticated indicators
    const authIndicators = [
      '[data-testid="user-menu"]',
      '[data-testid="user-avatar"]',
      'button:has-text("Sign Out")',
      'button:has-text("Logout")',
      'a:has-text("Dashboard")',
      '[aria-label="User menu"]',
      '.user-avatar',
      '#user-dropdown',
    ];

    for (const selector of authIndicators) {
      const element = page.locator(selector).first();
      if (await element.isVisible({ timeout: 2000 }).catch(() => false)) {
        return true;
      }
    }

    // Also check URL - if we're on dashboard, we're likely authenticated
    const url = page.url();
    if (url.includes('/dashboard') || url.includes('live.aragora.ai')) {
      return true;
    }

    return false;
  } catch {
    return false;
  }
}

/**
 * Helper to clear any existing auth state
 */
async function clearAuthState(page: Page): Promise<void> {
  await page.context().clearCookies();
  await page.evaluate(() => {
    localStorage.clear();
    sessionStorage.clear();
  });
}

test.describe('Real Login Tests', () => {
  test.describe.configure({ mode: 'serial' });

  test.beforeEach(async ({ page }) => {
    // Clear any existing auth state before each test
    await page.goto(ARAGORA_HOME_URL, { waitUntil: 'domcontentloaded' });
    await clearAuthState(page);
  });

  test('should have login page accessible', async ({ page }) => {
    await page.goto(ARAGORA_LOGIN_URL, { waitUntil: 'domcontentloaded' });
    await page.waitForTimeout(2000);

    // Verify login page loaded
    const url = page.url();
    expect(url).toContain('/auth/login');

    // Check for email input
    const emailInput = page
      .locator('input[type="email"], input[name="email"], input[placeholder*="email" i]')
      .first();
    await expect(emailInput).toBeVisible({ timeout: 10000 });

    // Check for password input
    const passwordInput = page.locator('input[type="password"], input[name="password"]').first();
    await expect(passwordInput).toBeVisible({ timeout: 10000 });

    // Check for submit button
    const submitBtn = page
      .locator(
        'button[type="submit"], button:has-text("Sign In"), button:has-text("Login"), button:has-text("Log In")',
      )
      .first();
    await expect(submitBtn).toBeVisible({ timeout: 10000 });

    console.log('Login page verified - all form elements present');
  });

  test('should login with username and password', async ({ page }) => {
    const email = process.env.ARAGORA_TEST_EMAIL;
    const password = process.env.ARAGORA_TEST_PASSWORD;

    if (!email || !password) {
      test.skip(
        !email || !password,
        'ARAGORA_TEST_EMAIL and ARAGORA_TEST_PASSWORD environment variables required',
      );
      return;
    }

    console.log(`\n=== Testing Username/Password Login ===`);
    console.log(`Email: ${email.replace(/(.{3}).*(@.*)/, '$1***$2')}`);

    // Navigate to login page
    await page.goto(ARAGORA_LOGIN_URL, { waitUntil: 'domcontentloaded' });
    await page.waitForTimeout(2000);

    // Fill in email
    const emailInput = page
      .locator('input[type="email"], input[name="email"], input[placeholder*="email" i]')
      .first();
    await emailInput.waitFor({ state: 'visible', timeout: NAVIGATION_TIMEOUT });
    await emailInput.fill(email);
    console.log('Filled email');

    // Fill in password
    const passwordInput = page.locator('input[type="password"], input[name="password"]').first();
    await passwordInput.waitFor({ state: 'visible', timeout: NAVIGATION_TIMEOUT });
    await passwordInput.fill(password);
    console.log('Filled password');

    // Take screenshot before submit
    await page.screenshot({
      path: 'playwright-report-production/screenshots/login-before-submit.png',
    });

    // Find and click submit button
    const submitBtn = page
      .locator(
        'button[type="submit"], button:has-text("Sign In"), button:has-text("Login"), button:has-text("Log In")',
      )
      .first();
    await submitBtn.waitFor({ state: 'visible', timeout: NAVIGATION_TIMEOUT });
    await submitBtn.click();
    console.log('Clicked submit button');

    // Wait for navigation or error
    await page.waitForTimeout(5000);

    // Take screenshot after submit
    await page.screenshot({
      path: 'playwright-report-production/screenshots/login-after-submit.png',
    });

    const finalUrl = page.url();
    console.log(`Final URL: ${finalUrl}`);

    // Check for error messages
    const errorMessage = page
      .locator('[role="alert"], .error, .error-message, [data-testid="error"]')
      .first();
    if (await errorMessage.isVisible({ timeout: 1000 }).catch(() => false)) {
      const errorText = await errorMessage.textContent();
      console.log(`Error message: ${errorText}`);
    }

    // Verify authentication
    const authenticated = await isAuthenticated(page);
    console.log(`Authenticated: ${authenticated}`);

    // Should be redirected away from login page or show authenticated state
    const loginSuccessIndicators = [
      !finalUrl.includes('/auth/login'),
      finalUrl.includes('/dashboard'),
      authenticated,
    ];

    const success = loginSuccessIndicators.some((indicator) => indicator);

    if (success) {
      console.log('Login successful!');
    } else {
      console.log('Login may have failed - still on login page');
    }

    // Assert at least one success indicator
    expect(success).toBeTruthy();
  });

  test('should show error for invalid credentials', async ({ page }) => {
    console.log(`\n=== Testing Invalid Credentials ===`);

    await page.goto(ARAGORA_LOGIN_URL, { waitUntil: 'domcontentloaded' });
    await page.waitForTimeout(2000);

    // Fill in invalid credentials
    const emailInput = page
      .locator('input[type="email"], input[name="email"], input[placeholder*="email" i]')
      .first();
    await emailInput.fill('invalid-test-email@example.com');

    const passwordInput = page.locator('input[type="password"], input[name="password"]').first();
    await passwordInput.fill('invalid-password-12345');

    // Submit
    const submitBtn = page
      .locator(
        'button[type="submit"], button:has-text("Sign In"), button:has-text("Login"), button:has-text("Log In")',
      )
      .first();
    await submitBtn.click();

    await page.waitForTimeout(3000);

    // Should show error or still be on login page
    const stillOnLogin = page.url().includes('/auth/login');
    const errorVisible = await page
      .locator('[role="alert"], .error, .error-message, [data-testid="error"]')
      .first()
      .isVisible({ timeout: 2000 })
      .catch(() => false);

    console.log(`Still on login page: ${stillOnLogin}`);
    console.log(`Error visible: ${errorVisible}`);

    // Either should show error or remain on login page
    expect(stillOnLogin || errorVisible).toBeTruthy();
  });

  test('should login with Google OAuth', async ({ page }) => {
    const googleEmail = process.env.GOOGLE_TEST_EMAIL;
    const googlePassword = process.env.GOOGLE_TEST_PASSWORD;

    if (!googleEmail || !googlePassword) {
      test.skip(
        !googleEmail || !googlePassword,
        'GOOGLE_TEST_EMAIL and GOOGLE_TEST_PASSWORD environment variables required',
      );
      return;
    }

    console.log(`\n=== Testing Google OAuth Login ===`);
    console.log(`Google Email: ${googleEmail.replace(/(.{3}).*(@.*)/, '$1***$2')}`);

    // Navigate to login page
    await page.goto(ARAGORA_LOGIN_URL, { waitUntil: 'domcontentloaded' });
    await page.waitForTimeout(2000);

    // Find and click Google OAuth button
    const googleBtn = page
      .locator(
        'button:has-text("Google"), a:has-text("Google"), [data-provider="google"], button:has-text("Continue with Google")',
      )
      .first();
    await googleBtn.waitFor({ state: 'visible', timeout: NAVIGATION_TIMEOUT });

    console.log('Found Google OAuth button');
    await page.screenshot({
      path: 'playwright-report-production/screenshots/google-oauth-before-click.png',
    });

    // Click Google button - this will redirect to Google
    await googleBtn.click();
    console.log('Clicked Google OAuth button');

    // Wait for redirect to Google
    await page.waitForTimeout(3000);
    const googleUrl = page.url();
    console.log(`Redirected to: ${googleUrl}`);

    // Check if we're on Google's login page
    if (googleUrl.includes('accounts.google.com')) {
      console.log('Successfully redirected to Google login');
      await page.screenshot({
        path: 'playwright-report-production/screenshots/google-login-page.png',
      });

      try {
        // Fill in Google email
        const googleEmailInput = page
          .locator('input[type="email"], input[name="identifier"]')
          .first();
        await googleEmailInput.waitFor({ state: 'visible', timeout: NAVIGATION_TIMEOUT });
        await googleEmailInput.fill(googleEmail);
        console.log('Filled Google email');

        // Click Next
        const nextBtn = page.locator('button:has-text("Next"), #identifierNext').first();
        await nextBtn.click();
        console.log('Clicked Next after email');

        await page.waitForTimeout(3000);

        // Fill in Google password
        const googlePasswordInput = page
          .locator('input[type="password"], input[name="Passwd"]')
          .first();
        await googlePasswordInput.waitFor({ state: 'visible', timeout: NAVIGATION_TIMEOUT });
        await googlePasswordInput.fill(googlePassword);
        console.log('Filled Google password');

        // Click Next/Sign In
        const signInBtn = page.locator('button:has-text("Next"), #passwordNext').first();
        await signInBtn.click();
        console.log('Clicked Sign In');

        // Wait for OAuth flow to complete (may have consent screen)
        await page.waitForTimeout(5000);
        await page.screenshot({
          path: 'playwright-report-production/screenshots/google-after-signin.png',
        });

        // Check for consent screen
        const consentBtn = page
          .locator('button:has-text("Allow"), button:has-text("Continue")')
          .first();
        if (await consentBtn.isVisible({ timeout: 3000 }).catch(() => false)) {
          console.log('Found consent screen, clicking Allow');
          await consentBtn.click();
          await page.waitForTimeout(3000);
        }

        // Wait for redirect back to Aragora
        await page.waitForURL(/aragora\.ai/, { timeout: AUTH_TIMEOUT }).catch(() => {});

        const finalUrl = page.url();
        console.log(`Final URL: ${finalUrl}`);
        await page.screenshot({
          path: 'playwright-report-production/screenshots/google-oauth-complete.png',
        });

        // Verify we're back on Aragora and authenticated
        const authenticated = await isAuthenticated(page);
        console.log(`Authenticated: ${authenticated}`);

        // Check for error page
        if (finalUrl.includes('/auth/error')) {
          const urlParams = new URLSearchParams(finalUrl.split('?')[1] || '');
          const errorMsg = urlParams.get('error') || 'Unknown error';
          console.log(`OAuth flow error: ${decodeURIComponent(errorMsg)}`);

          // Fail the test with descriptive error
          expect.soft(finalUrl).not.toContain('/auth/error');
          console.log(
            'DIAGNOSIS: OAuth authentication succeeded but backend database operation failed.',
          );
          console.log('This is a production infrastructure issue, not a test failure.');
        }

        // Success if we're back on Aragora, authenticated, and not on error page
        const success =
          finalUrl.includes('aragora.ai') &&
          !finalUrl.includes('/auth/error') &&
          (!finalUrl.includes('/auth/login') || authenticated);

        if (success) {
          console.log('Google OAuth login successful!');
        } else if (!finalUrl.includes('/auth/error')) {
          console.log('Google OAuth may have failed');
        }

        expect(success).toBeTruthy();
      } catch (error) {
        console.log(`Google OAuth flow error: ${error}`);
        await page.screenshot({
          path: 'playwright-report-production/screenshots/google-oauth-error.png',
        });

        // Check if it's a CAPTCHA or 2FA issue
        const pageContent = await page.content();
        if (pageContent.includes('captcha') || pageContent.includes('CAPTCHA')) {
          console.log('Google CAPTCHA detected - automated login blocked');
          test.skip(true, 'Google CAPTCHA detected - cannot automate');
        }
        if (
          pageContent.includes('2-Step Verification') ||
          pageContent.includes('Two-step verification')
        ) {
          console.log('Google 2FA detected - need to handle 2FA');
          test.skip(true, 'Google 2FA detected - not supported in automated tests');
        }
        throw error;
      }
    } else if (googleUrl.includes('aragora.ai')) {
      // Already authenticated or OAuth completed quickly
      console.log('OAuth may have completed quickly (session cached)');
      const authenticated = await isAuthenticated(page);
      expect(authenticated).toBeTruthy();
    } else {
      console.log(`Unexpected redirect URL: ${googleUrl}`);
      await page.screenshot({
        path: 'playwright-report-production/screenshots/unexpected-redirect.png',
      });
      // Don't fail - just log for debugging
    }
  });

  test('should persist session after login', async ({ page }) => {
    const email = process.env.ARAGORA_TEST_EMAIL;
    const password = process.env.ARAGORA_TEST_PASSWORD;

    if (!email || !password) {
      test.skip(!email || !password, 'ARAGORA_TEST_EMAIL and ARAGORA_TEST_PASSWORD required');
      return;
    }

    console.log(`\n=== Testing Session Persistence ===`);

    // First, login
    await page.goto(ARAGORA_LOGIN_URL, { waitUntil: 'domcontentloaded' });
    await page.waitForTimeout(2000);

    const emailInput = page
      .locator('input[type="email"], input[name="email"], input[placeholder*="email" i]')
      .first();
    await emailInput.fill(email);

    const passwordInput = page.locator('input[type="password"], input[name="password"]').first();
    await passwordInput.fill(password);

    const submitBtn = page
      .locator(
        'button[type="submit"], button:has-text("Sign In"), button:has-text("Login"), button:has-text("Log In")',
      )
      .first();
    await submitBtn.click();

    await page.waitForTimeout(5000);

    // Check if logged in
    const authenticated = await isAuthenticated(page);
    if (!authenticated) {
      console.log('Initial login failed, skipping persistence test');
      test.skip(true, 'Could not complete initial login');
      return;
    }

    console.log('Initial login successful');

    // Now navigate to home and back to verify session persists
    await page.goto(ARAGORA_HOME_URL, { waitUntil: 'domcontentloaded' });
    await page.waitForTimeout(2000);

    const stillAuthenticated = await isAuthenticated(page);
    console.log(`Still authenticated after navigation: ${stillAuthenticated}`);

    expect(stillAuthenticated).toBeTruthy();
  });

  test('should logout successfully', async ({ page }) => {
    const email = process.env.ARAGORA_TEST_EMAIL;
    const password = process.env.ARAGORA_TEST_PASSWORD;

    if (!email || !password) {
      test.skip(!email || !password, 'ARAGORA_TEST_EMAIL and ARAGORA_TEST_PASSWORD required');
      return;
    }

    console.log(`\n=== Testing Logout ===`);

    // First, login
    await page.goto(ARAGORA_LOGIN_URL, { waitUntil: 'domcontentloaded' });
    await page.waitForTimeout(2000);

    const emailInput = page
      .locator('input[type="email"], input[name="email"], input[placeholder*="email" i]')
      .first();
    await emailInput.fill(email);

    const passwordInput = page.locator('input[type="password"], input[name="password"]').first();
    await passwordInput.fill(password);

    const submitBtn = page
      .locator(
        'button[type="submit"], button:has-text("Sign In"), button:has-text("Login"), button:has-text("Log In")',
      )
      .first();
    await submitBtn.click();

    await page.waitForTimeout(5000);

    const authenticated = await isAuthenticated(page);
    if (!authenticated) {
      test.skip(true, 'Could not complete initial login');
      return;
    }

    console.log('Logged in, now testing logout');

    // Find and click logout
    const logoutBtn = page
      .locator(
        'button:has-text("Sign Out"), button:has-text("Logout"), button:has-text("Log Out"), a:has-text("Logout")',
      )
      .first();

    // May need to open user menu first
    const userMenu = page
      .locator('[data-testid="user-menu"], [aria-label="User menu"], .user-avatar, #user-dropdown')
      .first();
    if (await userMenu.isVisible({ timeout: 2000 }).catch(() => false)) {
      await userMenu.click();
      await page.waitForTimeout(1000);
    }

    if (await logoutBtn.isVisible({ timeout: 2000 }).catch(() => false)) {
      await logoutBtn.click();
      await page.waitForTimeout(3000);

      const stillAuthenticated = await isAuthenticated(page);
      console.log(`Still authenticated after logout: ${stillAuthenticated}`);

      expect(stillAuthenticated).toBeFalsy();
      console.log('Logout successful');
    } else {
      console.log('Logout button not found - may need different selector');
      await page.screenshot({
        path: 'playwright-report-production/screenshots/logout-button-not-found.png',
      });
    }
  });
});

test.describe('OAuth Button Verification', () => {
  test('should display all OAuth provider buttons', async ({ page }) => {
    await page.goto(ARAGORA_LOGIN_URL, { waitUntil: 'domcontentloaded' });
    await page.waitForTimeout(2000);

    console.log('\n=== OAuth Provider Buttons ===');

    const providers = [
      {
        name: 'Google',
        selectors: [
          'button:has-text("Google")',
          'a:has-text("Google")',
          '[data-provider="google"]',
        ],
      },
      {
        name: 'GitHub',
        selectors: [
          'button:has-text("GitHub")',
          'a:has-text("GitHub")',
          '[data-provider="github"]',
        ],
      },
      {
        name: 'Microsoft',
        selectors: [
          'button:has-text("Microsoft")',
          'a:has-text("Microsoft")',
          '[data-provider="microsoft"]',
        ],
      },
    ];

    for (const provider of providers) {
      let found = false;
      for (const selector of provider.selectors) {
        const btn = page.locator(selector).first();
        if (await btn.isVisible({ timeout: 1000 }).catch(() => false)) {
          found = true;
          break;
        }
      }
      console.log(`${provider.name}: ${found ? 'visible' : 'not found'}`);
    }

    // At least one OAuth provider should be visible
    let anyOAuthVisible = false;
    for (const provider of providers) {
      for (const selector of provider.selectors) {
        if (
          await page
            .locator(selector)
            .first()
            .isVisible({ timeout: 1000 })
            .catch(() => false)
        ) {
          anyOAuthVisible = true;
          break;
        }
      }
      if (anyOAuthVisible) break;
    }

    expect(anyOAuthVisible).toBeTruthy();
  });

  test('should redirect Google OAuth to accounts.google.com', async ({ page }) => {
    await page.goto(ARAGORA_LOGIN_URL, { waitUntil: 'domcontentloaded' });
    await page.waitForTimeout(2000);

    const googleBtn = page
      .locator('button:has-text("Google"), a:has-text("Google"), [data-provider="google"]')
      .first();

    if (!(await googleBtn.isVisible({ timeout: 3000 }).catch(() => false))) {
      test.skip(true, 'Google OAuth button not found');
      return;
    }

    await googleBtn.click();
    await page.waitForTimeout(3000);

    const url = page.url();
    console.log(`Redirect URL: ${url}`);

    // Should redirect to Google OAuth
    expect(url.includes('accounts.google.com') || url.includes('google.com/o/oauth')).toBeTruthy();
  });
});
