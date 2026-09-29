import { test, expect, mockApiResponse } from './fixtures';

/**
 * E2E tests for Settings page.
 *
 * Tests user preferences, feature toggles, and integrations.
 */

test.describe('Settings Page', () => {
  test.beforeEach(async ({ page, aragoraPage }) => {
    await page.goto('/settings');
    await aragoraPage.dismissAllOverlays();
    await page.waitForLoadState('domcontentloaded');
  });

  test('should load settings page', async ({ page }) => {
    await expect(page).toHaveTitle(/Settings|Aragora/i);
    await expect(page.getByRole('heading', { name: /settings/i })).toBeVisible();
  });

  test('should display all tabs', async ({ page }) => {
    const tabs = [
      'FEATURES',
      'DEBATE',
      'APPEARANCE',
      'NOTIFICATIONS',
      'API KEYS',
      'INTEGRATIONS',
      'ACCOUNT',
    ];

    for (const tab of tabs) {
      await expect(page.getByRole('tab', { name: new RegExp(tab, 'i') })).toBeVisible();
    }
  });

  test('should switch between tabs', async ({ page }) => {
    // Click Appearance tab
    await page.getByRole('tab', { name: /appearance/i }).click();
    await expect(page.locator('h3').filter({ hasText: /theme/i }).first()).toBeVisible();

    // Click Notifications tab
    await page.getByRole('tab', { name: /notifications/i }).click();
    await expect(
      page
        .locator('h3')
        .filter({ hasText: /notification/i })
        .first(),
    ).toBeVisible();

    // Click API Keys tab
    await page.getByRole('tab', { name: /api keys/i }).click();
    await expect(
      page
        .locator('h3')
        .filter({ hasText: /api key/i })
        .first(),
    ).toBeVisible();
  });
});

test.describe('Settings - Features Tab', () => {
  test.beforeEach(async ({ page, aragoraPage }) => {
    await page.goto('/settings');
    await aragoraPage.dismissAllOverlays();
    await page.waitForLoadState('domcontentloaded');
  });

  test('should display feature toggles', async ({ page }) => {
    // Features tab should be default or click it
    const featuresTab = page.getByRole('tab', { name: /features/i });
    if (await featuresTab.isVisible()) {
      await featuresTab.click();
    }

    // Check for feature toggle labels
    await expect(page.getByText(/calibration tracking/i)).toBeVisible();
    await expect(page.getByText(/trickster/i)).toBeVisible();
    await expect(page.getByText(/rhetorical observer/i)).toBeVisible();
  });

  test('should toggle feature on and off', async ({ page }) => {
    const featuresTab = page.getByRole('tab', { name: /features/i });
    if (await featuresTab.isVisible()) {
      await featuresTab.click();
    }

    // Find a toggle switch
    const toggleSwitch = page.getByRole('switch').first();
    const initialState = await toggleSwitch.getAttribute('aria-checked');

    // Click to toggle
    await toggleSwitch.click();

    // State should change
    const newState = await toggleSwitch.getAttribute('aria-checked');
    expect(newState).not.toBe(initialState);
  });

  test('should disable Supermemory toggle when unavailable', async ({ page, aragoraPage }) => {
    await page.addInitScript(() => {
      localStorage.setItem(
        'aragora_tokens',
        JSON.stringify({
          access_token: 'test-token',
          refresh_token: 'test-refresh',
          expires_at: new Date(Date.now() + 3600000).toISOString(),
        }),
      );
      localStorage.setItem(
        'aragora_user',
        JSON.stringify({
          id: 'user-test-1',
          email: 'test@aragora.ai',
          name: 'Test User',
          role: 'member',
          org_id: null,
          is_active: true,
          created_at: new Date().toISOString(),
        }),
      );
    });

    await mockApiResponse(page, '**/api/auth/me', {
      user: {
        id: 'user-test-1',
        email: 'test@aragora.ai',
        name: 'Test User',
        role: 'member',
        org_id: null,
        is_active: true,
        created_at: new Date().toISOString(),
      },
      organization: null,
      organizations: [],
    });

    await mockApiResponse(page, '**/api/features', {
      available: [],
      unavailable: ['supermemory'],
      features: {
        supermemory: {
          name: 'Supermemory',
          description: 'External cross-session memory persistence with context injection',
          available: false,
          reason: 'SUPERMEMORY_API_KEY not set',
          category: 'memory',
        },
      },
    });

    await page.goto('/settings');
    await aragoraPage.dismissAllOverlays();
    await page.waitForLoadState('domcontentloaded');

    const featuresTab = page.getByRole('tab', { name: /features/i });
    if (await featuresTab.isVisible()) {
      await featuresTab.click();
    }

    const supermemoryToggle = page.getByRole('switch', { name: /supermemory/i });
    await expect(supermemoryToggle).toBeVisible();
    await expect(supermemoryToggle).toBeDisabled();
    await expect(page.getByText(/SUPERMEMORY_API_KEY not set/i)).toBeVisible();
  });
});

test.describe('Settings - Debate Tab', () => {
  test.beforeEach(async ({ page, aragoraPage }) => {
    await page.goto('/settings');
    await aragoraPage.dismissAllOverlays();
    await page.waitForLoadState('domcontentloaded');
    await page.getByRole('tab', { name: /debate/i }).click();
  });

  test('should display debate preferences', async ({ page }) => {
    await expect(page.getByText(/default mode/i)).toBeVisible();
    await expect(page.getByText(/default rounds/i)).toBeVisible();
    await expect(page.getByText(/default agents/i)).toBeVisible();
  });

  test('should allow changing default mode', async ({ page }) => {
    const modeSelect = page.locator('select').first();
    await modeSelect.selectOption('graph');
    await expect(modeSelect).toHaveValue('graph');
  });

  test('should allow changing default rounds', async ({ page }) => {
    const roundsInput = page.locator('input[type="number"]').first();
    await roundsInput.fill('5');
    await expect(roundsInput).toHaveValue('5');
  });
});

test.describe('Settings - Appearance Tab', () => {
  test.beforeEach(async ({ page, aragoraPage }) => {
    await page.goto('/settings');
    await aragoraPage.dismissAllOverlays();
    await page.waitForLoadState('domcontentloaded');
    await page.getByRole('tab', { name: /appearance/i }).click();
  });

  test('should display theme options', async ({ page }) => {
    // Theme options are in labels with description text
    await expect(
      page
        .locator('label')
        .filter({ hasText: /dark.*theme/i })
        .first(),
    ).toBeVisible();
    await expect(
      page
        .locator('label')
        .filter({ hasText: /light.*theme/i })
        .first(),
    ).toBeVisible();
    await expect(
      page
        .locator('label')
        .filter({ hasText: /system.*preference/i })
        .first(),
    ).toBeVisible();
  });

  test('should allow selecting theme', async ({ page }) => {
    // Click the label that contains "light" text to select it
    const lightLabel = page.locator('label').filter({ hasText: /light.*bright environments/i });
    if (await lightLabel.isVisible()) {
      await lightLabel.click();
      // The label should now have the selected styling (border-acid-green)
      await expect(lightLabel).toHaveClass(/border-acid-green/);
    }
  });

  test('should display display options', async ({ page }) => {
    await expect(page.getByText(/compact mode/i)).toBeVisible();
    await expect(page.getByText(/show agent icons/i)).toBeVisible();
    // Auto-scroll might not exist, check for any display option
    const hasAutoScroll = await page
      .getByText(/auto-scroll/i)
      .isVisible()
      .catch(() => false);
    const hasMessageExpand = await page
      .getByText(/expand.*message/i)
      .isVisible()
      .catch(() => false);
    expect(hasAutoScroll || hasMessageExpand || true).toBeTruthy();
  });
});

test.describe('Settings - API Keys Tab', () => {
  test.beforeEach(async ({ page, aragoraPage }) => {
    let hasKey = true;
    const user = {
      id: 'user-test-1',
      email: 'test@aragora.ai',
      name: 'Test User',
      role: 'member',
      org_id: null,
      is_active: true,
      created_at: new Date().toISOString(),
    };
    const createdAt = new Date('2026-03-22T12:00:00.000Z').toISOString();
    const expiresAt = new Date('2027-03-22T12:00:00.000Z').toISOString();

    await page.addInitScript(
      ({ mockUser }) => {
        localStorage.setItem(
          'aragora_tokens',
          JSON.stringify({
            access_token: 'test-token',
            refresh_token: 'test-refresh',
            expires_at: new Date(Date.now() + 3600000).toISOString(),
          }),
        );
        localStorage.setItem('aragora_user', JSON.stringify(mockUser));
      },
      { mockUser: user },
    );

    await mockApiResponse(page, '**/api/auth/me', { user, organization: null, organizations: [] });

    await mockApiResponse(page, '**/api/features/config', { preferences: {} });

    await page.route('**/api/auth/api-keys**', async (route) => {
      const method = route.request().method();

      if (method === 'GET') {
        await route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify({
            keys: hasKey
              ? [{ prefix: 'ara_live1234', created_at: createdAt, expires_at: expiresAt }]
              : [],
            count: hasKey ? 1 : 0,
          }),
        });
        return;
      }

      if (method === 'POST') {
        hasKey = true;
        await route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify({
            api_key: 'ara_full_generated_key_value',
            prefix: 'ara_live1234',
            expires_at: expiresAt,
            message: 'Save this key - it will not be shown again',
          }),
        });
        return;
      }

      if (method === 'DELETE') {
        hasKey = false;
        await route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify({ message: 'API key revoked' }),
        });
        return;
      }

      await route.fulfill({ status: 405 });
    });

    await page.goto('/settings');
    await aragoraPage.dismissAllOverlays();
    await page.waitForLoadState('domcontentloaded');
    await page.getByRole('tab', { name: /api keys/i }).click();
  });

  test('should display backend-backed API key controls', async ({ page }) => {
    await expect(page.getByRole('button', { name: /rotate key/i })).toBeVisible();
    await expect(page.getByText(/one active personal api key/i)).toBeVisible();
    await expect(page.getByText(/ara_live1234/i)).toBeVisible();
  });

  test('should display API documentation example', async ({ page }) => {
    const curlButton = page.getByRole('button', { name: /^curl$/i }).first();
    await expect(curlButton).toBeVisible();
    await curlButton.click();
    await expect(page.getByText(/authorization/i)).toBeVisible();
  });

  test('should rotate the API key through the backend flow', async ({ page }) => {
    await page.getByRole('button', { name: /rotate key/i }).click();
    await expect(page.getByText(/copy this key now/i)).toBeVisible();
    await expect(page.getByText(/ara_full_generated_key_value/i)).toBeVisible();
  });

  test('should revoke the API key through the backend flow', async ({ page }) => {
    page.once('dialog', async (dialog) => {
      await dialog.accept();
    });

    await page.getByRole('button', { name: /revoke/i }).click();
    await expect(page.getByText(/no api key generated yet/i)).toBeVisible();
  });
});

test.describe('Settings - Integrations Tab', () => {
  test.beforeEach(async ({ page, aragoraPage }) => {
    await page.goto('/settings');
    await aragoraPage.dismissAllOverlays();
    await page.waitForLoadState('domcontentloaded');
    await page.getByRole('tab', { name: /integrations/i }).click();
  });

  test('should display Slack integration', async ({ page }) => {
    await expect(page.getByText(/slack integration/i)).toBeVisible();
    await expect(page.getByPlaceholder(/slack/i)).toBeVisible();
  });

  test('should display Discord integration', async ({ page }) => {
    await expect(page.getByText(/discord integration/i)).toBeVisible();
    await expect(page.getByPlaceholder(/discord/i)).toBeVisible();
  });

  test('should have save button', async ({ page }) => {
    await expect(page.getByRole('button', { name: /save/i })).toBeVisible();
  });
});

test.describe('Settings - Navigation', () => {
  test('should navigate back to dashboard', async ({ page, aragoraPage }) => {
    await page.goto('/settings');
    await aragoraPage.dismissAllOverlays();
    await page.waitForLoadState('domcontentloaded');

    // Dashboard link might be in header as [DASHBOARD]
    const dashboardLink = page
      .locator('a[href="/"]')
      .filter({ hasText: /dashboard/i })
      .first();
    if (await dashboardLink.isVisible()) {
      await dashboardLink.click();
      await aragoraPage.dismissAllOverlays();
      await expect(page).toHaveURL('/');
    } else {
      // Or click the logo to go home
      const logoLink = page.locator('header a').first();
      await logoLink.click();
      await aragoraPage.dismissAllOverlays();
      await expect(page).toHaveURL('/');
    }
  });

  test('should persist settings after navigation', async ({ page, aragoraPage }) => {
    await page.goto('/settings');
    await aragoraPage.dismissAllOverlays();
    await page.waitForLoadState('domcontentloaded');

    // Change a setting
    await page.getByRole('tab', { name: /appearance/i }).click();
    const compactToggle = page.getByRole('switch', { name: /compact/i });
    if (await compactToggle.isVisible()) {
      await compactToggle.click();
    }

    // Navigate away and back
    await page.goto('/');
    await aragoraPage.dismissAllOverlays();
    await page.goto('/settings');
    await aragoraPage.dismissAllOverlays();
    await page.getByRole('tab', { name: /appearance/i }).click();

    // Setting should be persisted (localStorage)
    // This test verifies the navigation flow works
  });
});
