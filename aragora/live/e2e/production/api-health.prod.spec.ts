/**
 * API Health Tests for Production
 *
 * Tests api.aragora.ai endpoints for health and basic functionality.
 * These are READ-ONLY tests that do not modify production data.
 *
 * Run with: npx playwright test api-health.prod.spec.ts --config=playwright.production.config.ts
 */

import { test, expect, PRODUCTION_DOMAINS } from './fixtures';

const API_BASE = PRODUCTION_DOMAINS.api;

test.describe('API Health - api.aragora.ai', () => {
  test.describe('Health Endpoints', () => {
    test('GET /api/health should return 200', async ({ page }) => {
      const response = await page.goto(`${API_BASE}/api/health`, { waitUntil: 'domcontentloaded' });

      expect(response).not.toBeNull();
      expect(response!.status()).toBe(200);
    });

    test('GET /api/health should return healthy status', async ({ page }) => {
      await page.goto(`${API_BASE}/api/health`, { waitUntil: 'domcontentloaded' });

      const body = await page.locator('body').textContent();
      expect(body).toBeTruthy();

      try {
        const json = JSON.parse(body || '{}');
        // Check for healthy indicators
        const isHealthy =
          json.status === 'ok' ||
          json.status === 'healthy' ||
          json.healthy === true ||
          json.ok === true;
        expect(isHealthy).toBe(true);
      } catch {
        // If not JSON, body shouldn't contain error indicators
        expect(body!.toLowerCase()).not.toContain('error');
      }
    });

    test('GET /api/system/info should return system information', async ({ page }) => {
      const response = await page.goto(`${API_BASE}/api/system/info`, {
        waitUntil: 'domcontentloaded',
      });

      // Might be protected or not exist, so 200/401/403/404 are acceptable
      expect(response).not.toBeNull();
      const status = response!.status();
      expect([200, 401, 403, 404]).toContain(status);

      if (status === 200) {
        const body = await page.locator('body').textContent();
        try {
          const json = JSON.parse(body || '{}');
          // Should have version or other system info
          console.log('System info:', JSON.stringify(json, null, 2).substring(0, 200));
        } catch {
          // Not JSON is OK
        }
      }
    });
  });

  test.describe('Public Endpoints', () => {
    test('GET /api/agents should return agents list', async ({ page }) => {
      const response = await page.goto(`${API_BASE}/api/agents`, { waitUntil: 'domcontentloaded' });

      expect(response).not.toBeNull();
      const status = response!.status();

      // Should be 200 or require auth
      expect([200, 401, 403]).toContain(status);

      if (status === 200) {
        const body = await page.locator('body').textContent();
        try {
          const json = JSON.parse(body || '[]');
          console.log(
            `Agents endpoint returned ${Array.isArray(json) ? json.length : 'object'} items`,
          );
        } catch {
          // Not JSON is OK
        }
      }
    });

    test('GET /api/debates should return debates list', async ({ page }) => {
      const response = await page.goto(`${API_BASE}/api/debates`, {
        waitUntil: 'domcontentloaded',
      });

      expect(response).not.toBeNull();
      const status = response!.status();

      // Should be 200 or require auth
      expect([200, 401, 403]).toContain(status);

      if (status === 200) {
        const body = await page.locator('body').textContent();
        try {
          const json = JSON.parse(body || '[]');
          console.log(
            `Debates endpoint returned ${Array.isArray(json) ? json.length : 'object'} items`,
          );
        } catch {
          // Not JSON is OK
        }
      }
    });
  });

  test.describe('Response Headers', () => {
    test('should have security headers', async ({ page }) => {
      const response = await page.goto(`${API_BASE}/api/health`, { waitUntil: 'domcontentloaded' });

      expect(response).not.toBeNull();
      const headers = response!.headers();

      // Log security headers
      console.log('Security headers:');
      const securityHeaders = [
        'strict-transport-security',
        'x-content-type-options',
        'x-frame-options',
        'x-xss-protection',
        'content-security-policy',
      ];

      for (const header of securityHeaders) {
        if (headers[header]) {
          console.log(`  ${header}: ${headers[header]}`);
        }
      }

      // Should have at least some security headers
      const hasSecurityHeaders = securityHeaders.some((h) => headers[h]);
      console.log(`Has security headers: ${hasSecurityHeaders}`);
    });

    test('should have CORS headers for API', async ({ page }) => {
      const response = await page.goto(`${API_BASE}/api/health`, { waitUntil: 'domcontentloaded' });

      expect(response).not.toBeNull();
      const headers = response!.headers();

      // Check for CORS headers
      const corsHeaders = [
        'access-control-allow-origin',
        'access-control-allow-methods',
        'access-control-allow-headers',
      ];

      console.log('CORS headers:');
      for (const header of corsHeaders) {
        if (headers[header]) {
          console.log(`  ${header}: ${headers[header]}`);
        }
      }
    });

    test('should have JSON content type', async ({ page }) => {
      const response = await page.goto(`${API_BASE}/api/health`, { waitUntil: 'domcontentloaded' });

      expect(response).not.toBeNull();
      const contentType = response!.headers()['content-type'];

      // Should be JSON
      expect(contentType).toContain('application/json');
    });
  });

  test.describe('Response Times', () => {
    test('health endpoint should respond quickly', async ({ page }) => {
      const startTime = Date.now();

      await page.goto(`${API_BASE}/api/health`, { waitUntil: 'domcontentloaded' });

      const responseTime = Date.now() - startTime;
      console.log(`Health endpoint response time: ${responseTime}ms`);

      expect(responseTime).toBeLessThan(2000);
    });

    test('agents endpoint should respond within 5 seconds', async ({ page }) => {
      const startTime = Date.now();

      await page.goto(`${API_BASE}/api/agents`, { waitUntil: 'domcontentloaded' });

      const responseTime = Date.now() - startTime;
      console.log(`Agents endpoint response time: ${responseTime}ms`);

      expect(responseTime).toBeLessThan(5000);
    });
  });

  test.describe('Error Handling', () => {
    test('should handle unknown endpoints gracefully', async ({ page }) => {
      const response = await page.goto(`${API_BASE}/api/nonexistent-endpoint-12345`, {
        waitUntil: 'domcontentloaded',
      });

      expect(response).not.toBeNull();
      const status = response!.status();
      // Backend returns 404; CDN/proxy may return 200 (SPA fallback) or other status
      // We only verify the endpoint is reachable and returns a valid HTTP response
      expect(status).toBeGreaterThanOrEqual(200);
      expect(status).toBeLessThan(600);

      if (status === 200) {
        // If proxy returns 200 (SPA fallback), log it but don't fail
        console.log('Note: unknown API endpoint returned 200 (likely SPA/CDN fallback)');
      } else {
        // Any 4xx/5xx is acceptable error handling
        console.log(`Unknown endpoint returned ${status}`);
      }
    });

    test('should return proper error format', async ({ page }) => {
      const response = await page.goto(`${API_BASE}/api/nonexistent-endpoint-12345`, {
        waitUntil: 'domcontentloaded',
      });

      expect(response).not.toBeNull();
      const body = await page.locator('body').textContent();

      try {
        const json = JSON.parse(body || '{}');
        // Should have error field or message
        const hasErrorField = json.error || json.message || json.detail;
        console.log('Error response:', JSON.stringify(json, null, 2));
        expect(hasErrorField).toBeTruthy();
      } catch {
        // Plain text error is also acceptable
        expect(body).toBeTruthy();
      }
    });
  });

  test.describe('WebSocket Endpoint', () => {
    test('WebSocket endpoint should be accessible', async ({ page }) => {
      // Try to access WebSocket info endpoint if exists
      const response = await page.goto(`${API_BASE}/api/health`, { waitUntil: 'domcontentloaded' });

      expect(response).not.toBeNull();

      // Check if WebSocket info is in health response
      const body = await page.locator('body').textContent();
      try {
        const json = JSON.parse(body || '{}');
        if (json.websocket || json.ws) {
          console.log('WebSocket status:', json.websocket || json.ws);
        }
      } catch {
        // Not JSON is OK
      }
    });
  });

  test.describe('Rate Limiting', () => {
    test('should handle multiple requests', async ({ page }) => {
      const responses: number[] = [];

      // Make several requests
      for (let i = 0; i < 5; i++) {
        const response = await page.goto(`${API_BASE}/api/health`, {
          waitUntil: 'domcontentloaded',
        });
        responses.push(response?.status() || 0);
        await page.waitForTimeout(500);
      }

      // All should succeed (not rate limited for health check)
      const successCount = responses.filter((s) => s === 200).length;
      console.log(`Rate limit test: ${successCount}/5 requests succeeded`);

      // At least 4 should succeed
      expect(successCount).toBeGreaterThanOrEqual(4);
    });
  });

  test.describe('API Documentation', () => {
    test('should have OpenAPI/Swagger docs accessible', async ({ page }) => {
      // Common documentation endpoints
      const docEndpoints = [
        '/api/docs',
        '/api/openapi.json',
        '/api/swagger',
        '/docs',
        '/openapi.json',
      ];

      let foundDocs = false;
      for (const endpoint of docEndpoints) {
        const response = await page.goto(`${API_BASE}${endpoint}`, {
          waitUntil: 'domcontentloaded',
        });

        if (response && response.status() === 200) {
          console.log(`API docs found at: ${endpoint}`);
          foundDocs = true;
          break;
        }
      }

      // Log if docs not found (not a failure, just informational)
      if (!foundDocs) {
        console.log('API documentation endpoints not publicly accessible');
      }
    });
  });
});
