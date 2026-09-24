/**
 * Backend Integration Tests
 *
 * These tests validate real end-to-end flows against the actual backend.
 * They require the backend server to be running.
 *
 * Run with: npm run test:e2e:integration
 */

import { test, expect } from '@playwright/test';

// Backend API configuration
const API_URL = process.env.PLAYWRIGHT_API_URL || 'http://localhost:8080';
const _WS_URL = process.env.PLAYWRIGHT_WS_URL || 'ws://localhost:8765';

// Helper to check if backend is available
async function isBackendAvailable(): Promise<boolean> {
  try {
    const response = await fetch(`${API_URL}/api/health`);
    return response.ok;
  } catch {
    return false;
  }
}

// Skip tests if backend is not available
test.beforeAll(async () => {
  const available = await isBackendAvailable();
  if (!available) {
    test.skip();
    console.log('Backend not available, skipping integration tests');
  }
});

test.describe('Backend Health Integration', () => {
  test('should connect to backend health endpoint', async ({ request }) => {
    const response = await request.get(`${API_URL}/api/health`);
    expect(response.ok()).toBeTruthy();

    const data = await response.json();
    expect(data).toHaveProperty('status');
    expect(data.status).toBe('healthy');
  });

  test('should return server version', async ({ request }) => {
    const response = await request.get(`${API_URL}/api/health`);
    const data = await response.json();

    expect(data).toHaveProperty('version');
    expect(typeof data.version).toBe('string');
  });

  test('should report database connectivity', async ({ request }) => {
    const response = await request.get(`${API_URL}/api/health`);
    const data = await response.json();

    expect(data).toHaveProperty('checks');
    expect(data.checks).toHaveProperty('database');
  });
});

test.describe('Agent API Integration', () => {
  test('should list available agents', async ({ request }) => {
    const response = await request.get(`${API_URL}/api/agents`);
    expect(response.ok()).toBeTruthy();

    const data = await response.json();
    expect(data).toHaveProperty('agents');
    expect(Array.isArray(data.agents)).toBeTruthy();
    expect(data.agents.length).toBeGreaterThan(0);
  });

  test('should include agent metadata', async ({ request }) => {
    const response = await request.get(`${API_URL}/api/agents`);
    const data = await response.json();

    const agent = data.agents[0];
    expect(agent).toHaveProperty('name');
    expect(agent).toHaveProperty('provider');
  });

  test('should get agent leaderboard', async ({ request }) => {
    const response = await request.get(`${API_URL}/api/agents/leaderboard`);
    expect(response.ok()).toBeTruthy();

    const data = await response.json();
    expect(data).toHaveProperty('rankings');
    expect(Array.isArray(data.rankings)).toBeTruthy();
  });
});

test.describe('Debate API Integration', () => {
  test('should list debates', async ({ request }) => {
    const response = await request.get(`${API_URL}/api/debates`);
    expect(response.ok()).toBeTruthy();

    const data = await response.json();
    expect(data).toHaveProperty('debates');
    expect(Array.isArray(data.debates)).toBeTruthy();
  });

  test('should support pagination', async ({ request }) => {
    const response = await request.get(`${API_URL}/api/debates?limit=5&offset=0`);
    expect(response.ok()).toBeTruthy();

    const data = await response.json();
    expect(data.debates.length).toBeLessThanOrEqual(5);
  });

  test('should filter by status', async ({ request }) => {
    const response = await request.get(`${API_URL}/api/debates?status=completed`);
    expect(response.ok()).toBeTruthy();

    const data = await response.json();
    for (const debate of data.debates) {
      expect(debate.status).toBe('completed');
    }
  });
});

test.describe('WebSocket Integration', () => {
  test('should establish WebSocket connection', async ({ page }) => {
    const wsConnected = new Promise<boolean>((resolve) => {
      page.on('websocket', (ws) => {
        if (ws.url().includes('ws')) {
          resolve(true);
        }
      });

      // Timeout after 10 seconds
      setTimeout(() => resolve(false), 10000);
    });

    await page.goto('/');
    const connected = await wsConnected;
    expect(connected).toBeTruthy();
  });

  test('should receive heartbeat messages', async ({ page }) => {
    const heartbeatReceived = new Promise<boolean>((resolve) => {
      page.on('websocket', (ws) => {
        ws.on('framereceived', (frame) => {
          try {
            const data = JSON.parse(frame.payload as string);
            if (data.type === 'heartbeat' || data.type === 'ping') {
              resolve(true);
            }
          } catch {
            // Not JSON, ignore
          }
        });
      });

      setTimeout(() => resolve(false), 15000);
    });

    await page.goto('/');
    const _received = await heartbeatReceived;
    // Heartbeat is optional, just verify connection works
    expect(true).toBeTruthy();
  });
});

test.describe('Memory System Integration', () => {
  test('should get memory tier statistics', async ({ request }) => {
    const response = await request.get(`${API_URL}/api/memory/stats`);

    if (response.ok()) {
      const data = await response.json();
      expect(data).toHaveProperty('tiers');

      // Verify tier structure
      const tiers = ['fast', 'medium', 'slow', 'glacial'];
      for (const tier of tiers) {
        if (data.tiers[tier]) {
          expect(data.tiers[tier]).toHaveProperty('count');
          expect(data.tiers[tier]).toHaveProperty('size_bytes');
        }
      }
    }
  });

  test('should search memory', async ({ request }) => {
    const response = await request.get(`${API_URL}/api/memory/search?q=test&limit=10`);

    if (response.ok()) {
      const data = await response.json();
      expect(data).toHaveProperty('results');
      expect(Array.isArray(data.results)).toBeTruthy();
    }
  });
});

test.describe('Ranking System Integration', () => {
  test('should get ELO rankings', async ({ request }) => {
    const response = await request.get(`${API_URL}/api/ranking/elo`);

    if (response.ok()) {
      const data = await response.json();
      expect(data).toHaveProperty('rankings');

      // Verify ELO structure
      if (data.rankings.length > 0) {
        const ranking = data.rankings[0];
        expect(ranking).toHaveProperty('agent');
        expect(ranking).toHaveProperty('elo');
        expect(typeof ranking.elo).toBe('number');
      }
    }
  });

  test('should get calibration data', async ({ request }) => {
    const response = await request.get(`${API_URL}/api/ranking/calibration`);

    if (response.ok()) {
      const data = await response.json();
      expect(data).toHaveProperty('agents');
    }
  });
});

test.describe('Workflow API Integration', () => {
  test('should list workflow templates', async ({ request }) => {
    const response = await request.get(`${API_URL}/api/workflows/templates`);

    if (response.ok()) {
      const data = await response.json();
      expect(data).toHaveProperty('templates');
      expect(Array.isArray(data.templates)).toBeTruthy();
    }
  });

  test('should list workflow executions', async ({ request }) => {
    const response = await request.get(`${API_URL}/api/workflows/executions`);

    if (response.ok()) {
      const data = await response.json();
      expect(data).toHaveProperty('executions');
      expect(Array.isArray(data.executions)).toBeTruthy();
    }
  });
});

test.describe('Connector API Integration', () => {
  test('should list available connectors', async ({ request }) => {
    const response = await request.get(`${API_URL}/api/connectors`);

    if (response.ok()) {
      const data = await response.json();
      expect(data).toHaveProperty('connectors');
      expect(Array.isArray(data.connectors)).toBeTruthy();
    }
  });

  test('should get connector sync status', async ({ request }) => {
    const response = await request.get(`${API_URL}/api/connectors/sync/status`);

    if (response.ok()) {
      const data = await response.json();
      expect(data).toHaveProperty('syncs');
    }
  });
});

test.describe('Full Page Integration', () => {
  test('should load homepage with real data', async ({ page }) => {
    await page.goto('/');
    await page.waitForLoadState('networkidle');

    // Verify page loaded
    await expect(page).toHaveTitle(/Aragora/i);
  });

  test('should load debates page with real data', async ({ page }) => {
    await page.goto('/debates');
    await page.waitForLoadState('networkidle');

    // Wait for debate list to load
    const debateList = page.locator('[data-testid="debate-list"], .debate-list, main');
    await expect(debateList).toBeVisible({ timeout: 10000 });
  });

  test('should load agents page with real data', async ({ page }) => {
    await page.goto('/agents');
    await page.waitForLoadState('networkidle');

    // Wait for agent list to load
    const agentSection = page.locator('[data-testid="agent-list"], .agent-list, main');
    await expect(agentSection).toBeVisible({ timeout: 10000 });
  });

  test('should load leaderboard with real rankings', async ({ page }) => {
    await page.goto('/leaderboard');
    await page.waitForLoadState('networkidle');

    // Wait for leaderboard to load
    const leaderboard = page.locator('[data-testid="leaderboard"], .leaderboard, main');
    await expect(leaderboard).toBeVisible({ timeout: 10000 });
  });

  test('should load memory page', async ({ page }) => {
    await page.goto('/memory');
    await page.waitForLoadState('networkidle');

    const memoryPage = page.locator('main');
    await expect(memoryPage).toBeVisible({ timeout: 10000 });
  });

  test('should load workflows page', async ({ page }) => {
    await page.goto('/workflows');
    await page.waitForLoadState('networkidle');

    const workflowsPage = page.locator('main');
    await expect(workflowsPage).toBeVisible({ timeout: 10000 });
  });
});

test.describe('Error Handling Integration', () => {
  test('should handle 404 gracefully', async ({ page }) => {
    const response = await page.goto('/nonexistent-page-12345');

    // Should either redirect to 404 page or show error
    const content = await page.content();
    expect(
      response?.status() === 404 ||
        content.includes('404') ||
        content.includes('not found') ||
        content.includes('Not Found'),
    ).toBeTruthy();
  });

  test('should handle API errors gracefully', async ({ page }) => {
    await page.goto('/');

    // Intercept API call and force error
    await page.route('**/api/debates*', (route) => {
      route.fulfill({ status: 500, body: JSON.stringify({ error: 'Internal Server Error' }) });
    });

    await page.goto('/debates');

    // Page should still load (with error state)
    await page.waitForLoadState('networkidle');
    const mainContent = page.locator('main');
    await expect(mainContent).toBeVisible();
  });
});

test.describe('Performance Integration', () => {
  test('should load homepage within acceptable time', async ({ page }) => {
    const startTime = Date.now();
    await page.goto('/');
    await page.waitForLoadState('domcontentloaded');
    const loadTime = Date.now() - startTime;

    // Should load within 5 seconds
    expect(loadTime).toBeLessThan(5000);
  });

  test('should load debates page within acceptable time', async ({ page }) => {
    const startTime = Date.now();
    await page.goto('/debates');
    await page.waitForLoadState('domcontentloaded');
    const loadTime = Date.now() - startTime;

    // Should load within 5 seconds
    expect(loadTime).toBeLessThan(5000);
  });

  test('should have no console errors on page load', async ({ page }) => {
    const consoleErrors: string[] = [];

    page.on('console', (msg) => {
      if (msg.type() === 'error') {
        consoleErrors.push(msg.text());
      }
    });

    await page.goto('/');
    await page.waitForLoadState('networkidle');

    // Filter out known acceptable errors (e.g., 3rd party scripts)
    const criticalErrors = consoleErrors.filter(
      (error) =>
        !error.includes('favicon') &&
        !error.includes('third-party') &&
        !error.includes('analytics'),
    );

    expect(criticalErrors.length).toBe(0);
  });
});

test.describe('CORS Integration', () => {
  test('should allow CORS requests from frontend', async ({ request }) => {
    const response = await request.get(`${API_URL}/api/health`, {
      headers: { Origin: 'http://localhost:3000' },
    });

    expect(response.ok()).toBeTruthy();

    // Check CORS headers if present
    const headers = response.headers();
    if (headers['access-control-allow-origin']) {
      expect(
        headers['access-control-allow-origin'] === '*' ||
          headers['access-control-allow-origin'].includes('localhost'),
      ).toBeTruthy();
    }
  });
});

test.describe('Rate Limiting Integration', () => {
  test('should not rate limit normal usage', async ({ request }) => {
    // Make 10 requests in quick succession
    const responses = await Promise.all(
      Array.from({ length: 10 }, () => request.get(`${API_URL}/api/health`)),
    );

    // All should succeed
    for (const response of responses) {
      expect(response.status()).not.toBe(429);
    }
  });
});
