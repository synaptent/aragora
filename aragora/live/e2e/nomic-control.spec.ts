import { test, expect, mockApiResponse } from './fixtures';

/**
 * E2E tests for Nomic Loop Control functionality.
 *
 * Tests the nomic-control dashboard including:
 * - Loop status display (running, paused, stopped)
 * - Phase progress visualization
 * - Control actions (start, stop, pause, resume, skip)
 * - Proposal approval/rejection
 * - WebSocket connection status
 * - Metrics display
 */

// Mock nomic state data
const mockStateNotRunning = {
  running: false,
  paused: false,
  cycle: 0,
  phase: 'not_running',
  target_cycles: 0,
};

const mockStateRunning = {
  running: true,
  paused: false,
  cycle: 2,
  phase: 'debate',
  started_at: new Date().toISOString(),
  target_cycles: 3,
  pid: 12345,
};

const mockStatePaused = {
  running: true,
  paused: true,
  cycle: 2,
  phase: 'design',
  started_at: new Date().toISOString(),
  target_cycles: 3,
  pid: 12345,
};

// Mock health data
const mockHealthNotRunning = { status: 'not_running', cycle: 0, phase: 'unknown', warnings: [] };

const mockHealthHealthy = {
  status: 'healthy',
  cycle: 2,
  phase: 'debate',
  last_activity: new Date().toISOString(),
  warnings: [],
};

const mockHealthStalled = {
  status: 'stalled',
  cycle: 2,
  phase: 'implement',
  last_activity: new Date(Date.now() - 300000).toISOString(),
  stall_duration_seconds: 300,
  warnings: ['Loop appears to be stalled'],
};

// Mock proposals
const mockProposals = {
  proposals: [
    {
      id: 'proposal-1',
      title: 'Improve error handling',
      description: 'Add better error handling to the debate orchestrator.',
      status: 'pending',
      created_at: new Date().toISOString(),
      category: 'design',
      risk_level: 'low',
    },
    {
      id: 'proposal-2',
      title: 'Optimize memory usage',
      description: 'Reduce memory footprint of the continuum memory system.',
      status: 'pending',
      created_at: new Date().toISOString(),
      category: 'implement',
      risk_level: 'medium',
    },
  ],
};

const mockNoProposals = { proposals: [] };

// Mock logs
const mockLogs = {
  lines: [
    '[2026-01-18 10:00:00] Starting nomic loop cycle 2',
    '[2026-01-18 10:00:05] Phase: context - gathering codebase information',
    '[2026-01-18 10:00:30] Phase: debate - agents discussing improvements',
  ],
  total: 100,
  showing: 3,
};

test.describe('Nomic Control Page', () => {
  test.describe('Page Load and Navigation', () => {
    test('should load nomic control page', async ({ page, aragoraPage }) => {
      await page.goto('/nomic-control');
      await aragoraPage.dismissAllOverlays();

      // Page should load successfully
      await expect(page).toHaveURL(/\/nomic-control/);
      await expect(page.locator('body')).toBeVisible();
    });

    test('should display page header', async ({ page, aragoraPage }) => {
      await mockApiResponse(page, '**/api/nomic/state', mockStateNotRunning);
      await mockApiResponse(page, '**/api/nomic/health', mockHealthNotRunning);
      await mockApiResponse(page, '**/api/nomic/proposals', mockNoProposals);

      await page.goto('/nomic-control');
      await aragoraPage.dismissAllOverlays();

      // Should show the page title
      await expect(page.locator('h1:has-text("Nomic Loop Control")')).toBeVisible();
    });

    test('should have link to control plane', async ({ page, aragoraPage }) => {
      await mockApiResponse(page, '**/api/nomic/state', mockStateNotRunning);
      await mockApiResponse(page, '**/api/nomic/health', mockHealthNotRunning);
      await mockApiResponse(page, '**/api/nomic/proposals', mockNoProposals);

      await page.goto('/nomic-control');
      await aragoraPage.dismissAllOverlays();

      // Should have control plane link (case insensitive)
      const controlPlaneLink = page.locator('a[href="/control-plane"]').first();
      await expect(controlPlaneLink).toBeVisible({ timeout: 10000 });
    });
  });

  test.describe('Loop Status Display', () => {
    test('should display not running status when loop is stopped', async ({
      page,
      aragoraPage,
    }) => {
      await mockApiResponse(page, '**/api/nomic/state', mockStateNotRunning);
      await mockApiResponse(page, '**/api/nomic/health', mockHealthNotRunning);
      await mockApiResponse(page, '**/api/nomic/proposals', mockNoProposals);

      await page.goto('/nomic-control');
      await aragoraPage.dismissAllOverlays();

      // Should show not running status (case insensitive)
      await expect(page.locator('text=/not.?running/i').first()).toBeVisible({ timeout: 10000 });
    });

    test('should display healthy status when loop is running', async ({ page, aragoraPage }) => {
      await mockApiResponse(page, '**/api/nomic/state', mockStateRunning);
      await mockApiResponse(page, '**/api/nomic/health', mockHealthHealthy);
      await mockApiResponse(page, '**/api/nomic/proposals', mockNoProposals);

      await page.goto('/nomic-control');
      await aragoraPage.dismissAllOverlays();

      // Should show healthy status
      await expect(page.locator('text=healthy').first()).toBeVisible();
    });

    test('should display stalled warning when loop is stalled', async ({ page, aragoraPage }) => {
      await mockApiResponse(page, '**/api/nomic/state', mockStateRunning);
      await mockApiResponse(page, '**/api/nomic/health', mockHealthStalled);
      await mockApiResponse(page, '**/api/nomic/proposals', mockNoProposals);

      await page.goto('/nomic-control');
      await aragoraPage.dismissAllOverlays();

      // Should show stalled status
      await expect(page.locator('text=stalled').first()).toBeVisible();
      // Should show warning message
      await expect(page.locator('text=Loop appears to be stalled')).toBeVisible();
    });

    test('should display phase progress bar', async ({ page, aragoraPage }) => {
      await mockApiResponse(page, '**/api/nomic/state', mockStateRunning);
      await mockApiResponse(page, '**/api/nomic/health', mockHealthHealthy);
      await mockApiResponse(page, '**/api/nomic/proposals', mockNoProposals);

      await page.goto('/nomic-control');
      await aragoraPage.dismissAllOverlays();

      // Should show phase names (case insensitive)
      await expect(page.locator('text=/context/i').first()).toBeVisible({ timeout: 10000 });
      await expect(page.locator('text=/debate/i').first()).toBeVisible();
      await expect(page.locator('text=/design/i').first()).toBeVisible();
      await expect(page.locator('text=/implement/i').first()).toBeVisible();
      await expect(page.locator('text=/verify/i').first()).toBeVisible();
    });
  });

  test.describe('Control Actions', () => {
    test('should show start button when loop is not running', async ({ page, aragoraPage }) => {
      await mockApiResponse(page, '**/api/nomic/state', mockStateNotRunning);
      await mockApiResponse(page, '**/api/nomic/health', mockHealthNotRunning);
      await mockApiResponse(page, '**/api/nomic/proposals', mockNoProposals);

      await page.goto('/nomic-control');
      await aragoraPage.dismissAllOverlays();

      // Should show start button
      await expect(page.locator('button:has-text("Start Loop")')).toBeVisible();
    });

    test('should show cycle count input when not running', async ({ page, aragoraPage }) => {
      await mockApiResponse(page, '**/api/nomic/state', mockStateNotRunning);
      await mockApiResponse(page, '**/api/nomic/health', mockHealthNotRunning);
      await mockApiResponse(page, '**/api/nomic/proposals', mockNoProposals);

      await page.goto('/nomic-control');
      await aragoraPage.dismissAllOverlays();

      // Should show cycle count input
      const cycleInput = page.locator('input[type="number"]');
      await expect(cycleInput).toBeVisible();
    });

    test('should show auto-approve checkbox when not running', async ({ page, aragoraPage }) => {
      await mockApiResponse(page, '**/api/nomic/state', mockStateNotRunning);
      await mockApiResponse(page, '**/api/nomic/health', mockHealthNotRunning);
      await mockApiResponse(page, '**/api/nomic/proposals', mockNoProposals);

      await page.goto('/nomic-control');
      await aragoraPage.dismissAllOverlays();

      // Should show auto-approve checkbox
      await expect(page.locator('text=Auto-approve')).toBeVisible();
    });

    test('should show pause and stop buttons when loop is running', async ({
      page,
      aragoraPage,
    }) => {
      await mockApiResponse(page, '**/api/nomic/state', mockStateRunning);
      await mockApiResponse(page, '**/api/nomic/health', mockHealthHealthy);
      await mockApiResponse(page, '**/api/nomic/proposals', mockNoProposals);

      await page.goto('/nomic-control');
      await aragoraPage.dismissAllOverlays();

      // Should show pause and stop buttons
      await expect(page.locator('button:has-text("Pause")')).toBeVisible();
      await expect(page.locator('button:has-text("Stop")')).toBeVisible();
      await expect(page.locator('button:has-text("Skip Phase")')).toBeVisible();
    });

    test('should show resume button when loop is paused', async ({ page, aragoraPage }) => {
      await mockApiResponse(page, '**/api/nomic/state', mockStatePaused);
      await mockApiResponse(page, '**/api/nomic/health', mockHealthHealthy);
      await mockApiResponse(page, '**/api/nomic/proposals', mockNoProposals);

      await page.goto('/nomic-control');
      await aragoraPage.dismissAllOverlays();

      // Should show resume button instead of pause
      await expect(page.locator('button:has-text("Resume")')).toBeVisible();
      await expect(page.locator('button:has-text("Pause")')).not.toBeVisible();
    });
  });

  test.describe('Proposals', () => {
    test('should display pending proposals', async ({ page, aragoraPage }) => {
      await mockApiResponse(page, '**/api/nomic/state', mockStateRunning);
      await mockApiResponse(page, '**/api/nomic/health', mockHealthHealthy);
      await mockApiResponse(page, '**/api/nomic/proposals', mockProposals);

      await page.goto('/nomic-control');
      await aragoraPage.dismissAllOverlays();

      // Should show proposals section
      await expect(page.locator('text=Pending Proposals')).toBeVisible();
      // Should show proposal count
      await expect(page.locator('text=2 pending')).toBeVisible();
    });

    test('should display proposal details', async ({ page, aragoraPage }) => {
      await mockApiResponse(page, '**/api/nomic/state', mockStateRunning);
      await mockApiResponse(page, '**/api/nomic/health', mockHealthHealthy);
      await mockApiResponse(page, '**/api/nomic/proposals', mockProposals);

      await page.goto('/nomic-control');
      await aragoraPage.dismissAllOverlays();

      // Should show proposal titles
      await expect(page.locator('text=Improve error handling')).toBeVisible();
      await expect(page.locator('text=Optimize memory usage')).toBeVisible();
    });

    test('should show approve and reject buttons for each proposal', async ({
      page,
      aragoraPage,
    }) => {
      await mockApiResponse(page, '**/api/nomic/state', mockStateRunning);
      await mockApiResponse(page, '**/api/nomic/health', mockHealthHealthy);
      await mockApiResponse(page, '**/api/nomic/proposals', mockProposals);

      await page.goto('/nomic-control');
      await aragoraPage.dismissAllOverlays();

      // Should have approve/reject buttons (2 of each for 2 proposals)
      const approveButtons = page.locator('button:has-text("Approve")');
      const rejectButtons = page.locator('button:has-text("Reject")');
      await expect(approveButtons).toHaveCount(2);
      await expect(rejectButtons).toHaveCount(2);
    });

    test('should show empty state when no proposals', async ({ page, aragoraPage }) => {
      await mockApiResponse(page, '**/api/nomic/state', mockStateNotRunning);
      await mockApiResponse(page, '**/api/nomic/health', mockHealthNotRunning);
      await mockApiResponse(page, '**/api/nomic/proposals', mockNoProposals);

      await page.goto('/nomic-control');
      await aragoraPage.dismissAllOverlays();

      // Should show empty message
      await expect(page.locator('text=No pending proposals')).toBeVisible();
    });
  });

  test.describe('Metrics', () => {
    test('should display cycle metrics', async ({ page, aragoraPage }) => {
      await mockApiResponse(page, '**/api/nomic/state', mockStateRunning);
      await mockApiResponse(page, '**/api/nomic/health', mockHealthHealthy);
      await mockApiResponse(page, '**/api/nomic/proposals', mockNoProposals);

      await page.goto('/nomic-control');
      await aragoraPage.dismissAllOverlays();

      // Should show metrics section
      await expect(page.locator('text=Cycle Metrics')).toBeVisible();
      // Should show current cycle
      await expect(page.locator('text=Current Cycle')).toBeVisible();
      // Should show target cycles
      await expect(page.locator('text=Target Cycles')).toBeVisible();
    });
  });

  test.describe('Logs', () => {
    test('should toggle logs visibility', async ({ page, aragoraPage }) => {
      await mockApiResponse(page, '**/api/nomic/state', mockStateNotRunning);
      await mockApiResponse(page, '**/api/nomic/health', mockHealthNotRunning);
      await mockApiResponse(page, '**/api/nomic/proposals', mockNoProposals);
      await mockApiResponse(page, '**/api/nomic/log*', mockLogs);

      await page.goto('/nomic-control');
      await aragoraPage.dismissAllOverlays();

      // Should have logs section with toggle
      await expect(page.locator('text=Loop Logs')).toBeVisible();

      // Click to show logs
      await page.locator('text=[SHOW]').click();

      // Should now show logs content (wait for fetch)
      await page.waitForTimeout(500);
      await expect(page.locator('text=[HIDE]')).toBeVisible();
    });
  });

  test.describe('WebSocket Connection', () => {
    test('should show connection status indicator', async ({ page, aragoraPage }) => {
      await mockApiResponse(page, '**/api/nomic/state', mockStateNotRunning);
      await mockApiResponse(page, '**/api/nomic/health', mockHealthNotRunning);
      await mockApiResponse(page, '**/api/nomic/proposals', mockNoProposals);

      await page.goto('/nomic-control');
      await aragoraPage.dismissAllOverlays();

      // Should show connection status (either WS LIVE or POLLING)
      const wsLive = page.locator('text=WS LIVE');
      const polling = page.locator('text=POLLING');

      // One of these should be visible
      const wsVisible = await wsLive.isVisible().catch(() => false);
      const pollVisible = await polling.isVisible().catch(() => false);
      expect(wsVisible || pollVisible).toBe(true);
    });
  });

  test.describe('Quick Links', () => {
    test('should display quick links section', async ({ page, aragoraPage }) => {
      await mockApiResponse(page, '**/api/nomic/state', mockStateNotRunning);
      await mockApiResponse(page, '**/api/nomic/health', mockHealthNotRunning);
      await mockApiResponse(page, '**/api/nomic/proposals', mockNoProposals);

      await page.goto('/nomic-control');
      await aragoraPage.dismissAllOverlays();

      // Should show quick links
      await expect(page.locator('text=Quick Links')).toBeVisible();
      await expect(page.locator('text=> Admin Dashboard')).toBeVisible();
      await expect(page.locator('text=> Control Plane')).toBeVisible();
      await expect(page.locator('text=> Debates History')).toBeVisible();
    });
  });

  test.describe('Control Actions - API Calls', () => {
    test('should call start API when clicking start button', async ({ page, aragoraPage }) => {
      await mockApiResponse(page, '**/api/nomic/state', mockStateNotRunning);
      await mockApiResponse(page, '**/api/nomic/health', mockHealthNotRunning);
      await mockApiResponse(page, '**/api/nomic/proposals', mockNoProposals);

      // Mock the start endpoint
      let startCalled = false;
      await page.route('**/api/nomic/control/start', async (route) => {
        startCalled = true;
        await route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify({ status: 'started' }),
        });
      });

      await page.goto('/nomic-control');
      await aragoraPage.dismissAllOverlays();

      // Click start button
      await page.locator('button:has-text("Start Loop")').click();

      // Wait for API call
      await page.waitForTimeout(500);
      expect(startCalled).toBe(true);
    });

    test('should call stop API when clicking stop button', async ({ page, aragoraPage }) => {
      await mockApiResponse(page, '**/api/nomic/state', mockStateRunning);
      await mockApiResponse(page, '**/api/nomic/health', mockHealthHealthy);
      await mockApiResponse(page, '**/api/nomic/proposals', mockNoProposals);

      // Mock the stop endpoint
      let stopCalled = false;
      await page.route('**/api/nomic/control/stop', async (route) => {
        stopCalled = true;
        await route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify({ status: 'stopped' }),
        });
      });

      await page.goto('/nomic-control');
      await aragoraPage.dismissAllOverlays();

      // Click stop button
      await page.locator('button:has-text("Stop")').click();

      // Wait for API call
      await page.waitForTimeout(500);
      expect(stopCalled).toBe(true);
    });
  });
});
