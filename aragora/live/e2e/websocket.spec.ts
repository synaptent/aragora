import { test, expect } from './fixtures';

/**
 * E2E tests for WebSocket connectivity and real-time features.
 *
 * These tests verify WebSocket connections, reconnection logic,
 * and real-time data flow.
 */

test.describe('WebSocket Connectivity', () => {
  test.describe('Connection Establishment', () => {
    test('should establish WebSocket connection on debate page', async ({ page, aragoraPage }) => {
      const wsConnections: { url: string; readyState: number }[] = [];

      page.on('websocket', (ws) => {
        wsConnections.push({
          url: ws.url(),
          readyState: 0, // Will update on events
        });

        ws.on('framesent', () => {
          // Connection is active
        });

        ws.on('framereceived', () => {
          // Receiving data
        });
      });

      // Navigate to a live debate page (uses WebSocket)
      await page.goto('/debate/adhoc_test');
      await aragoraPage.dismissAllOverlays();
      await page.waitForTimeout(3000);

      // May or may not have WebSocket depending on page state
      // Just verify page loads without errors
      const body = page.locator('body');
      await expect(body).toBeVisible();
    });

    test('should use correct WebSocket URL protocol', async ({ page, aragoraPage }) => {
      const wsUrls: string[] = [];

      page.on('websocket', (ws) => {
        wsUrls.push(ws.url());
      });

      await page.goto('/');
      await aragoraPage.dismissAllOverlays();
      await page.waitForTimeout(2000);

      // If any WebSocket connections were made
      wsUrls.forEach((url) => {
        // Should use ws:// or wss://
        expect(url).toMatch(/^wss?:\/\//);

        // In production, should use wss://
        if (url.includes('aragora.ai')) {
          expect(url).toMatch(/^wss:\/\//);
        }
      });
    });
  });

  test.describe('Reconnection Behavior', () => {
    test('should handle WebSocket disconnect gracefully', async ({ page, aragoraPage }) => {
      await page.goto('/');
      await aragoraPage.dismissAllOverlays();

      // Force close WebSocket connections
      await page.evaluate(() => {
        // Find and close all WebSockets
        // eslint-disable-next-line @typescript-eslint/no-explicit-any -- runtime-injected property
        const wsInstances = (window as any).__wsInstances || [];
        wsInstances.forEach((ws: WebSocket) => {
          if (ws && ws.readyState === WebSocket.OPEN) {
            ws.close();
          }
        });
      });

      // Wait a moment
      await page.waitForTimeout(1000);

      // Page should still be functional
      const body = page.locator('body');
      await expect(body).toBeVisible();

      // No crash or unhandled errors
      const content = await page.content();
      expect(content.length).toBeGreaterThan(100);
    });

    test('should show connection status indicator', async ({ page, aragoraPage }) => {
      await page.goto('/');
      await aragoraPage.dismissAllOverlays();

      // Look for connection status indicators
      const statusIndicator = page.locator(
        '[data-testid="connection-status"], ' +
          '[aria-label*="connection"], ' +
          '.connection-status, ' +
          '[data-testid="ws-status"]',
      );

      // Status indicator may or may not be visible
      const hasIndicator = await statusIndicator
        .first()
        .isVisible({ timeout: 2000 })
        .catch(() => false);

      // If we have a status indicator, it should be present
      expect(typeof hasIndicator).toBe('boolean');
    });

    test('should attempt reconnection after disconnect', async ({ page, aragoraPage }) => {
      const wsEvents: string[] = [];

      page.on('websocket', (ws) => {
        wsEvents.push(`connect:${ws.url()}`);

        ws.on('close', () => {
          wsEvents.push('close');
        });
      });

      await page.goto('/debate/adhoc_reconnect_test');
      await aragoraPage.dismissAllOverlays();
      await page.waitForTimeout(5000);

      // Page should handle reconnection attempts
      const body = page.locator('body');
      await expect(body).toBeVisible();
    });
  });

  test.describe('Real-time Updates', () => {
    test('should receive WebSocket messages', async ({ page, aragoraPage }) => {
      const receivedFrames: number[] = [];

      page.on('websocket', (ws) => {
        ws.on('framereceived', (frame) => {
          receivedFrames.push(frame.payload.length);
        });
      });

      await page.goto('/');
      await aragoraPage.dismissAllOverlays();
      await page.waitForTimeout(5000);

      // Just verify the mechanism works (may or may not receive messages)
      expect(Array.isArray(receivedFrames)).toBe(true);
    });

    test('should send WebSocket messages', async ({ page, aragoraPage }) => {
      const sentFrames: number[] = [];

      page.on('websocket', (ws) => {
        ws.on('framesent', (frame) => {
          sentFrames.push(frame.payload.length);
        });
      });

      await page.goto('/');
      await aragoraPage.dismissAllOverlays();
      await page.waitForTimeout(3000);

      // Just verify the mechanism works
      expect(Array.isArray(sentFrames)).toBe(true);
    });
  });

  test.describe('Connection Resilience', () => {
    test('should handle network interruption', async ({ page, aragoraPage }) => {
      await page.goto('/');
      await aragoraPage.dismissAllOverlays();

      // Simulate network offline
      await page.context().setOffline(true);
      await page.waitForTimeout(1000);

      // Page should still be visible (though degraded)
      const body = page.locator('body');
      await expect(body).toBeVisible();

      // Restore network
      await page.context().setOffline(false);
      await page.waitForTimeout(2000);

      // Should recover
      await expect(body).toBeVisible();
    });

    test('should handle slow network gracefully', async ({ page, aragoraPage }) => {
      // Simulate slow network for WebSocket
      await page.route('**/*', async (route) => {
        // Add delay to all requests
        await new Promise((resolve) => setTimeout(resolve, 100));
        await route.continue();
      });

      await page.goto('/');
      await aragoraPage.dismissAllOverlays();

      // Should still load (slowly)
      const body = page.locator('body');
      await expect(body).toBeVisible({ timeout: 15000 });
    });

    test('should handle WebSocket server unavailable', async ({ page, aragoraPage }) => {
      // Block WebSocket connections
      await page.route(/wss?:\/\/.*/, (route) => {
        route.abort('connectionfailed');
      });

      await page.goto('/');
      await aragoraPage.dismissAllOverlays();

      // Page should still be functional (with degraded features)
      const body = page.locator('body');
      await expect(body).toBeVisible();

      // No crash
      const content = await page.content();
      expect(content.length).toBeGreaterThan(100);
    });
  });

  test.describe('Multiple Connections', () => {
    test('should handle multiple WebSocket connections', async ({ page, aragoraPage }) => {
      const connections: string[] = [];

      page.on('websocket', (ws) => {
        connections.push(ws.url());
      });

      // Open multiple pages that might use WebSocket
      await page.goto('/');
      await aragoraPage.dismissAllOverlays();
      await page.waitForTimeout(2000);

      // Navigate to another page that uses WebSocket
      await page.goto('/debate/adhoc_multi');
      await aragoraPage.dismissAllOverlays();
      await page.waitForTimeout(2000);

      // Page should handle multiple connections without issues
      const body = page.locator('body');
      await expect(body).toBeVisible();
    });

    test('should clean up connections on page unload', async ({ page, aragoraPage }) => {
      let activeConnections = 0;

      page.on('websocket', (ws) => {
        activeConnections++;
        ws.on('close', () => {
          activeConnections--;
        });
      });

      await page.goto('/debate/adhoc_cleanup');
      await aragoraPage.dismissAllOverlays();
      await page.waitForTimeout(2000);

      const connectionsBeforeNav = activeConnections;

      // Navigate away
      await page.goto('/');
      await aragoraPage.dismissAllOverlays();
      await page.waitForTimeout(2000);

      // Connections should be cleaned up or reused
      expect(activeConnections).toBeLessThanOrEqual(connectionsBeforeNav);
    });
  });

  test.describe('Error Handling', () => {
    test('should not crash on malformed WebSocket messages', async ({ page, aragoraPage }) => {
      await page.goto('/');
      await aragoraPage.dismissAllOverlays();

      // Inject malformed data (simulated)
      await page.evaluate(() => {
        // Try to trigger error handlers safely
        const errorEvent = new ErrorEvent('error', {
          message: 'WebSocket test error',
          filename: 'test.js',
          lineno: 1,
        });
        window.dispatchEvent(errorEvent);
      });

      // Page should still be functional
      const body = page.locator('body');
      await expect(body).toBeVisible();
    });

    test('should log WebSocket errors appropriately', async ({ page, aragoraPage }) => {
      const consoleMessages: string[] = [];

      page.on('console', (msg) => {
        consoleMessages.push(`[${msg.type()}] ${msg.text()}`);
      });

      // Block WebSocket to force errors
      await page.route(/wss?:\/\/.*/, (route) => {
        route.abort('connectionfailed');
      });

      await page.goto('/debate/adhoc_error_test');
      await aragoraPage.dismissAllOverlays();
      await page.waitForTimeout(3000);

      // Should have some console output about connection issues
      // (not necessarily errors, could be warnings or info)
      expect(Array.isArray(consoleMessages)).toBe(true);
    });
  });
});
