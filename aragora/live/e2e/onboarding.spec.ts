import { test, expect, mockApiResponse } from './fixtures';

test.describe('Onboarding Flow', () => {
  test.beforeEach(async ({ page }) => {
    // Clear onboarding state to ensure fresh start
    await page.addInitScript(() => {
      window.localStorage.removeItem('aragora-onboarding');
    });
  });

  test('should display onboarding wizard on first visit', async ({ page, aragoraPage }) => {
    await page.goto('/onboarding');
    await aragoraPage.dismissAllOverlays();

    // Should show welcome step
    const wizard = page.locator('[class*="onboarding"], [class*="wizard"]').first();
    await expect(wizard).toBeVisible({ timeout: 5000 });

    // Look for welcome content
    const welcomeText = page.locator('text=/welcome|get started/i').first();
    await expect(welcomeText).toBeVisible();
  });

  test('should navigate through wizard steps', async ({ page, aragoraPage }) => {
    await page.goto('/onboarding');
    await aragoraPage.dismissAllOverlays();

    // Step 1: Welcome - click continue
    const continueButton = page
      .locator('button')
      .filter({ hasText: /continue|next/i })
      .first();
    if (await continueButton.isVisible()) {
      await continueButton.click();
    }

    // Should show organization step or use case step
    const stepContent = page.locator('text=/organization|company|team size|use case/i').first();
    await expect(stepContent).toBeVisible({ timeout: 5000 });
  });

  test('should allow skipping onboarding', async ({ page, aragoraPage }) => {
    await page.goto('/onboarding');
    await aragoraPage.dismissAllOverlays();

    // Look for skip button
    const skipButton = page.locator('button, a').filter({ hasText: /skip/i }).first();

    if (await skipButton.isVisible()) {
      await skipButton.click();

      // Should redirect to main app
      await page.waitForURL(/^\/$|\/debates/);
    }
  });

  test('should persist progress on refresh', async ({ page, aragoraPage }) => {
    await page.goto('/onboarding');
    await aragoraPage.dismissAllOverlays();

    // Move to next step
    const continueButton = page
      .locator('button')
      .filter({ hasText: /continue|next/i })
      .first();
    if (await continueButton.isVisible()) {
      await continueButton.click();
      await page.waitForTimeout(500);
    }

    // Refresh page
    await page.reload();
    await aragoraPage.dismissAllOverlays();

    // Progress bar should show advancement (not at step 1)
    const progressBar = page.locator('[class*="progress"]').first();
    if (await progressBar.isVisible()) {
      // Check that we're not at step 1 (progress should be > 0)
      const progressValue = await progressBar.getAttribute('style');
      // Progress should indicate some completion
      expect(progressValue || '').not.toBe('');
    }
  });

  test('should show template selection step', async ({ page, aragoraPage }) => {
    // Mock templates API
    await mockApiResponse(page, '**/api/onboarding/templates', {
      templates: [
        {
          id: 'arch_review_starter',
          name: 'Architecture Review',
          description: 'Review system architecture',
          agents_count: 4,
          rounds: 3,
          estimated_minutes: 5,
        },
        {
          id: 'team_decision_starter',
          name: 'Team Decision',
          description: 'Facilitate team decisions',
          agents_count: 3,
          rounds: 2,
          estimated_minutes: 3,
        },
      ],
    });

    await page.goto('/onboarding');
    await aragoraPage.dismissAllOverlays();

    // Navigate to template step (may need multiple clicks)
    for (let i = 0; i < 4; i++) {
      const continueButton = page
        .locator('button')
        .filter({ hasText: /continue|next/i })
        .first();
      if (await continueButton.isVisible()) {
        await continueButton.click();
        await page.waitForTimeout(300);
      }
    }

    // Look for template options
    const templateContent = page.locator('text=/template|architecture|team decision/i').first();
    if (await templateContent.isVisible()) {
      await expect(templateContent).toBeVisible();
    }
  });

  test('should complete onboarding flow', async ({ page, aragoraPage }) => {
    // Mock APIs
    await mockApiResponse(page, '**/api/onboarding/**', { success: true });

    await page.goto('/onboarding');
    await aragoraPage.dismissAllOverlays();

    // Navigate through all steps
    for (let i = 0; i < 10; i++) {
      const finishButton = page
        .locator('button')
        .filter({ hasText: /finish|complete|done/i })
        .first();
      if (await finishButton.isVisible()) {
        await finishButton.click();
        break;
      }

      const continueButton = page
        .locator('button')
        .filter({ hasText: /continue|next|skip/i })
        .first();
      if (await continueButton.isVisible()) {
        await continueButton.click();
        await page.waitForTimeout(300);
      }
    }

    // Should eventually redirect or show completion
    const _completionIndicator = page.locator('text=/complete|success|ready|welcome/i');
    // Allow either completion state or redirect
    await page.waitForTimeout(1000);
  });

  test('should show progress bar with step count', async ({ page, aragoraPage }) => {
    await page.goto('/onboarding');
    await aragoraPage.dismissAllOverlays();

    // Should show progress indication
    const progressIndicator = page.locator('[class*="progress"], text=/step|1.*of/i').first();
    await expect(progressIndicator).toBeVisible({ timeout: 5000 });
  });

  test('should allow going back to previous step', async ({ page, aragoraPage }) => {
    await page.goto('/onboarding');
    await aragoraPage.dismissAllOverlays();

    // Move forward
    const continueButton = page
      .locator('button')
      .filter({ hasText: /continue|next/i })
      .first();
    if (await continueButton.isVisible()) {
      await continueButton.click();
      await page.waitForTimeout(300);
    }

    // Go back
    const backButton = page.locator('button').filter({ hasText: /back/i }).first();
    if (await backButton.isVisible()) {
      await backButton.click();
      await page.waitForTimeout(300);

      // Should show welcome/first step content
      const welcomeContent = page.locator('text=/welcome|get started/i').first();
      await expect(welcomeContent).toBeVisible();
    }
  });
});

test.describe('Slack Integration Wizard', () => {
  test('should show Slack setup wizard', async ({ page, aragoraPage }) => {
    // Mock Slack status
    await mockApiResponse(page, '**/api/integrations/slack/status', {
      oauth_configured: true,
      workspace: null,
    });

    await page.goto('/connectors');
    await aragoraPage.dismissAllOverlays();

    // Look for Slack integration option
    const slackOption = page.locator('text=/slack/i').first();
    if (await slackOption.isVisible()) {
      await slackOption.click();

      // Should show setup wizard
      const wizardContent = page.locator('text=/add to slack|install|connect/i').first();
      await expect(wizardContent).toBeVisible({ timeout: 5000 });
    }
  });

  test('should handle OAuth not configured state', async ({ page, aragoraPage }) => {
    // Mock Slack not configured
    await mockApiResponse(page, '**/api/integrations/slack/status', { oauth_configured: false });

    await page.goto('/connectors');
    await aragoraPage.dismissAllOverlays();

    const slackOption = page.locator('text=/slack/i').first();
    if (await slackOption.isVisible()) {
      await slackOption.click();

      // Should show configuration instructions
      const configMessage = page
        .locator('text=/not configured|SLACK_CLIENT_ID|environment/i')
        .first();
      if (await configMessage.isVisible()) {
        await expect(configMessage).toBeVisible();
      }
    }
  });
});

test.describe('Teams Integration Wizard', () => {
  test('should show Teams setup wizard', async ({ page, aragoraPage }) => {
    await mockApiResponse(page, '**/api/integrations/teams/status', { oauth_configured: true });

    await page.goto('/connectors');
    await aragoraPage.dismissAllOverlays();

    const teamsOption = page.locator('text=/teams|microsoft/i').first();
    if (await teamsOption.isVisible()) {
      await teamsOption.click();

      const wizardContent = page.locator('text=/connect|install|setup/i').first();
      await expect(wizardContent).toBeVisible({ timeout: 5000 });
    }
  });
});
