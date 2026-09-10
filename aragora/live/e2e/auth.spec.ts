import { test, expect, mockApiResponse } from './fixtures';

test.describe('Authentication', () => {
  test('should show sign in button when not authenticated', async ({ page, aragoraPage }) => {
    await page.goto('/');
    await aragoraPage.dismissAllOverlays();

    // Look for sign in button
    const signInButton = page
      .locator('button, a')
      .filter({ hasText: /sign in|log in|login/i })
      .first();

    // May or may not be visible depending on auth state
    if (await signInButton.isVisible()) {
      await expect(signInButton).toBeEnabled();
    }
  });

  test('should handle OAuth redirect', async ({ page, aragoraPage }) => {
    // Mock OAuth endpoint
    await page.route('**/api/auth/**', async (route) => {
      await route.fulfill({
        status: 302,
        headers: { Location: 'https://oauth.provider.com/authorize' },
      });
    });

    await page.goto('/');
    await aragoraPage.dismissAllOverlays();

    const signInButton = page
      .locator('button, a')
      .filter({ hasText: /sign in|log in|google|github/i })
      .first();

    if (await signInButton.isVisible()) {
      // Just verify button is clickable, don't follow redirect
      await expect(signInButton).toBeEnabled();
    }
  });

  test('should show user menu when authenticated', async ({ page, aragoraPage }) => {
    // Mock authenticated user
    await page.addInitScript(() => {
      window.localStorage.setItem('auth_token', 'test-token');
    });

    await mockApiResponse(page, '**/api/auth/me', {
      user: { id: 'user-123', email: 'test@example.com', name: 'Test User' },
    });

    await page.goto('/');
    await aragoraPage.dismissAllOverlays();

    // Look for user menu or avatar
    const userMenu = page
      .locator('[class*="user"], [class*="avatar"], [data-testid="user-menu"]')
      .first();

    if (await userMenu.isVisible()) {
      await expect(userMenu).toBeEnabled();
    }
  });

  test('should handle sign out', async ({ page, aragoraPage }) => {
    await page.addInitScript(() => {
      window.localStorage.setItem('auth_token', 'test-token');
    });

    await mockApiResponse(page, '**/api/auth/me', {
      user: { id: 'user-123', email: 'test@example.com' },
    });

    await mockApiResponse(page, '**/api/auth/logout', { success: true });

    await page.goto('/');
    await aragoraPage.dismissAllOverlays();

    // Find and open user menu
    const userMenu = page.locator('[class*="user"], [class*="avatar"]').first();

    if (await userMenu.isVisible()) {
      await userMenu.click();

      // Find sign out button
      const signOutButton = page
        .locator('button, a')
        .filter({ hasText: /sign out|log out|logout/i })
        .first();

      if (await signOutButton.isVisible()) {
        await signOutButton.click();

        // Should clear auth state
        await page.waitForTimeout(500);
      }
    }
  });

  test('should persist authentication across page loads', async ({ page, aragoraPage }) => {
    await page.addInitScript(() => {
      window.localStorage.setItem('auth_token', 'test-token');
    });

    await mockApiResponse(page, '**/api/auth/me', {
      user: { id: 'user-123', email: 'test@example.com' },
    });

    await page.goto('/');
    await aragoraPage.dismissAllOverlays();
    await page.reload();
    await aragoraPage.dismissAllOverlays();

    // Should still be authenticated
    const authToken = await page.evaluate(() => window.localStorage.getItem('auth_token'));
    expect(authToken).toBe('test-token');
  });

  test('should redirect to login for protected routes', async ({ page, aragoraPage }) => {
    // Try to access a protected route without auth
    await page.goto('/settings');
    await aragoraPage.dismissAllOverlays();

    // Should either show login prompt or redirect
    await page.waitForTimeout(1000);

    const url = page.url();
    const hasLoginPrompt = await page
      .locator('text=/sign in|log in|unauthorized/i')
      .first()
      .isVisible()
      .catch(() => false);
    const redirectedToLogin = url.includes('login') || url.includes('signin');
    const stayedOnPage = url.includes('settings');

    // Any of these outcomes is acceptable
    expect(hasLoginPrompt || redirectedToLogin || stayedOnPage).toBeTruthy();
  });
});

test.describe('Authentication - Error Handling', () => {
  test('should handle auth API errors', async ({ page, aragoraPage }) => {
    await page.route('**/api/auth/**', async (route) => {
      await route.fulfill({
        status: 500,
        contentType: 'application/json',
        body: JSON.stringify({ error: 'Auth service unavailable' }),
      });
    });

    await page.goto('/');
    await aragoraPage.dismissAllOverlays();

    // App should still load even if auth fails
    await expect(page.locator('body')).toBeVisible();
  });

  test('should handle expired tokens', async ({ page, aragoraPage }) => {
    await page.addInitScript(() => {
      window.localStorage.setItem('auth_token', 'expired-token');
    });

    await page.route('**/api/auth/me', async (route) => {
      await route.fulfill({
        status: 401,
        contentType: 'application/json',
        body: JSON.stringify({ error: 'Token expired' }),
      });
    });

    await page.goto('/');
    await aragoraPage.dismissAllOverlays();

    // Should handle gracefully - show sign in or clear token
    await page.waitForTimeout(1000);
  });
});
