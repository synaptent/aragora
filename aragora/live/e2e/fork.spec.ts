import { test, expect, mockApiResponse } from './fixtures';

const mockForkFamilies = {
  debates: [
    {
      id: 'test-debate',
      task: 'Test debate topic',
      agents: ['claude', 'gpt'],
      created_at: new Date().toISOString(),
    },
  ],
};

const mockForkTree = {
  forks: [
    {
      id: 'fork-1',
      parent_id: 'test-debate',
      debate_id: 'fork-1',
      branch_point: 2,
      status: 'completed',
      messages_inherited: 4,
      modified_context: 'What if pricing pressure forced a different constraint set?',
      created_at: new Date().toISOString(),
    },
    {
      id: 'fork-2',
      parent_id: 'test-debate',
      debate_id: 'fork-2',
      branch_point: 3,
      status: 'running',
      messages_inherited: 6,
      created_at: new Date(Date.now() - 3_600_000).toISOString(),
    },
  ],
};

test.describe('Fork Visualizer', () => {
  test.beforeEach(async ({ page, aragoraPage }) => {
    await mockApiResponse(page, '**/api/health', { status: 'ok' });
    await mockApiResponse(page, '**/api/debates?has_forks=true&limit=50', mockForkFamilies);
    await mockApiResponse(page, '**/api/debates/test-debate/fork-tree', mockForkTree);
    await page.goto('/forks');
    await aragoraPage.dismissAllOverlays();
    await page.waitForLoadState('domcontentloaded');
  });

  test('should display fork explorer section', async ({ page }) => {
    await expect(page.getByRole('heading', { name: /> FORK EXPLORER/i })).toBeVisible();
    await expect(page.getByText(/Browse counterfactual debate branches/i)).toBeVisible();
  });

  test('should show fork tree visualization', async ({ page }) => {
    await page.getByRole('button', { name: /Test debate topic/i }).click();
    await expect(page.getByText(/ROOT: Test debate topic/i)).toBeVisible();
    await expect(page.getByText(/Branch @ round 2/i)).toBeVisible();
    await expect(page.getByText(/Branch @ round 3/i)).toBeVisible();
  });

  test('should display fork count', async ({ page }) => {
    await expect(page.getByText(/2 forks/i)).toBeVisible();
  });

  test('should show fork status indicators', async ({ page }) => {
    await page.getByRole('button', { name: /Test debate topic/i }).click();
    await expect(page.getByText('completed')).toBeVisible();
    await expect(page.getByText('running')).toBeVisible();
  });

  test('should show fork metadata', async ({ page }) => {
    await page.getByRole('button', { name: /Test debate topic/i }).click();
    await expect(page.getByText(/messages inherited/i).first()).toBeVisible();
    await expect(
      page.getByText(/What if pricing pressure forced a different constraint set/i),
    ).toBeVisible();
  });
});

test.describe('Fork Visualizer - Empty State', () => {
  test('should show empty state when no forks', async ({ page, aragoraPage }) => {
    await mockApiResponse(page, '**/api/health', { status: 'ok' });
    await mockApiResponse(page, '**/api/debates?has_forks=true&limit=50', { debates: [] });

    await page.goto('/forks');
    await aragoraPage.dismissAllOverlays();

    await expect(page.getByText(/No forked debates found/i)).toBeVisible();
    await expect(page.getByRole('link', { name: /\[BROWSE DEBATES\]/i })).toBeVisible();
  });
});
