/**
 * Tests for Aragora Client SDK
 *
 * Tests critical API methods including:
 * - AragoraClient initialization
 * - HttpClient request handling
 * - AragoraError handling
 * - DebatesAPI (list, get, create)
 * - MFAAPI (setup, enable, verify)
 * - BillingAPI (usage, subscription, plans)
 */

import {
  AragoraClient,
  AragoraError,
  getClient,
  type AragoraClientConfig,
} from '@/lib/aragora-client';

// Mock fetch globally
const mockFetch = jest.fn();
global.fetch = mockFetch;

describe('AragoraError', () => {
  beforeEach(() => {
    mockFetch.mockClear();
  });

  it('should create error with all properties', () => {
    const error = new AragoraError('Test error', 'TEST_CODE', 400, { detail: 'extra info' });

    expect(error.message).toBe('Test error');
    expect(error.code).toBe('TEST_CODE');
    expect(error.status).toBe(400);
    expect(error.details).toEqual({ detail: 'extra info' });
    expect(error.name).toBe('AragoraError');
  });

  it('should return user-friendly message for TIMEOUT', () => {
    const error = new AragoraError('Timeout', 'TIMEOUT', 408);
    expect(error.toUserMessage()).toBe(
      'Request timed out. Please try again or check your network connection.',
    );
  });

  it('should return user-friendly message for NETWORK_ERROR', () => {
    const error = new AragoraError('Network failed', 'NETWORK_ERROR', 0);
    expect(error.toUserMessage()).toBe(
      'Network error. Please check your internet connection and try again.',
    );
  });

  it('should return user-friendly message for RATE_LIMITED', () => {
    const error = new AragoraError('Rate limited', 'RATE_LIMITED', 429);
    expect(error.toUserMessage()).toBe(
      'Too many requests. Please wait a moment before trying again.',
    );
  });

  it('should return user-friendly message for UNAUTHORIZED', () => {
    const error = new AragoraError('Unauthorized', 'UNAUTHORIZED', 401);
    expect(error.toUserMessage()).toBe('Authentication failed. Please sign in again.');
  });

  it('should return user-friendly message for FORBIDDEN', () => {
    const error = new AragoraError('Forbidden', 'FORBIDDEN', 403);
    expect(error.toUserMessage()).toBe(
      'Access denied. You do not have permission to perform this action.',
    );
  });

  it('should return user-friendly message for NOT_FOUND', () => {
    const error = new AragoraError('Not found', 'NOT_FOUND', 404);
    expect(error.toUserMessage()).toBe('The requested resource was not found.');
  });

  it('should return original message for unknown codes', () => {
    const error = new AragoraError('Custom error', 'CUSTOM_CODE', 500);
    expect(error.toUserMessage()).toBe('Custom error');
  });
});

describe('AragoraClient', () => {
  const baseConfig: AragoraClientConfig = {
    baseUrl: 'https://api.test.com',
    apiKey: 'test-token-123',
  };

  beforeEach(() => {
    mockFetch.mockClear();
  });

  describe('initialization', () => {
    it('should create client with all API modules', () => {
      const client = new AragoraClient(baseConfig);

      expect(client.debates).toBeDefined();
      expect(client.agents).toBeDefined();
      expect(client.leaderboard).toBeDefined();
      expect(client.organizations).toBeDefined();
      expect(client.billing).toBeDefined();
      expect(client.analytics).toBeDefined();
      expect(client.mfa).toBeDefined();
      expect(client.admin).toBeDefined();
      expect(client.system).toBeDefined();
      expect(client.training).toBeDefined();
      expect(client.evidence).toBeDefined();
      expect(client.tournaments).toBeDefined();
      expect(client.gallery).toBeDefined();
    });

    it('should strip trailing slash from baseUrl', async () => {
      const client = new AragoraClient({ baseUrl: 'https://api.test.com/', apiKey: 'token' });

      mockFetch.mockResolvedValueOnce({
        ok: true,
        json: () => Promise.resolve({ status: 'healthy' }),
      });

      await client.health();

      expect(mockFetch).toHaveBeenCalledWith('https://api.test.com/api/health', expect.any(Object));
    });
  });

  describe('health', () => {
    it('should call system health endpoint', async () => {
      const client = new AragoraClient(baseConfig);
      const healthResponse = {
        status: 'healthy',
        uptime_seconds: 3600,
        version: '1.0.0',
        components: {
          database: { status: 'healthy', latency_ms: 5 },
          agents: { status: 'healthy', available: 10, total: 10 },
          memory: { status: 'healthy', usage_mb: 512 },
          websocket: { status: 'healthy', connections: 50 },
        },
        timestamp: '2024-01-15T10:00:00Z',
      };

      mockFetch.mockResolvedValueOnce({ ok: true, json: () => Promise.resolve(healthResponse) });

      const result = await client.health();

      expect(result).toEqual(healthResponse);
      expect(mockFetch).toHaveBeenCalledWith(
        'https://api.test.com/api/health',
        expect.objectContaining({
          method: 'GET',
          headers: expect.objectContaining({
            'Content-Type': 'application/json',
            Authorization: 'Bearer test-token-123',
          }),
        }),
      );
    });
  });
});

describe('DebatesAPI', () => {
  let client: AragoraClient;

  beforeEach(() => {
    mockFetch.mockClear();
    client = new AragoraClient({ baseUrl: 'https://api.test.com', apiKey: 'test-token' });
  });

  describe('list', () => {
    it('should list debates without options', async () => {
      mockFetch.mockResolvedValueOnce({ ok: true, json: () => Promise.resolve({ debates: [] }) });

      const result = await client.debates.list();

      expect(result).toEqual({ debates: [] });
      expect(mockFetch).toHaveBeenCalledWith(
        'https://api.test.com/api/debates',
        expect.any(Object),
      );
    });

    it('should list debates with pagination options', async () => {
      mockFetch.mockResolvedValueOnce({
        ok: true,
        json: () => Promise.resolve({ debates: [{ id: '1' }, { id: '2' }] }),
      });

      const result = await client.debates.list({ limit: 10, offset: 20, status: 'completed' });

      expect(result.debates).toHaveLength(2);
      expect(mockFetch).toHaveBeenCalledWith(
        'https://api.test.com/api/debates?limit=10&offset=20&status=completed',
        expect.any(Object),
      );
    });
  });

  describe('get', () => {
    it('should get debate by ID', async () => {
      const debateData = {
        debate_id: 'test-123',
        task: 'Test task',
        status: 'completed',
        agents: ['claude', 'gpt-4'],
        rounds: [],
      };

      mockFetch.mockResolvedValueOnce({ ok: true, json: () => Promise.resolve(debateData) });

      const result = await client.debates.get('test-123');

      expect(result).toEqual(debateData);
      expect(mockFetch).toHaveBeenCalledWith(
        'https://api.test.com/api/debates/test-123',
        expect.any(Object),
      );
    });
  });

  describe('create', () => {
    it('should create debate with minimal options', async () => {
      mockFetch.mockResolvedValueOnce({
        ok: true,
        json: () => Promise.resolve({ debate_id: 'new-debate-123' }),
      });

      const result = await client.debates.create({ task: 'Discuss AI safety' });

      expect(result.debate_id).toBe('new-debate-123');
      expect(mockFetch).toHaveBeenCalledWith(
        'https://api.test.com/api/debates',
        expect.objectContaining({
          method: 'POST',
          body: JSON.stringify({ task: 'Discuss AI safety' }),
        }),
      );
    });

    it('should create debate with all options', async () => {
      mockFetch.mockResolvedValueOnce({
        ok: true,
        json: () => Promise.resolve({ debate_id: 'new-debate-456' }),
      });

      await client.debates.create({
        task: 'Compare frameworks',
        agents: ['claude', 'gpt-4', 'gemini'],
        max_rounds: 5,
      });

      expect(mockFetch).toHaveBeenCalledWith(
        'https://api.test.com/api/debates',
        expect.objectContaining({
          body: JSON.stringify({
            task: 'Compare frameworks',
            agents: ['claude', 'gpt-4', 'gemini'],
            max_rounds: 5,
          }),
        }),
      );
    });
  });
});

describe('MFAAPI', () => {
  let client: AragoraClient;

  beforeEach(() => {
    mockFetch.mockClear();
    client = new AragoraClient({ baseUrl: 'https://api.test.com', apiKey: 'test-token' });
  });

  describe('setup', () => {
    it('should initialize MFA setup', async () => {
      const setupResponse = {
        secret: 'JBSWY3DPEHPK3PXP',
        provisioning_uri: 'otpauth://totp/Aragora:user@example.com?secret=JBSWY3DPEHPK3PXP',
        message: 'MFA setup initiated',
      };

      mockFetch.mockResolvedValueOnce({ ok: true, json: () => Promise.resolve(setupResponse) });

      const result = await client.mfa.setup();

      expect(result).toEqual(setupResponse);
      expect(mockFetch).toHaveBeenCalledWith(
        'https://api.test.com/api/auth/mfa/setup',
        expect.objectContaining({ method: 'POST' }),
      );
    });
  });

  describe('enable', () => {
    it('should enable MFA with code', async () => {
      const enableResponse = {
        message: 'MFA enabled successfully',
        backup_codes: ['12345678', '87654321', '11111111'],
        warning: 'Store these backup codes securely',
      };

      mockFetch.mockResolvedValueOnce({ ok: true, json: () => Promise.resolve(enableResponse) });

      const result = await client.mfa.enable('123456');

      expect(result).toEqual(enableResponse);
      expect(mockFetch).toHaveBeenCalledWith(
        'https://api.test.com/api/auth/mfa/enable',
        expect.objectContaining({ method: 'POST', body: JSON.stringify({ code: '123456' }) }),
      );
    });
  });

  describe('verify', () => {
    it('should verify MFA code during login', async () => {
      const verifyResponse = {
        message: 'MFA verified',
        user: { id: 'user-123', email: 'user@example.com' },
        tokens: {
          access_token: 'new-access-token',
          refresh_token: 'new-refresh-token',
          token_type: 'Bearer',
          expires_in: 3600,
        },
      };

      mockFetch.mockResolvedValueOnce({ ok: true, json: () => Promise.resolve(verifyResponse) });

      const result = await client.mfa.verify('pending-token-abc', '654321');

      expect(result).toEqual(verifyResponse);
      expect(mockFetch).toHaveBeenCalledWith(
        'https://api.test.com/api/auth/mfa/verify',
        expect.objectContaining({
          body: JSON.stringify({ pending_token: 'pending-token-abc', code: '654321' }),
        }),
      );
    });
  });

  describe('disable', () => {
    it('should disable MFA with code', async () => {
      mockFetch.mockResolvedValueOnce({
        ok: true,
        json: () => Promise.resolve({ message: 'MFA disabled' }),
      });

      await client.mfa.disable({ code: '123456' });

      expect(mockFetch).toHaveBeenCalledWith(
        'https://api.test.com/api/auth/mfa/disable',
        expect.objectContaining({ body: JSON.stringify({ code: '123456' }) }),
      );
    });

    it('should disable MFA with password', async () => {
      mockFetch.mockResolvedValueOnce({
        ok: true,
        json: () => Promise.resolve({ message: 'MFA disabled' }),
      });

      await client.mfa.disable({ password: 'user-password' });

      expect(mockFetch).toHaveBeenCalledWith(
        'https://api.test.com/api/auth/mfa/disable',
        expect.objectContaining({ body: JSON.stringify({ password: 'user-password' }) }),
      );
    });
  });

  describe('regenerateBackupCodes', () => {
    it('should regenerate backup codes', async () => {
      const response = {
        message: 'Backup codes regenerated',
        backup_codes: ['aaaaaaaa', 'bbbbbbbb', 'cccccccc'],
        warning: 'Previous codes invalidated',
      };

      mockFetch.mockResolvedValueOnce({ ok: true, json: () => Promise.resolve(response) });

      const result = await client.mfa.regenerateBackupCodes('123456');

      expect(result).toEqual(response);
      expect(mockFetch).toHaveBeenCalledWith(
        'https://api.test.com/api/auth/mfa/backup-codes',
        expect.objectContaining({ body: JSON.stringify({ code: '123456' }) }),
      );
    });
  });
});

describe('BillingAPI', () => {
  let client: AragoraClient;

  beforeEach(() => {
    mockFetch.mockClear();
    client = new AragoraClient({ baseUrl: 'https://api.test.com', apiKey: 'test-token' });
  });

  describe('usage', () => {
    it('should get billing usage', async () => {
      const usageData = {
        usage: {
          debates_used: 50,
          debates_limit: 100,
          debates_remaining: 50,
          tokens_used: 500000,
          tokens_in: 300000,
          tokens_out: 200000,
          estimated_cost_usd: 15.5,
          period_start: '2024-01-01',
          period_end: '2024-01-31',
        },
      };

      mockFetch.mockResolvedValueOnce({ ok: true, json: () => Promise.resolve(usageData) });

      const result = await client.billing.usage();

      expect(result).toEqual(usageData);
      expect(mockFetch).toHaveBeenCalledWith(
        'https://api.test.com/api/billing/usage',
        expect.any(Object),
      );
    });
  });

  describe('subscription', () => {
    it('should get subscription details', async () => {
      const subscriptionData = {
        subscription: {
          tier: 'pro',
          status: 'active',
          is_active: true,
          organization: { id: 'org-123', name: 'Test Org' },
          limits: {
            debates_per_month: 500,
            users_per_org: 10,
            api_access: true,
            all_agents: true,
            custom_agents: false,
            sso_enabled: false,
            audit_logs: true,
            priority_support: false,
            price_monthly_cents: 4900,
          },
        },
      };

      mockFetch.mockResolvedValueOnce({ ok: true, json: () => Promise.resolve(subscriptionData) });

      const result = await client.billing.subscription();

      expect(result.subscription.tier).toBe('pro');
      expect(result.subscription.is_active).toBe(true);
    });
  });

  describe('plans', () => {
    it('should get available plans', async () => {
      const plansData = {
        plans: [
          {
            id: 'free',
            name: 'Free',
            price_monthly_cents: 0,
            price_monthly: '$0',
            features: {
              debates_per_month: 10,
              users_per_org: 1,
              api_access: false,
              all_agents: false,
              custom_agents: false,
              sso_enabled: false,
              audit_logs: false,
              priority_support: false,
            },
          },
          {
            id: 'pro',
            name: 'Pro',
            price_monthly_cents: 4900,
            price_monthly: '$49',
            features: {
              debates_per_month: 500,
              users_per_org: 10,
              api_access: true,
              all_agents: true,
              custom_agents: false,
              sso_enabled: false,
              audit_logs: true,
              priority_support: false,
            },
          },
        ],
      };

      mockFetch.mockResolvedValueOnce({ ok: true, json: () => Promise.resolve(plansData) });

      const result = await client.billing.plans();

      expect(result.plans).toHaveLength(2);
      expect(result.plans[0].id).toBe('free');
      expect(result.plans[1].id).toBe('pro');
    });
  });

  describe('invoices', () => {
    it('should get invoices with default limit', async () => {
      mockFetch.mockResolvedValueOnce({ ok: true, json: () => Promise.resolve({ invoices: [] }) });

      await client.billing.invoices();

      expect(mockFetch).toHaveBeenCalledWith(
        'https://api.test.com/api/billing/invoices?limit=10',
        expect.any(Object),
      );
    });

    it('should get invoices with custom limit', async () => {
      mockFetch.mockResolvedValueOnce({ ok: true, json: () => Promise.resolve({ invoices: [] }) });

      await client.billing.invoices(25);

      expect(mockFetch).toHaveBeenCalledWith(
        'https://api.test.com/api/billing/invoices?limit=25',
        expect.any(Object),
      );
    });
  });

  describe('forecast', () => {
    it('should get usage forecast', async () => {
      const forecastData = {
        forecast: {
          current_usage: { debates: 50, debates_limit: 100 },
          projection: {
            debates_end_of_cycle: 75,
            debates_per_day: 2.5,
            tokens_per_day: 25000,
            cost_end_of_cycle_usd: 23.5,
          },
          days_remaining: 15,
          days_elapsed: 15,
          will_hit_limit: false,
          debates_overage: 0,
        },
      };

      mockFetch.mockResolvedValueOnce({ ok: true, json: () => Promise.resolve(forecastData) });

      const result = await client.billing.forecast();

      expect(result.forecast.will_hit_limit).toBe(false);
      expect(result.forecast.days_remaining).toBe(15);
    });
  });

  describe('createCheckout', () => {
    it('should create checkout session', async () => {
      mockFetch.mockResolvedValueOnce({
        ok: true,
        json: () =>
          Promise.resolve({
            checkout: { id: 'cs_123', url: 'https://checkout.stripe.com/pay/cs_123' },
          }),
      });

      const result = await client.billing.createCheckout(
        'pro',
        'https://app.aragora.ai/success',
        'https://app.aragora.ai/cancel',
      );

      expect(result.checkout.url).toContain('stripe.com');
      expect(mockFetch).toHaveBeenCalledWith(
        'https://api.test.com/api/billing/checkout',
        expect.objectContaining({
          body: JSON.stringify({
            tier: 'pro',
            success_url: 'https://app.aragora.ai/success',
            cancel_url: 'https://app.aragora.ai/cancel',
          }),
        }),
      );
    });
  });

  describe('createPortal', () => {
    it('should create customer portal session', async () => {
      mockFetch.mockResolvedValueOnce({
        ok: true,
        json: () =>
          Promise.resolve({ portal: { url: 'https://billing.stripe.com/portal/ps_123' } }),
      });

      const result = await client.billing.createPortal('https://app.aragora.ai/billing');

      expect(result.portal.url).toContain('stripe.com');
    });
  });

  describe('cancelSubscription', () => {
    it('should cancel subscription', async () => {
      mockFetch.mockResolvedValueOnce({
        ok: true,
        json: () =>
          Promise.resolve({
            message: 'Subscription cancelled',
            subscription: { status: 'cancelled' },
          }),
      });

      const result = await client.billing.cancelSubscription();

      expect(result.message).toBe('Subscription cancelled');
    });
  });

  describe('resumeSubscription', () => {
    it('should resume cancelled subscription', async () => {
      mockFetch.mockResolvedValueOnce({
        ok: true,
        json: () =>
          Promise.resolve({ message: 'Subscription resumed', subscription: { status: 'active' } }),
      });

      const result = await client.billing.resumeSubscription();

      expect(result.message).toBe('Subscription resumed');
    });
  });
});

describe('HTTP Error Handling', () => {
  let client: AragoraClient;

  beforeEach(() => {
    mockFetch.mockClear();
    client = new AragoraClient({ baseUrl: 'https://api.test.com', apiKey: 'test-token' });
  });

  it('should throw AragoraError on 401', async () => {
    mockFetch.mockResolvedValueOnce({
      ok: false,
      status: 401,
      json: () => Promise.resolve({ error: 'Unauthorized', code: 'UNAUTHORIZED' }),
    });

    try {
      await client.debates.list();
      fail('Expected error to be thrown');
    } catch (error) {
      expect(error).toBeInstanceOf(AragoraError);
      expect((error as AragoraError).status).toBe(401);
      expect((error as AragoraError).code).toBe('UNAUTHORIZED');
    }
  });

  it('should throw AragoraError on 403', async () => {
    mockFetch.mockResolvedValueOnce({
      ok: false,
      status: 403,
      json: () => Promise.resolve({ error: 'Forbidden', code: 'FORBIDDEN' }),
    });

    try {
      await client.debates.list();
      fail('Expected error to be thrown');
    } catch (error) {
      expect(error).toBeInstanceOf(AragoraError);
      expect((error as AragoraError).status).toBe(403);
    }
  });

  it('should throw AragoraError on 404', async () => {
    mockFetch.mockResolvedValueOnce({
      ok: false,
      status: 404,
      json: () => Promise.resolve({ error: 'Debate not found', code: 'NOT_FOUND' }),
    });

    try {
      await client.debates.get('nonexistent-id');
      fail('Expected error to be thrown');
    } catch (error) {
      expect(error).toBeInstanceOf(AragoraError);
      expect((error as AragoraError).status).toBe(404);
    }
  });

  it('should throw AragoraError on 429', async () => {
    mockFetch.mockResolvedValueOnce({
      ok: false,
      status: 429,
      json: () => Promise.resolve({ error: 'Rate limit exceeded', code: 'RATE_LIMITED' }),
    });

    try {
      await client.debates.list();
      fail('Expected error to be thrown');
    } catch (error) {
      expect(error).toBeInstanceOf(AragoraError);
      expect((error as AragoraError).status).toBe(429);
      expect((error as AragoraError).toUserMessage()).toContain('Too many requests');
    }
  });

  it('should handle network errors', async () => {
    mockFetch.mockRejectedValueOnce(new Error('Network failed'));

    try {
      await client.debates.list();
      fail('Expected error to be thrown');
    } catch (error) {
      expect(error).toBeInstanceOf(AragoraError);
      expect((error as AragoraError).code).toBe('NETWORK_ERROR');
    }
  });

  it('should handle timeout via AbortError', async () => {
    const abortError = new Error('Aborted');
    abortError.name = 'AbortError';
    mockFetch.mockRejectedValueOnce(abortError);

    try {
      await client.debates.list();
      fail('Expected error to be thrown');
    } catch (error) {
      expect(error).toBeInstanceOf(AragoraError);
      expect((error as AragoraError).code).toBe('TIMEOUT');
      expect((error as AragoraError).status).toBe(408);
    }
  });

  it('should handle malformed JSON response', async () => {
    mockFetch.mockResolvedValueOnce({
      ok: false,
      status: 500,
      json: () => Promise.reject(new Error('Invalid JSON')),
    });

    try {
      await client.debates.list();
      fail('Expected error to be thrown');
    } catch (error) {
      expect(error).toBeInstanceOf(AragoraError);
      expect((error as AragoraError).status).toBe(500);
      expect((error as AragoraError).message).toBe('HTTP 500');
    }
  });
});

describe('getClient', () => {
  beforeEach(() => {
    mockFetch.mockClear();
    // Clear any cached client by calling with different params
    getClient('reset-token-1', 'https://reset.test.com');
    getClient('reset-token-2', 'https://reset2.test.com');
  });

  it('should create client with default baseUrl', () => {
    const client = getClient('my-token');

    expect(client).toBeInstanceOf(AragoraClient);
  });

  it('should create client with custom baseUrl', () => {
    const client = getClient('my-token', 'https://custom.api.com');

    expect(client).toBeInstanceOf(AragoraClient);
  });

  it('should reuse client with same config', () => {
    const client1 = getClient('same-token', 'https://same.api.com');
    const client2 = getClient('same-token', 'https://same.api.com');

    expect(client1).toBe(client2);
  });

  it('should create new client when token changes', () => {
    const client1 = getClient('token-1', 'https://api.test.com');
    const client2 = getClient('token-2', 'https://api.test.com');

    expect(client1).not.toBe(client2);
  });

  it('should create new client when baseUrl changes', () => {
    const client1 = getClient('token', 'https://api1.test.com');
    const client2 = getClient('token', 'https://api2.test.com');

    expect(client1).not.toBe(client2);
  });
});

describe('AgentsAPI', () => {
  let client: AragoraClient;

  beforeEach(() => {
    mockFetch.mockClear();
    client = new AragoraClient({ baseUrl: 'https://api.test.com', apiKey: 'test-token' });
  });

  it('should list agents', async () => {
    const agentsData = {
      agents: [
        { agent_id: 'claude', name: 'Claude', provider: 'anthropic' },
        { agent_id: 'gpt-4', name: 'GPT-4', provider: 'openai' },
      ],
    };

    mockFetch.mockResolvedValueOnce({ ok: true, json: () => Promise.resolve(agentsData) });

    const result = await client.agents.list();

    expect(result.agents).toHaveLength(2);
    expect(mockFetch).toHaveBeenCalledWith('https://api.test.com/api/agents', expect.any(Object));
  });

  it('should get agent by ID', async () => {
    mockFetch.mockResolvedValueOnce({
      ok: true,
      json: () =>
        Promise.resolve({
          agent_id: 'claude',
          name: 'Claude',
          provider: 'anthropic',
          elo_rating: 1500,
        }),
    });

    const result = await client.agents.get('claude');

    expect(result).toMatchObject({ agent_id: 'claude' });
  });
});

describe('LeaderboardAPI', () => {
  let client: AragoraClient;

  beforeEach(() => {
    mockFetch.mockClear();
    client = new AragoraClient({ baseUrl: 'https://api.test.com', apiKey: 'test-token' });
  });

  it('should get leaderboard without limit', async () => {
    mockFetch.mockResolvedValueOnce({
      ok: true,
      json: () =>
        Promise.resolve({
          entries: [
            { agent_id: 'claude', elo_rating: 1600, rank: 1 },
            { agent_id: 'gpt-4', elo_rating: 1550, rank: 2 },
          ],
        }),
    });

    const result = await client.leaderboard.get();

    expect(result.entries).toHaveLength(2);
    expect(mockFetch).toHaveBeenCalledWith(
      'https://api.test.com/api/leaderboard',
      expect.any(Object),
    );
  });

  it('should get leaderboard with limit', async () => {
    mockFetch.mockResolvedValueOnce({ ok: true, json: () => Promise.resolve({ entries: [] }) });

    await client.leaderboard.get({ limit: 5 });

    expect(mockFetch).toHaveBeenCalledWith(
      'https://api.test.com/api/leaderboard?limit=5',
      expect.any(Object),
    );
  });
});

describe('AnalyticsAPI', () => {
  let client: AragoraClient;

  beforeEach(() => {
    mockFetch.mockClear();
    client = new AragoraClient({ baseUrl: 'https://api.test.com', apiKey: 'test-token' });
  });

  it('should get analytics overview with default days', async () => {
    mockFetch.mockResolvedValueOnce({
      ok: true,
      json: () => Promise.resolve({ total_debates: 100, consensus_rate: 0.75 }),
    });

    await client.analytics.overview();

    expect(mockFetch).toHaveBeenCalledWith(
      'https://api.test.com/api/analytics?days=30',
      expect.any(Object),
    );
  });

  it('should get analytics overview with custom days', async () => {
    mockFetch.mockResolvedValueOnce({ ok: true, json: () => Promise.resolve({}) });

    await client.analytics.overview(7);

    expect(mockFetch).toHaveBeenCalledWith(
      'https://api.test.com/api/analytics?days=7',
      expect.any(Object),
    );
  });

  it('should get cost analysis', async () => {
    mockFetch.mockResolvedValueOnce({
      ok: true,
      json: () =>
        Promise.resolve({
          analysis: {
            total_cost_usd: 150.5,
            cost_by_model: { 'gpt-4': 100, claude: 50.5 },
            projected_monthly_cost: 450,
          },
        }),
    });

    const result = await client.analytics.cost();

    expect(result.analysis.total_cost_usd).toBe(150.5);
  });
});
