/**
 * Aragora SDK Enterprise Namespace API Tests
 *
 * Tests for enterprise namespaces: rbac, audit, webhooks, plugins, workspaces,
 * integrations, organizations, tenants, controlPlane.
 */

import { describe, it, expect, beforeEach, vi } from 'vitest';
import { createClient } from '../client';

// Mock fetch globally
const mockFetch = vi.fn();
global.fetch = mockFetch;

describe('Enterprise Namespace APIs', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  describe('rbac namespace', () => {
    it('should expose rbac namespace', () => {
      const client = createClient({ baseUrl: 'https://api.example.com' });
      expect(client.rbac).toBeDefined();
      expect(typeof client.rbac.listRoles).toBe('function');
      expect(typeof client.rbac.getRole).toBe('function');
      expect(typeof client.rbac.createRole).toBe('function');
    });

    it('should list roles via namespace', async () => {
      const client = createClient({ baseUrl: 'https://api.example.com' });

      mockFetch.mockResolvedValueOnce({
        ok: true,
        text: () => Promise.resolve(JSON.stringify({
          roles: [{ id: 'admin', name: 'Admin', permissions: ['*'] }]
        })),
      });

      const result = await client.rbac.listRoles();
      expect(result.roles).toHaveLength(1);
      expect(result.roles[0].id).toBe('admin');
    });

    it('should create role via namespace', async () => {
      const client = createClient({ baseUrl: 'https://api.example.com' });

      mockFetch.mockResolvedValueOnce({
        ok: true,
        text: () => Promise.resolve(JSON.stringify({ id: 'new-role', name: 'Custom Role' })),
      });

      const result = await client.rbac.createRole({
        name: 'Custom Role',
        permissions: ['debates.read', 'debates.create']
      });
      expect(result.id).toBe('new-role');
    });

    it('should get user roles via namespace', async () => {
      const client = createClient({ baseUrl: 'https://api.example.com' });

      mockFetch.mockResolvedValueOnce({
        ok: true,
        text: () => Promise.resolve(JSON.stringify({
          roles: [{ id: 'editor', name: 'Editor', permissions: ['debates.read'] }]
        })),
      });

      const result = await client.rbac.getUserRoles('user-123');
      expect(result.roles).toHaveLength(1);
    });

    it('should check permission via namespace', async () => {
      const client = createClient({ baseUrl: 'https://api.example.com' });

      mockFetch.mockResolvedValueOnce({
        ok: true,
        text: () => Promise.resolve(JSON.stringify({ allowed: true })),
      });

      const result = await client.rbac.checkPermission('user-123', 'debates.create');
      expect(result.allowed).toBe(true);
    });
  });

  describe('audit namespace', () => {
    it('should expose audit namespace', () => {
      const client = createClient({ baseUrl: 'https://api.example.com' });
      expect(client.audit).toBeDefined();
      expect(typeof client.audit.listEvents).toBe('function');
    });

    it('should list audit events via namespace', async () => {
      const client = createClient({ baseUrl: 'https://api.example.com' });

      mockFetch.mockResolvedValueOnce({
        ok: true,
        text: () => Promise.resolve(JSON.stringify({
          events: [{ id: 'e1', action: 'debate.create', actor_id: 'user-123' }],
          total: 1
        })),
      });

      const result = await client.audit.listEvents();
      expect(result.events).toHaveLength(1);
      expect(result.events[0].action).toBe('debate.create');
    });

    it('should export audit logs via namespace', async () => {
      const client = createClient({ baseUrl: 'https://api.example.com' });

      mockFetch.mockResolvedValueOnce({
        ok: true,
        text: () => Promise.resolve(JSON.stringify({
          url: 'https://storage.example.com/audit-export.csv',
          expires_at: '2024-01-16T10:00:00Z'
        })),
      });

      const result = await client.audit.export({ format: 'csv' });
      expect(result.url).toBeDefined();
    });
  });

  describe('webhooks namespace', () => {
    it('should expose webhooks namespace', () => {
      const client = createClient({ baseUrl: 'https://api.example.com' });
      expect(client.webhooks).toBeDefined();
      expect(typeof client.webhooks.list).toBe('function');
      expect(typeof client.webhooks.create).toBe('function');
    });

    it('should list webhooks via namespace', async () => {
      const client = createClient({ baseUrl: 'https://api.example.com' });

      mockFetch.mockResolvedValueOnce({
        ok: true,
        text: () => Promise.resolve(JSON.stringify({
          webhooks: [{ id: 'wh1', url: 'https://example.com/hook', events: ['debate.completed'] }]
        })),
      });

      const result = await client.webhooks.list();
      expect(result.webhooks).toHaveLength(1);
    });

    it('should create webhook via namespace', async () => {
      const client = createClient({ baseUrl: 'https://api.example.com' });

      mockFetch.mockResolvedValueOnce({
        ok: true,
        text: () => Promise.resolve(JSON.stringify({
          id: 'webhook-123',
          url: 'https://example.com/hook',
          secret: 'whsec_xxx'
        })),
      });

      const result = await client.webhooks.create({
        url: 'https://example.com/hook',
        events: ['debate.completed']
      });
      expect(result.id).toBe('webhook-123');
    });
  });

  describe('plugins namespace', () => {
    it('should expose plugins namespace', () => {
      const client = createClient({ baseUrl: 'https://api.example.com' });
      expect(client.plugins).toBeDefined();
      expect(typeof client.plugins.list).toBe('function');
      expect(typeof client.plugins.install).toBe('function');
    });

    it('should list available plugins via namespace', async () => {
      const client = createClient({ baseUrl: 'https://api.example.com' });

      mockFetch.mockResolvedValueOnce({
        ok: true,
        text: () => Promise.resolve(JSON.stringify({
          plugins: [{ id: 'jira', name: 'Jira Integration', version: '1.0.0' }]
        })),
      });

      const result = await client.plugins.list();
      expect(result.plugins).toHaveLength(1);
    });

    it('should install plugin via namespace', async () => {
      const client = createClient({ baseUrl: 'https://api.example.com' });

      mockFetch.mockResolvedValueOnce({
        ok: true,
        text: () => Promise.resolve(JSON.stringify({
          id: 'install-123',
          plugin_id: 'jira',
          status: 'installed'
        })),
      });

      const result = await client.plugins.install({ plugin_id: 'jira', config: {} });
      expect(result.status).toBe('installed');
    });
  });

  describe('workspaces namespace', () => {
    it('should expose workspaces namespace', () => {
      const client = createClient({ baseUrl: 'https://api.example.com' });
      expect(client.workspaces).toBeDefined();
      expect(typeof client.workspaces.list).toBe('function');
      expect(typeof client.workspaces.create).toBe('function');
    });

    it('should list workspaces via namespace', async () => {
      const client = createClient({ baseUrl: 'https://api.example.com' });

      mockFetch.mockResolvedValueOnce({
        ok: true,
        text: () => Promise.resolve(JSON.stringify({
          workspaces: [{ id: 'ws1', name: 'Engineering', member_count: 10 }]
        })),
      });

      const result = await client.workspaces.list();
      expect(result.workspaces).toHaveLength(1);
    });

    it('should create workspace via namespace', async () => {
      const client = createClient({ baseUrl: 'https://api.example.com' });

      mockFetch.mockResolvedValueOnce({
        ok: true,
        text: () => Promise.resolve(JSON.stringify({
          id: 'workspace-123',
          name: 'New Workspace'
        })),
      });

      const result = await client.workspaces.create({ name: 'New Workspace' });
      expect(result.id).toBe('workspace-123');
    });
  });

  describe('integrations namespace', () => {
    it('should expose integrations namespace', () => {
      const client = createClient({ baseUrl: 'https://api.example.com' });
      expect(client.integrations).toBeDefined();
      expect(typeof client.integrations.list).toBe('function');
      expect(typeof client.integrations.create).toBe('function');
    });

    it('should list integrations via namespace', async () => {
      const client = createClient({ baseUrl: 'https://api.example.com' });

      mockFetch.mockResolvedValueOnce({
        ok: true,
        text: () => Promise.resolve(JSON.stringify({
          integrations: [{ id: 'slack', status: 'connected' }]
        })),
      });

      const result = await client.integrations.list();
      expect(result.integrations).toHaveLength(1);
    });
  });

  describe('organizations namespace', () => {
    it('should expose organizations namespace', () => {
      const client = createClient({ baseUrl: 'https://api.example.com' });
      expect(client.organizations).toBeDefined();
      expect(typeof client.organizations.get).toBe('function');
      expect(typeof client.organizations.update).toBe('function');
    });

    it('should get organization via namespace', async () => {
      const client = createClient({ baseUrl: 'https://api.example.com' });

      mockFetch.mockResolvedValueOnce({
        ok: true,
        text: () => Promise.resolve(JSON.stringify({
          id: 'org-123',
          name: 'Acme Corp',
          plan: 'enterprise'
        })),
      });

      const org = await client.organizations.get();
      expect(org.name).toBe('Acme Corp');
    });
  });

  describe('tenants namespace', () => {
    it('should expose tenants namespace', () => {
      const client = createClient({ baseUrl: 'https://api.example.com' });
      expect(client.tenants).toBeDefined();
      expect(typeof client.tenants.list).toBe('function');
    });

    it('should list tenants via namespace', async () => {
      const client = createClient({ baseUrl: 'https://api.example.com' });

      mockFetch.mockResolvedValueOnce({
        ok: true,
        text: () => Promise.resolve(JSON.stringify({
          tenants: [{ id: 'tenant-123', name: 'Acme Tenant' }]
        })),
      });

      const result = await client.tenants.list();
      expect(result.tenants[0].name).toBe('Acme Tenant');
    });
  });

  describe('controlPlane namespace', () => {
    it('should expose controlPlane namespace', () => {
      const client = createClient({ baseUrl: 'https://api.example.com' });
      expect(client.controlPlane).toBeDefined();
      expect(typeof client.controlPlane.getHealth).toBe('function');
    });

    it('should get control plane health via namespace', async () => {
      const client = createClient({ baseUrl: 'https://api.example.com' });

      mockFetch.mockResolvedValueOnce({
        ok: true,
        text: () => Promise.resolve(JSON.stringify({
          status: 'healthy',
          active_agents: 5
        })),
      });

      const health = await client.controlPlane.getHealth();
      expect(health.status).toBe('healthy');
    });

    it('should list control plane agents via namespace', async () => {
      const client = createClient({ baseUrl: 'https://api.example.com' });

      mockFetch.mockResolvedValueOnce({
        ok: true,
        text: () => Promise.resolve(JSON.stringify({
          agents: [{ agent_id: 'a1', status: 'online' }]
        })),
      });

      const result = await client.controlPlane.agents.list();
      expect(result.agents).toHaveLength(1);
    });

    it('should submit task via namespace', async () => {
      const client = createClient({ baseUrl: 'https://api.example.com' });

      mockFetch.mockResolvedValueOnce({
        ok: true,
        text: () => Promise.resolve(JSON.stringify({
          task_id: 'task-123',
          status: 'queued'
        })),
      });

      const result = await client.controlPlane.tasks.submit({
        task_type: 'debate',
        payload: { task: 'Review PR' }
      });
      expect(result.task_id).toBe('task-123');
    });
  });
});
