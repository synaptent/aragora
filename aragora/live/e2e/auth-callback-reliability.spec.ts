import { test, expect } from '@playwright/test';

const RETURN_URL_STORAGE_KEY = 'aragora_return_url';

function makeToken(label: string): string {
  return `test.${label}.token`;
}

test.describe('Auth Callback Reliability', () => {
  test('restores return URL after successful OAuth callback token exchange', async ({ page }) => {
    const returnUrl = '/debates?source=e2e-callback';

    await page.goto('/', { waitUntil: 'domcontentloaded' });
    await page.evaluate(
      ({ storageKey, value }) => {
        sessionStorage.setItem(storageKey, value);
      },
      { storageKey: RETURN_URL_STORAGE_KEY, value: returnUrl },
    );

    await page.route('**/api/auth/me', async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          user: {
            id: 'user-e2e-1',
            email: 'e2e@aragora.ai',
            name: 'E2E User',
            role: 'member',
            org_id: null,
            is_active: true,
            created_at: '2026-01-01T00:00:00.000Z',
          },
          organization: null,
          organizations: [],
        }),
      });
    });

    const callbackUrl = `/auth/callback/#access_token=${makeToken('access')}&refresh_token=${makeToken('refresh')}&expires_in=3600`;
    await page.goto(callbackUrl, { waitUntil: 'domcontentloaded' });

    await expect
      .poll(() => page.url().includes('/auth/callback'), {
        timeout: 10_000,
        message:
          'OAuth callback should redirect away from /auth/callback after successful token exchange',
      })
      .toBe(false);

    const storedTokens = await page.evaluate(() => localStorage.getItem('aragora_tokens'));
    const storedUser = await page.evaluate(() => localStorage.getItem('aragora_user'));

    expect(storedTokens).toBeTruthy();
    expect(storedUser).toBeTruthy();
  });

  test('surfaces callback failure instead of hanging when token validation fails', async ({
    page,
  }) => {
    await page.route('**/api/auth/me', async (route) => {
      await route.fulfill({
        status: 401,
        contentType: 'application/json',
        body: JSON.stringify({ error: 'invalid token' }),
      });
    });

    const callbackUrl = `/auth/callback/#access_token=${makeToken('bad-access')}&refresh_token=${makeToken('bad-refresh')}&expires_in=3600`;
    await page.goto(callbackUrl, { waitUntil: 'domcontentloaded' });

    await expect(page.getByText('AUTHENTICATION FAILED')).toBeVisible({ timeout: 8_000 });
    await expect(
      page.getByText('OAuth tokens were rejected by the server. Please try logging in again.'),
    ).toBeVisible({ timeout: 8_000 });
  });
});
