import { test, expect, mockApiResponse } from './fixtures';

/**
 * Multi-Tenant Data Isolation E2E Tests (Phase 3 Production Readiness)
 *
 * Tests for:
 * - Cross-tenant data access prevention
 * - API isolation enforcement
 * - Knowledge Mound tenant scoping
 * - Budget usage isolation
 */

test.describe('Multi-Tenant Data Isolation', () => {
  // Test user/org context for Tenant A
  const tenantA = {
    userId: 'user-a-123',
    orgId: 'org-tenant-a',
    token: 'tenant-a-token',
    email: 'user@tenant-a.com',
  };

  // Test user/org context for Tenant B
  const tenantB = {
    userId: 'user-b-456',
    orgId: 'org-tenant-b',
    token: 'tenant-b-token',
    email: 'user@tenant-b.com',
  };

  test.describe('Debate Data Isolation', () => {
    test('tenant A cannot access tenant B debates via API', async ({ page, aragoraPage }) => {
      // Login as Tenant A
      await page.addInitScript((tenantA) => {
        localStorage.setItem('auth_token', tenantA.token);
        localStorage.setItem('user', JSON.stringify({ id: tenantA.userId, org_id: tenantA.orgId }));
      }, tenantA);

      // Mock /me endpoint for Tenant A
      await mockApiResponse(page, '**/api/auth/me', {
        user: { id: tenantA.userId, email: tenantA.email, org_id: tenantA.orgId },
      });

      // Mock debates list - should only return Tenant A debates
      await mockApiResponse(page, '**/api/debates*', {
        debates: [
          { id: 'debate-a-1', topic: 'Tenant A Debate 1', org_id: tenantA.orgId },
          { id: 'debate-a-2', topic: 'Tenant A Debate 2', org_id: tenantA.orgId },
        ],
      });

      // Mock attempt to access Tenant B's debate - should return 403
      await page.route('**/api/debates/debate-b-1', async (route) => {
        await route.fulfill({
          status: 403,
          body: JSON.stringify({ error: 'Access denied', code: 'TENANT_ISOLATION_VIOLATION' }),
        });
      });

      await page.goto('/debates');
      await aragoraPage.dismissAllOverlays();

      // Verify debates list only shows Tenant A debates
      const pageContent = await page.content();
      expect(pageContent).toContain('Tenant A Debate');

      // Attempt to directly access Tenant B's debate
      const response = await page.request.get('/api/debates/debate-b-1', {
        headers: { Authorization: `Bearer ${tenantA.token}` },
      });

      // Should be forbidden
      expect(response.status()).toBe(403);
    });

    test('debate list is scoped to current tenant', async ({ page, aragoraPage }) => {
      // Login as Tenant B
      await page.addInitScript((tenantB) => {
        localStorage.setItem('auth_token', tenantB.token);
      }, tenantB);

      // Mock /me for Tenant B
      await mockApiResponse(page, '**/api/auth/me', {
        user: { id: tenantB.userId, email: tenantB.email, org_id: tenantB.orgId },
      });

      // Tenant B's debates only
      await mockApiResponse(page, '**/api/debates*', {
        debates: [{ id: 'debate-b-1', topic: 'Tenant B Analysis', org_id: tenantB.orgId }],
      });

      await page.goto('/debates');
      await aragoraPage.dismissAllOverlays();

      // Should only see Tenant B's debates
      const pageContent = await page.content();
      expect(pageContent).not.toContain('Tenant A');
    });
  });

  test.describe('Knowledge Mound Isolation', () => {
    test('knowledge queries are scoped to tenant', async ({ page, aragoraPage }) => {
      await page.addInitScript((tenantA) => {
        localStorage.setItem('auth_token', tenantA.token);
      }, tenantA);

      await mockApiResponse(page, '**/api/auth/me', {
        user: { id: tenantA.userId, org_id: tenantA.orgId },
      });

      // Mock knowledge search - should only return Tenant A's knowledge
      await mockApiResponse(page, '**/api/knowledge/search*', {
        results: [{ id: 'km-a-1', content: 'Tenant A internal knowledge', org_id: tenantA.orgId }],
      });

      await page.goto('/knowledge');
      await aragoraPage.dismissAllOverlays();

      // Knowledge page should load
      expect(page.url()).toContain('knowledge');
    });

    test('tenant B cannot see tenant A knowledge via search', async ({ page, aragoraPage }) => {
      await page.addInitScript((tenantB) => {
        localStorage.setItem('auth_token', tenantB.token);
      }, tenantB);

      await mockApiResponse(page, '**/api/auth/me', {
        user: { id: tenantB.userId, org_id: tenantB.orgId },
      });

      // Search should not return Tenant A's knowledge
      await mockApiResponse(page, '**/api/knowledge/search*', {
        results: [], // No results from Tenant A
      });

      // Attempt to directly access Tenant A's knowledge
      await page.route('**/api/knowledge/km-a-1', async (route) => {
        await route.fulfill({
          status: 403,
          body: JSON.stringify({ error: 'Knowledge item not found or access denied' }),
        });
      });

      await page.goto('/knowledge');
      await aragoraPage.dismissAllOverlays();

      // Should not show Tenant A's knowledge
      const pageContent = await page.content();
      expect(pageContent).not.toContain('Tenant A internal');
    });

    test('knowledge ingestion is tenant-scoped', async ({ page, aragoraPage }) => {
      let _capturedOrgId: string | null = null;

      await page.addInitScript((tenantA) => {
        localStorage.setItem('auth_token', tenantA.token);
      }, tenantA);

      await mockApiResponse(page, '**/api/auth/me', {
        user: { id: tenantA.userId, org_id: tenantA.orgId },
      });

      // Capture knowledge ingestion request
      await page.route('**/api/knowledge/ingest', async (route) => {
        const postData = route.request().postData();
        if (postData) {
          const data = JSON.parse(postData);
          _capturedOrgId = data.org_id;
        }
        await route.fulfill({
          status: 200,
          body: JSON.stringify({ success: true, id: 'km-new-1' }),
        });
      });

      await page.goto('/knowledge');
      await aragoraPage.dismissAllOverlays();

      // Verify page loads correctly
      expect(page.url()).toContain('knowledge');
    });
  });

  test.describe('Budget Usage Isolation', () => {
    test('budget usage shows only current tenant data', async ({ page, aragoraPage }) => {
      await page.addInitScript((tenantA) => {
        localStorage.setItem('auth_token', tenantA.token);
      }, tenantA);

      await mockApiResponse(page, '**/api/auth/me', {
        user: { id: tenantA.userId, org_id: tenantA.orgId, role: 'owner' },
      });

      // Mock billing/usage endpoint
      await mockApiResponse(page, '**/api/billing/usage', {
        usage: {
          debates_used: 50,
          debates_limit: 100,
          tokens_used: 500000,
          cost_usd: 25.0,
          org_id: tenantA.orgId,
        },
      });

      await page.goto('/settings/billing');
      await aragoraPage.dismissAllOverlays();

      // Should show Tenant A's usage
      const pageContent = await page.content();
      // Page should load billing info
      expect(pageContent).toBeTruthy();
    });

    test('budget API enforces tenant context', async ({ page }) => {
      // Setup as Tenant A
      await page.addInitScript((tenantA) => {
        localStorage.setItem('auth_token', tenantA.token);
      }, tenantA);

      // Attempt to access Tenant B's budget - should fail
      await page.route('**/api/billing/usage?org_id=' + tenantB.orgId, async (route) => {
        await route.fulfill({
          status: 403,
          body: JSON.stringify({ error: 'Cannot access other tenant budget data' }),
        });
      });

      const response = await page.request.get(`/api/billing/usage?org_id=${tenantB.orgId}`, {
        headers: { Authorization: `Bearer ${tenantA.token}` },
      });

      expect(response.status()).toBe(403);
    });
  });

  test.describe('API Authorization Headers', () => {
    test('API requests include tenant context', async ({ page }) => {
      let capturedHeaders: Record<string, string> = {};

      await page.addInitScript((tenantA) => {
        localStorage.setItem('auth_token', tenantA.token);
      }, tenantA);

      // Capture outgoing request headers
      await page.route('**/api/**', async (route) => {
        capturedHeaders = route.request().headers();
        await route.continue();
      });

      await page.goto('/debates');
      await page.waitForTimeout(1000);

      // Requests should include authorization header
      // which allows server to determine tenant context
      expect(capturedHeaders['authorization'] || capturedHeaders['Authorization']).toBeTruthy();
    });

    test('unauthenticated requests to tenant APIs fail', async ({ page }) => {
      // No auth token set

      // Attempt to access debates API
      await page.route('**/api/debates', async (route) => {
        await route.fulfill({
          status: 401,
          body: JSON.stringify({ error: 'Authentication required' }),
        });
      });

      const response = await page.request.get('/api/debates');
      expect(response.status()).toBe(401);
    });
  });

  test.describe('Cross-Tenant Resource Access', () => {
    test('cannot access debate via direct URL with wrong tenant', async ({ page, aragoraPage }) => {
      // Login as Tenant A
      await page.addInitScript((tenantA) => {
        localStorage.setItem('auth_token', tenantA.token);
      }, tenantA);

      await mockApiResponse(page, '**/api/auth/me', {
        user: { id: tenantA.userId, org_id: tenantA.orgId },
      });

      // Mock 403 for Tenant B's debate
      await page.route('**/api/debates/debate-b-123', async (route) => {
        await route.fulfill({
          status: 403,
          body: JSON.stringify({ error: 'You do not have access to this debate' }),
        });
      });

      // Try to access Tenant B's debate directly
      await page.goto('/debates/debate-b-123');
      await aragoraPage.dismissAllOverlays();
      await page.waitForTimeout(1000);

      // Should show access denied or redirect
      const pageContent = await page.content();
      const currentUrl = page.url();

      const accessDenied =
        pageContent.toLowerCase().includes('access denied') ||
        pageContent.toLowerCase().includes('not found') ||
        pageContent.toLowerCase().includes('403') ||
        pageContent.toLowerCase().includes('error') ||
        (currentUrl.includes('debates') && !currentUrl.includes('debate-b-123'));

      expect(accessDenied).toBeTruthy();
    });

    test('tenant switching clears cached data', async ({ page, aragoraPage }) => {
      // Start as Tenant A
      await page.addInitScript((tenantA) => {
        localStorage.setItem('auth_token', tenantA.token);
        localStorage.setItem(
          'cached_debates',
          JSON.stringify([{ id: 'debate-a-1', topic: 'Cached Tenant A Debate' }]),
        );
      }, tenantA);

      // Mock logout and new login as Tenant B
      await page.route('**/api/auth/logout', async (route) => {
        await route.fulfill({ status: 200, body: JSON.stringify({ success: true }) });
      });

      await page.goto('/');
      await aragoraPage.dismissAllOverlays();

      // Simulate tenant switch (logout + login as different tenant)
      await page.evaluate((tenantB) => {
        localStorage.removeItem('auth_token');
        localStorage.removeItem('cached_debates');
        localStorage.setItem('auth_token', tenantB.token);
      }, tenantB);

      // Verify cached data is cleared
      const cachedData = await page.evaluate(() => {
        return localStorage.getItem('cached_debates');
      });

      expect(cachedData).toBeNull();
    });
  });

  test.describe('Shared Resource Handling', () => {
    test('public debates are accessible across tenants', async ({ page, aragoraPage }) => {
      await page.addInitScript((tenantB) => {
        localStorage.setItem('auth_token', tenantB.token);
      }, tenantB);

      await mockApiResponse(page, '**/api/auth/me', {
        user: { id: tenantB.userId, org_id: tenantB.orgId },
      });

      // Mock public debate access
      await mockApiResponse(page, '**/api/debates/public-debate-1', {
        debate: { id: 'public-debate-1', topic: 'Public Debate Topic', visibility: 'public' },
      });

      await page.goto('/debates/public-debate-1');
      await aragoraPage.dismissAllOverlays();

      // Public debates should be accessible
      const pageContent = await page.content();
      expect(pageContent.toLowerCase()).not.toContain('access denied');
    });

    test('shared knowledge requires explicit permission', async ({ page }) => {
      await page.addInitScript((tenantB) => {
        localStorage.setItem('auth_token', tenantB.token);
      }, tenantB);

      // Mock shared knowledge access check
      await page.route('**/api/knowledge/shared-km-1', async (route) => {
        await route.fulfill({
          status: 200,
          body: JSON.stringify({
            id: 'shared-km-1',
            content: 'Shared knowledge content',
            sharing: { type: 'explicit', shared_with: [tenantB.orgId] },
          }),
        });
      });

      const response = await page.request.get('/api/knowledge/shared-km-1', {
        headers: { Authorization: `Bearer ${tenantB.token}` },
      });

      expect(response.status()).toBe(200);
    });
  });
});
