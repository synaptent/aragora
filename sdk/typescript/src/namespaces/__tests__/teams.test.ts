/**
 * Teams Bot Namespace Tests
 *
 * Comprehensive tests for the Teams bot namespace API including:
 * - Status and configuration
 * - OAuth and installation
 * - Tenant management
 * - Channel management
 * - Notification settings
 * - Debate integration
 */

import { describe, it, expect, beforeEach, vi, type Mock } from 'vitest';
import { TeamsAPI } from '../teams';

interface MockClient {
  request: Mock;
  getBaseUrl: Mock;
}

describe('TeamsAPI Namespace', () => {
  let api: TeamsAPI;
  let mockClient: MockClient;

  beforeEach(() => {
    mockClient = {
      request: vi.fn(),
      getBaseUrl: vi.fn().mockReturnValue('https://api.aragora.ai'),
    };
    api = new TeamsAPI(mockClient as any);
  });

  // ===========================================================================
  // Status & Configuration
  // ===========================================================================

  describe('Status & Configuration', () => {
    it('should get Teams bot status', async () => {
      const mockStatus = {
        platform: 'teams',
        enabled: true,
        app_id_configured: true,
        password_configured: true,
        sdk_available: true,
        sdk_error: null,
      };
      mockClient.request.mockResolvedValue(mockStatus);

      const result = await api.getStatus();

      expect(mockClient.request).toHaveBeenCalledWith('GET', '/api/v1/bots/teams/status');
      expect(result.enabled).toBe(true);
      expect(result.sdk_available).toBe(true);
    });

    it('should show SDK error when unavailable', async () => {
      const mockStatus = {
        platform: 'teams',
        enabled: true,
        app_id_configured: true,
        password_configured: true,
        sdk_available: false,
        sdk_error: 'botbuilder package not installed',
      };
      mockClient.request.mockResolvedValue(mockStatus);

      const result = await api.getStatus();

      expect(result.sdk_available).toBe(false);
      expect(result.sdk_error).toBe('botbuilder package not installed');
    });

    it('should check if healthy', async () => {
      mockClient.request.mockResolvedValue({
        enabled: true,
        sdk_available: true,
      });

      const result = await api.isHealthy();

      expect(result).toBe(true);
    });

    it('should return false when not healthy', async () => {
      mockClient.request.mockResolvedValue({
        enabled: false,
        sdk_available: true,
      });

      const result = await api.isHealthy();

      expect(result).toBe(false);
    });

    it('should return false on error', async () => {
      mockClient.request.mockRejectedValue(new Error('Connection failed'));

      const result = await api.isHealthy();

      expect(result).toBe(false);
    });
  });

  // ===========================================================================
  // OAuth & Installation
  // ===========================================================================

  describe('OAuth & Installation', () => {
    it('should get install URL', async () => {
      const mockInstall = {
        authorization_url: 'https://login.microsoftonline.com/...',
        state: 'state123',
      };
      mockClient.request.mockResolvedValue(mockInstall);

      const result = await api.getInstallUrl();

      expect(mockClient.request).toHaveBeenCalledWith('GET', '/api/integrations/teams/install', {
        params: undefined,
      });
      expect(result.authorization_url).toContain('microsoftonline.com');
    });

    it('should get install URL with options', async () => {
      const mockInstall = {
        authorization_url: 'https://login.microsoftonline.com/...',
        state: 'custom_state',
      };
      mockClient.request.mockResolvedValue(mockInstall);

      const result = await api.getInstallUrl({
        redirect_uri: 'https://app.example.com/callback',
        state: 'custom_state',
      });

      expect(mockClient.request).toHaveBeenCalledWith('GET', '/api/integrations/teams/install', {
        params: {
          redirect_uri: 'https://app.example.com/callback',
          state: 'custom_state',
        },
      });
      expect(result.state).toBe('custom_state');
    });

    it('should refresh tokens', async () => {
      mockClient.request.mockResolvedValue({ success: true });

      const result = await api.refreshTokens('tenant-123');

      expect(mockClient.request).toHaveBeenCalledWith('POST', '/api/integrations/teams/refresh', {
        body: { tenant_id: 'tenant-123' },
      });
      expect(result.success).toBe(true);
    });
  });

  // ===========================================================================
  // Tenant Management
  // ===========================================================================

  describe('Tenant Management', () => {
    it('should list tenants', async () => {
      const mockTenants = {
        tenants: [
          { tenant_id: 't1', name: 'Acme Corp', enabled: true, created_at: '2024-01-01' },
          { tenant_id: 't2', name: 'TechStart', enabled: false, created_at: '2024-01-02' },
        ],
      };
      mockClient.request.mockResolvedValue(mockTenants);

      const result = await api.listTenants();

      expect(mockClient.request).toHaveBeenCalledWith('GET', '/api/teams/tenants');
      expect(result).toHaveLength(2);
      expect(result[0].name).toBe('Acme Corp');
    });

  });

  // ===========================================================================
  // Channel Management
  // ===========================================================================

  describe('Channel Management', () => {
    it('should list channels for tenant', async () => {
      const mockChannels = {
        channels: [
          { id: 'c1', name: 'General', member_count: 50, created_at: '2024-01-01' },
          { id: 'c2', name: 'Engineering', member_count: 20, created_at: '2024-01-02' },
        ],
      };
      mockClient.request.mockResolvedValue(mockChannels);

      const result = await api.listChannels('t1');

      expect(mockClient.request).toHaveBeenCalledWith('GET', '/api/v1/teams/tenants/t1/channels');
      expect(result).toHaveLength(2);
      expect(result[0].name).toBe('General');
    });
  });

  // ===========================================================================
  // Debate Integration
  // ===========================================================================

  describe('Debate Integration', () => {
    it('should send debate to channel', async () => {
      const mockMessage = {
        debate_id: 'd1',
        channel_id: 'c1',
        message_id: 'msg_123',
        sent_at: '2024-01-20T10:00:00Z',
      };
      mockClient.request.mockResolvedValue(mockMessage);

      const result = await api.sendDebateToChannel('d1', 'c1');

      expect(mockClient.request).toHaveBeenCalledWith('POST', '/api/v1/teams/debates/send', {
        body: {
          debate_id: 'd1',
          channel_id: 'c1',
        },
      });
      expect(result.message_id).toBe('msg_123');
    });

    it('should send debate with options', async () => {
      const mockMessage = {
        debate_id: 'd1',
        channel_id: 'c1',
        message_id: 'msg_124',
      };
      mockClient.request.mockResolvedValue(mockMessage);

      const result = await api.sendDebateToChannel('d1', 'c1', {
        tenant_id: 't1',
        include_voting: true,
        include_summary: true,
      });

      expect(mockClient.request).toHaveBeenCalledWith('POST', '/api/v1/teams/debates/send', {
        body: {
          debate_id: 'd1',
          channel_id: 'c1',
          tenant_id: 't1',
          include_voting: true,
          include_summary: true,
        },
      });
    });

    it('should list debate messages', async () => {
      const mockMessages = {
        messages: [
          { debate_id: 'd1', channel_id: 'c1', message_id: 'msg_1' },
          { debate_id: 'd2', channel_id: 'c1', message_id: 'msg_2' },
        ],
      };
      mockClient.request.mockResolvedValue(mockMessages);

      const result = await api.listDebateMessages({ channel_id: 'c1' });

      expect(mockClient.request).toHaveBeenCalledWith('GET', '/api/teams/debates', {
        params: { channel_id: 'c1' },
      });
      expect(result).toHaveLength(2);
    });

    it('should list debate messages with pagination', async () => {
      const mockMessages = {
        messages: [{ debate_id: 'd3', channel_id: 'c1', message_id: 'msg_3' }],
      };
      mockClient.request.mockResolvedValue(mockMessages);

      const result = await api.listDebateMessages({ limit: 10, offset: 20 });

      expect(mockClient.request).toHaveBeenCalledWith('GET', '/api/teams/debates', {
        params: { limit: 10, offset: 20 },
      });
    });
  });
});
